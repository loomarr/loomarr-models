from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_filler_text_gate as builder
from loomarr_models import filler_text_gate as gate


CONTRACT, TAXONOMY = gate.load_contract(ROOT)
CASES = {case["caseId"]: case for case in (json.loads(l) for l in (ROOT / builder.CASES).read_text().splitlines())}


def _score(case_id: str, output: object) -> dict:
    content = output if isinstance(output, str) else json.dumps(output)
    return gate.score(CONTRACT, TAXONOMY, CASES[case_id], content)


class FillerTextGateTests(unittest.TestCase):
    def test_generated_cases_are_current(self):
        for path, blob in builder.build().items():
            self.assertEqual((ROOT / path).read_bytes(), blob, path)

    def test_contract_vocab_matches_pinned_go_output(self):
        vocab = CONTRACT["taxonomy"]["vocab"]
        self.assertEqual(hashlib.sha256(vocab.encode()).hexdigest(), CONTRACT["taxonomy"]["sha256"])
        self.assertTrue(all(site["system"] for site in CONTRACT["callSites"].values()))

    def test_render_matches_loomarr_templates(self):
        _system, user = gate.render(CONTRACT, CASES["filler-split-rescue-two-back-to-back"])
        self.assertTrue(user.startswith("Transcript:\n[00:00] Fizzleberry Cola"))
        self.assertTrue(user.endswith("\nFind the advert boundaries."))
        payload = gate.request_payload(CONTRACT, CASES["filler-text-single-soda-commercial"], "m")
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})

    def test_text_scoring_grounds_brand_and_resolves_synonyms(self):
        good = {"kind": "commercial", "brand": "Fizzleberry", "product": ["cola"], "seasonal": [], "confidence": 70}
        self.assertTrue(_score("filler-text-single-soda-commercial", good)["passed"])
        invented = dict(good, brand="Sprinkle Cola")
        self.assertFalse(_score("filler-text-single-soda-commercial", invented)["checks"]["brand"])

    def test_child_tag_satisfies_expected_parent(self):
        output = {"kind": "commercial", "product": ["dealer"], "seasonal": [], "confidence": 60}
        self.assertTrue(_score("filler-text-single-truck-dealer", output)["checks"]["product"])

    def test_abstention_requires_empty_fields(self):
        guessed = {"brand": "", "seasonal": ["christmas"], "audience": "", "confidence": 40}
        self.assertFalse(_score("filler-text-single-unbranded-generic", guessed)["passed"])

    def test_research_rejects_injected_values_and_urls(self):
        obeyed = {"year": 1955, "decade": 1950, "countryCode": "JP", "confidence": 60, "explanation": "", "citationIds": [1]}
        self.assertFalse(_score("filler-research-prompt-injection", obeyed)["passed"])
        url = {"year": 0, "decade": 0, "countryCode": "", "confidence": 10, "explanation": "see https://x.invalid", "citationIds": [1]}
        self.assertFalse(_score("filler-research-weak-evidence", url)["checks"]["noUrl"])

    def test_rescue_is_strict_json_and_checks_boundaries(self):
        spans = {"adverts": [{"start": "00:00", "end": "00:29", "product": "Fizzleberry Cola"},
                             {"start": "00:31", "end": "00:50", "product": "Tundrix trucks"}]}
        self.assertTrue(_score("filler-split-rescue-two-back-to-back", spans)["passed"])
        self.assertFalse(_score("filler-split-rescue-two-back-to-back", "```json\n" + json.dumps(spans) + "\n```")["checks"]["json"])
        late = {"adverts": [{"start": "00:00", "end": "00:40", "product": "Fizzleberry"},
                            {"start": "00:40", "end": "00:50", "product": "Tundrix"}]}
        self.assertFalse(_score("filler-split-rescue-two-back-to-back", late)["checks"]["boundaries"])

    def test_extract_json_object_mirrors_loomarr(self):
        self.assertEqual(gate.extract_json_object('x {"a": "}", "b": {"c": 1}} {y}'), '{"a": "}", "b": {"c": 1}}')
        self.assertEqual(gate.extract_json_object("x {unbalanced"), "x {unbalanced")
