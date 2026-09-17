from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from loomarr_models.budget_reconciliation import validate_budget_reconciliation


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from extend_runpod_budget_reconciliation import _costs, extend


RECONCILIATION = ROOT / "budgets/runpod-pod-billing-current-stock-baseline-v2-v1.json"
BASE_RECONCILIATION = ROOT / "budgets/runpod-pod-billing-2026-09-03-v1.json"
LEDGER = ROOT / "budgets/external-spend-v1.json"


class BudgetReconciliationContractTests(unittest.TestCase):
    def test_provider_display_rounding_is_preserved_with_a_strict_bound(self):
        provider = {
            "costUsd": {
                "gpu": "0.10506307706236839",
                "disk": "0.002777777728624642",
                "persistentStorage": "0",
                "total": "0.10784085479099303",
            }
        }
        self.assertEqual(_costs(provider)["total"], Decimal("0.10784085479099303"))
        provider["costUsd"]["total"] = "0.1078408547909"
        with self.assertRaisesRegex(ValueError, "components"):
            _costs(provider)

    def assert_reconciliation_rejected(self, mutate, expected: str):
        payload = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
        mutate(payload)
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "reconciliation.json"
            candidate.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, expected):
                validate_budget_reconciliation(candidate, LEDGER, ROOT)

    def test_reconciliation_artifact_is_internally_consistent(self):
        validate_budget_reconciliation(RECONCILIATION, LEDGER, ROOT)

    def test_canonical_ledger_matches_provider_reconciliation(self):
        reconciliation = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        corrected = reconciliation["correctedLedger"]

        self.assertEqual(
            Decimal(ledger["postedSpendUsd"]),
            Decimal(corrected["postedSpendUsd"]),
        )
        self.assertEqual(
            Decimal(ledger["outstandingReservationsUsd"]),
            Decimal(corrected["outstandingReservationsUsd"]),
        )
        self.assertEqual(
            Decimal(ledger["committedSpendUsd"]),
            Decimal(corrected["committedSpendUsd"]),
        )

    def test_rejects_provider_total_outside_display_rounding_tolerance(self):
        self.assert_reconciliation_rejected(
            lambda payload: payload["providerBilling"]["buckets"][0].__setitem__("totalUsd", "0.0135711240489035845"),
            "display-rounding tolerance",
        )

    def test_rejects_historical_publication_digest_drift(self):
        self.assert_reconciliation_rejected(
            lambda payload: payload["historicalAccounting"]["adapterEvaluation"].__setitem__(
                "publicationSha256", "0" * 64
            ),
            "publicationSha256",
        )

    def test_rejects_remaining_authorization_drift(self):
        self.assert_reconciliation_rejected(
            lambda payload: payload["correctedLedger"].__setitem__("remainingAuthorizationUsd", "11.31"),
            "correctedLedger.remainingAuthorizationUsd",
        )

    def test_extends_canonical_reconciliation_with_exact_settled_baseline(self):
        base = json.loads(BASE_RECONCILIATION.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            provider_path = directory / "provider-settlement.json"
            provider = {
                "schemaVersion": 2,
                "experimentId": "planner-current-qwen-stock-baseline-v2",
                "provider": "runpod",
                "status": "settled-resources-deleted",
                "capturedAt": "2026-09-17T03:05:00Z",
                "createdAt": "2026-09-17T02:45:05Z",
                "deletedAt": "2026-09-17T02:58:13Z",
                "podIdSha256": "a" * 64,
                "zeroActivePods": True,
                "persistentStorageDeletedWithPod": True,
                "costUsd": {
                    "gpu": "0.49",
                    "disk": "0.01",
                    "persistentStorage": "0.02",
                    "total": "0.52",
                },
            }
            provider_path.write_text(json.dumps(provider), encoding="utf-8")
            ledger = {
                "schemaVersion": 1,
                "authorizationUsd": "40.00",
                "postedSpendUsd": "29.2167677051754599875",
                "outstandingReservationsUsd": "0",
                "committedSpendUsd": "29.2167677051754599875",
            }
            ledger_path = directory / "ledger.json"
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            publication_path = directory / "publication.json"
            publication = {
                "experimentId": provider["experimentId"],
                "providerCostUsd": "0.52",
                "providerEvidence": {
                    "sha256": hashlib.sha256(provider_path.read_bytes()).hexdigest()
                },
                "budgetAfterSettlement": {
                    name: ledger[name]
                    for name in (
                        "postedSpendUsd",
                        "outstandingReservationsUsd",
                        "committedSpendUsd",
                        "authorizationUsd",
                    )
                },
            }
            publication_path.write_text(json.dumps(publication), encoding="utf-8")
            result = extend(
                base,
                provider,
                publication,
                ledger,
                allocation="current-stock-baseline-v2",
                publication_path=publication_path,
                provider_path=provider_path,
            )
            output = directory / "reconciliation.json"
            output.write_text(json.dumps(result), encoding="utf-8")
            validate_budget_reconciliation(output, ledger_path, ROOT)
            self.assertEqual(
                result["historicalAccounting"]["currentStockBaselineV2"][
                    "billedAllocationUsd"
                ],
                "0.52",
            )
            self.assertEqual(result["providerBilling"]["uniqueResourceCount"], 8)

            with self.assertRaisesRegex(ValueError, "already contains"):
                extend(
                    result,
                    provider,
                    publication,
                    ledger,
                    allocation="current-stock-baseline-v2",
                    publication_path=publication_path,
                    provider_path=provider_path,
                )


if __name__ == "__main__":
    unittest.main()
