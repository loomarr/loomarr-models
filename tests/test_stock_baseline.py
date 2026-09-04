from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from loomarr_models.experiment import PreflightError
from loomarr_models.stock_baseline import preflight


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-v4-qwen-stock-baseline-v1.json"


class StockBaselinePreflightTests(unittest.TestCase):
    def test_reconstructs_exact_plan_without_authorizing_paid_execution(self):
        report = preflight(
            ROOT,
            CONFIG,
            require_authorized=False,
            git_probe=lambda _root, _paths: "a" * 40,
        )
        self.assertEqual(report.caseCount, 120)
        self.assertEqual(report.candidateId, "qwen38-27b-unsloth-bnb-4bit")
        self.assertEqual(report.reservationUsd, "1.50")
        self.assertEqual(report.projectedSpendUsd, "29.4826615675672820")
        self.assertFalse(report.paidBaselineAuthorized)
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        authorization = ROOT / config["bindings"]["authorization"]["path"]
        publisher = ROOT / config["bindings"]["publisher"]["path"]
        self.assertEqual(
            config["bindings"]["authorization"]["sha256"],
            hashlib.sha256(authorization.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            config["bindings"]["publisher"]["sha256"],
            hashlib.sha256(publisher.read_bytes()).hexdigest(),
        )

    def test_paid_execution_refuses_before_heavy_import_or_network(self):
        with self.assertRaisesRegex(PreflightError, "not authorized"):
            preflight(
                ROOT,
                CONFIG,
                require_authorized=True,
                git_probe=lambda _root, _paths: "a" * 40,
            )

    def test_status_or_budget_projection_drift_fails_closed(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["status"] = "ready-for-paid-baseline"
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "status and authorization differ"):
                preflight(
                    ROOT,
                    path,
                    require_authorized=False,
                    git_probe=lambda _root, _paths: "a" * 40,
                )


if __name__ == "__main__":
    unittest.main()
