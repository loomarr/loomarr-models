from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_flash_next_screen as builder
from loomarr_models import flash_next_screen as screen
from loomarr_models.current_baseline import evaluate_current_case
from loomarr_models.current_contract import read_jsonl
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-current-flash-next-screen-v1.json"


def _probe(_root: Path, _paths: object) -> str:
    return "0" * 40


def _call(name: str, arguments: object) -> dict:
    return {"id": "x", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class FlashNextScreenTests(unittest.TestCase):
    def test_generated_plan_is_current(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())

    def test_preflight_accepts_committed_plan(self):
        plan = screen.preflight(ROOT, CONFIG, git_probe=_probe)
        self.assertEqual(plan["externalSpendUsd"], "0")

    def test_preflight_rejects_tampered_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in [*screen.BINDINGS.values(), str(CONFIG.relative_to(ROOT))]:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, root / path)
            with (root / screen.BINDINGS["cases"]).open("a", encoding="utf-8") as handle:
                handle.write("\n")
            with self.assertRaisesRegex(PreflightError, "cases digest mismatch"):
                screen.preflight(root, root / CONFIG.relative_to(ROOT), git_probe=_probe)

    def test_parses_single_tool_call_arguments(self):
        turn = screen.parse_openai_turn({"tool_calls": [_call("catalog_search", {"query": "x"})]}, 1)
        self.assertEqual(turn["toolCalls"], [{"id": "model-call-1-0", "name": "catalog_search", "arguments": {"query": "x"}}])

    def test_strips_reasoning_from_final_content(self):
        turn = screen.parse_openai_turn({"content": "<think>plan</think>\n{\"a\": 1}"}, 1)
        self.assertEqual(turn, {"role": "assistant", "content": "{\"a\": 1}"})

    def test_parallel_tool_calls_fail_the_single_operation_contract(self):
        case = read_jsonl(ROOT / screen.BINDINGS["cases"])[0]
        contract = json.loads((ROOT / screen.BINDINGS["contract"]).read_text(encoding="utf-8"))
        two_calls = screen.parse_openai_turn(
            {"tool_calls": [_call("catalog_search", {"query": "a"}), _call("catalog_search", {"query": "b"})]}, 1
        )
        result = evaluate_current_case(
            case,
            system_prompt=contract["systemPrompt"],
            tools=contract["tools"],
            generate=lambda _messages, _tools: two_calls,
        )
        self.assertIn("incorrect_tool_operation", result.as_dict()["hardFailures"])

    def test_replayed_tool_call_arguments_are_json_strings(self):
        messages = [
            {"role": "assistant", "toolCalls": [{"id": "c1", "name": "catalog_search", "arguments": {"query": "x"}}]}
        ]
        converted = screen._to_openai_messages(messages)
        self.assertEqual(converted[0]["tool_calls"][0]["function"]["arguments"], '{"query": "x"}')


if __name__ == "__main__":
    unittest.main()
