from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from loomarr_models.experiment import (
    PreflightError,
    _git_probe,
    _output_path,
    preflight,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "experiments/planner-qwen38-smoke-v1.json"


class ExperimentPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = self._build_approved_workspace()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_accepts_exact_approved_single_run_without_heavy_imports(self):
        before = set(sys.modules)
        report = preflight(self.root, self.config_path, git_probe=self._clean_git)
        imported = {
            name.split(".", 1)[0]
            for name in set(sys.modules) - before
            if name.split(".", 1)[0]
            in {"torch", "unsloth", "transformers", "trl", "peft", "datasets"}
        }
        self.assertEqual(imported, set())
        self.assertEqual((report.traceCount, report.approvedCount), (50, 50))
        self.assertEqual(report.sourceCommit, "a" * 40)
        self.assertEqual(report.projectedSpendUsd, "5.954895891125471")

    def test_current_repository_config_refuses_pending_corpus(self):
        with self.assertRaisesRegex(ValueError, "not approved"):
            preflight(PROJECT_ROOT, CONFIG_PATH, git_probe=self._clean_git)

    def test_refuses_pending_trace(self):
        traces = self._load_corpus()
        traces[0]["review"] = {
            "status": "pending",
            "reviewer": "",
            "reviewedAt": None,
            "notes": "",
        }
        self._write_corpus(traces)
        self._rebind("corpus")
        with self.assertRaisesRegex(ValueError, "not approved"):
            preflight(self.root, self.config_path, git_probe=self._clean_git)

    def test_refuses_blocked_experiment_after_review(self):
        config = self._load_config()
        config["status"] = "blocked-pending-independent-review"
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "not ready-for-smoke"):
            preflight(self.root, self.config_path, git_probe=self._clean_git)

    def test_refuses_bound_artifact_digest_drift(self):
        for binding in ("corpus", "contract", "environment"):
            with self.subTest(binding=binding):
                root = Path(self.temporary.name)
                config = self._load_config()
                path = root / config["bindings"][binding]["path"]
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(PreflightError, f"{binding} digest mismatch"):
                    preflight(root, self.config_path, git_probe=self._clean_git)
                path.write_bytes(original)

    def test_refuses_model_revision_drift(self):
        config = self._load_config()
        config["models"]["trainingArtifact"]["revision"] = "b" * 40
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "model revision differs"):
            preflight(self.root, self.config_path, git_probe=self._clean_git)

    def test_refuses_aggregate_budget_overflow(self):
        budget_path = self.root / "budgets/external-spend-v1.json"
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        budget["postedSpendUsd"] = "19.00"
        budget["outstandingReservationsUsd"] = "0.00"
        budget["committedSpendUsd"] = "19.00"
        budget_path.write_text(json.dumps(budget), encoding="utf-8")
        with self.assertRaisesRegex(PreflightError, "exceed aggregate authorization"):
            preflight(self.root, self.config_path, git_probe=self._clean_git)

    def test_refuses_output_path_escape(self):
        with self.assertRaisesRegex(PreflightError, "under .artifacts"):
            _output_path(self.root, Path("elsewhere/output"))
        with self.assertRaisesRegex(PreflightError, "repository-relative"):
            _output_path(self.root, Path("/tmp/output"))

    def test_refuses_more_than_one_training_configuration(self):
        config = self._load_config()
        config["runs"].append(copy.deepcopy(config["runs"][0]))
        self._write_config(config)
        with self.assertRaisesRegex(PreflightError, "exactly one"):
            preflight(self.root, self.config_path, git_probe=self._clean_git)

    def test_refuses_heavyweight_module_loaded_before_completion(self):
        prior = sys.modules.get("torch")
        sys.modules["torch"] = types.ModuleType("torch")
        try:
            with self.assertRaisesRegex(PreflightError, "imported before preflight"):
                preflight(self.root, self.config_path, git_probe=self._clean_git)
        finally:
            if prior is None:
                del sys.modules["torch"]
            else:
                sys.modules["torch"] = prior

    def test_git_probe_refuses_dirty_or_untracked_runner_input(self):
        repo = self.root / "git-probe"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        tracked = repo / "runner.py"
        tracked.write_text("clean\n", encoding="utf-8")
        subprocess.run(["git", "add", "runner.py"], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Loomarr Test",
                "-c",
                "user.email=test@loomarr.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=repo,
            check=True,
        )
        self.assertRegex(_git_probe(repo, [tracked]), r"^[0-9a-f]{40}$")
        tracked.write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(PreflightError, "uncommitted changes"):
            _git_probe(repo, [tracked])
        untracked = repo / "new-runner.py"
        untracked.write_text("new\n", encoding="utf-8")
        with self.assertRaisesRegex(PreflightError, "untracked or uncommitted"):
            _git_probe(repo, [untracked])

    def _build_approved_workspace(self) -> Path:
        copy_paths = [
            "contracts/planner-contract-v3.json",
            "contracts/holdout-denylist-v1.json",
            "corpus/planner-smoke-v1/drafts.jsonl",
            "corpus/planner-smoke-v1/draft-manifest.json",
            "environments/qwen38-a40-v1.json",
            "environments/qwen38-a40-v1.requirements.in",
            "environments/qwen38-a40-v1.overrides.txt",
            "environments/qwen38-a40-v1.requirements.lock",
            "budgets/external-spend-v1.json",
            "experiments/planner-qwen38-smoke-v1.json",
        ]
        for relative in copy_paths:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT_ROOT / relative, destination)
        traces = self._load_corpus()
        for trace in traces:
            trace["review"] = {
                "status": "approved",
                "reviewer": "reviewer:test",
                "reviewedAt": "2026-09-03T00:00:00Z",
                "notes": "Synthetic fixture approved for preflight test.",
            }
        self._write_corpus(traces)
        config = self._load_config()
        config["status"] = "ready-for-smoke"
        self._write_config(config)
        for binding in ("corpus", "corpusManifest", "contract", "denylist", "environment"):
            self._rebind(binding)
        return self.root / "experiments/planner-qwen38-smoke-v1.json"

    def _load_corpus(self) -> list[dict]:
        config = self._load_config()
        path = self.root / config["bindings"]["corpus"]["path"]
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def _write_corpus(self, traces: list[dict]) -> None:
        path = self.root / "corpus/planner-smoke-v1/drafts.jsonl"
        path.write_text(
            "".join(
                json.dumps(trace, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                + "\n"
                for trace in traces
            ),
            encoding="utf-8",
        )

    def _rebind(self, binding: str) -> None:
        config = self._load_config()
        path = self.root / config["bindings"][binding]["path"]
        config["bindings"][binding]["sha256"] = sha256_file(path)
        self._write_config(config)

    def _load_config(self) -> dict:
        path = self.root / "experiments/planner-qwen38-smoke-v1.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_config(self, config: dict) -> None:
        path = self.root / "experiments/planner-qwen38-smoke-v1.json"
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _clean_git(_root: Path, _paths: object) -> str:
        return "a" * 40


if __name__ == "__main__":
    unittest.main()
