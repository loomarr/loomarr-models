from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from loomarr_models.current_contract import (
    CURRENT_CAPABILITIES,
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_current_development_case,
    validate_current_trace,
    validate_disjoint_splits,
)
from loomarr_models.validator import ValidationError


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts/planner-contract-v5.json"
DENYLIST_PATH = ROOT / "contracts/planner-holdout-denylist-v2.json"
TRAINING_PATH = ROOT / "corpus/planner-current-v1/drafts.jsonl"
TRAINING_MANIFEST_PATH = ROOT / "corpus/planner-current-v1/draft-manifest.json"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-current-v1/cases.jsonl"
DEVELOPMENT_MANIFEST_PATH = ROOT / "evaluation/planner-current-v1/manifest.json"
COMPATIBILITY_PATH = ROOT / "reports/planner-current-contract-compatibility-v1.json"


class CurrentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.training = read_jsonl(TRAINING_PATH)
        cls.development = read_jsonl(DEVELOPMENT_PATH)
        cls.denylist = load_current_denylist(DENYLIST_PATH)

    def test_current_artifacts_cover_every_capability_and_validate(self):
        self.assertEqual(len(self.training), len(CURRENT_CAPABILITIES))
        self.assertEqual(len(self.development), len(CURRENT_CAPABILITIES))
        self.assertEqual({trace["axes"][0] for trace in self.training}, set(CURRENT_CAPABILITIES))
        self.assertEqual({case["axis"] for case in self.development}, set(CURRENT_CAPABILITIES))
        for trace in self.training:
            validate_current_trace(trace, self.contract, "planner-current-training-catalog-v1")
            assert_not_denylisted(trace["traceId"], trace, *self.denylist)
        for case in self.development:
            validate_current_development_case(case, self.contract, "planner-current-development-catalog-v1")
            assert_not_denylisted(case["caseId"], case, *self.denylist)

    def test_contract_and_hash_only_denylist_bind_the_same_source_revision(self):
        denylist = json.loads(DENYLIST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.contract["sourceRevision"], denylist["sourceRevision"])
        self.assertFalse(denylist["protection"]["rawApplicationContentStored"])
        self.assertGreater(len(denylist["artifactBindings"]), 40)
        for field in ("exactValueSha256", "normalizedTextSha256"):
            self.assertTrue(denylist["protection"][field])
            self.assertTrue(all(len(value) == 64 for value in denylist["protection"][field]))

    def test_missing_date_meaning_and_obsolete_or_ungrounded_finals_fail_closed(self):
        missing_meaning = copy.deepcopy(self.training[0])
        del missing_meaning["messages"][2]["toolCalls"][0]["arguments"]["dateMeaning"]
        with self.assertRaisesRegex(ValidationError, "dateMeaning is required"):
            validate_current_trace(missing_meaning, self.contract, "planner-current-training-catalog-v1")

        obsolete_id = copy.deepcopy(self.training[0])
        final = json.loads(obsolete_id["messages"][-1]["content"])
        final["picks"][0]["tmdbId"] = 42
        obsolete_id["messages"][-1]["content"] = json.dumps(final)
        with self.assertRaisesRegex(ValidationError, "obsolete external-ID"):
            validate_current_trace(obsolete_id, self.contract, "planner-current-training-catalog-v1")

        replaced_key = copy.deepcopy(self.training[0])
        final = json.loads(replaced_key["messages"][-1]["content"])
        final["picks"][0]["key"] = "movie:synthetic:not-surfaced"
        replaced_key["messages"][-1]["content"] = json.dumps(final)
        with self.assertRaisesRegex(ValidationError, "not grounded"):
            validate_current_trace(replaced_key, self.contract, "planner-current-training-catalog-v1")

        unsupported_tool = copy.deepcopy(self.training[0])
        unsupported_tool["messages"][2]["toolCalls"][0]["arguments"]["invented_operation"] = True
        with self.assertRaisesRegex(ValidationError, "unsupported tool arguments"):
            validate_current_trace(unsupported_tool, self.contract, "planner-current-training-catalog-v1")

        stale_policy = copy.deepcopy(self.training[0])
        final = json.loads(stale_policy["messages"][-1]["content"])
        final["policy"]["legacySchedule"] = "weekends"
        stale_policy["messages"][-1]["content"] = json.dumps(final)
        with self.assertRaisesRegex(ValidationError, "stale or unsupported"):
            validate_current_trace(stale_policy, self.contract, "planner-current-training-catalog-v1")

    def test_recovery_requires_an_injected_observed_fault(self):
        recovery = copy.deepcopy(next(case for case in self.development if case["axis"] == "observed-fault-recovery"))
        fault = json.loads(recovery["script"][0]["result"])
        fault["fault"]["observed"] = False
        recovery["script"][0]["result"] = json.dumps(fault)
        with self.assertRaisesRegex(ValidationError, "lacks observed fault evidence"):
            validate_current_development_case(recovery, self.contract, "planner-current-development-catalog-v1")

    def test_synthetic_evidence_encodes_the_behavior_instead_of_only_the_shape(self):
        cases = {case["axis"]: case for case in self.development}

        empty = cases["empty-results"]
        self.assertEqual(len(empty["script"]), 2)
        self.assertIn("keywords", empty["script"][0]["arguments"])
        self.assertIn("query", empty["script"][1]["arguments"])

        network = cases["network-editorial-epoch"]
        self.assertEqual(network["script"][0]["arguments"]["dateMeaning"]["kind"], "none")
        network_result = json.loads(network["script"][0]["result"])[0]
        self.assertEqual(network_result["networks"], [network["script"][0]["arguments"]["network"]])

        dated_movie = cases["date-movie-release"]
        dated_result = json.loads(dated_movie["script"][0]["result"])[0]
        self.assertLessEqual(1990, dated_result["year"])
        self.assertLessEqual(dated_result["year"], 1999)

        refinement = next(trace for trace in self.training if trace["axes"] == ["refinement-preservation"])
        refinement_prompt = refinement["messages"][1]["content"]
        self.assertTrue(refinement_prompt.startswith("This channel already exists:"))
        self.assertIn("The user wants to change it:", refinement_prompt)
        self.assertIn("Re-ground EVERY title", refinement_prompt)

        conflict = next(trace for trace in self.training if trace["axes"] == ["constraint-conflict-abstention"])
        self.assertIn("Must include: Amber Signal", conflict["messages"][1]["content"])
        self.assertIn("Must exclude: Amber Signal", conflict["messages"][1]["content"])

    def test_normalized_semantic_overlap_fails_even_with_new_ids_and_keys(self):
        left = copy.deepcopy(self.training[0])
        right = copy.deepcopy(self.development[0])
        right["provenance"]["intent"] = left["provenance"]["intent"]
        right["intent"] = left["provenance"]["intent"]
        right["script"][0]["arguments"] = left["messages"][2]["toolCalls"][0]["arguments"]
        with self.assertRaisesRegex(ValidationError, "normalized semantic overlap"):
            validate_disjoint_splits({"left": [left], "right": [right]})

    def test_denylist_rejects_a_protected_application_value(self):
        record = copy.deepcopy(self.development[0])
        record["intent"]["description"] = "protected application case"
        exact = {hashlib.sha256(b"protected application case").hexdigest()}
        with self.assertRaisesRegex(ValidationError, "application evaluation value leaked"):
            assert_not_denylisted(record["caseId"], record, exact, set(), 1, {"description"})

    def test_historical_artifacts_are_machine_excluded(self):
        report = json.loads(COMPATIBILITY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(report["decision"], "exclude-all-historical-v3-v4-training-and-development-records")
        self.assertEqual(report["activeMixture"], [])
        self.assertEqual(report["candidateMixtureAfterIndependentReview"], ["corpus/planner-current-v1/drafts.jsonl"])
        self.assertEqual([item["records"] for item in report["historicalArtifacts"]], [120, 60, 50, 120])
        self.assertTrue(all(item["currentContractCompatibleRecords"] == 0 for item in report["historicalArtifacts"]))
        self.assertTrue(all(not Path(item["path"]).is_absolute() for item in report["historicalArtifacts"]))

    def test_manifests_bind_artifacts_and_holdout_hashes(self):
        training = json.loads(TRAINING_MANIFEST_PATH.read_text(encoding="utf-8"))
        development = json.loads(DEVELOPMENT_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(training["sha256"], hashlib.sha256(TRAINING_PATH.read_bytes()).hexdigest())
        self.assertEqual(development["sha256"], hashlib.sha256(DEVELOPMENT_PATH.read_bytes()).hexdigest())
        expected_denylist = hashlib.sha256(DENYLIST_PATH.read_bytes()).hexdigest()
        self.assertEqual(training["holdoutDenylist"]["sha256"], expected_denylist)
        self.assertEqual(development["holdoutDenylist"]["sha256"], expected_denylist)
        self.assertEqual(training["reviewStatus"], "pending")
        self.assertFalse(training["trainingAuthorized"])
        self.assertEqual(development["modelExposure"], "none")
        self.assertFalse(development["certificationAuthority"])


if __name__ == "__main__":
    unittest.main()
