from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_planner_v4_local_screen as publication


class LocalScreenPublicationTests(unittest.TestCase):
    def test_qwen_pass_means_training_is_not_justified_by_screen(self):
        decision = publication._decision(
            {
                "qwen38-27b-mlx-nvfp4": self._summary(),
                "gemma4-12b-q4-k-m": self._summary(proposalQualityRate=0.8),
            }
        )
        self.assertEqual(decision["outcome"], "qlora-not-justified-by-local-screen")
        self.assertFalse(decision["trainingAuthorized"])
        self.assertFalse(decision["releaseAuthorized"])

    def test_only_gemma_pass_means_reconsider_base_before_training(self):
        decision = publication._decision(
            {
                "qwen38-27b-mlx-nvfp4": self._summary(policyAccuracyRate=0.8),
                "gemma4-12b-q4-k-m": self._summary(),
            }
        )
        self.assertEqual(decision["outcome"], "change-base-candidate-before-training")

    def test_two_failures_require_authoritative_baseline(self):
        decision = publication._decision(
            {
                "qwen38-27b-mlx-nvfp4": self._summary(schemaValidityRate=0.5),
                "gemma4-12b-q4-k-m": self._summary(hardFailureCount=1),
            }
        )
        self.assertEqual(
            decision["outcome"], "authoritative-a40-baseline-required-before-training"
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
