from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_planner_v4_local_screen as publication


class LocalScreenPublicationTests(unittest.TestCase):
    def test_published_mixed_outcome_is_hash_bound_and_non_authoritative(self):
        publication_path = ROOT / "runs/planner-v4-local-screen-v1/publication.json"
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        exposure = json.loads(
            (ROOT / "reviews/planner-v4-local-screen/development-exposure.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(publication["status"], "complete")
        self.assertEqual(publication["externalCostUsd"], "0")
        self.assertEqual(
            publication["decision"]["outcome"],
            "local-screen-rejects-gemma-qwen-authoritative-baseline-required",
        )
        self.assertFalse(publication["decision"]["trainingAuthorized"])
        self.assertFalse(publication["decision"]["releaseAuthorized"])
        self.assertEqual(
            publication["candidateEvidence"]["qwen38-27b-mlx-nvfp4"]["failure"]["kind"],
            "metal-out-of-memory",
        )
        gemma = publication["summaries"]["gemma4-12b-q4-k-m"]
        self.assertEqual(gemma["caseCount"], 120)
        self.assertEqual(gemma["hardFailureCount"], 120)
        self.assertEqual(gemma["schemaValidityRate"], 0.0)
        self.assertEqual(gemma["qualityScore"], 0.043333333333333335)
        self.assertEqual(exposure["status"], "local-screen-complete")
        self.assertEqual(
            exposure["exposures"][0]["publicationSha256"],
            hashlib.sha256(publication_path.read_bytes()).hexdigest(),
        )

    def test_qwen_pass_means_training_is_not_justified_by_screen(self):
        decision = publication._decision(
            {
                "qwen38-27b-mlx-nvfp4": {"status": "complete", "summary": self._summary()},
                "gemma4-12b-q4-k-m": {
                    "status": "complete",
                    "summary": self._summary(proposalQualityRate=0.8),
                },
            }
        )
        self.assertEqual(decision["outcome"], "qlora-not-justified-by-local-screen")
        self.assertFalse(decision["trainingAuthorized"])
        self.assertFalse(decision["releaseAuthorized"])

    def test_qwen_host_failure_and_gemma_pass_still_require_authoritative_baseline(self):
        decision = publication._decision(
            {
                "qwen38-27b-mlx-nvfp4": {"status": "failed"},
                "gemma4-12b-q4-k-m": {"status": "complete", "summary": self._summary()},
            }
        )
        self.assertEqual(
            decision["outcome"],
            "gemma-local-candidate-viable-qwen-authoritative-baseline-required",
        )

    def test_two_failures_require_authoritative_baseline(self):
        decision = publication._decision(
            {
                "qwen38-27b-mlx-nvfp4": {"status": "failed"},
                "gemma4-12b-q4-k-m": {
                    "status": "complete",
                    "summary": self._summary(hardFailureCount=1),
                },
            }
        )
        self.assertEqual(
            decision["outcome"],
            "local-screen-rejects-gemma-qwen-authoritative-baseline-required",
        )
        self.assertFalse(decision["certificationAuthority"])

    @staticmethod
    def _summary(**changes):
        value = {
            "groundedCompletionRate": 1.0,
            "correctToolOperationRate": 1.0,
            "schemaValidityRate": 1.0,
            "policyAccuracyRate": 1.0,
            "proposalQualityRate": 1.0,
            "recoveryRate": 1.0,
            "hardFailureCount": 0,
            "p95ToolCalls": 2,
        }
        value.update(changes)
        return value


if __name__ == "__main__":
    unittest.main()
