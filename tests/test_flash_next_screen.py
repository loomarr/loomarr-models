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


CONFIG = ROOT / "experiments/planner-current-flash-next-screen-v2.json"


def _probe(_root: Path, _paths: object) -> str:
    return "0" * 40


def _call(name: str, arguments: object) -> dict:
    return {"id": "x", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class FlashNextScreenTests(unittest.TestCase):
    def test_generated_plans_are_current(self):
        for gate in screen.GATES:
            self.assertEqual((ROOT / builder.output(gate)).read_bytes(), builder.content(gate))

    def test_v2_plan_binds_v2_cases_and_scorer(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["bindings"]["cases"]["path"], "evaluation/planner-current-v2/cases.jsonl")
        self.assertEqual(config["scoring"]["scorerVersion"], "planner-current-development-scorer-v3")

    def test_preflight_accepts_committed_plan(self):
        plan = screen.preflight(ROOT, CONFIG, git_probe=_probe)
        self.assertEqual(plan["externalSpendUsd"], "0")

    def test_preflight_rejects_tampered_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in [*screen.bindings("v2").values(), str(CONFIG.relative_to(ROOT))]:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, root / path)
            with (root / screen.GATES["v2"]["cases"]).open("a", encoding="utf-8") as handle:
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
        case = read_jsonl(ROOT / screen.GATES["v1"]["cases"])[0]
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


class PromptCandidateTests(unittest.TestCase):
    def test_candidate_rules_are_inserted_once_before_the_final_json_instruction(self):
        contract = json.loads((ROOT / screen.BINDINGS["contract"]).read_text(encoding="utf-8"))
        patched = screen.apply_prompt(contract["systemPrompt"], ROOT / screen.PROMPTS["candidate-a"])
        self.assertEqual(patched.count("ONE SEARCH PER TURN"), 1)
        self.assertLess(patched.index("ONE SEARCH PER TURN"), patched.index(screen.PROMPT_ANCHOR))
        self.assertTrue(patched.startswith(contract["systemPrompt"].split(screen.PROMPT_ANCHOR)[0]))

    def test_production_prompt_is_unchanged(self):
        contract = json.loads((ROOT / screen.BINDINGS["contract"]).read_text(encoding="utf-8"))
        self.assertEqual(screen.apply_prompt(contract["systemPrompt"], None), contract["systemPrompt"])

    def test_trainsplit_screen_is_never_a_training_gate(self):
        manifest = json.loads((ROOT / screen.GATES["v2-trainsplit"]["casesManifest"]).read_text(encoding="utf-8"))
        self.assertIs(manifest["trainingDecisionAuthority"], False)
        cases = read_jsonl(ROOT / screen.GATES["v2-trainsplit"]["cases"])
        self.assertEqual(len(cases), 24)
        keys = [key for c in cases for key in c["expectation"]["selectedKeys"]]
        self.assertTrue(keys and all(key.split(":")[2].startswith("97") for key in keys))


class WireProfileTests(unittest.TestCase):
    TOOLS = [{"Name": "catalog_search", "Description": "d", "Parameters": {"type": "object"}}]

    def test_search_turn_matches_loomarr_selfhosted_request(self):
        payload = screen.request_payload("m", [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], self.TOOLS, {})
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["max_tokens"], 640)
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("response_format", payload)
        self.assertNotIn("tool_choice", payload)

    def test_finalization_keeps_tools_but_forbids_calls_and_asks_for_json(self):
        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "toolCalls": [{"id": "c", "name": "catalog_search", "arguments": {}}]},
            {"role": "tool", "toolCallId": "c", "name": "catalog_search", "content": "[]"},
            {"role": "user", "content": "Retrieval is complete."},
        ]
        payload = screen.request_payload("m", messages, self.TOOLS, {})
        self.assertEqual(payload["max_tokens"], 1024)
        self.assertEqual(payload["tool_choice"], "none")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertTrue(payload["tools"])
