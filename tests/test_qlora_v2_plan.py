from __future__ import annotations

import hashlib
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_qwen38_qlora_v2 as builder
from loomarr_models.experiment import PreflightError, preflight


class QLoRAV2PlanTests(unittest.TestCase):
    def test_generated_plan_is_exact_and_no_spend(self):
        outputs = builder.build_outputs()
        for path, expected in outputs.items():
            self.assertEqual(path.read_bytes(), expected)

        config = json.loads(builder.CONFIG_PATH.read_text(encoding="utf-8"))
        run = config["runs"][0]
        self.assertEqual(config["experimentId"], "planner-qwen38-qlora-v2")
        self.assertEqual(config["status"], "planned-no-paid-run-authorized")
        self.assertEqual(config["bindings"]["corpus"]["traceCount"], 120)
        self.assertEqual(
            config["bindings"]["corpus"]["path"],
            "corpus/planner-behavior-v2/traces.jsonl",
        )
        self.assertEqual(run["maxSteps"], 45)
        self.assertEqual(run["perDeviceTrainBatchSize"] * run["gradientAccumulationSteps"] * 45, 180)
        self.assertEqual((run["loraR"], run["loraAlpha"], run["loraDropout"]), (8, 8, 0))
        self.assertTrue(run["trainOnResponsesOnly"])
        self.assertEqual(run["saveMode"], "adapter-only")

        index = json.loads(builder.INDEX_PATH.read_text(encoding="utf-8"))
        self.assertFalse(index["paidTrainingAuthorized"])
        self.assertFalse(index["trainingAuthorized"])
        self.assertFalse(index["releaseAuthorized"])
        self.assertEqual(index["budget"]["maximumAggregateCommitmentUsd"], "32.4826615675672820")
        self.assertLessEqual(
            Decimal(index["budget"]["maximumAggregateCommitmentUsd"]),
            Decimal(index["budget"]["aggregateAuthorizationUsd"]),
        )

    def test_no_spend_preflight_accepts_only_the_exact_frozen_corpus(self):
        report = preflight(
            ROOT,
            builder.CONFIG_PATH,
            git_probe=lambda _root, _paths: "a" * 40,
            require_authorized=False,
        )
        self.assertEqual((report.traceCount, report.approvedCount), (120, 120))
        self.assertEqual(report.corpusSha256, "857c3c0b6b6d00e395555d14f3556c8c37d66e99a9343c38e25416b461d8ef57")
        self.assertEqual(report.reservationUsd, "1.50")
        self.assertEqual(report.projectedSpendUsd, "29.4826615675672820")
        with self.assertRaisesRegex(PreflightError, "not ready-for-training"):
            preflight(
                ROOT,
                builder.CONFIG_PATH,
                git_probe=lambda _root, _paths: "a" * 40,
            )

    def test_evaluation_is_preregistered_but_cannot_run_without_the_adapter(self):
        plan = json.loads(builder.EVAL_PLAN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(plan["status"], "waiting-for-hash-bound-adapter")
        self.assertFalse(plan["paidEvaluationAuthorized"])
        self.assertIsNone(plan["adapterBinding"])
        self.assertEqual(plan["bindings"]["cases"]["caseCount"], 60)
        self.assertEqual(plan["candidateOrder"], ["stock", "adapter"])
        self.assertFalse(plan["comparison"]["doSample"])
        self.assertEqual(plan["comparison"]["trials"], 1)
        self.assertEqual(plan["promotion"]["maximumUnsupportedIds"], 0)
        self.assertEqual(plan["promotion"]["maximumAuthorityViolations"], 0)
        self.assertEqual(plan["promotion"]["maximumExecutableEnvelopeRegressions"], 0)
        config_sha = hashlib.sha256(builder.CONFIG_PATH.read_bytes()).hexdigest()
        self.assertEqual(plan["bindings"]["trainingConfig"]["sha256"], config_sha)
        self.assertEqual(plan["promotion"]["certifiedPillars"], ["channel-curation"])
        self.assertEqual(
            plan["promotion"]["uncertifiedPillars"],
            ["channel-recommendation", "filler-curation"],
        )


if __name__ == "__main__":
    unittest.main()
