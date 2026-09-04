from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from loomarr_models.budget_reconciliation import validate_budget_reconciliation


ROOT = Path(__file__).resolve().parents[1]
RECONCILIATION = ROOT / "budgets/runpod-pod-billing-2026-09-03-v1.json"
LEDGER = ROOT / "budgets/external-spend-v1.json"


class BudgetReconciliationContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
