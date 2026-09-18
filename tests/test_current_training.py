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
from loomarr_models.current_contract import read_jsonl
from loomarr_models.current_training import _validate_capacity, preflight
from loomarr_models import current_training_runtime
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-current-qwen38-qlora-v1.json"
SOURCE_CONFIG = ROOT / "runs/planner-current-qwen38-qlora-v1/source-experiment.json"


class CurrentTrainingTests(unittest.TestCase):
    def test_generated_plan_is_exact_terminal_and_cannot_be_reexecuted(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["status"], "failed-settled")
        self.assertFalse(any(config["authority"].values()))
        self.assertEqual(
            config["budgetAfterSettlement"]["committedSpendUsd"],
            "29.3563469369284740175",
        )
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
        self.assertEqual(authorization["status"], "complete-failed")
        self.assertEqual(authorization["actualTrainingCostUsd"], "0.160050047095865")
        with self.assertRaisesRegex(PreflightError, "terminal"):
            preflight(ROOT, CONFIG, git_probe=lambda *_: "a" * 40)

    def test_recipe_is_one_adapter_only_one_and_a_half_pass_run(self):
        config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
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
        config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
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

        report_path = ROOT / json.loads(SOURCE_CONFIG.read_text())["bindings"]["capacityReport"]["path"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["measurements"][0]["tokens"] = 8193
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            candidate_report = directory / "capacity.json"
            candidate_report.write_text(json.dumps(report), encoding="utf-8")
            candidate = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
            traces = read_jsonl(ROOT / candidate["bindings"]["corpus"]["path"])
            with self.assertRaisesRegex(PreflightError, "capacity"):
                _validate_capacity(candidate, candidate_report, traces)


if __name__ == "__main__":
    unittest.main()
