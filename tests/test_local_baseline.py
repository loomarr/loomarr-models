from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_local_baseline as builder
from loomarr_models import local_baseline
from loomarr_models.current_baseline_v3 import COMPARISON as V3_COMPARISON
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-current-qwen-local-baseline-v1.json"
V3_CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v3.json"


def _probe(_root: Path, _paths: object) -> str:
    return "0" * 40


class LocalBaselineTests(unittest.TestCase):
    def test_generated_plan_is_current(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())

    def test_preflight_accepts_committed_plan_with_zero_spend(self):
        plan = local_baseline.preflight(ROOT, CONFIG, git_probe=_probe)
        self.assertEqual(plan["caseCount"], 24)
        self.assertEqual(plan["externalSpendUsd"], "0")
        self.assertEqual(plan["candidateId"], "qwen38-27b-bf16")

    def test_plan_reuses_v3_cases_contract_scoring_and_decoding(self):
        local = json.loads(CONFIG.read_text(encoding="utf-8"))
        v3 = json.loads(V3_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(local["comparison"], V3_COMPARISON)
        self.assertEqual(local["scoring"], v3["scoring"])
        for name in ("cases", "casesManifest", "contract", "holdoutDenylist"):
            self.assertEqual(local["bindings"][name]["sha256"], v3["bindings"][name]["sha256"])

    def test_plan_keeps_pinned_unsloth_template_with_bf16_weights(self):
        model = json.loads(CONFIG.read_text(encoding="utf-8"))["model"]
        self.assertEqual(model["repository"], "Qwen/Qwen3.8-27B")
        self.assertEqual(model["tokenizer"]["revision"], "8aa5f05d26b7205477066e1449e0af13f762a299")

    def test_preflight_rejects_tampered_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_inputs(Path(tmp))
            (root / "contracts/planner-contract-v5.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "contract digest mismatch"):
                local_baseline.preflight(root, root / CONFIG.relative_to(ROOT), git_probe=_probe)

    def test_preflight_rejects_changed_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_inputs(Path(tmp))
            path = root / CONFIG.relative_to(ROOT)
            config = json.loads(path.read_text(encoding="utf-8"))
            config["execution"]["flashSdpa"] = True
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(PreflightError, "differs from the pinned plan"):
                local_baseline.preflight(root, path, git_probe=_probe)


def _copy_inputs(root: Path) -> Path:
    for path in [*local_baseline.BINDINGS.values(), str(CONFIG.relative_to(ROOT))]:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, root / path)
    return root


if __name__ == "__main__":
    unittest.main()
