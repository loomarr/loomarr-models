from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from loomarr_models.behavior_review import (
    BehaviorReviewError,
    derive_review,
    load_review_decisions,
)
from loomarr_models.evaluation import load_cases
from loomarr_models.targeted import (
    BEHAVIORS,
    validate_disjoint_splits,
    validate_targeted_development,
    validate_targeted_training,
)
from loomarr_models.validator import ValidationError, load_contract, load_denylist, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
TRAINING_PATH = ROOT / "corpus/planner-behavior-v2/drafts.jsonl"
TRAINING_MANIFEST_PATH = ROOT / "corpus/planner-behavior-v2/draft-manifest.json"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-behavior-development-v2/cases.jsonl"
DEVELOPMENT_MANIFEST_PATH = ROOT / "evaluation/planner-behavior-development-v2/manifest.json"
PRIOR_TRAINING_PATH = ROOT / "corpus/planner-smoke-v1/traces.jsonl"
PRIOR_DEVELOPMENT_PATH = ROOT / "evaluation/planner-development-v1/cases.jsonl"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
REVIEW_PATH = ROOT / "reviews/planner-behavior-v2.jsonl"
PLAN_PATH = ROOT / "experiments/planner-behavior-review-v2.json"
INDEX_PATH = ROOT / "runs/planner-behavior-corpus-v2/index.json"


class TargetedCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(CONTRACT_PATH)
        cls.identities, cls.digests = load_denylist(DENYLIST_PATH)
        cls.training = load_jsonl(TRAINING_PATH)
        cls.development = load_cases(DEVELOPMENT_PATH)
        cls.prior_training = load_jsonl(PRIOR_TRAINING_PATH)
        cls.prior_development = load_cases(PRIOR_DEVELOPMENT_PATH)

    def validate_training(self, traces=None):
        return validate_targeted_training(
            traces if traces is not None else self.training,
            contract=self.contract,
            denylisted_identities=self.identities,
            denylisted_sha256=self.digests,
        )

    def validate_development(self, cases=None):
        return validate_targeted_development(
            cases if cases is not None else self.development,
            contract=self.contract,
            denylisted_identities=self.identities,
            denylisted_sha256=self.digests,
        )

    def test_exact_balanced_pending_training_and_untouched_development_gate(self):
        training = self.validate_training()
        development = self.validate_development()
        self.assertEqual(training.records, 120)
        self.assertEqual(development.records, 60)
        self.assertEqual(training.behaviorCounts, {behavior: 20 for behavior in BEHAVIORS})
        self.assertEqual(development.behaviorCounts, {behavior: 10 for behavior in BEHAVIORS})
        self.assertTrue(all(trace["review"]["status"] == "pending" for trace in self.training))
        self.assertTrue(all("messages" not in case and "review" not in case for case in self.development))

    def test_all_four_splits_are_pairwise_disjoint(self):
        report = validate_disjoint_splits(
            prior_training=self.prior_training,
            prior_development=self.prior_development,
            targeted_training=self.training,
            targeted_development=self.development,
            denylisted_identities=self.identities,
            denylisted_sha256=self.digests,
        )
        self.assertEqual(report.pairCount, 6)
        self.assertEqual(report.splits["planner-behavior-v2"]["records"], 120)
        self.assertEqual(report.splits["planner-behavior-development-v2"]["records"], 60)

    def test_training_rejects_each_observed_failure_class(self):
        sabotages = []

        unsupported = copy.deepcopy(self.training)
        final = json.loads(unsupported[0]["messages"][-1]["content"])
        final["picks"][0]["tmdbId"] = 999999
        unsupported[0]["messages"][-1]["content"] = json.dumps(final)
        sabotages.append((unsupported, "unsupported selected id"))

        malformed = copy.deepcopy(self.training)
        malformed[0]["messages"][2]["toolCalls"][0]["arguments"]["unknown"] = True
        sabotages.append((malformed, "invalid catalog_search arguments"))

        multiple = copy.deepcopy(self.training)
        extra = copy.deepcopy(multiple[20]["messages"][2]["toolCalls"][0])
        extra["id"] += "-extra"
        multiple[20]["messages"][2]["toolCalls"].append(extra)
        sabotages.append((multiple, "unresolved tool calls|exactly one tool operation"))

        missing_field = copy.deepcopy(self.training)
        final = json.loads(missing_field[40]["messages"][-1]["content"])
        del final["policy"]
        missing_field[40]["messages"][-1]["content"] = json.dumps(final)
        sabotages.append((missing_field, "required fields differ"))

        prose = copy.deepcopy(self.training)
        prose[60]["messages"][-1]["content"] = "I cannot make a proposal."
        sabotages.append((prose, "final assistant content is not JSON|prose or malformed"))

        wrong_recovery = copy.deepcopy(self.training)
        del wrong_recovery[80]["messages"][3]["content"]["error"]
        sabotages.append((wrong_recovery, "recovery order drifted"))

        fixture_refusal = copy.deepcopy(self.training)
        final = json.loads(fixture_refusal[80]["messages"][-1]["content"])
        final["picks"] = []
        fixture_refusal[80]["messages"][-1]["content"] = json.dumps(final)
        sabotages.append((fixture_refusal, "fixture was refused"))

        argument_drift = copy.deepcopy(self.training)
        del argument_drift[0]["messages"][2]["toolCalls"][0]["arguments"]["vote_count_min"]
        sabotages.append((argument_drift, "narrowed or altered"))

        for traces, message in sabotages:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValidationError, message):
                    self.validate_training(traces)

    def test_development_rejects_leakage_secrets_household_data_and_bad_expectations(self):
        certification = copy.deepcopy(self.development)
        certification[0]["intent"] += " " + next(iter(self.identities))
        with self.assertRaisesRegex(ValidationError, "holdout identity"):
            self.validate_development(certification)

        secret = copy.deepcopy(self.development)
        secret[0]["intent"] += " sk_exampleSecretToken123"
        with self.assertRaisesRegex(ValidationError, "secret"):
            self.validate_development(secret)

        household = copy.deepcopy(self.development)
        household[0]["intent"] = "Build this from my library and watch history."
        with self.assertRaisesRegex(ValidationError, "household-like"):
            self.validate_development(household)

        unsupported = copy.deepcopy(self.development)
        unsupported[0]["expectation"]["selectedIds"][0]["tmdbId"] = 999999
        with self.assertRaisesRegex(ValidationError, "unscripted id"):
            self.validate_development(unsupported)

    def test_disjointness_rejects_relabelled_cross_split_copy(self):
        development = copy.deepcopy(self.development)
        source = self.training[0]
        turns = source["messages"][2:-1]
        copied_script = [
            {
                "arguments": copy.deepcopy(turns[index]["toolCalls"][0]["arguments"]),
                "result": copy.deepcopy(turns[index + 1]["content"]),
            }
            for index in range(0, len(turns), 2)
        ]
        for step in copied_script:
            for candidate in step["result"].get("candidates", []):
                candidate["tmdbId"] += 50000
        development[0]["intent"] = source["messages"][1]["content"]
        development[0]["script"] = copied_script
        with self.assertRaisesRegex(ValidationError, "normalized digest overlap"):
            validate_disjoint_splits(
                prior_training=self.prior_training,
                prior_development=self.prior_development,
                targeted_training=self.training,
                targeted_development=development,
                denylisted_identities=self.identities,
                denylisted_sha256=self.digests,
            )

    def test_review_contract_is_exactly_120_independent_fail_closed_decisions(self):
        expected = [trace["traceId"] for trace in self.training]
        decisions = load_review_decisions(REVIEW_PATH, expected)
        self.assertEqual(len(decisions), 120)
        first = copy.deepcopy(next(iter(decisions.values())))
        first["primary"] = {
            "verdict": "approved",
            "reviewer": "openrouter:google/gemini-3.1-pro-preview",
            "reviewedAt": "2026-09-03T12:00:00Z",
            "notes": "All six criteria pass with trace-grounded evidence.",
        }
        self.assertEqual(derive_review(first).status, "pending")
        first["secondary"] = {
            "verdict": "approved",
            "reviewer": "openrouter:anthropic/claude-sonnet-4.6",
            "reviewedAt": "2026-09-03T12:00:01Z",
            "notes": "Independent review confirms every criterion.",
        }
        self.assertEqual(derive_review(first, require_complete=True).status, "approved")
        first["secondary"]["reviewer"] = first["primary"]["reviewer"]
        with self.assertRaisesRegex(BehaviorReviewError, "exact pinned model|independent"):
            derive_review(first)

    def test_manifests_plan_and_publication_index_bind_every_artifact(self):
        training_manifest = json.loads(TRAINING_MANIFEST_PATH.read_text(encoding="utf-8"))
        development_manifest = json.loads(DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(training_manifest["tracesSha256"], hashlib.sha256(TRAINING_PATH.read_bytes()).hexdigest())
        self.assertEqual(development_manifest["casesSha256"], hashlib.sha256(DEVELOPMENT_PATH.read_bytes()).hexdigest())
        self.assertEqual(training_manifest["status"], "draft-pending-independent-review")
        self.assertEqual(development_manifest["status"], "frozen-development-only")

        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(plan["status"], "complete-with-escalations")
        self.assertFalse(plan["execution"]["paidReviewAuthorized"])
        self.assertEqual(plan["budget"]["aggregateAuthorizationUsd"], "40.00")
        for value in plan["bindings"].values():
            path = ROOT / value["path"]
            self.assertEqual(value["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        self.assertFalse(index["trainingAuthorized"])
        for artifact in index["artifacts"]:
            path = ROOT / artifact["path"]
            self.assertEqual(artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
