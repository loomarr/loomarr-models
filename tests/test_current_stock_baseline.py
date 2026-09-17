from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
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

    def test_preflight_reconstructs_exact_authorized_plan(self):
        plan = preflight(ROOT, CONFIG, require_authorized=False, git_probe=lambda *_: "a" * 40)
        self.assertEqual(plan.caseCount, 24)
        self.assertEqual(plan.reservationUsd, "1.50")
        self.assertTrue(plan.paidBaselineAuthorized)
        paid = preflight(ROOT, CONFIG, require_authorized=True, git_probe=lambda *_: "a" * 40)
        self.assertEqual(paid, plan)

    def test_preflight_rejects_binding_budget_and_heavy_import_drift(self):
        config = copy.deepcopy(self.config)
        config["bindings"]["cases"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "cases digest mismatch"):
                preflight(ROOT, path, require_authorized=False, git_probe=lambda *_: "a" * 40)

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            ledger = json.loads((ROOT / "budgets/external-spend-v1.json").read_text(encoding="utf-8"))
            ledger["authorizationUsd"] = "28.00"
            ledger_path = directory / "ledger.json"
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            config = copy.deepcopy(self.config)
            config["bindings"]["budgetLedger"] = {
                "path": str(ledger_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
            }
            config["budget"].update(
                {
                    "aggregateAuthorizationUsd": "28.00",
                    "projectedCommitmentUsd": str(
                        Decimal(ledger["committedSpendUsd"]) + Decimal("1.50")
                    ),
                    "remainingAuthorizationUsd": str(
                        Decimal("28.00")
                        - Decimal(ledger["committedSpendUsd"])
                        - Decimal("1.50")
                    ),
                }
            )
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "exceed aggregate"):
                preflight(ROOT, config_path, require_authorized=False, git_probe=lambda *_: "a" * 40)

        sentinel = object()
        previous = sys.modules.get("torch", sentinel)
        sys.modules["torch"] = object()
        try:
            with self.assertRaisesRegex(PreflightError, "heavyweight modules"):
                preflight(ROOT, CONFIG, require_authorized=False, git_probe=lambda *_: "a" * 40)
        finally:
            if previous is sentinel:
                del sys.modules["torch"]
            else:
                sys.modules["torch"] = previous


if __name__ == "__main__":
    unittest.main()
