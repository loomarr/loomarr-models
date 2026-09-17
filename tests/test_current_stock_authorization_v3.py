from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import authorize_planner_current_stock_baseline_v3 as authorization


class CurrentStockAuthorizationV3Tests(unittest.TestCase):
    def test_prior_runtime_failure_must_be_settled_without_justifying_training(self):
        ledger = {
            "postedSpendUsd": "29.00",
            "committedSpendUsd": "29.00",
            "authorizationUsd": "40.00",
        }
        publication = {
            "experimentId": "planner-current-qwen-stock-baseline-v2",
            "status": "baseline-invalid-settled",
            "decision": {
                "failureClass": "runtime-configuration-failure",
                "qloraJustified": False,
            },
            "budgetAfterSettlement": ledger,
        }
        authorization.validate_prior_settlement(publication, ledger)

        drifted = copy.deepcopy(publication)
        drifted["decision"]["qloraJustified"] = True
        with self.assertRaisesRegex(Exception, "do not reconcile"):
            authorization.validate_prior_settlement(drifted, ledger)

    def test_authorization_metadata_is_strict(self):
        self.assertTrue(authorization._timestamp("2026-09-17T04:12:30Z"))
        self.assertFalse(authorization._timestamp("2026-09-17"))
        self.assertFalse(authorization._timestamp("2026-09-17T04:12:30+00:00"))


if __name__ == "__main__":
    unittest.main()
