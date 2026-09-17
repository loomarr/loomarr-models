from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))

from verify_planner_qwen38_qlora_v2_artifact import (
    ArtifactVerificationError,
    verify_artifact,
)


SOURCE_COMMIT = "a" * 40


class QLoRAV2ArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in (
            "experiments/planner-qwen38-qlora-v2.json",
            "environments/qwen38-a40-v1.json",
            "budgets/external-spend-v1.json",
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE_ROOT / relative, destination)
        config_path = self.root / "experiments/planner-qwen38-qlora-v2.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["status"] = "ready-for-training"
        self._write_json(config_path, config)
        self.artifact_dir = self.root / ".artifacts/planner-qwen38-qlora-v2"
        self.adapter_dir = self.artifact_dir / "adapter"
        self.adapter_dir.mkdir(parents=True)
        self._write_adapter()
        self._write_manifest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_accepts_exact_adapter_only_artifact(self) -> None:
        report = self._verify()
        self.assertEqual(report["status"], "verified-adapter-only-artifact")
        self.assertEqual(report["completedSteps"], 45)
        self.assertEqual(report["adapterFileCount"], 3)

    def test_rejects_adapter_digest_drift(self) -> None:
        (self.adapter_dir / "adapter_model.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(ArtifactVerificationError, "inventory or digest"):
            self._verify()

    def test_rejects_wrong_source_commit(self) -> None:
        with self.assertRaisesRegex(ArtifactVerificationError, "preflight differs"):
            self._verify("b" * 40)

    def test_rejects_incomplete_training(self) -> None:
        manifest = self._manifest()
        manifest["completedSteps"] = 44
        self._write_json(self.artifact_dir / "run-manifest.json", manifest)
        with self.assertRaisesRegex(ArtifactVerificationError, "exact step count"):
            self._verify()

    def test_rejects_merged_weights(self) -> None:
        merged = self.adapter_dir / "model.safetensors"
        merged.write_bytes(b"base weights")
        manifest = self._manifest()
        manifest["adapterFiles"][merged.name] = self._sha(merged)
        self._write_json(self.artifact_dir / "run-manifest.json", manifest)
        with self.assertRaisesRegex(ArtifactVerificationError, "base-model weights"):
            self._verify()

    def test_rejects_planned_but_unauthorized_config(self) -> None:
        config_path = self.root / "experiments/planner-qwen38-qlora-v2.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["status"] = "planned-no-paid-run-authorized"
        self._write_json(config_path, config)
        with self.assertRaisesRegex(ArtifactVerificationError, "not the authorized"):
            self._verify()

    def _verify(self, source_commit: str = SOURCE_COMMIT):
        return verify_artifact(
            self.root,
            self.root / "experiments/planner-qwen38-qlora-v2.json",
            self.artifact_dir,
            source_commit,
        )

    def _write_adapter(self) -> None:
        self._write_json(
            self.adapter_dir / "adapter_config.json",
            {"peft_type": "LORA", "r": 8, "lora_alpha": 8, "lora_dropout": 0},
        )
        (self.adapter_dir / "adapter_model.safetensors").write_bytes(b"adapter")
        self._write_json(self.adapter_dir / "tokenizer.json", {"version": "1"})

    def _write_manifest(self) -> None:
        self._write_json(self.artifact_dir / "run-manifest.json", self._manifest())

    def _manifest(self) -> dict:
        config_path = self.root / "experiments/planner-qwen38-qlora-v2.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        environment = json.loads(
            (self.root / "environments/qwen38-a40-v1.json").read_text(encoding="utf-8")
        )
        budget = json.loads(
            (self.root / "budgets/external-spend-v1.json").read_text(encoding="utf-8")
        )
        return {
            "schemaVersion": 1,
            "preflight": {
                "schemaVersion": 1,
                "experimentId": config["experimentId"],
                "configSha256": self._sha(config_path),
                "corpusSha256": config["bindings"]["corpus"]["sha256"],
                "traceCount": 120,
                "approvedCount": 120,
                "environmentSha256": config["bindings"]["environment"]["sha256"],
                "environmentId": environment["environmentId"],
                "upstreamRevision": config["models"]["upstream"]["revision"],
                "trainingArtifactRevision": config["models"]["trainingArtifact"][
                    "revision"
                ],
                "committedSpendUsd": budget["committedSpendUsd"],
                "reservationUsd": "1.50",
                "projectedSpendUsd": "30.6962968898326090175",
                "authorizationUsd": "40.00",
                "sourceCommit": SOURCE_COMMIT,
                "outputDir": ".artifacts/planner-qwen38-qlora-v2",
            },
            "runId": "qwen38-qlora-a40-v2",
            "elapsedSeconds": 2100.0,
            "completedSteps": 45,
            "renderedTrainingSha256": "c" * 64,
            "packages": {
                "torch": "2.8.0+cu128",
                "unsloth": "2026.9.2",
                "unsloth-zoo": "2026.9.1",
                "transformers": "5.15.1",
                "trl": "0.22.2",
                "peft": "0.18.0",
                "datasets": "4.3.0",
            },
            "runtime": {
                "python": "3.12.3",
                "cuda": "12.8",
                "gpu": [
                    {
                        "name": "NVIDIA A40",
                        "totalMemoryBytes": 47_708_110_848,
                        "peakReservedBytes": 26_742_882_304,
                    }
                ],
            },
            "metrics": {"train_runtime": 1900.0},
            "adapterFiles": {
                str(path.relative_to(self.adapter_dir)): self._sha(path)
                for path in sorted(self.adapter_dir.rglob("*"))
                if path.is_file()
            },
            "loadProbe": {
                "activeAdapter": "default",
                "generatedTokenCount": 8,
                "outputSha256": "d" * 64,
            },
        }

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
