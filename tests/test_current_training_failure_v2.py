from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from loomarr_models.current_training_failure_v2 import (
    ARTIFACT_DIRECTORY,
    EXPECTED_MEMBERS,
    EXPECTED_SOURCE_COMMIT,
    settle_budget,
    terminal_config,
    validate_failure_archive,
    validate_provider_evidence,
)
from loomarr_models.experiment import PreflightError


class CurrentTrainingFailureV2Tests(unittest.TestCase):
    def archive_fixture(self, path: Path) -> str:
        values = {name: b"evidence\n" for name in EXPECTED_MEMBERS}
        values["loomarr-logs/training.exit"] = b"2\n"
        values["loomarr-logs/training.log"] = (
            b"Loading weights: 100%\n"
            b"live rendered training capacity differs from the preregistered report\n"
        )
        values["loomarr-logs/prelaunch-snapshot.txt"] = (
            f"2026-09-18T13:07:55Z\n{EXPECTED_SOURCE_COMMIT}\nconfig hash\n"
        ).encode()
        values["loomarr-logs/paid-preflight.json"] = json.dumps(
            {
                "experimentId": "planner-current-qwen38-qlora-v2",
                "sourceCommit": EXPECTED_SOURCE_COMMIT,
                "trainingArtifactRevision": "8aa5f05d26b7205477066e1449e0af13f762a299",
                "trainingAuthorized": True,
            }
        ).encode()
        values["loomarr-logs/failure-evidence/postfailure-snapshot.txt"] = (
            f"trainingExit=2\n{EXPECTED_SOURCE_COMMIT}\n"
            f"d /workspace/{ARTIFACT_DIRECTORY} 1\n"
            "8aa5f05d26b7205477066e1449e0af13f762a299\n"
        ).encode()
        with tarfile.open(path, "w:gz") as archive:
            directory = tarfile.TarInfo(ARTIFACT_DIRECTORY)
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
            for name in sorted(values):
                info = tarfile.TarInfo(name)
                info.size = len(values[name])
                archive.addfile(info, io.BytesIO(values[name]))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_failure_archive_is_exact_terminal_and_adapter_free(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "failure.tgz"
            digest = self.archive_fixture(path)
            with patch(
                "loomarr_models.current_training_failure_v2.EXPECTED_ARCHIVE_SHA256",
                digest,
            ):
                result = validate_failure_archive(path)
            self.assertEqual(result["exitCode"], 2)
            self.assertEqual(result["optimizerSteps"], 0)
            self.assertFalse(result["adapterProduced"])
            self.assertEqual(result["failureClass"], "live-rendered-capacity-mismatch")

    def provider_fixture(self) -> dict:
        return {
            "schemaVersion": 1,
            "experimentId": "planner-current-qwen38-qlora-v2",
            "provider": "runpod",
            "status": "settled-resources-deleted",
            "capturedAt": "2026-09-18T13:30:00Z",
            "cloud": "SECURE",
            "dataCenterId": "CA-MTL-1",
            "gpuSku": "NVIDIA A40",
            "gpuHourlyUsd": "0.49",
            "createdAt": "2026-09-18T13:01:05Z",
            "deletedAt": "2026-09-18T13:24:34Z",
            "podIdSha256": "a" * 64,
            "zeroActivePods": True,
            "storageMode": "pod-persistent",
            "containerDiskGb": 40,
            "persistentStorageGb": 80,
            "persistentStorageDeletedWithPod": True,
            "costUsd": {"cpu": "0", "disk": "0.01", "gpu": "0.191", "total": "0.201"},
        }

    def test_provider_evidence_is_exact_bounded_and_deleted(self):
        evidence = self.provider_fixture()
        self.assertIs(validate_provider_evidence(evidence), evidence)
        evidence["persistentStorageGb"] = 40
        with self.assertRaisesRegex(PreflightError, "teardown"):
            validate_provider_evidence(evidence)

    def test_settlement_posts_only_actual_training_cost(self):
        budget = {
            "postedSpendUsd": "29.3563469369284740175",
            "outstandingReservationsUsd": "0",
            "committedSpendUsd": "29.3563469369284740175",
            "authorizationUsd": "40.00",
        }
        settled = settle_budget(budget, Decimal("0.201"), budget["committedSpendUsd"])
        self.assertEqual(settled["postedSpendUsd"], "29.5573469369284740175")
        with self.assertRaisesRegex(PreflightError, "exceeds authorization"):
            settle_budget(budget, Decimal("1.51"), budget["committedSpendUsd"])

    def test_terminal_config_revokes_every_authority(self):
        budget = {
            "postedSpendUsd": "29.5573469369284740175",
            "outstandingReservationsUsd": "0",
            "committedSpendUsd": "29.5573469369284740175",
            "authorizationUsd": "40.00",
        }
        value = json.loads(
            terminal_config("runs/x/publication.json", "a" * 64, "runs/x/source.json", "b" * 64, budget)
        )
        self.assertEqual(value["status"], "failed-settled")
        self.assertFalse(any(value["authority"].values()))


if __name__ == "__main__":
    unittest.main()
