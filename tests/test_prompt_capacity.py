from __future__ import annotations

import json
import unittest
from pathlib import Path

from loomarr_models.current_contract import read_jsonl
from loomarr_models.experiment import PreflightError
from loomarr_models.prompt_capacity import measure_prompt_capacity


ROOT = Path(__file__).resolve().parents[1]


class _Shape:
    def __init__(self, tokens: int):
        self.shape = (1, tokens)


class FakeTokenizer:
    def apply_chat_template(self, messages, *, tools, **_kwargs):
        return json.dumps({"messages": messages, "tools": tools}, sort_keys=True)

    def __call__(self, *, text, return_tensors):
        self.assert_return_tensors = return_tensors
        return {"input_ids": _Shape(len(text) // 4)}


class PromptCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(
            (ROOT / "contracts/planner-contract-v5.json").read_text(encoding="utf-8")
        )
        cls.cases = read_jsonl(ROOT / "evaluation/planner-current-v1/cases.jsonl")

    def test_measures_every_scripted_model_call_and_finalization(self):
        expected_stages = sum(len(case["script"]) + 1 for case in self.cases)
        report = measure_prompt_capacity(
            FakeTokenizer(),
            self.contract,
            self.cases,
            {"maxSeqLength": 32768, "maxNewTokens": 2048, "reasoningEffort": "low"},
        )
        self.assertEqual(report["caseCount"], 24)
        self.assertEqual(report["stageCount"], expected_stages)
        self.assertEqual(len(report["measurementsSha256"]), 64)
        self.assertGreaterEqual(report["minAvailableGenerationTokens"], 2048)

    def test_fails_when_any_stage_lacks_the_full_generation_budget(self):
        with self.assertRaisesRegex(PreflightError, "prompt capacity is insufficient"):
            measure_prompt_capacity(
                FakeTokenizer(),
                self.contract,
                self.cases,
                {"maxSeqLength": 4096, "maxNewTokens": 2048, "reasoningEffort": "low"},
            )


if __name__ == "__main__":
    unittest.main()
