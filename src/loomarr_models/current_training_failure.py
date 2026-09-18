from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import tarfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .current_training import EXPERIMENT_ID, NO_AUTHORITY, TRAINING_RESERVATION_USD
from .experiment import PreflightError


EXPECTED_SOURCE_COMMIT = "4900124cbd052a19d87230f0d0e309da7efb8571"
EXPECTED_ARCHIVE_SHA256 = "8858d36143a4b7c64dbb3cea5ef32ec1c3be696814735b1d995d0f3183b4fc38"
EXPECTED_MEMBERS = {
    "loomarr-evidence/artifact-files.txt",
    "loomarr-evidence/git-status.txt",
    "loomarr-evidence/gpu.txt",
    "loomarr-evidence/log-sha256.txt",
    "loomarr-evidence/source-commit.txt",
    "loomarr-evidence/storage.txt",
    "loomarr-evidence/tar.stderr",
    "loomarr-logs/compatibility-probe.log",
    "loomarr-logs/dependency-sync.log",
    "loomarr-logs/make-check.log",
    "loomarr-logs/paid-preflight.log",
    "loomarr-logs/training.exit",
    "loomarr-logs/training.log",
    "loomarr-logs/training.pid",
    "loomarr-logs/uv-install.log",
    "loomarr-logs/venv.log",
}


def validate_failure_archive(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_ARCHIVE_SHA256:
        raise PreflightError("current QLoRA failure archive digest mismatch")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            files = {member.name: member for member in archive.getmembers() if member.isfile()}
            normalized = {name.removeprefix("loomarr-models/.artifacts/planner-current-qwen38-qlora-v1/") for name in files}
            evidence_names = {name for name in normalized if not name.startswith("loomarr-models/")}
            if evidence_names != EXPECTED_MEMBERS:
                raise PreflightError("current QLoRA failure archive inventory drifted")
            values = {
                normalized_name: archive.extractfile(member).read()
                for name, member in files.items()
                if (normalized_name := name.removeprefix(
                    "loomarr-models/.artifacts/planner-current-qwen38-qlora-v1/"
                )) in EXPECTED_MEMBERS
            }
    except (tarfile.TarError, OSError, AttributeError) as exc:
        raise PreflightError("cannot read current QLoRA failure archive") from exc
    if values["loomarr-logs/training.exit"] != b"1\n":
        raise PreflightError("current QLoRA failure exit code is not terminal")
    if values["loomarr-evidence/source-commit.txt"] != (EXPECTED_SOURCE_COMMIT + "\n").encode():
        raise PreflightError("current QLoRA failure source commit drifted")
    if values["loomarr-evidence/git-status.txt"] != b"":
        raise PreflightError("current QLoRA execution checkout was dirty")
    if values["loomarr-evidence/artifact-files.txt"] != b"":
        raise PreflightError("current QLoRA failure unexpectedly produced adapter files")
    log = values["loomarr-logs/training.log"].decode("utf-8")
    if "Disk quota exceeded" not in log or "optimizer step" in log.lower():
        raise PreflightError("current QLoRA failure class is not the recorded storage exhaustion")
    return {
        "sha256": digest,
        "exitCode": 1,
        "failureClass": "model-download-storage-exhausted",
        "optimizerSteps": 0,
        "adapterProduced": False,
    }


def validate_provider_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "experimentId", "provider", "status", "capturedAt",
        "cloud", "dataCenterId", "gpuSku", "gpuHourlyUsd", "createdAt",
        "deletedAt", "podIdSha256", "zeroActivePods", "storageMode",
        "persistentStorageDeletedWithPod", "costUsd",
    }
    if set(evidence) != required or evidence.get("schemaVersion") != 1:
        raise PreflightError("current QLoRA provider settlement fields drifted")
    if (
        evidence.get("experimentId") != EXPERIMENT_ID
        or evidence.get("provider") != "runpod"
        or evidence.get("status") != "settled-resources-deleted"
        or evidence.get("cloud") != "SECURE"
        or evidence.get("dataCenterId") != "CA-MTL-1"
        or evidence.get("gpuSku") != "NVIDIA A40"
        or evidence.get("storageMode") != "pod-persistent"
        or evidence.get("zeroActivePods") is not True
        or evidence.get("persistentStorageDeletedWithPod") is not True
        or re.fullmatch(r"[0-9a-f]{64}", evidence.get("podIdSha256", "")) is None
    ):
        raise PreflightError("current QLoRA provider identity or teardown drifted")
    try:
        created = _timestamp(evidence["createdAt"])
        deleted = _timestamp(evidence["deletedAt"])
        captured = _timestamp(evidence["capturedAt"])
        hourly = Decimal(evidence["gpuHourlyUsd"])
        costs = {key: Decimal(value) for key, value in evidence["costUsd"].items()}
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise PreflightError("current QLoRA provider settlement values are invalid") from exc
    duration = Decimal(str((deleted - created).total_seconds()))
    if duration <= 0 or duration > 9000 or captured < deleted or hourly != Decimal("0.49"):
        raise PreflightError("current QLoRA provider duration or hourly rate drifted")
    if set(costs) != {"cpu", "disk", "gpu", "total"} or any(value < 0 for value in costs.values()):
        raise PreflightError("current QLoRA provider cost fields drifted")
    component_delta = abs(
        costs["cpu"] + costs["disk"] + costs["gpu"] - costs["total"]
    )
    if component_delta > Decimal("0.000000000000001"):
        raise PreflightError("current QLoRA provider cost components do not sum")
    if abs(costs["gpu"] - hourly * duration / Decimal(3600)) > Decimal("0.01"):
        raise PreflightError("current QLoRA provider GPU charge differs from runtime")
    if costs["total"] > TRAINING_RESERVATION_USD:
        raise PreflightError("current QLoRA provider cost exceeds the training reservation")
    return evidence


def settle_budget(budget: dict[str, Any], cost: Decimal, committed_before: str) -> dict[str, Any]:
    try:
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("current QLoRA budget settlement is invalid") from exc
    if posted + outstanding != committed or str(committed) != committed_before:
        raise PreflightError("budget changed after current QLoRA execution")
    if cost < 0 or cost > TRAINING_RESERVATION_USD or committed + cost > authorization:
        raise PreflightError("settled current QLoRA cost exceeds authorization")
    result = dict(budget)
    result["postedSpendUsd"] = str(posted + cost)
    result["committedSpendUsd"] = str(posted + cost + outstanding)
    return result


def terminal_config(publication_path: str, publication_sha256: str, source_path: str,
                    source_sha256: str, budget: dict[str, Any]) -> bytes:
    value = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "issue": "https://github.com/loomarr/loomarr-models/issues/20",
        "status": "failed-settled",
        "sourceExperiment": {"path": source_path, "sha256": source_sha256},
        "publication": {"path": publication_path, "sha256": publication_sha256},
        "budgetAfterSettlement": {
            "postedSpendUsd": budget["postedSpendUsd"],
            "outstandingReservationsUsd": budget["outstandingReservationsUsd"],
            "committedSpendUsd": budget["committedSpendUsd"],
            "authorizationUsd": budget["authorizationUsd"],
        },
        "authority": NO_AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def _timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed
