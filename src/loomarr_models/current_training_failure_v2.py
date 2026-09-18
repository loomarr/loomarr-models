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

from .current_training import NO_AUTHORITY
from .current_training_v2 import EXPERIMENT_ID, TRAINING_RESERVATION_USD
from .experiment import PreflightError


EXPECTED_SOURCE_COMMIT = "6c1a43d8af777be0d475060c3a3ff22df7b312db"
EXPECTED_PLAN_COMMIT = "adbde9e6d9e42f0eaf8402fb0aef5325d2fe4d9b"
EXPECTED_SOURCE_CONFIG_SHA256 = "c5d38651b1c2a17540d9b69de26e1b3f605d8d50f565409906ce4add660a7595"
EXPECTED_ARCHIVE_SHA256 = "958fa29db90c4cae4c85719c25b1472851f6f50cccb30f515769b3b80b0984ad"
ARTIFACT_DIRECTORY = "loomarr-models/.artifacts/planner-current-qwen38-qlora-v2"
EXPECTED_MEMBERS = {
    "loomarr-logs/environment-setup.log",
    "loomarr-logs/failure-evidence/postfailure-snapshot.txt",
    "loomarr-logs/failure-evidence/sha256sums.txt",
    "loomarr-logs/import-probe.json",
    "loomarr-logs/make-check.log",
    "loomarr-logs/paid-preflight.json",
    "loomarr-logs/prelaunch-snapshot.txt",
    "loomarr-logs/source-setup.log",
    "loomarr-logs/training.exit",
    "loomarr-logs/training.log",
}


def validate_failure_archive(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_ARCHIVE_SHA256:
        raise PreflightError("corrected current QLoRA failure archive digest mismatch")
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            files = {member.name: member for member in members if member.isfile()}
            if set(files) != EXPECTED_MEMBERS:
                raise PreflightError("corrected current QLoRA failure archive inventory drifted")
            if not any(
                member.isdir() and member.name.rstrip("/") == ARTIFACT_DIRECTORY
                for member in members
            ):
                raise PreflightError("corrected current QLoRA empty output directory is missing")
            values = {
                name: archive.extractfile(member).read()
                for name, member in files.items()
            }
    except (tarfile.TarError, OSError, AttributeError) as exc:
        raise PreflightError("cannot read corrected current QLoRA failure archive") from exc

    if values["loomarr-logs/training.exit"] != b"2\n":
        raise PreflightError("corrected current QLoRA failure exit code is not terminal")
    prelaunch = values["loomarr-logs/prelaunch-snapshot.txt"].decode("utf-8")
    if f"\n{EXPECTED_SOURCE_COMMIT}\n" not in prelaunch or "?? " in prelaunch:
        raise PreflightError("corrected current QLoRA prelaunch source identity drifted")
    paid_preflight = json.loads(values["loomarr-logs/paid-preflight.json"])
    if (
        paid_preflight.get("experimentId") != EXPERIMENT_ID
        or paid_preflight.get("sourceCommit") != EXPECTED_SOURCE_COMMIT
        or paid_preflight.get("trainingArtifactRevision")
        != "8aa5f05d26b7205477066e1449e0af13f762a299"
        or paid_preflight.get("trainingAuthorized") is not True
    ):
        raise PreflightError("corrected current QLoRA paid preflight identity drifted")
    log = values["loomarr-logs/training.log"].decode("utf-8")
    if (
        "live rendered training capacity differs from the preregistered report" not in log
        or "Loading weights: 100%" not in log
        or "9/9" in log
    ):
        raise PreflightError("corrected current QLoRA failure class is not the recorded mismatch")
    postfailure = values[
        "loomarr-logs/failure-evidence/postfailure-snapshot.txt"
    ].decode("utf-8")
    if (
        "trainingExit=2" not in postfailure
        or EXPECTED_SOURCE_COMMIT not in postfailure
        or "8aa5f05d26b7205477066e1449e0af13f762a299" not in postfailure
        or f"d /workspace/{ARTIFACT_DIRECTORY} " not in postfailure
    ):
        raise PreflightError("corrected current QLoRA postfailure evidence drifted")
    return {
        "sha256": digest,
        "exitCode": 2,
        "failureClass": "live-rendered-capacity-mismatch",
        "optimizerSteps": 0,
        "adapterProduced": False,
    }


def validate_provider_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "experimentId", "provider", "status", "capturedAt",
        "cloud", "dataCenterId", "gpuSku", "gpuHourlyUsd", "createdAt",
        "deletedAt", "podIdSha256", "zeroActivePods", "storageMode",
        "containerDiskGb", "persistentStorageGb", "persistentStorageDeletedWithPod",
        "costUsd",
    }
    if set(evidence) != required or evidence.get("schemaVersion") != 1:
        raise PreflightError("corrected current QLoRA provider settlement fields drifted")
    if (
        evidence.get("experimentId") != EXPERIMENT_ID
        or evidence.get("provider") != "runpod"
        or evidence.get("status") != "settled-resources-deleted"
        or evidence.get("cloud") != "SECURE"
        or evidence.get("dataCenterId") != "CA-MTL-1"
        or evidence.get("gpuSku") != "NVIDIA A40"
        or evidence.get("storageMode") != "pod-persistent"
        or evidence.get("containerDiskGb") != 40
        or evidence.get("persistentStorageGb") != 80
        or evidence.get("zeroActivePods") is not True
        or evidence.get("persistentStorageDeletedWithPod") is not True
        or re.fullmatch(r"[0-9a-f]{64}", evidence.get("podIdSha256", "")) is None
    ):
        raise PreflightError("corrected current QLoRA provider identity or teardown drifted")
    try:
        created = _timestamp(evidence["createdAt"])
        deleted = _timestamp(evidence["deletedAt"])
        captured = _timestamp(evidence["capturedAt"])
        hourly = Decimal(evidence["gpuHourlyUsd"])
        costs = {key: Decimal(value) for key, value in evidence["costUsd"].items()}
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise PreflightError("corrected current QLoRA provider settlement values are invalid") from exc
    duration = Decimal(str((deleted - created).total_seconds()))
    if duration <= 0 or duration > 9000 or captured < deleted or hourly != Decimal("0.49"):
        raise PreflightError("corrected current QLoRA provider duration or hourly rate drifted")
    if set(costs) != {"cpu", "disk", "gpu", "total"} or any(value < 0 for value in costs.values()):
        raise PreflightError("corrected current QLoRA provider cost fields drifted")
    component_delta = abs(costs["cpu"] + costs["disk"] + costs["gpu"] - costs["total"])
    if component_delta > Decimal("0.000000000000001"):
        raise PreflightError("corrected current QLoRA provider cost components do not sum")
    if abs(costs["gpu"] - hourly * duration / Decimal(3600)) > Decimal("0.01"):
        raise PreflightError("corrected current QLoRA provider GPU charge differs from runtime")
    if costs["total"] > TRAINING_RESERVATION_USD:
        raise PreflightError("corrected current QLoRA provider cost exceeds the training reservation")
    return evidence


def settle_budget(budget: dict[str, Any], cost: Decimal, committed_before: str) -> dict[str, Any]:
    try:
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("corrected current QLoRA budget settlement is invalid") from exc
    if posted + outstanding != committed or str(committed) != committed_before:
        raise PreflightError("budget changed after corrected current QLoRA execution")
    if cost < 0 or cost > TRAINING_RESERVATION_USD or committed + cost > authorization:
        raise PreflightError("settled corrected current QLoRA cost exceeds authorization")
    result = dict(budget)
    result["postedSpendUsd"] = str(posted + cost)
    result["committedSpendUsd"] = str(posted + cost + outstanding)
    return result


def terminal_config(
    publication_path: str,
    publication_sha256: str,
    source_path: str,
    source_sha256: str,
    budget: dict[str, Any],
) -> bytes:
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
