from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_v4_delta as corpus
import publish_planner_v4_review as publisher
import run_planner_v4_review as runner
from loomarr_models.model_review import CRITERIA, ModelReviewError
from loomarr_models.v4_review import derive_review
from loomarr_models.validator import load_contract


class V4ReviewPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config, cls.plan, _snapshot = runner.build_plan(
            runner.CONFIG_PATH,
            require_authorized=False,
            git_probe=lambda _root, _paths: "b" * 40,
        )

    def observations(self) -> list[dict]:
        attestations = []
        for request in self.plan.requests:
            secondary = request.role == "secondary"
            attestations.append(
                {
                    "traceId": request.traceIds[0],
                    "role": request.role,
                    "reviewer": f"openrouter:{request.model}",
                    "reviewedAt": (
                        "2026-09-04T12:00:01Z" if secondary else "2026-09-04T12:00:00Z"
                    ),
                    "verdict": "approved",
                    "summary": "Every criterion passes against concrete synthetic trace evidence.",
                    "criteria": [
                        {
                            "criterion": criterion,
                            "passed": True,
                            "evidence": "Concrete synthetic trace evidence passes this criterion.",
                        }
                        for criterion in CRITERIA
                    ],
                }
            )
        return attestations

    def test_derives_exactly_sixty_unanimous_decisions(self):
        decisions, escalations = publisher.derive_decisions(
            self.observations(), [], self.plan
        )
        self.assertEqual(len(decisions), 60)
        self.assertEqual(escalations, [])
        self.assertTrue(
            all(
                derive_review(decision, require_complete=True).status == "approved"
                for decision in decisions
            )
        )

    def test_invalid_observation_keeps_trace_pending_with_evidence(self):
        attestations = self.observations()
        first = attestations.pop(0)
        invalid = {
            "role": first["role"],
            "traceId": first["traceId"],
            "reviewer": first["reviewer"],
            "error": "synthetic invalid completion",
            "responseSha256": "c" * 64,
        }
        decisions, escalations = publisher.derive_decisions(
            attestations, [invalid], self.plan
        )
        self.assertEqual(len(escalations), 1)
        self.assertEqual(derive_review(decisions[0]).status, "pending")
        self.assertEqual(escalations[0]["primary"]["verdict"], "invalid")

    def test_settlement_is_exact_and_refuses_drift_or_overflow(self):
        budget = json.loads((ROOT / "budgets/external-spend-v1.json").read_text())
        settled = publisher.settle_budget(budget, Decimal("2.50"), self.plan)
        self.assertEqual(settled["postedSpendUsd"], "31.6962968898326090175")
        self.assertEqual(settled["committedSpendUsd"], "31.6962968898326090175")

        drifted = copy.deepcopy(budget)
        drifted["committedSpendUsd"] = "29.00"
        with self.assertRaisesRegex(ModelReviewError, "changed after"):
            publisher.settle_budget(drifted, Decimal("2.50"), self.plan)
        with self.assertRaisesRegex(ModelReviewError, "exceeds authorization"):
            publisher.settle_budget(budget, Decimal("13.00"), self.plan)

    def test_generator_projects_promoted_review_without_rewriting_synthetic_content(self):
        decisions, _escalations = publisher.derive_decisions(
            self.observations(), [], self.plan
        )
        mapped = {decision["traceId"]: decision for decision in decisions}
        contract = load_contract(corpus.CONTRACT_PATH)
        promoted = corpus.build_training(contract, mapped)
        pending = corpus.build_training(
            contract,
            {
                trace_id: corpus.empty_decision(trace_id)
                for trace_id in corpus.trace_ids()
            },
        )
        self.assertTrue(all(trace["review"]["status"] == "approved" for trace in promoted))
        self.assertTrue(all(trace["review"]["status"] == "pending" for trace in pending))
        for reviewed, draft in zip(promoted, pending, strict=True):
            review = reviewed.pop("review")
            draft_review = draft.pop("review")
            self.assertEqual(reviewed, draft)
            self.assertNotEqual(review, draft_review)

    def test_review_plan_binds_the_exact_publisher(self):
        binding = self.config["bindings"]["reviewPublisher"]
        path = ROOT / binding["path"]
        self.assertEqual(path, Path(publisher.__file__).resolve())
        self.assertEqual(binding["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
