from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from loomarr_models.experiment import PreflightError
from loomarr_models.local_screen import CANDIDATE_IDS, build_plan


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-v4-local-screen-v1.json"


class LocalScreenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        for binding in config["bindings"].values():
            source = ROOT / binding["path"]
            destination = self.root / binding["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self.config_path = self.root / CONFIG.relative_to(ROOT)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CONFIG, self.config_path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_accepts_exact_unexposed_v4_screen_without_network(self):
        config, plan, snapshot = build_plan(
            self.root,
            self.config_path,
            git_probe=lambda _root, _paths: "a" * 40,
        )
        self.assertEqual(plan.caseCount, 120)
        self.assertEqual(plan.candidateIds, CANDIDATE_IDS)
        self.assertEqual(plan.externalCostUsd, "0")
        self.assertFalse(config["authority"]["certificationAuthority"])
        self.assertEqual(len(snapshot["candidates"]), 2)

    def test_refuses_bound_source_drift(self):
        scorer = self.root / self._config()["bindings"]["scorer"]["path"]
        scorer.write_bytes(scorer.read_bytes() + b"\n")
        with self.assertRaisesRegex(PreflightError, "scorer digest mismatch"):
            self._preflight()

    def test_refuses_prior_development_exposure(self):
        config = self._config()
        exposure_path = self.root / config["bindings"]["developmentExposure"]["path"]
        exposure = json.loads(exposure_path.read_text(encoding="utf-8"))
        exposure["status"] = "local-screen-complete"
        exposure["exposures"] = [{}]
        exposure_path.write_text(json.dumps(exposure), encoding="utf-8")
        config["bindings"]["developmentExposure"]["sha256"] = hashlib.sha256(
            exposure_path.read_bytes()
        ).hexdigest()
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "already exposed"):
            self._preflight()

    def test_refuses_authority_or_candidate_drift(self):
        config = self._config()
        config["authority"]["trainingAuthority"] = True
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "authority boundary drifted"):
            self._preflight()

        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        config["candidates"].reverse()
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "candidates differ"):
            self._preflight()

    def _config(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _write_config(self, config):
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def _preflight(self):
        return build_plan(
            self.root,
            self.config_path,
            git_probe=lambda _root, _paths: "a" * 40,
        )


if __name__ == "__main__":
    unittest.main()
