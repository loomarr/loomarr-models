from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from loomarr_models.evaluation import load_cases
from loomarr_models.planner_v4 import (
    DEVELOPMENT_BEHAVIORS,
    ENTITY_BEHAVIORS,
    validate_delta_training,
    validate_development,
    validate_disjoint_splits,
)
from loomarr_models.v4_review import derive_review, load_review_decisions
from loomarr_models.validator import ValidationError, load_contract, load_denylist, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts/planner-contract-v4.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
TRAINING_PATH = ROOT / "corpus/planner-v4-delta/drafts.jsonl"
TRAINING_MANIFEST_PATH = ROOT / "corpus/planner-v4-delta/draft-manifest.json"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-development-v4/cases.jsonl"
DEVELOPMENT_MANIFEST_PATH = ROOT / "evaluation/planner-development-v4/manifest.json"
DISJOINTNESS_PATH = ROOT / "reports/planner-v4-disjointness.json"
REVIEW_PATH = ROOT / "reviews/planner-v4-delta.jsonl"
PRIOR_SPLITS = {
    "planner-smoke-v1": ROOT / "corpus/planner-smoke-v1/traces.jsonl",
    "planner-development-v1": ROOT / "evaluation/planner-development-v1/cases.jsonl",
    "planner-behavior-v2": ROOT / "corpus/planner-behavior-v2/traces.jsonl",
    "planner-behavior-development-v2": ROOT / "evaluation/planner-behavior-development-v2/cases.jsonl",
}


class PlannerV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(CONTRACT_PATH)
        cls.identities, cls.digests = load_denylist(DENYLIST_PATH)
        cls.training = load_jsonl(TRAINING_PATH)
        cls.development = load_cases(DEVELOPMENT_PATH)

    def validate_training(self, traces=None):
        return validate_delta_training(
            traces if traces is not None else self.training,
            contract=self.contract,
            denylisted_identities=self.identities,
            denylisted_sha256=self.digests,
        )

    def validate_development(self, cases=None):
        return validate_development(
            cases if cases is not None else self.development,
            contract=self.contract,
            denylisted_identities=self.identities,
            denylisted_sha256=self.digests,
        )

    def test_exact_pending_delta_and_fresh_v4_development_gate(self):
        training = self.validate_training()
        development = self.validate_development()
        self.assertEqual(training.records, 60)
        self.assertEqual(development.records, 120)
        self.assertEqual(training.behavior_counts, {behavior: 10 for behavior in ENTITY_BEHAVIORS})
        self.assertEqual(
            development.behavior_counts,
            {behavior: 10 for behavior in DEVELOPMENT_BEHAVIORS},
        )
        self.assertTrue(all(trace["review"]["status"] == "pending" for trace in self.training))
        self.assertTrue(all("messages" not in case and "review" not in case for case in self.development))

    def test_entity_route_sabotage_fails_closed(self):
        wrong_media = copy.deepcopy(self.training)
        wrong_media[0]["messages"][2]["toolCalls"][0]["arguments"]["media_type"] = "movie"
        with self.assertRaisesRegex(ValidationError, "network requires media_type series"):
            self.validate_training(wrong_media)

        invalid_mix = copy.deepcopy(self.training)
        series_evidence = next(
            trace for trace in invalid_mix if trace["axes"] == ["series-person-evidence-routing"]
        )
        series_evidence["messages"][2]["toolCalls"][0]["arguments"]["cast"] = [
            "Saffron Performer 1"
        ]
        with self.assertRaisesRegex(ValidationError, "network and person constraints"):
            self.validate_training(invalid_mix)

        wrong_person_role = copy.deepcopy(self.development)
        creator = next(case for case in wrong_person_role if case["axis"] == "creator-routing")
        arguments = creator["script"][0]["arguments"]
        arguments["cast"] = arguments.pop("creators")
        with self.assertRaisesRegex(ValidationError, "creator route arguments drifted"):
            self.validate_development(wrong_person_role)

    def test_all_six_data_splits_are_pairwise_disjoint(self):
        prior = {
            name: load_jsonl(path) if "development" not in name else load_cases(path)
            for name, path in PRIOR_SPLITS.items()
        }
        report = validate_disjoint_splits(
            {**prior, "planner-v4-delta": self.training, "planner-development-v4": self.development}
        )
        self.assertEqual(report.pair_count, 15)
        self.assertEqual(report.splits["planner-v4-delta"], 60)
        self.assertEqual(report.splits["planner-development-v4"], 120)

    def test_review_ledger_is_exact_and_carries_no_false_evidence(self):
        trace_ids = [trace["traceId"] for trace in self.training]
        decisions = load_review_decisions(REVIEW_PATH, trace_ids)
        self.assertEqual(len(decisions), 60)
        self.assertTrue(all(derive_review(decision).status == "pending" for decision in decisions.values()))

    def test_manifests_bind_generated_artifacts(self):
        training = json.loads(TRAINING_MANIFEST_PATH.read_text(encoding="utf-8"))
        development = json.loads(DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8"))
        disjointness = json.loads(DISJOINTNESS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(training["tracesSha256"], hashlib.sha256(TRAINING_PATH.read_bytes()).hexdigest())
        self.assertEqual(
            development["casesSha256"], hashlib.sha256(DEVELOPMENT_PATH.read_bytes()).hexdigest()
        )
        self.assertEqual(training["contractId"], "loomarr-planner-contract-v4")
        self.assertEqual(training["review"], {"approved": 0, "pending": 60, "rejected": 0})
        self.assertEqual(disjointness["pairwiseComparisons"], 15)
        self.assertEqual(
            training["disjointnessReportSha256"],
            hashlib.sha256(DISJOINTNESS_PATH.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
