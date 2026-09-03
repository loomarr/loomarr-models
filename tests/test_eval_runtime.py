from __future__ import annotations

import ast
import unittest
from pathlib import Path

from loomarr_models.eval_runtime import _to_huggingface_messages, parse_qwen_turn


ROOT = Path(__file__).resolve().parents[1]


class EvalRuntimeTests(unittest.TestCase):
    def test_parses_qwen_xml_tool_call_and_reasoning_prefix(self):
        raw = """<think>choose the title route</think>
<tool_call>
<function=catalog_search>
<parameter=query>
Copper Meridian 12
</parameter>
<parameter=keywords>
[\"signal\",\"desert\"]
</parameter>
</function>
</tool_call><|im_end|>"""
        self.assertEqual(
            parse_qwen_turn(raw, 7),
            {
                "role": "assistant",
                "toolCalls": [
                    {
                        "id": "model-call-7",
                        "name": "catalog_search",
                        "arguments": {
                            "query": "Copper Meridian 12",
                            "keywords": ["signal", "desert"],
                        },
                    }
                ],
            },
        )

    def test_malformed_tool_markup_remains_content_and_fails_later_schema_checks(self):
        raw = "<tool_call><function=catalog_search>junk</function></tool_call>"
        self.assertEqual(parse_qwen_turn(raw, 1), {"role": "assistant", "content": raw})

    def test_converts_tool_messages_for_the_pinned_chat_template(self):
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "intent"},
            {
                "role": "assistant",
                "toolCalls": [
                    {"id": "call-1", "name": "catalog_search", "arguments": {"query": "X"}}
                ],
            },
            {
                "role": "tool",
                "toolCallId": "call-1",
                "name": "catalog_search",
                "content": {"candidates": []},
            },
        ]
        converted = _to_huggingface_messages(messages)
        self.assertEqual(converted[2]["tool_calls"][0]["function"]["arguments"], {"query": "X"})
        self.assertEqual(converted[3]["tool_call_id"], "call-1")
        self.assertEqual(converted[3]["content"], '{"candidates":[]}')

    def test_unsloth_import_precedes_torch_and_peft(self):
        source = (ROOT / "src/loomarr_models/eval_runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_evaluation"
        )
        imports = [
            (index, alias.name)
            for index, node in enumerate(function.body)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        positions = {name: index for index, name in imports if name in {"FastModel", "torch", "PeftModel"}}
        self.assertLess(positions["FastModel"], positions["torch"])
        self.assertLess(positions["FastModel"], positions["PeftModel"])


if __name__ == "__main__":
    unittest.main()
