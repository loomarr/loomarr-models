from __future__ import annotations

import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_planner_v4_stock_baseline as publication


class StockBaselinePublicationTests(unittest.TestCase):
    def setUp(self):
        self.plan = SimpleNamespace(
            reservationUsd="1.50",
            committedSpendUsd="27.9826615675672820",
        )

    def test_accepts_exact_settled_deleted_resource_evidence(self):
        evidence = self._evidence()
        self.assertIs(
            publication.validate_provider_evidence(
                evidence,
                {
                    "cloud": "SECURE",
                    "gpuSku": "NVIDIA A40",
                    "maxWallClockSeconds": 9000,
                },
                self.plan,
            ),
            evidence,
        )

    def test_rejects_deadline_cost_or_teardown_drift(self):
        execution = {
            "cloud": "SECURE",
            "gpuSku": "NVIDIA A40",
            "maxWallClockSeconds": 9000,
        }
        late = self._evidence()
        late["deletedAt"] = "2026-09-04T03:00:01Z"
        with self.assertRaisesRegex(Exception, "deadline"):
            publication.validate_provider_evidence(late, execution, self.plan)

        expensive = self._evidence()
        expensive["costUsd"] = {
            "gpu": "0.49",
            "disk": "1.02",
            "networkVolume": "0",
            "total": "1.51",
        }
        with self.assertRaisesRegex(Exception, "reservation"):
            publication.validate_provider_evidence(expensive, execution, self.plan)

        active = self._evidence()
        active["zeroActivePods"] = False
        with self.assertRaisesRegex(Exception, "teardown"):
            publication.validate_provider_evidence(active, execution, self.plan)

    def test_budget_settlement_posts_only_actual_cost(self):
        budget = {
            "schemaVersion": 1,
            "ledgerId": "loomarr-ai-external-spend-v1",
            "asOf": "2026-09-03",
            "currency": "USD",
            "authorizationUsd": "40.00",
            "postedSpendUsd": "27.8826615675672820",
            "outstandingReservationsUsd": "0.10",
            "committedSpendUsd": "27.9826615675672820",
            "authorizedBy": "loomarr-maintainer",
        }
        settled = publication.settle_budget(budget, Decimal("0.50"), self.plan)
        self.assertEqual(settled["postedSpendUsd"], "28.3826615675672820")
        self.assertEqual(settled["committedSpendUsd"], "28.4826615675672820")
        drifted = copy.deepcopy(budget)
        drifted["committedSpendUsd"] = "28.00"
        with self.assertRaisesRegex(Exception, "changed after"):
            publication.settle_budget(drifted, Decimal("0.50"), self.plan)

    @staticmethod
    def _evidence():
        return {
            "schemaVersion": 1,
            "experimentId": "planner-v4-qwen-stock-baseline-v1",
            "provider": "runpod",
            "status": "settled-resources-deleted",
            "capturedAt": "2026-09-04T01:00:00Z",
            "cloud": "SECURE",
            "dataCenterId": "US-SYNTHETIC-1",
            "gpuSku": "NVIDIA A40",
            "gpuHourlyUsd": "0.49",
            "createdAt": "2026-09-04T00:00:00Z",
            "deletedAt": "2026-09-04T01:00:00Z",
            "podIdSha256": "a" * 64,
            "networkVolumeIdSha256": "b" * 64,
            "zeroActivePods": True,
            "networkVolumeDeleted": True,
            "costUsd": {
                "gpu": "0.49",
                "disk": "0.01",
                "networkVolume": "0",
                "total": "0.50",
            },
        }


if __name__ == "__main__":
    unittest.main()
