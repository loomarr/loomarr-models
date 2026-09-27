from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_candidate_screen as builder
from loomarr_models import candidate_screen as screen
from loomarr_models.experiment import PreflightError


CONFIG = ROOT / "experiments/planner-candidate-screen-v1.json"


def _probe(_root: Path, _paths: object) -> str:
    return "0" * 40


class CandidateScreenTests(unittest.TestCase):
    def test_generated_plan_is_current(self):
        self.assertEqual(CONFIG.read_bytes(), builder.content())

    def test_preflight_accepts_committed_plan(self):
        self.assertEqual(screen.preflight(ROOT, CONFIG, git_probe=_probe)["externalSpendUsd"], "0")

    def test_candidates_share_the_incumbent_gates_and_decoding(self):
        self.assertEqual(screen.SCREEN_GATES, ("v2", "v2-trainsplit"))
        self.assertEqual(screen.TRIALS, 5)

    def test_server_runs_beside_production_on_its_own_port(self):
        command = screen.server_command("qwen35-9b-q8_0", Path("/m.gguf"))
        self.assertIn("--jinja", command)
        self.assertEqual(command[command.index("--port") + 1], "8090")
        self.assertEqual(command[command.index("--alias") + 1], "qwen35-9b-q8_0")

    def test_exclusive_reference_refuses_while_production_is_up(self):
        with mock.patch.object(screen, "_primary_active", return_value=True), tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PreflightError, "with_gpu.sh"):
                screen.run_candidate(Path(tmp), {}, "qwen38-27b-q8_k_xl", Path(tmp) / "log")

    def _cache(self, root: Path, blob_name: str, size: int) -> None:
        candidate = screen.CANDIDATES["qwen35-4b-q4_k_m"]
        repo = root / ("models--" + candidate["repository"].replace("/", "--"))
        blob = repo / "blobs" / blob_name
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b"x" * size)
        link = repo / "snapshots" / candidate["revision"] / candidate["file"]
        link.parent.mkdir(parents=True)
        link.symlink_to(blob)

    def test_model_path_rejects_an_unpinned_blob(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(screen, "HF_HUB", tmp):
            self._cache(Path(tmp), "0" * 64, 4)
            with self.assertRaisesRegex(PreflightError, "pinned SHA-256"):
                screen.model_path(screen.CANDIDATES["qwen35-4b-q4_k_m"])

    def test_model_path_accepts_the_pinned_blob(self):
        candidate = screen.CANDIDATES["qwen35-4b-q4_k_m"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(screen, "HF_HUB", tmp), \
                mock.patch.dict(candidate, {"bytes": 4}):
            self._cache(Path(tmp), candidate["sha256"], 4)
            self.assertEqual(screen.model_path(candidate).name, candidate["file"])


if __name__ == "__main__":
    unittest.main()
