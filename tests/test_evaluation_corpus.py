from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from loomarr_models.evaluation import FAMILIES, load_cases, validate_development_corpus
from loomarr_models.validator import ValidationError, load_contract, load_denylist, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evaluation/planner-development-v1/cases.jsonl"
CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
TRAINING_PATH = ROOT / "corpus/planner-smoke-v1/traces.jsonl"


class EvaluationCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases(CASES_PATH)
        cls.contract = load_contract(CONTRACT_PATH)
        cls.identities, cls.digests = load_denylist(DENYLIST_PATH)
        cls.training = load_jsonl(TRAINING_PATH)

    def validate(self, cases=None, training=None):
        return validate_development_corpus(
            cases if cases is not None else self.cases,
            contract=self.contract,
            training_traces=training if training is not None else self.training,
            denylisted_identities=self.identities,
            denylisted_sha256=self.digests,
        )

    def test_current_corpus_is_fifty_balanced_disjoint_cases(self):
        report = self.validate()
        self.assertEqual(report.cases, 50)
        self.assertEqual(report.familyCounts, {family: 5 for family in FAMILIES})
        self.assertEqual(
            report.sha256,
            "2a3179166a05f068bcdc01fac32d1c4bc521bcf0b65f783163426408722a5209",
        )

    def test_rejects_training_intent_or_candidate_overlap(self):
        for sabotage in ("intent", "candidate"):
            with self.subTest(sabotage=sabotage):
                cases = copy.deepcopy(self.cases)
                training = copy.deepcopy(self.training)
                if sabotage == "intent":
                    cases[0]["intent"] = training[0]["messages"][1]["content"]
                else:
                    training_candidate = next(
                        candidate
                        for message in training[0]["messages"]
                        if message.get("role") == "tool"
                        for candidate in message["content"].get("candidates", [])
                    )
                    cases[0]["script"][0]["result"]["candidates"][0]["mediaType"] = (
                        training_candidate["mediaType"]
                    )
                    cases[0]["script"][0]["result"]["candidates"][0]["tmdbId"] = (
                        training_candidate["tmdbId"]
                    )
                    cases[0]["expectation"]["selectedIds"][0] = {
                        "mediaType": training_candidate["mediaType"],
                        "tmdbId": training_candidate["tmdbId"],
                    }
                with self.assertRaisesRegex(ValidationError, "overlaps training"):
                    self.validate(cases, training)

    def test_rejects_holdout_secret_and_private_path_leakage(self):
        leaks = (
            next(iter(self.identities)),
            next(iter(self.digests)),
            "sk_exampleSecretToken123",
            "/Users/alice/private/library.db",
        )
        for leaked in leaks:
            with self.subTest(leaked=leaked):
                cases = copy.deepcopy(self.cases)
                cases[0]["intent"] += f" {leaked}"
                with self.assertRaisesRegex(ValidationError, "holdout|secret or household"):
                    self.validate(cases)

    def test_rejects_unbalanced_or_duplicate_cases(self):
        for cases, message in (
            (self.cases[:-1], "five cases per ten axes"),
            ([*self.cases, copy.deepcopy(self.cases[0])], "duplicate caseId"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValidationError, message):
                    self.validate(cases)

    def test_rejects_unscripted_expected_id_or_contract_drift(self):
        cases = copy.deepcopy(self.cases)
        cases[0]["expectation"]["selectedIds"][0]["tmdbId"] = 999999
        with self.assertRaisesRegex(ValidationError, "unscripted id"):
            self.validate(cases)

        cases = copy.deepcopy(self.cases)
        cases[0]["contract"]["promptVersion"] = "untracked-prompt"
        with self.assertRaisesRegex(ValidationError, "contract identity drifted"):
            self.validate(cases)

    def test_manifest_binds_every_input_and_scoring_rule(self):
        manifest = json.loads(
            (ROOT / "evaluation/planner-development-v1/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["casesSha256"], self.validate().sha256)
        self.assertEqual(manifest["status"], "frozen-development-only")
        self.assertEqual(manifest["scoring"]["qualityMargin"], 0.02)
        self.assertAlmostEqual(sum(manifest["scoring"]["weights"].values()), 1.0)
        self.assertEqual(manifest["trainingCorpusSha256"], "56663b037c2d298c0bbd4b4a7f30368631f495e7618d3089ee97f14504c0df5b")


if __name__ == "__main__":
    unittest.main()
