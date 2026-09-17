from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
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
        config = json.loads(runner.CONFIG_PATH.read_text(encoding="utf-8"))
        config["bindings"]["budget"]["path"] = (
            "tests/fixtures/external-spend-before-planner-behavior-v3.json"
        )
        for binding in config["bindings"].values():
            if "sha256" in binding:
                binding["sha256"] = hashlib.sha256(
                    (ROOT / binding["path"]).read_bytes()
                ).hexdigest()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=ROOT, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(config, handle)
            fixture_path = Path(handle.name)
        try:
            _config, cls.plan, _snapshot = runner.build_plan(
                fixture_path,
                require_authorized=False,
                git_probe=lambda _root, _paths: "b" * 40,
            )
        finally:
            fixture_path.unlink(missing_ok=True)

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
            "postedSpendUsd": "23.2611685675672820",
            "outstandingReservationsUsd": "0.10",
            "committedSpendUsd": "23.3611685675672820",
            "authorizationUsd": "40.00",
        }
        settled = publisher.settle_budget(budget, Decimal("2.50"), self.plan)
        self.assertEqual(settled["postedSpendUsd"], "25.7611685675672820")
        self.assertEqual(settled["committedSpendUsd"], "25.8611685675672820")

        drifted = copy.deepcopy(budget)
        drifted["committedSpendUsd"] = "19.29"
        with self.assertRaisesRegex(ModelReviewError, "changed after"):
            publisher.settle_budget(drifted, Decimal("2.50"), self.plan)
        with self.assertRaisesRegex(ModelReviewError, "exceeds authorization"):
            publisher.settle_budget(budget, Decimal("16.00"), self.plan)

    def test_freeze_uses_the_unanimous_v3_publication(self):
        publication = json.loads(finalizer.PUBLICATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(publication["reviewId"], "planner-behavior-review-v3")
        self.assertEqual((publication["approved"], publication["escalations"]), (120, 0))

    def test_published_disagreement_is_hash_bound_settled_and_terminal(self):
        public = ROOT / "reviews/planner-behavior-v2/publications/planner-behavior-review-v2"
        publication = json.loads((public / "publication.json").read_text(encoding="utf-8"))
        self.assertEqual(publication["status"], "complete-with-escalations")
        self.assertEqual(publication["approved"], 118)
        self.assertEqual(publication["escalations"], 2)
        self.assertEqual(publication["actualCostUsd"], "4.080632")
        for label in ("runManifest", "attestations", "invalidReviews", "decisions", "escalations"):
            path = ROOT / publication[f"{label}Path"]
            self.assertEqual(
                publication[f"{label}Sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        manifest = json.loads((ROOT / publication["runManifestPath"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["requestCount"], 240)
        self.assertEqual(manifest["attestationCount"], 240)
        self.assertEqual(manifest["invalidReviewCount"], 0)
        self.assertEqual(manifest["actualCostUsd"], publication["actualCostUsd"])
        budget = json.loads((ROOT / "budgets/external-spend-v1.json").read_text(encoding="utf-8"))
        self.assertEqual(budget["postedSpendUsd"], "29.1962968898326090175")
        self.assertEqual(budget["committedSpendUsd"], "29.1962968898326090175")


if __name__ == "__main__":
    unittest.main()
