from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from loomarr_models.current_baseline_v3 import preflight
from loomarr_models.experiment import PreflightError


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v3.json"


class CurrentStockBaselineV3Tests(unittest.TestCase):
    def test_plan_is_exact_hash_bound_and_not_authorized(self):
        report = preflight(ROOT, CONFIG, git_probe=lambda *_: "a" * 40)
        self.assertEqual(report.caseCount, 24)
        self.assertEqual(report.proposedReservationUsd, "1.50")
        self.assertEqual(report.promptCapacityStatus, "passed")
        self.assertEqual(report.outputDir, ".artifacts/planner-current-qwen-stock-baseline-v3")
        self.assertFalse(report.paidBaselineAuthorized)
        with self.assertRaisesRegex(PreflightError, "not authorized"):
            preflight(ROOT, CONFIG, require_authorized=True, git_probe=lambda *_: "a" * 40)

    def test_context_or_authority_drift_fails_closed(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["comparison"]["maxSeqLength"] = 4096
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "protocol or authority drifted"):
                preflight(ROOT, path, git_probe=lambda *_: "a" * 40)


if __name__ == "__main__":
    unittest.main()
