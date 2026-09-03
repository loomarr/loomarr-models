from __future__ import annotations

import ast
import unittest
from pathlib import Path

from loomarr_models.eval_runtime import (
    HuggingFaceTurnGenerator,
    _to_huggingface_messages,
    parse_qwen_turn,
)


ROOT = Path(__file__).resolve().parents[1]


class EvalRuntimeTests(unittest.TestCase):
    def test_multimodal_processor_receives_rendered_prompt_as_text_keyword(self):
        class Tensor:
            shape = (1, 3)

        class Batch(dict):
            def to(self, _device):
                return self

        class Generated:
            shape = (2,)

        class Output:
            def __getitem__(self, key):
                self.key = key
                return Generated()

        class Tokenizer:
            eos_token_id = 1

            def apply_chat_template(self, *_args, **_kwargs):
                return "rendered prompt"

            def __call__(self, *args, **kwargs):
                if args or kwargs.get("text") != "rendered prompt":
                    raise AssertionError("multimodal processor input was not passed as text=")
                return Batch(input_ids=Tensor())

            def decode(self, _tokens, **_kwargs):
                return '{"channelName":"Test Signal","rationale":"Synthetic.","picks":[],"policy":{}}'

        class Model:
            device = "cuda:0"

            def generate(self, **_kwargs):
                return Output()

        class InferenceMode:
            def __enter__(self):
                return None

            def __exit__(self, *_args):
                return False

        class Torch:
            @staticmethod
            def inference_mode():
                return InferenceMode()

        generator = HuggingFaceTurnGenerator(
            Model(),
            Tokenizer(),
            {
                "reasoningEffort": "low",
                "maxSeqLength": 4096,
                "maxNewTokens": 768,
                "doSample": False,
            },
            Torch(),
        )
        turn = generator(
            [{"role": "system", "content": "system"}, {"role": "user", "content": "intent"}],
            [],
        )
        self.assertEqual(turn["role"], "assistant")
        self.assertIn("channelName", turn["content"])

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

    def test_model_load_keeps_embeddings_on_gpu_for_pinned_a40(self):
        source = (ROOT / "src/loomarr_models/eval_runtime.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_evaluation"
        )
        call = next(
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "from_pretrained"
        )
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        self.assertIn("offload_embedding", keywords)
        self.assertEqual(
            ast.unparse(keywords["offload_embedding"]),
            "comparison_config['offloadEmbedding']",
        )


if __name__ == "__main__":
    unittest.main()
