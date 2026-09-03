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


CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v2.json"


class BehaviorReviewRunnerTests(unittest.TestCase):
    def build(self, path=CONFIG_PATH, *, authorized=False):
        return runner.build_plan(
            path,
            require_authorized=authorized,
            git_probe=lambda _root, _paths: "a" * 40,
        )

    def test_reconstructs_the_exact_committed_runtime_requests(self):
        config, plan, snapshot = self.build()
        self.assertTrue(plan.paidReviewAuthorized)
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

    def test_execution_refuses_before_key_or_network_while_plan_is_disabled(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["status"] = "planned-no-paid-calls-authorized"
        config["execution"]["paidReviewAuthorized"] = False
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=ROOT,
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(config, handle)
            disabled_path = Path(handle.name)
        try:
            with self.assertRaisesRegex(BehaviorReviewPreflightError, "not authorized"):
                self.build(disabled_path, authorized=True)
        finally:
            disabled_path.unlink(missing_ok=True)

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
