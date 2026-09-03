from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_planner_behavior_review as runner
from loomarr_models.behavior_model_review import BehaviorReviewPreflightError
from loomarr_models.validator import load_jsonl


CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v2.json"
CORRECTED_CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v3.json"


class BehaviorReviewRunnerTests(unittest.TestCase):
    def build(self, path=CONFIG_PATH, *, authorized=False):
        return runner.build_plan(
            path,
            require_authorized=authorized,
            git_probe=lambda _root, _paths: "a" * 40,
        )

    def test_reconstructs_the_exact_committed_runtime_requests(self):
        config, plan, snapshot = self.build()
        self.assertFalse(plan.paidReviewAuthorized)
        self.assertEqual(config["status"], "complete-with-escalations")
        self.assertEqual(plan.requestCount, 240)
        self.assertEqual(len(plan.requests), 240)
        self.assertEqual(plan.sourceCommit, "a" * 40)
        self.assertEqual(plan.requests[0].role, "primary")
        self.assertEqual(plan.requests[119].role, "primary")
        self.assertEqual(plan.requests[120].role, "secondary")
        self.assertEqual(plan.requests[-1].role, "secondary")
        self.assertEqual(plan.requests[-1].providerTag, "anthropic")
        self.assertEqual(
            plan.requests[-1].upstreamModel,
            "anthropic/claude-4.6-sonnet-20260217",
        )
        self.assertEqual(snapshot["reviewers"][1]["providerTag"], "anthropic")
        self.assertEqual(config["execution"]["maxCalls"], len(plan.requests))

    def test_terminal_execution_refuses_before_key_or_network(self):
        with self.assertRaisesRegex(BehaviorReviewPreflightError, "not authorized"):
            self.build(authorized=True)

    def test_corrected_plan_is_full_independent_and_disabled(self):
        config, plan, _snapshot = self.build(CORRECTED_CONFIG_PATH)
        self.assertEqual(config["status"], "ready-for-review")
        self.assertTrue(plan.paidReviewAuthorized)
        self.assertEqual(plan.reviewId, "planner-behavior-review-v3")
        self.assertEqual(plan.requestCount, 240)
        self.assertEqual(plan.traceCount, 120)
        self.assertEqual(plan.reservationUsd, "16.50")
        self.assertEqual(plan.worstCaseCostUsd, "15.617740")
        self.assertEqual(plan.projectedSpendUsd, "39.8611685675672820")
        self.assertEqual(plan.outputDir, ".artifacts/planner-behavior-review-v3")
        primary_ids = [request.traceIds[0] for request in plan.requests if request.role == "primary"]
        secondary_ids = [
            request.traceIds[0] for request in plan.requests if request.role == "secondary"
        ]
        expected_ids = [
            trace["traceId"]
            for trace in load_jsonl(ROOT / "corpus/planner-behavior-v2/drafts.jsonl")
        ]
        self.assertEqual(primary_ids, expected_ids)
        self.assertEqual(secondary_ids, expected_ids)
        packet = json.loads(plan.requests[0].payload["messages"][1]["content"])
        self.assertIn("auditContract", packet)
        self.assertNotIn("contractBinding", packet)
        _config, authorized_plan, _snapshot = self.build(
            CORRECTED_CONFIG_PATH, authorized=True
        )
        self.assertTrue(authorized_plan.paidReviewAuthorized)

    def test_execution_and_binding_drift_fail_closed(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["execution"]["automaticInferenceRetry"] = True
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=ROOT,
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(config, handle)
            drifted_path = Path(handle.name)
        try:
            with self.assertRaisesRegex(BehaviorReviewPreflightError, "execution envelope drifted"):
                self.build(drifted_path)
        finally:
            drifted_path.unlink(missing_ok=True)

        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["bindings"] = copy.deepcopy(config["bindings"])
        del config["bindings"]["routeSnapshot"]
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=ROOT,
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(config, handle)
            drifted_path = Path(handle.name)
        try:
            with self.assertRaisesRegex(BehaviorReviewPreflightError, "bindings differ"):
                self.build(drifted_path)
        finally:
            drifted_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
