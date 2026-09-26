from __future__ import annotations

import unittest

from loomarr_models.experiment import PreflightError
from loomarr_models.local_screen import SCORING
from loomarr_models.stock_runtime import baseline_decision, redact_generation_records


class StockBaselineRuntimeTests(unittest.TestCase):
    def test_stock_pass_blocks_qlora_without_granting_release(self):
        decision = baseline_decision(self._summary(), SCORING)
        self.assertEqual(
            decision["outcome"], "qlora-not-justified-stock-clears-development-gate"
        )
        self.assertFalse(decision["qloraJustified"])
        self.assertFalse(decision["trainingAuthorized"])
        self.assertFalse(decision["releaseAuthorized"])

    def test_stock_failure_justifies_but_does_not_authorize_qlora(self):
        decision = baseline_decision(
            self._summary(schemaValidityRate=0.9, hardFailureCount=2), SCORING
        )
        self.assertTrue(decision["qloraJustified"])
        self.assertEqual(
            decision["thresholdFailures"], ["schemaValidityRate", "hardFailureCount"]
        )
        self.assertFalse(decision["trainingAuthorized"])

    def test_generation_publication_hashes_and_removes_raw_output(self):
        records = redact_generation_records(
            [{"schemaVersion": 1, "raw": "private model output", "parsed": {"content": "{}"}}]
        )
        self.assertNotIn("raw", records[0])
        self.assertEqual(
            records[0]["rawSha256"],
            "6d0f7ee6bbac6f5e19aef026ed1a30759543b6016db1c4a03f13847788c12e7f",
        )
        with self.assertRaisesRegex(PreflightError, "lacks raw"):
            redact_generation_records([{"parsed": {}}])

    @staticmethod
    def _summary(**changes):
        value = {
            "groundedCompletionRate": 1.0,
            "correctToolOperationRate": 1.0,
            "schemaValidityRate": 1.0,
            "policyAccuracyRate": 1.0,
            "proposalQualityRate": 1.0,
            "recoveryRate": 1.0,
            "p95ToolCalls": 1,
            "hardFailureCount": 0,
        }
        value.update(changes)
        return value


if __name__ == "__main__":
    unittest.main()
