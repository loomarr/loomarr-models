from __future__ import annotations

import inspect
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_qwen38_qlora_v2 as builder
from loomarr_models import current_training_runtime
from loomarr_models.current_training_v2 import preflight
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-current-qwen38-qlora-v2.json"


class CurrentTrainingV2Tests(unittest.TestCase):
    def test_terminal_plan_is_exact_settled_and_revoked(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(config["status"], "failed-settled")
        self.assertFalse(any(config["authority"].values()))
        self.assertEqual(
            config["budgetAfterSettlement"]["committedSpendUsd"],
            "29.4222990406298941475",
        )
        publication = json.loads((ROOT / config["publication"]["path"]).read_text())
        self.assertEqual(publication["providerCostUsd"], "0.06595210370142013")
        self.assertEqual(publication["failureEvidence"]["optimizerSteps"], 0)
        self.assertFalse(publication["failureEvidence"]["adapterProduced"])

    def test_terminal_preflight_refuses_reexecution(self):
        for require_authorized in (False, True):
            with self.assertRaisesRegex(PreflightError, "terminal"):
                preflight(
                    ROOT,
                    CONFIG,
                    require_authorized=require_authorized,
                    git_probe=lambda *_: "a" * 40,
                )

    def test_xet_is_disabled_before_unsloth_import(self):
        source = inspect.getsource(current_training_runtime.run_training)
        self.assertLess(source.index('os.environ[name] = value'), source.index('from unsloth import FastModel'))


if __name__ == "__main__":
    unittest.main()
