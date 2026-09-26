from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "runs/planner-adapter-eval-v1/failure-analysis.json"


class FailureAnalysisTests(unittest.TestCase):
    def test_analysis_exhaustively_classifies_hash_bound_hard_failures(self):
        analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
        source = analysis["source"]
        manifest_path = ROOT / source["runManifestPath"]
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)

        self.assertEqual(
            hashlib.sha256(manifest_bytes).hexdigest(), source["runManifestSha256"]
        )
        self.assertEqual(
            manifest["replay"]["resultSha256"]["adapter"],
            source["correctedAdapterResultsSha256"],
        )
        self.assertEqual(
            manifest["sourceRun"]["rawArtifactSha256"]["adapterGenerations"],
            source["adapterGenerationsSha256"],
        )

        expected = {
            item["caseId"]
            for item in manifest["comparison"]["adapter"]["caseMetrics"]
            if item["hardFailures"]
        }
        classified = [
            case_id
            for group in analysis["categories"]
            for case_id in group["caseIds"]
        ]
        self.assertEqual(len(classified), len(set(classified)))
        self.assertEqual(set(classified), expected)
        self.assertEqual(
            sum(group["count"] for group in analysis["categories"]), len(classified)
        )
        for group in analysis["categories"]:
            self.assertEqual(group["count"], len(group["caseIds"]))

        summary = analysis["summary"]
        candidate = manifest["comparison"]["adapter"]
        self.assertEqual(summary["evaluatedCases"], candidate["caseCount"])
        self.assertEqual(summary["hardFailureCases"], len(expected))
        self.assertEqual(summary["hardFailureEvents"], candidate["hardFailureCount"])
        self.assertEqual(summary["hardFailureTypeCounts"], {"schema_invalid": 16})
        self.assertEqual(summary["unsupportedIdCount"], candidate["unsupportedIdCount"])
        self.assertEqual(
            summary["authorityViolationCount"], candidate["authorityViolationCount"]
        )

    def test_analysis_authorizes_no_training_or_release_action(self):
        analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
        decision = analysis["decision"]
        self.assertEqual(decision["status"], "no-second-training-run-on-current-corpus")
        self.assertFalse(decision["secondTrainingAuthorized"])
        self.assertFalse(decision["certificationAuthorized"])
        self.assertFalse(decision["packagingAuthorized"])
        self.assertFalse(decision["deploymentAuthorized"])
        self.assertEqual(decision["externalSpendUsd"], "0")
        self.assertEqual(len(decision["requiredCoverage"]), 6)


if __name__ == "__main__":
    unittest.main()
