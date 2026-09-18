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

from loomarr_models.current_training_failure import (
    EXPECTED_MEMBERS,
    EXPECTED_SOURCE_COMMIT,
    settle_budget,
    terminal_config,
    validate_failure_archive,
    validate_provider_evidence,
)
from loomarr_models.experiment import PreflightError


class CurrentTrainingFailureTests(unittest.TestCase):
    def archive_fixture(self, path: Path) -> str:
        values = {name: b"evidence\n" for name in EXPECTED_MEMBERS}
        values["loomarr-logs/training.exit"] = b"1\n"
        values["loomarr-logs/training.log"] = b"model download: Disk quota exceeded\n"
        values["loomarr-evidence/source-commit.txt"] = (EXPECTED_SOURCE_COMMIT + "\n").encode()
        values["loomarr-evidence/git-status.txt"] = b""
        values["loomarr-evidence/artifact-files.txt"] = b""
        with tarfile.open(path, "w:gz") as archive:
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
                "loomarr_models.current_training_failure.EXPECTED_ARCHIVE_SHA256", digest
            ):
                result = validate_failure_archive(path)
            self.assertEqual(result["exitCode"], 1)
            self.assertEqual(result["optimizerSteps"], 0)
            self.assertFalse(result["adapterProduced"])

            data = path.read_bytes() + b"drift"
            path.write_bytes(data)
            with self.assertRaisesRegex(PreflightError, "digest mismatch"):
                validate_failure_archive(path)

    def provider_fixture(self) -> dict:
        return {
            "schemaVersion": 1,
            "experimentId": "planner-current-qwen38-qlora-v1",
            "provider": "runpod",
            "status": "settled-resources-deleted",
            "capturedAt": "2026-09-18T03:00:00Z",
            "cloud": "SECURE",
            "dataCenterId": "CA-MTL-1",
            "gpuSku": "NVIDIA A40",
            "gpuHourlyUsd": "0.49",
            "createdAt": "2026-09-18T02:08:08Z",
            "deletedAt": "2026-09-18T02:28:08Z",
            "podIdSha256": "a" * 64,
            "zeroActivePods": True,
            "storageMode": "pod-persistent",
            "persistentStorageDeletedWithPod": True,
            "costUsd": {"cpu": "0", "disk": "0.01", "gpu": "0.163", "total": "0.173"},
        }

    def test_provider_evidence_is_exact_bounded_and_deleted(self):
        evidence = self.provider_fixture()
        self.assertIs(validate_provider_evidence(evidence), evidence)
        evidence["zeroActivePods"] = False
        with self.assertRaisesRegex(PreflightError, "teardown"):
            validate_provider_evidence(evidence)

    def test_provider_evidence_accepts_only_sub_femtodollar_component_rounding(self):
        evidence = self.provider_fixture()
        evidence["costUsd"] = {
            "cpu": "0",
            "disk": "0.003703703638166189",
            "gpu": "0.15634634345769882",
            "total": "0.160050047095865",
        }
        self.assertIs(validate_provider_evidence(evidence), evidence)
        evidence["costUsd"]["total"] = "0.1600500470958"
        with self.assertRaisesRegex(PreflightError, "components do not sum"):
            validate_provider_evidence(evidence)

    def test_settlement_posts_only_actual_training_cost(self):
        budget = {
            "postedSpendUsd": "29.1962968898326090175",
            "outstandingReservationsUsd": "0",
            "committedSpendUsd": "29.1962968898326090175",
            "authorizationUsd": "40.00",
        }
        settled = settle_budget(budget, Decimal("0.173"), budget["committedSpendUsd"])
        self.assertEqual(settled["postedSpendUsd"], "29.3692968898326090175")
        with self.assertRaisesRegex(PreflightError, "exceeds authorization"):
            settle_budget(budget, Decimal("1.51"), budget["committedSpendUsd"])

    def test_terminal_config_revokes_every_paid_and_product_authority(self):
        budget = {
            "postedSpendUsd": "29.3692968898326090175",
            "outstandingReservationsUsd": "0",
            "committedSpendUsd": "29.3692968898326090175",
            "authorizationUsd": "40.00",
        }
        value = json.loads(
            terminal_config("runs/x/publication.json", "a" * 64, "runs/x/source.json", "b" * 64, budget)
        )
        self.assertEqual(value["status"], "failed-settled")
        self.assertFalse(any(value["authority"].values()))
        self.assertEqual(value["budgetAfterSettlement"]["committedSpendUsd"], budget["committedSpendUsd"])


if __name__ == "__main__":
    unittest.main()
