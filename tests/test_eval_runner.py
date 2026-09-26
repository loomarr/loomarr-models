from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from loomarr_models.eval_runner import evaluate_case, compare_candidates, summarize_candidate
from loomarr_models.evaluation import load_cases
from loomarr_models.validator import load_contract


ROOT = Path(__file__).resolve().parents[1]
CASES = load_cases(ROOT / "evaluation/planner-development-v1/cases.jsonl")
CONTRACT = load_contract(ROOT / "contracts/planner-contract-v3.json")
SCORING = json.loads(
    (ROOT / "evaluation/planner-development-v1/manifest.json").read_text(encoding="utf-8")
)["scoring"]


class OracleGenerator:
    def __init__(
        self,
        case: dict,
        *,
        bad_policy: bool = False,
        unsupported_pick: bool = False,
        bad_arguments: bool = False,
    ):
        self.case = case
        self.bad_policy = bad_policy
        self.unsupported_pick = unsupported_pick
        self.bad_arguments = bad_arguments

    def __call__(self, messages: list[dict], _tools: list[dict]) -> dict:
        completed_steps = sum(message.get("role") == "tool" for message in messages)
        if completed_steps < len(self.case["script"]):
            arguments = copy.deepcopy(self.case["script"][completed_steps]["arguments"])
            if self.bad_arguments:
                arguments = {"query": "wrong", "genres": ["Adventure"]}
            return {
                "role": "assistant",
                "toolCalls": [
                    {
                        "id": f"generated-{completed_steps + 1}",
                        "name": "catalog_search",
                        "arguments": arguments,
                    }
                ],
            }
        final = self._final()
        return {"role": "assistant", "content": json.dumps(final, separators=(",", ":"))}

    def _final(self) -> dict:
        candidates = {
            (candidate["mediaType"], candidate["tmdbId"]): candidate
            for step in self.case["script"]
            for candidate in step["result"].get("candidates", [])
        }
        picks = []
        for identity in self.case["expectation"]["selectedIds"]:
            candidate = candidates[(identity["mediaType"], identity["tmdbId"])]
            picks.append(
                {
                    "mediaType": candidate["mediaType"],
                    "tmdbId": candidate["tmdbId"],
                    "name": candidate["name"],
                    "rationale": "The synthetic fixture supports this exact selection.",
                    "confidence": 0.91,
                }
            )
        if self.unsupported_pick:
            picks.append(
                {
                    "mediaType": "movie",
                    "tmdbId": 999999,
                    "name": "Invented Candidate",
                    "rationale": "This candidate was not surfaced.",
                    "confidence": 0.5,
                }
            )
        return {
            "channelName": "Development Signal",
            "rationale": "A deterministic proposal from synthetic catalog evidence.",
            "picks": picks,
            "policy": (
                {}
                if self.bad_policy and self.case["expectation"]["expectedPolicy"]
                else copy.deepcopy(self.case["expectation"]["expectedPolicy"])
            ),
        }


def run_case(case: dict, generator=None):
    return evaluate_case(
        case,
        system_prompt=CONTRACT["systemPrompt"],
        tools=CONTRACT["tools"],
        generate=generator or OracleGenerator(case),
    )


class EvalRunnerTests(unittest.TestCase):
    def test_oracle_clears_every_metric_on_all_fifty_cases(self):
        results = [run_case(case) for case in CASES]
        summary = summarize_candidate("oracle", results, SCORING)
        self.assertEqual(summary["caseCount"], 50)
        self.assertEqual(summary["hardFailureCount"], 0)
        for field in (
            "groundedCompletionRate",
            "correctToolOperationRate",
            "argumentValidityRate",
            "schemaValidityRate",
            "policyAccuracyRate",
            "proposalQualityRate",
            "recoveryRate",
            "qualityScore",
        ):
            self.assertEqual(summary[field], 1.0, field)

    def test_repair_cases_receive_frozen_feedback_before_final_generation(self):
        case = next(case for case in CASES if case["axis"] == "malformed-final-repair")
        result = run_case(case)
        self.assertTrue(result.recoverySuccessful)
        self.assertEqual(
            result.transcript[-2],
            {"role": "user", "content": case["repairPrompt"]},
        )
        self.assertEqual(result.modelCalls, 2)

    def test_unexpected_or_invalid_tool_arguments_fail_closed(self):
        case = CASES[0]
        result = run_case(case, OracleGenerator(case, bad_arguments=True))
        self.assertFalse(result.argumentValidity)
        self.assertFalse(result.correctToolOperation)
        self.assertFalse(result.proposalQuality)

    def test_unsupported_id_is_a_hard_failure(self):
        case = CASES[0]
        result = run_case(case, OracleGenerator(case, unsupported_pick=True))
        self.assertEqual(result.unsupportedIdCount, 1)
        self.assertIn("unsupported_id", result.hardFailures)

    def test_adapter_advances_only_with_margin_target_gain_and_thresholds(self):
        stock_results = [
            run_case(case, OracleGenerator(case, bad_policy=True)) for case in CASES
        ]
        adapter_results = [run_case(case) for case in CASES]
        stock = summarize_candidate("stock", stock_results, SCORING)
        adapter = summarize_candidate("adapter", adapter_results, SCORING)
        comparison = compare_candidates(stock, adapter, SCORING)
        self.assertEqual(
            comparison["decision"], "adapter-advances-to-single-certification-run"
        )
        self.assertGreaterEqual(comparison["qualityDelta"], 0.02)
        self.assertGreater(comparison["metricDeltas"]["policyAccuracyRate"], 0)

    def test_hard_regression_or_no_target_gain_rejects_adapter(self):
        perfect_results = [run_case(case) for case in CASES]
        stock = summarize_candidate("stock", perfect_results, SCORING)
        adapter_results = list(perfect_results)
        adapter_results[0] = run_case(CASES[0], OracleGenerator(CASES[0], unsupported_pick=True))
        adapter = summarize_candidate("adapter", adapter_results, SCORING)
        comparison = compare_candidates(stock, adapter, SCORING)
        self.assertEqual(comparison["decision"], "adapter-rejected-no-release")
        self.assertIn("adapter has hard-gate failures", comparison["failures"])

    def test_refuses_asymmetric_candidate_counts(self):
        result = run_case(CASES[0])
        stock = summarize_candidate("stock", [result], SCORING)
        adapter = summarize_candidate("adapter", [result, result], SCORING)
        with self.assertRaisesRegex(ValueError, "case counts differ"):
            compare_candidates(stock, adapter, SCORING)


if __name__ == "__main__":
    unittest.main()
