from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_contract_v2 as builder
from loomarr_models.current_contract import read_jsonl
from loomarr_models.current_gate_v2 import evaluate_current_case_v2, meanings_equivalent, policy_matches, step_accepts


CASES = {case["axis"]: case for case in read_jsonl(ROOT / "evaluation/planner-current-v2/cases.jsonl")}
CONTRACT = json.loads((ROOT / "contracts/planner-contract-v5.json").read_text(encoding="utf-8"))


def _step(axis: str, index: int = 0) -> dict:
    return CASES[axis]["script"][index]


def _with(axis: str, **changes) -> dict:
    arguments = copy.deepcopy(_step(axis)["arguments"])
    for key, value in changes.items():
        if value is None:
            arguments.pop(key, None)
        else:
            arguments[key] = value
    return arguments


class GateV2Tests(unittest.TestCase):
    def test_generated_artifacts_are_current(self):
        for path, blob in builder.build_outputs().items():
            self.assertEqual((ROOT / path).read_bytes(), blob, path)

    def test_every_canonical_scripted_call_is_accepted(self):
        for case in CASES.values():
            for step in case["script"]:
                self.assertTrue(step_accepts(step, step["arguments"]), case["caseId"])

    def test_reasonable_equivalent_calls_are_accepted(self):
        self.assertTrue(step_accepts(_step("date-movie-release"), _with("date-movie-release", keywords=["ocean", "beach", "coastal"])))
        self.assertTrue(step_accepts(_step("exact-title-unfamiliar"), _with("exact-title-unfamiliar", media_type=None)))
        self.assertTrue(step_accepts(_step("thin-results"), _with("thin-results", keywords=["orchard"], genres=["Fantasy"])))
        self.assertTrue(step_accepts(_step("medium-constraint"), _with("medium-constraint", genres=None, keywords=["mountains"])))

    def test_genuine_errors_are_rejected(self):
        creator = _with("creator-routing", cast=_step("creator-routing")["arguments"]["creators"], creators=None)
        self.assertFalse(step_accepts(_step("creator-routing"), creator))
        self.assertFalse(step_accepts(_step("date-series-premiere"), _with("date-series-premiere", runtime_max=90)))
        self.assertFalse(step_accepts(_step("season-window"), _with("season-window", media_type="movie")))
        self.assertFalse(step_accepts(_step("date-ambiguity"), _with("date-ambiguity", genres=None, mode="collection", titles=["Casablanca"])))
        self.assertFalse(step_accepts(_step("date-series-airing"), _with("date-series-airing", genres=["Drama"])))

    def test_split_date_anchors_are_equivalent_but_other_years_are_not(self):
        canonical = _step("date-disjoint-intervals")["arguments"]["dateMeaning"]
        split = copy.deepcopy(canonical)
        split["anchors"] = [{"field": "description", "start": 0, "end": 5}, {"field": "description", "start": 9, "end": 14}]
        split["axes"][0]["intervals"][1]["anchor"] = 1
        self.assertTrue(meanings_equivalent(split, canonical))
        wrong = copy.deepcopy(split)
        wrong["axes"][0]["intervals"][1]["start"] = 2010
        self.assertFalse(meanings_equivalent(wrong, canonical))

    def test_policy_follows_the_production_prompt(self):
        plain = CASES["cast-routing"]["expectation"]["policy"]
        capped = CASES["audience-ceiling"]["expectation"]["policy"]
        self.assertTrue(policy_matches(plain, {"genres": {"include": ["Drama"]}, "ordering": "shuffle"}))
        self.assertTrue(policy_matches(plain, {}))
        self.assertFalse(policy_matches(plain, {"audience": {"ceiling": "TV-14"}}))
        self.assertFalse(policy_matches(plain, {"rules": [{"when": "weekend-daytime"}]}))
        self.assertFalse(policy_matches(plain, {"ordering": "random"}))
        self.assertTrue(policy_matches(capped, {"audience": {"ceiling": "TV-14"}, "genres": {"include": ["Science Fiction"]}}))
        self.assertFalse(policy_matches(capped, {"genres": {"include": ["Science Fiction"]}}))

    def test_replaying_an_ideal_trajectory_passes_every_metric(self):
        case = CASES["date-movie-release"]
        turns = [{"role": "assistant", "toolCalls": [{"id": "c1", "name": "catalog_search", "arguments": step["arguments"]}]} for step in case["script"]]
        candidates = json.loads(case["script"][0]["result"])
        final = {
            "channelName": "Coastal Nights",
            "rationale": "Nineties coastal thrillers.",
            "dateMeaning": case["expectation"]["dateMeaning"],
            "picks": [{"mediaType": c["mediaType"], "key": c["key"], "name": c["name"], "rationale": "Fits.", "confidence": 0.9} for c in candidates],
            "policy": {"genres": {"include": ["Thriller"]}, "ordering": "shuffle"},
        }
        turns.append({"role": "assistant", "content": json.dumps(final)})
        result = evaluate_current_case_v2(case, system_prompt=CONTRACT["systemPrompt"], tools=CONTRACT["tools"], generate=lambda _m, _t: turns.pop(0))
        self.assertEqual(result.hardFailures, [])
        self.assertTrue(result.policyAccuracy and result.correctToolOperation and result.dateMeaningAccuracy)

    def test_v2_drafts_carry_prompt_aligned_policy_and_stay_pending(self):
        drafts = read_jsonl(ROOT / "corpus/planner-current-v2/drafts.jsonl")
        policies = {d["axes"][0]: json.loads(d["messages"][-1]["content"])["policy"] for d in drafts}
        self.assertEqual(policies["audience-ceiling"], {"audience": {"ceiling": "TV-PG"}, "genres": {"include": ["Animation"]}})
        self.assertEqual(policies["date-movie-release"], {"genres": {"include": ["Adventure"]}})
        self.assertEqual(policies["exact-key-final"], {})
        self.assertTrue(all(d["review"]["status"] == "pending" for d in drafts))
