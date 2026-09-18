from __future__ import annotations

import ast
import inspect
import json
import sys
import tempfile
import textwrap
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_qwen38_qlora_v1 as builder
import verify_planner_current_qwen38_qlora_v1_artifact as artifact_verifier
from loomarr_models.current_training import preflight
from loomarr_models import current_training_runtime
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-current-qwen38-qlora-v1.json"


class CurrentTrainingTests(unittest.TestCase):
    def test_generated_plan_is_exact_current_and_training_authorized(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())
        plan = preflight(
            ROOT,
            CONFIG,
            require_authorized=False,
            git_probe=lambda *_: "a" * 40,
        )
        self.assertEqual((plan.traceCount, plan.maximumRenderedTokens), (24, 5416))
        self.assertEqual(plan.maxSeqLength, 8192)
        self.assertEqual(plan.corpusSha256, "a4ce7ac3e3365148ee4bd057928cfe3f72847637fe9c8ae7ebbadc29b608dcfa")
        self.assertEqual(plan.stockPublicationSha256, "0b033229b49585a9c12e6adbe7d16b3333f94950fc8d18e8c693e9a42e4dbf79")
        self.assertEqual(plan.combinedReservationUsd, "3.00")
        self.assertEqual(plan.projectedCombinedSpendUsd, "32.1962968898326090175")
        self.assertLessEqual(Decimal(plan.projectedCombinedSpendUsd), Decimal(plan.authorizationUsd))
        self.assertTrue(plan.trainingAuthorized)
        authorization = json.loads(
            (ROOT / "reviews/planner-current-qwen38-qlora-v1/authorization.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            authorization["authorizedPlanCommit"],
            "c75e9f00700d94e54ab91dc62089b85686832f45",
        )
        self.assertEqual(
            authorization["authorizationReference"],
            "https://github.com/loomarr/loomarr-models/issues/20#issuecomment-5723983019",
        )
        preflight(ROOT, CONFIG, git_probe=lambda *_: "a" * 40)

    def test_recipe_is_one_adapter_only_one_and_a_half_pass_run(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(len(config["runs"]), 1)
        run = config["runs"][0]
        self.assertEqual(run["maxSteps"], 9)
        self.assertEqual(
            run["maxSteps"] * run["perDeviceTrainBatchSize"] * run["gradientAccumulationSteps"],
            36,
        )
        self.assertEqual(run["maxSeqLength"], 8192)
        self.assertTrue(run["trainOnResponsesOnly"])
        self.assertEqual(run["saveMode"], "adapter-only")
        self.assertFalse(config["execution"]["automaticRetry"])
        self.assertTrue(config["evaluation"]["reusePublishedStockResults"])
        self.assertEqual(config["evaluation"]["candidateOrder"], ["stock", "adapter"])

    def test_runtime_imports_unsloth_before_the_training_stack(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(current_training_runtime.run_training)))
        modules = [
            node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            for node in tree.body[0].body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        self.assertEqual(modules[:2], ["unsloth", "unsloth.chat_templates"])
        self.assertLess(modules.index("unsloth"), modules.index("torch"))
        self.assertLess(modules.index("unsloth"), modules.index("trl"))

    def test_artifact_verifier_rejects_merged_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "adapter").mkdir()
            (root / "trainer").mkdir()
            (root / "run-manifest.json").write_text("{}\n", encoding="utf-8")
            (root / "trainer/model.safetensors").write_bytes(b"forbidden")
            with self.assertRaisesRegex(
                artifact_verifier.ArtifactVerificationError,
                "merged or base-model weights",
            ):
                artifact_verifier._verify_output_tree(root)

    def test_protocol_and_capacity_drift_fail_closed(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["runs"][0]["maxSeqLength"] = 4096
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "protocol drifted"):
                preflight(
                    ROOT,
                    path,
                    require_authorized=False,
                    git_probe=lambda *_: "a" * 40,
                )

        report_path = ROOT / json.loads(CONFIG.read_text())["bindings"]["capacityReport"]["path"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["measurements"][0]["tokens"] = 8193
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            candidate_report = directory / "capacity.json"
            candidate_report.write_text(json.dumps(report), encoding="utf-8")
            candidate = json.loads(CONFIG.read_text(encoding="utf-8"))
            import hashlib

            candidate["bindings"]["capacityReport"] = {
                "path": str(candidate_report.relative_to(ROOT)),
                "sha256": hashlib.sha256(candidate_report.read_bytes()).hexdigest(),
            }
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "capacity"):
                preflight(
                    ROOT,
                    config_path,
                    require_authorized=False,
                    git_probe=lambda *_: "a" * 40,
                )


if __name__ == "__main__":
    unittest.main()
