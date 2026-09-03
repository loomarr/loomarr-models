from __future__ import annotations

import copy
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finalize_planner_behavior_corpus as finalizer
import publish_planner_behavior_review as publisher
import run_planner_behavior_review as runner
from loomarr_models.behavior_review import derive_review
from loomarr_models.model_review import CRITERIA, ModelReviewError


class BehaviorReviewPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _config, cls.plan, _snapshot = runner.build_plan(
            runner.CONFIG_PATH,
            require_authorized=False,
            git_probe=lambda _root, _paths: "b" * 40,
        )

    def observations(self):
        attestations = []
        for request in self.plan.requests:
            second = request.role == "secondary"
            attestations.append(
                {
                    "traceId": request.traceIds[0],
                    "role": request.role,
                    "reviewer": f"openrouter:{request.model}",
                    "reviewedAt": "2026-09-03T12:00:01Z" if second else "2026-09-03T12:00:00Z",
                    "verdict": "approved",
                    "summary": "Every criterion passes against concrete trace evidence.",
                    "criteria": [
                        {"criterion": criterion, "passed": True, "evidence": "Concrete trace evidence passes this criterion."}
                        for criterion in CRITERIA
                    ],
                }
            )
        return attestations

    def test_derives_exactly_120_unanimous_decisions(self):
        decisions, escalations = publisher.derive_decisions(self.observations(), [], self.plan)
        self.assertEqual(len(decisions), 120)
        self.assertEqual(escalations, [])
        self.assertTrue(all(derive_review(item, require_complete=True).status == "approved" for item in decisions))

    def test_invalid_or_disputed_observation_stays_pending(self):
        attestations = self.observations()
        first = attestations.pop(0)
        invalid = {
            "role": first["role"],
            "traceId": first["traceId"],
            "reviewer": first["reviewer"],
            "error": "synthetic invalid completion",
            "responseSha256": "c" * 64,
        }
        decisions, escalations = publisher.derive_decisions(attestations, [invalid], self.plan)
        self.assertEqual(len(escalations), 1)
        self.assertEqual(derive_review(decisions[0]).status, "pending")
        self.assertEqual(decisions[0]["secondary"]["verdict"], "pending")

    def test_budget_settlement_is_exact_and_refuses_drift_or_overflow(self):
        budget = {
            "postedSpendUsd": "19.1805365675672820",
            "outstandingReservationsUsd": "0.10",
            "committedSpendUsd": "19.2805365675672820",
            "authorizationUsd": "40.00",
        }
        settled = publisher.settle_budget(budget, Decimal("2.50"), self.plan)
        self.assertEqual(settled["postedSpendUsd"], "21.6805365675672820")
        self.assertEqual(settled["committedSpendUsd"], "21.7805365675672820")

        drifted = copy.deepcopy(budget)
        drifted["committedSpendUsd"] = "19.29"
        with self.assertRaisesRegex(ModelReviewError, "changed after"):
            publisher.settle_budget(drifted, Decimal("2.50"), self.plan)
        with self.assertRaisesRegex(ModelReviewError, "exceeds authorization"):
            publisher.settle_budget(budget, Decimal("16.00"), self.plan)

    def test_freeze_refuses_pending_decisions_and_creates_no_partial_artifact(self):
        for path in (finalizer.TRACES_PATH, finalizer.MANIFEST_PATH, finalizer.REPORT_PATH):
            self.assertFalse(path.exists())
        with self.assertRaisesRegex(ValueError, "two approvals"):
            finalizer.build_outputs()
        for path in (finalizer.TRACES_PATH, finalizer.MANIFEST_PATH, finalizer.REPORT_PATH):
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
