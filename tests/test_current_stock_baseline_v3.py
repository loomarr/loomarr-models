from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from loomarr_models.current_baseline_v3 import PAID_AUTHORITY, preflight
from loomarr_models.experiment import PreflightError


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v3.json"
PUBLICATION = ROOT / "runs/planner-current-qwen-stock-baseline-v3/publication.json"


class CurrentStockBaselineV3Tests(unittest.TestCase):
    def test_terminal_plan_is_hash_bound_settled_and_revoked(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        publication = json.loads(PUBLICATION.read_text(encoding="utf-8"))
        self.assertEqual(config["status"], "complete-settled")
        self.assertEqual(publication["status"], "qlora-justified-settled")
        self.assertEqual(publication["summary"]["caseCount"], 24)
        self.assertEqual(publication["providerCostUsd"], "0.391688329866156")
        self.assertFalse(config["authority"]["paidBaselineAuthorized"])
        self.assertFalse(config["authority"]["gpuAuthorized"])
        self.assertFalse(config["authority"]["modelDownloadAuthorized"])
        with self.assertRaisesRegex(PreflightError, "terminal and cannot run again"):
            preflight(ROOT, CONFIG, git_probe=lambda *_: "a" * 40)

    def test_context_or_authority_drift_fails_closed(self):
        config = json.loads(
            (ROOT / "runs/planner-current-qwen-stock-baseline-v3/source-experiment.json").read_text(
                encoding="utf-8"
            )
        )
        config["comparison"]["maxSeqLength"] = 4096
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "protocol or authority drifted"):
                preflight(ROOT, path, git_probe=lambda *_: "a" * 40)

    def test_paid_authority_requires_the_settled_v2_failure_and_exact_ledger(self):
        config = json.loads(
            (ROOT / "runs/planner-current-qwen-stock-baseline-v3/source-experiment.json").read_text(
                encoding="utf-8"
            )
        )
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
            config["bindings"]["budgetLedger"] = {
                "path": "budgets/external-spend-v1.json",
                "sha256": hashlib.sha256(
                    (ROOT / "budgets/external-spend-v1.json").read_bytes()
                ).hexdigest(),
            }
            extender = ROOT / config["bindings"]["budgetReconciliationExtender"]["path"]
            config["bindings"]["budgetReconciliationExtender"]["sha256"] = hashlib.sha256(
                extender.read_bytes()
            ).hexdigest()
            committed = ledger["committedSpendUsd"]
            config["budget"] = {
                "aggregateAuthorizationUsd": ledger["authorizationUsd"],
                "currentCommittedUsd": committed,
                "outstandingReservationsUsd": ledger["outstandingReservationsUsd"],
                "proposedReservationUsd": "1.50",
                "projectedCommitmentUsd": str(
                    Decimal(committed) + Decimal("1.50")
                ),
                "remainingAuthorizationUsd": str(
                    Decimal(ledger["authorizationUsd"])
                    - Decimal(committed)
                    - Decimal("1.50")
                ),
            }
            path = directory / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            report = preflight(
                ROOT, path, require_authorized=True, git_probe=lambda *_: "b" * 40
            )
            self.assertTrue(report.paidBaselineAuthorized)


if __name__ == "__main__":
    unittest.main()
