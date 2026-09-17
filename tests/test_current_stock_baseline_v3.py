from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from loomarr_models.current_baseline_v3 import PAID_AUTHORITY, preflight
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

    def test_paid_authority_requires_the_settled_v2_failure_and_exact_ledger(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        ledger = json.loads(
            (ROOT / config["bindings"]["budgetLedger"]["path"]).read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            publication = {
                "experimentId": "planner-current-qwen-stock-baseline-v2",
                "status": "baseline-invalid-settled",
                "decision": {
                    "failureClass": "runtime-configuration-failure",
                    "qloraJustified": False,
                },
                "budgetAfterSettlement": {
                    "postedSpendUsd": ledger["postedSpendUsd"],
                    "committedSpendUsd": ledger["committedSpendUsd"],
                    "authorizationUsd": ledger["authorizationUsd"],
                },
            }
            publication_path = directory / "prior-publication.json"
            publication_path.write_text(json.dumps(publication), encoding="utf-8")
            prior_binding = {
                "path": str(publication_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(publication_path.read_bytes()).hexdigest(),
            }
            authorization = {
                "schemaVersion": 1,
                "experimentId": config["experimentId"],
                "status": "authorized",
                "maxReservationUsd": "1.50",
                "authorizedBy": "loomarr-maintainer",
                "authorizedAt": "2026-09-17T04:12:30Z",
                "authorizedPlanCommit": "a" * 40,
                "authorizationReference": (
                    "https://github.com/loomarr/loomarr-models/issues/29#issuecomment-1"
                ),
                "priorBaselinePublication": prior_binding,
            }
            authorization_path = directory / "authorization.json"
            authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
            config["status"] = "ready-for-paid-baseline"
            config["authority"] = PAID_AUTHORITY
            config["bindings"]["authorization"] = {
                "path": str(authorization_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(authorization_path.read_bytes()).hexdigest(),
            }
            config["bindings"]["priorBaselinePublication"] = prior_binding
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            report = preflight(
                ROOT, path, require_authorized=True, git_probe=lambda *_: "b" * 40
            )
            self.assertTrue(report.paidBaselineAuthorized)


if __name__ == "__main__":
    unittest.main()
