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

    def test_affected_families_preserve_intent_and_recovery_contracts(self):
        traces = [
            json.loads(line)
            for line in (ROOT / "corpus/planner-smoke-v1/drafts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        by_axis = {
            axis: [trace for trace in traces if trace["axes"] == [axis]]
            for axis in (
                "genre-discovery",
                "keyword-discovery",
                "must-include",
                "ambiguous-intent",
                "tool-error-recovery",
            )
        }
        self.assertTrue(all(len(items) == 5 for items in by_axis.values()))
        for axis in ("genre-discovery", "keyword-discovery"):
            for trace in by_axis[axis]:
                arguments = trace["messages"][2]["toolCalls"][0]["arguments"]
                self.assertNotIn("media_type", arguments)
        for trace in by_axis["keyword-discovery"]:
            keyword = trace["messages"][2]["toolCalls"][0]["arguments"]["keywords"][0]
            overview = trace["messages"][3]["content"]["candidates"][0]["overview"]
            self.assertIn(keyword, overview)
        for trace in by_axis["must-include"]:
            self.assertNotIn("varied", trace["messages"][1]["content"].lower())
        for trace in by_axis["ambiguous-intent"]:
            arguments = trace["messages"][2]["toolCalls"][0]["arguments"]
            self.assertEqual(set(arguments), {"genres"})
            self.assertEqual(
                arguments["genres"], trace["messages"][3]["content"]["candidates"][0]["genres"]
            )
        for trace in by_axis["tool-error-recovery"]:
            first = trace["messages"][2]["toolCalls"][0]["arguments"]
            second = trace["messages"][4]["toolCalls"][0]["arguments"]
            self.assertEqual(set(first), {"genres"})
            self.assertEqual(set(second), {"query"})


if __name__ == "__main__":
    unittest.main()
