from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CurrentStockRuntimeV3Tests(unittest.TestCase):
    def test_live_runner_refuses_before_heavy_imports_when_unauthorized(self):
        script = ROOT / "scripts/run_planner_current_stock_baseline_v3.py"
        result = subprocess.run(
            [sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("paid current stock v3 execution is not authorized", result.stderr)
        self.assertNotIn("unsloth", result.stdout)

    def test_runtime_imports_unsloth_before_torch(self):
        source = (ROOT / "src/loomarr_models/current_stock_runtime_v3.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(source.index("from unsloth import FastModel"), source.index("import torch"))


if __name__ == "__main__":
    unittest.main()
