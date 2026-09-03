from __future__ import annotations

import json
import unittest
from pathlib import Path

from loomarr_models.training_data import to_huggingface_tools, to_qwen_conversation


ROOT = Path(__file__).resolve().parents[1]


class TrainingDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.trace = json.loads(
            (ROOT / "corpus/planner-smoke-v1/drafts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )

    def test_preserves_prompt_intent_tool_arguments_results_and_final(self):
        converted = to_qwen_conversation(self.trace)
        source = self.trace["messages"]
        self.assertEqual(converted[0], source[0])
        self.assertEqual(converted[1], source[1])
        self.assertEqual(
            converted[2]["tool_calls"][0]["function"]["arguments"],
            source[2]["toolCalls"][0]["arguments"],
        )
        self.assertEqual(json.loads(converted[3]["content"]), source[3]["content"])
        self.assertEqual(converted[-1]["content"], source[-1]["content"])

    def test_adapts_frozen_tool_schema_to_huggingface_wrapper(self):
        tools = to_huggingface_tools(self.trace["tools"])
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], self.trace["tools"][0]["Name"])
        self.assertEqual(
            tools[0]["function"]["parameters"], self.trace["tools"][0]["Parameters"]
        )


if __name__ == "__main__":
    unittest.main()
