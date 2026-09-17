from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from loomarr_models.current_baseline import (
    CANDIDATE_ID,
    baseline_decision,
    evaluate_current_case,
    preflight,
    summarize_current_candidate,
)
from loomarr_models.current_contract import read_jsonl
from loomarr_models.experiment import PreflightError


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v2.json"
CASES = ROOT / "evaluation/planner-current-v1/cases.jsonl"
CONTRACT = ROOT / "contracts/planner-contract-v5.json"


def oracle(case: dict):
    candidates = {}
    for step in case["script"]:
        payload = json.loads(step["result"])
        if isinstance(payload, list):
            candidates.update({item["key"]: item for item in payload})

    def generate(messages, _tools):
        if messages[-1]["role"] == "user" and messages[-1]["content"].startswith("Retrieval is complete"):
            picks = []
            for key in case["expectation"]["selectedKeys"]:
                item = candidates[key]
                pick = {
                    "mediaType": item["mediaType"],
                    "key": key,
                    "name": item["name"],
                    "rationale": "Exact synthetic evidence matches the request.",
                    "confidence": 0.9,
                }
                if case["axis"] == "season-window":
                    pick.update({"seasonMin": 1, "seasonMax": 3})
                picks.append(pick)
            policy = {"audience": {"ceiling": "TV-14"}} if case["axis"] == "audience-ceiling" else {}
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "channelName": "Synthetic Oracle",
                        "rationale": "A bounded synthetic proposal.",
                        "dateMeaning": case["expectation"]["dateMeaning"],
                        "picks": picks,
                        "policy": policy,
                    }
                ),
            }
        step_index = sum(message["role"] == "tool" for message in messages)
        return {
            "role": "assistant",
            "toolCalls": [
                {
                    "id": f"oracle-{step_index + 1}",
                    "name": "catalog_search",
                    "arguments": case["script"][step_index]["arguments"],
                }
            ],
        }

    return generate


class CurrentStockBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = read_jsonl(CASES)
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def evaluate(self, case, generate=None):
        return evaluate_current_case(
            case,
            system_prompt=self.contract["systemPrompt"],
            tools=self.contract["tools"],
            generate=generate or oracle(case),
            max_model_calls=self.config["comparison"]["maxModelCallsPerCase"],
        )

    def test_oracle_clears_all_current_capabilities(self):
        results = [self.evaluate(case) for case in self.cases]
        self.assertEqual(len(results), 24)
        self.assertTrue(all(not result.hardFailures for result in results))
        self.assertTrue(all(result.proposalQuality for result in results))
        self.assertTrue(all(result.correctToolOperation for result in results))
        recovery = next(result for result in results if result.axis == "observed-fault-recovery")
        self.assertTrue(recovery.faultInjected)
        self.assertTrue(recovery.faultObserved)
        self.assertTrue(recovery.recoverySuccessful)

        summary = summarize_current_candidate(CANDIDATE_ID, results)
        decision = baseline_decision(summary, self.config["scoring"])
        self.assertEqual(summary["caseCount"], 24)
        self.assertEqual(summary["dateMeaningAccuracyRate"], 1.0)
        self.assertFalse(decision["qloraJustified"])
        self.assertEqual(decision["outcome"], "qlora-not-justified-stock-clears-current-development-gate")

    def test_unsupported_key_and_recovery_without_observed_fault_fail(self):
        case = copy.deepcopy(self.cases[0])
        base = oracle(case)

        def unsupported(messages, tools):
            turn = base(messages, tools)
            if "content" in turn:
                final = json.loads(turn["content"])
                final["picks"][0]["key"] = "movie:synthetic:not-surfaced"
                turn["content"] = json.dumps(final)
            return turn

        result = self.evaluate(case, unsupported)
        self.assertEqual(result.unsupportedKeyCount, 1)
        self.assertIn("unsupported_key", result.hardFailures)

        recovery_case = copy.deepcopy(next(item for item in self.cases if item["axis"] == "observed-fault-recovery"))
        fault = json.loads(recovery_case["script"][0]["result"])
        fault["fault"]["observed"] = False
        recovery_case["script"][0]["result"] = json.dumps(fault)
        recovery = self.evaluate(recovery_case)
        self.assertFalse(recovery.recoverySuccessful)
        self.assertIn("recovery_without_observed_fault", recovery.hardFailures)

    def test_incorrect_tool_operation_is_a_hard_failure(self):
        case = copy.deepcopy(self.cases[0])

        def wrong_operation(_messages, _tools):
            arguments = copy.deepcopy(case["script"][0]["arguments"])
            arguments["query"] = "wrong synthetic query"
            return {
                "role": "assistant",
                "toolCalls": [
                    {"id": "wrong-operation", "name": "catalog_search", "arguments": arguments}
                ],
            }

        result = self.evaluate(case, wrong_operation)
        self.assertFalse(result.correctToolOperation)
        self.assertIn("incorrect_tool_operation", result.hardFailures)

    def test_quality_miss_can_justify_but_never_authorize_training(self):
        results = [self.evaluate(case) for case in self.cases]
        failed = copy.deepcopy(results[0])
        object.__setattr__(failed, "schemaValidity", False)
        object.__setattr__(failed, "hardFailures", ["schema_invalid"])
        summary = summarize_current_candidate(CANDIDATE_ID, [failed, *results[1:]])
        decision = baseline_decision(summary, self.config["scoring"])
        self.assertTrue(decision["qloraJustified"])
        self.assertFalse(decision["trainingAuthorized"])
        invalid = baseline_decision(summary, self.config["scoring"], run_status="infrastructure-failure")
        self.assertFalse(invalid["qloraJustified"])
        self.assertEqual(invalid["outcome"], "baseline-invalid-no-training-decision")

    def test_terminal_config_refuses_reexecution(self):
        self.assertEqual(self.config["status"], "complete-settled")
        self.assertFalse(self.config["authority"]["paidBaselineAuthorized"])
        self.assertEqual(self.config["budget"]["proposedReservationUsd"], "0")
        for require_authorized in (False, True):
            with self.assertRaisesRegex(PreflightError, "terminal and cannot run again"):
                preflight(
                    ROOT,
                    CONFIG,
                    require_authorized=require_authorized,
                    git_probe=lambda *_: "a" * 40,
                )

    def test_terminal_bindings_are_current_and_paid_authority_is_revoked(self):
        for binding in self.config["bindings"].values():
            path = ROOT / binding["path"]
            self.assertEqual(binding["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertFalse(self.config["authority"]["gpuAuthorized"])
        self.assertFalse(self.config["authority"]["modelDownloadAuthorized"])


if __name__ == "__main__":
    unittest.main()
