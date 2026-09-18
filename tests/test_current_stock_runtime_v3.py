from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from loomarr_models.experiment import PreflightError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_planner_current_stock_baseline_v3 as runner


class CurrentStockRuntimeV3Tests(unittest.TestCase):
    def test_live_runner_refuses_before_heavy_imports_when_unauthorized(self):
        sys.modules.pop("loomarr_models.current_stock_runtime_v3", None)
        with (
            patch.object(
                runner,
                "preflight",
                side_effect=PreflightError("paid current stock v3 execution is not authorized"),
            ),
            patch.object(sys, "argv", [str(runner.__file__)]),
            self.assertRaises(SystemExit) as raised,
        ):
            runner.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("loomarr_models.current_stock_runtime_v3", sys.modules)

    def test_runtime_imports_unsloth_before_torch(self):
        source = (ROOT / "src/loomarr_models/current_stock_runtime_v3.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(source.index("from unsloth import FastModel"), source.index("import torch"))


if __name__ == "__main__":
    unittest.main()
