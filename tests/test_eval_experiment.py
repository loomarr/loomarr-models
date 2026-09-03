from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

from loomarr_models.eval_experiment import preflight_eval
from loomarr_models.experiment import PreflightError


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "runs/planner-adapter-eval-v1/source-experiment.json"
CURRENT_CONFIG = ROOT / "experiments/planner-adapter-eval-v1.json"
ADAPTER_HASHES = json.loads(
    (ROOT / "runs/planner-qwen38-smoke-v1/run-manifest.json").read_text(encoding="utf-8")
)["adapterFiles"]


class EvalExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = self._workspace()

    def tearDown(self):
        self.temporary.cleanup()

    def test_accepts_exact_clean_fifty_case_comparison_without_heavy_imports(self):
        before = set(sys.modules)
        report = preflight_eval(
            self.root,
            self.config_path,
            git_probe=self._clean_git,
            adapter_probe=self._approved_adapter,
        )
        imported = {
            name.split(".", 1)[0]
            for name in set(sys.modules) - before
            if name.split(".", 1)[0]
            in {"torch", "unsloth", "transformers", "trl", "peft", "datasets"}
        }
        self.assertEqual(imported, set())
        self.assertEqual(report.caseCount, 50)
        self.assertEqual(report.projectedSpendUsd, "21.4977636149929768")
        self.assertEqual(report.authorizationUsd, "40.00")

    def test_current_repository_config_refuses_completed_experiment(self):
        with self.assertRaisesRegex(PreflightError, "not ready-for-development-eval"):
            preflight_eval(
                ROOT,
                CURRENT_CONFIG,
                git_probe=self._clean_git,
                adapter_probe=self._approved_adapter,
            )

    def test_refuses_bound_digest_drift(self):
        config = self._config()
        cases_path = self.root / config["bindings"]["cases"]["path"]
        cases_path.write_bytes(cases_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(PreflightError, "cases digest mismatch"):
            self._preflight()

    def test_refuses_generator_drift_even_when_frozen_cases_are_unchanged(self):
        generator = self.root / "scripts/build_planner_development_eval.py"
        generator.write_bytes(generator.read_bytes() + b"\n")
        with self.assertRaisesRegex(PreflightError, "generator digest differs"):
            self._preflight()

    def test_refuses_missing_or_mismatched_adapter(self):
        config = self._config()
        adapter = self.root / config["execution"]["adapterPath"]
        adapter.unlink()
        with self.assertRaisesRegex(PreflightError, "local adapter is missing"):
            self._preflight()

        adapter.parent.mkdir(parents=True, exist_ok=True)
        adapter.write_bytes(b"wrong adapter")
        with self.assertRaisesRegex(PreflightError, "local adapter file digest mismatch"):
            preflight_eval(
                self.root,
                self.config_path,
                git_probe=self._clean_git,
            )

    def test_refuses_adapter_source_drift(self):
        config = self._config()
        source_path = self.root / config["bindings"]["adapterSourceManifest"]["path"]
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source["adapterFiles"]["adapter_model.safetensors"] = "b" * 64
        source_path.write_text(json.dumps(source), encoding="utf-8")
        self._rebind("adapterSourceManifest")
        with self.assertRaisesRegex(PreflightError, "adapter source manifest digest differs"):
            self._preflight()

    def test_refuses_model_revision_drift(self):
        config = self._config()
        config["models"]["inferenceArtifact"]["revision"] = "b" * 40
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "revision differs"):
            self._preflight()

    def test_refuses_protocol_status_or_budget_drift(self):
        changes = (
            ("status", "completed", "not ready-for-development-eval"),
            ("order", ["adapter", "stock"], "comparison protocol drifted"),
            ("sampling", True, "comparison protocol drifted"),
        )
        for field, value, message in changes:
            with self.subTest(field=field):
                config = self._config()
                if field == "status":
                    config["status"] = value
                elif field == "order":
                    config["comparison"]["candidateOrder"] = value
                else:
                    config["comparison"]["doSample"] = value
                self._write_config(config)
                with self.assertRaisesRegex(PreflightError, message):
                    self._preflight()
                self._write_config(json.loads(CONFIG.read_text(encoding="utf-8")))

        budget_path = self.root / "budgets/external-spend-v1.json"
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        budget["postedSpendUsd"] = "39.00"
        budget["outstandingReservationsUsd"] = "0.00"
        budget["committedSpendUsd"] = "39.00"
        budget_path.write_text(json.dumps(budget), encoding="utf-8")
        with self.assertRaisesRegex(PreflightError, "exceed aggregate authorization"):
            self._preflight()

    def test_refuses_heavy_module_loaded_before_preflight_completion(self):
        prior = sys.modules.get("torch")
        sys.modules["torch"] = types.ModuleType("torch")
        try:
            with self.assertRaisesRegex(PreflightError, "imported before evaluation preflight"):
                self._preflight()
        finally:
            if prior is None:
                del sys.modules["torch"]
            else:
                sys.modules["torch"] = prior

    def _workspace(self) -> Path:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        paths = [
            CONFIG.relative_to(ROOT),
            Path("scripts/build_planner_development_eval.py"),
            *(
                Path(binding["path"])
                for name, binding in config["bindings"].items()
                if name != "budget"
            ),
            Path(config["bindings"]["budget"]["path"]),
        ]
        for relative in paths:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        budget_path = self.root / config["bindings"]["budget"]["path"]
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        budget["postedSpendUsd"] = "18.3977636149929768"
        budget["outstandingReservationsUsd"] = "0.10"
        budget["committedSpendUsd"] = "18.4977636149929768"
        budget_path.write_text(json.dumps(budget, indent=2) + "\n", encoding="utf-8")
        adapter = self.root / config["execution"]["adapterPath"]
        adapter.parent.mkdir(parents=True, exist_ok=True)
        for relative in ADAPTER_HASHES:
            local_file = adapter.parent / relative
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(f"fixture {relative}".encode())
        return self.root / CONFIG.relative_to(ROOT)

    def _config(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def _write_config(self, config: dict) -> None:
        self.config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    def _rebind(self, name: str) -> None:
        config = self._config()
        path = self.root / config["bindings"][name]["path"]
        config["bindings"][name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self._write_config(config)

    def _preflight(self):
        return preflight_eval(
            self.root,
            self.config_path,
            git_probe=self._clean_git,
            adapter_probe=self._approved_adapter,
        )

    @staticmethod
    def _clean_git(_root: Path, _paths: object) -> str:
        return "a" * 40

    @staticmethod
    def _approved_adapter(path: Path) -> str:
        return ADAPTER_HASHES[path.name]


if __name__ == "__main__":
    unittest.main()
