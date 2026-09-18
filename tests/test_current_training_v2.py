from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_qwen38_qlora_v2 as builder
from loomarr_models import current_training_runtime
from loomarr_models.current_training_v2 import preflight
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-current-qwen38-qlora-v2.json"


class CurrentTrainingV2Tests(unittest.TestCase):
    def test_corrected_plan_is_exact_no_spend_and_storage_safe(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        execution = config["execution"]
        self.assertEqual(config["status"], "planned-no-paid-run-authorized")
        self.assertFalse(any(config["authority"].values()))
        self.assertEqual(execution["containerDiskGb"], 40)
        self.assertEqual(execution["environmentInstallDir"], "/opt/loomarr-venv")
        self.assertEqual(execution["persistentVolumeGb"], 80)
        self.assertEqual(execution["minimumFreePersistentGbBeforeDownload"], 70)
        self.assertEqual(
            execution["environment"],
            {"HF_HOME": "/workspace/hf-cache", "HF_HUB_DISABLE_XET": "1"},
        )
        self.assertFalse(execution["automaticRetry"])
        plan = preflight(
            ROOT,
            CONFIG,
            require_authorized=False,
            git_probe=lambda *_: "a" * 40,
        )
        self.assertEqual((plan.traceCount, plan.maximumRenderedTokens), (24, 5416))
        self.assertEqual(plan.maxSeqLength, 8192)
        self.assertEqual(plan.committedSpendUsd, "29.3563469369284740175")
        self.assertEqual(plan.projectedCombinedSpendUsd, "32.3563469369284740175")
        self.assertLessEqual(Decimal(plan.projectedCombinedSpendUsd), Decimal(plan.authorizationUsd))
        self.assertFalse(plan.trainingAuthorized)

    def test_paid_preflight_refuses_before_heavy_imports(self):
        with self.assertRaisesRegex(PreflightError, "not authorized"):
            preflight(ROOT, CONFIG, git_probe=lambda *_: "a" * 40)

    def test_storage_or_failure_prerequisite_drift_fails_closed(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["execution"]["persistentVolumeGb"] = 40
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

    def test_xet_is_disabled_before_unsloth_import(self):
        source = inspect.getsource(current_training_runtime.run_training)
        self.assertLess(source.index('os.environ[name] = value'), source.index('from unsloth import FastModel'))


if __name__ == "__main__":
    unittest.main()
