from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .current_baseline import (
    CurrentCaseResult,
    baseline_decision,
    summarize_current_candidate,
)
from .current_baseline_v3 import EXPERIMENT_ID
from .experiment import PreflightError, sha256_file


ROOT = Path(__file__).resolve().parents[2]


def validate_run(
    directory: Path, config: dict[str, Any], plan: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _object(directory / "run-manifest.json")
    required = {
        "schemaVersion",
        "experimentId",
        "status",
        "completionClass",
        "preflight",
        "elapsedSeconds",
        "packages",
        "runtime",
        "artifacts",
        "summary",
        "decision",
        "providerCostUsd",
        "authority",
    }
    if set(manifest) != required:
        raise PreflightError("current stock v3 run manifest fields differ from schema v3")
    if (
        manifest["schemaVersion"] != 3
        or manifest["experimentId"] != EXPERIMENT_ID
        or manifest["status"] != "complete-unsettled"
        or manifest["completionClass"] != "complete-model-quality"
        or manifest["preflight"] != plan.as_dict()
        or manifest["providerCostUsd"] is not None
        or manifest["authority"] != config["authority"]
        or not isinstance(manifest["elapsedSeconds"], (int, float))
        or not 0 < manifest["elapsedSeconds"] <= config["execution"]["maxWallClockSeconds"]
    ):
        raise PreflightError("current stock v3 run identity or status drifted")
    _validate_runtime(manifest["runtime"], manifest["packages"], config)
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"results", "generations"}:
        raise PreflightError("current stock v3 artifact bindings drifted")
    paths: dict[str, Path] = {}
    for name, binding in artifacts.items():
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise PreflightError(f"current stock v3 {name} binding is invalid")
        path = (directory / binding["path"]).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or sha256_file(path) != binding["sha256"]:
            raise PreflightError(f"current stock v3 {name} digest mismatch")
        paths[name] = path
    try:
        results = [CurrentCaseResult(**row) for row in _jsonl(paths["results"])]
    except TypeError as exc:
        raise PreflightError("current stock v3 result fields differ from scorer") from exc
    if len(results) != plan.caseCount:
        raise PreflightError("current stock v3 result coverage differs from the plan")
    peak = manifest["runtime"]["gpu"]["peakReservedBytes"]
    summary = summarize_current_candidate(plan.candidateId, results, peak_vram_bytes=peak)
    if summary != manifest["summary"]:
        raise PreflightError("current stock v3 summary does not replay")
    decision = baseline_decision(summary, config["scoring"], run_status=manifest["completionClass"])
    if decision != manifest["decision"]:
        raise PreflightError("current stock v3 decision does not replay")
    generations = _jsonl(paths["generations"])
    if len(generations) != sum(result.modelCalls for result in results):
        raise PreflightError("current stock v3 generation coverage differs from results")
    for generation in generations:
        if "raw" in generation or re.fullmatch(r"[0-9a-f]{64}", generation.get("rawSha256", "")) is None:
            raise PreflightError("current stock v3 generation is not safely redacted")
    return manifest, summary, decision


def validate_provider_evidence(
    evidence: dict[str, Any], execution: dict[str, Any], plan: Any
) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "experimentId",
        "provider",
        "status",
        "capturedAt",
        "cloud",
        "dataCenterId",
        "gpuSku",
        "gpuHourlyUsd",
        "createdAt",
        "deletedAt",
        "podIdSha256",
        "zeroActivePods",
        "storageMode",
        "persistentStorageDeletedWithPod",
        "costUsd",
    }
    if set(evidence) != required or evidence.get("schemaVersion") != 3:
        raise PreflightError("current Runpod v3 settlement fields differ from schema v3")
    if (
        evidence["experimentId"] != EXPERIMENT_ID
        or evidence["provider"] != "runpod"
        or evidence["status"] != "settled-resources-deleted"
        or evidence["cloud"] != execution["cloud"]
        or evidence["gpuSku"] != execution["gpuSku"]
        or not evidence["zeroActivePods"]
        or evidence["storageMode"] != execution["storageMode"]
        or not evidence["persistentStorageDeletedWithPod"]
        or re.fullmatch(r"[0-9a-f]{64}", evidence["podIdSha256"]) is None
    ):
        raise PreflightError("current Runpod v3 settlement identity or teardown evidence drifted")
    try:
        created = dt.datetime.fromisoformat(evidence["createdAt"].replace("Z", "+00:00"))
        deleted = dt.datetime.fromisoformat(evidence["deletedAt"].replace("Z", "+00:00"))
        captured = dt.datetime.fromisoformat(evidence["capturedAt"].replace("Z", "+00:00"))
        hourly = Decimal(evidence["gpuHourlyUsd"])
        costs = {key: Decimal(value) for key, value in evidence["costUsd"].items()}
        reservation = Decimal(plan.proposedReservationUsd)
    except (AttributeError, KeyError, ValueError, InvalidOperation) as exc:
        raise PreflightError("current Runpod v3 settlement values are invalid") from exc
    duration = Decimal(str((deleted - created).total_seconds()))
    if (
        any(value.tzinfo is None for value in (created, deleted, captured))
        or duration <= 0
        or duration > execution["maxWallClockSeconds"]
        or captured < deleted
    ):
        raise PreflightError("current Runpod v3 settlement exceeds the provider-creation deadline")
    if set(costs) != {"gpu", "disk", "persistentStorage", "total"} or any(
        value < 0 for value in costs.values()
    ):
        raise PreflightError("current Runpod v3 settlement cost fields are invalid")
    expected_gpu = hourly * duration / Decimal(3600)
    if (
        abs(costs["gpu"] - expected_gpu) > Decimal("0.01")
        or costs["gpu"] + costs["disk"] + costs["persistentStorage"] != costs["total"]
        or costs["total"] > reservation
    ):
        raise PreflightError("current Runpod v3 settlement arithmetic or reservation drifted")
    return evidence


def settle_budget(budget: dict[str, Any], cost: Decimal, plan: Any) -> dict[str, Any]:
    try:
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
        reservation = Decimal(plan.proposedReservationUsd)
    except (AttributeError, KeyError, InvalidOperation) as exc:
        raise PreflightError("current stock v3 budget settlement is invalid") from exc
    if posted + outstanding != committed or str(committed) != plan.committedSpendUsd:
        raise PreflightError("budget changed after the committed current stock v3 preflight")
    if cost < 0 or cost > reservation or committed + cost > authorization:
        raise PreflightError("settled current stock v3 cost exceeds authorization")
    result = dict(budget)
    result["postedSpendUsd"] = str(posted + cost)
    result["committedSpendUsd"] = str(posted + cost + outstanding)
    return result


def _validate_runtime(runtime: Any, packages: Any, config: dict[str, Any]) -> None:
    if not isinstance(runtime, dict) or set(runtime) != {"python", "cuda", "gpu"}:
        raise PreflightError("current stock v3 runtime fields drifted")
    gpu = runtime["gpu"]
    if (
        not isinstance(gpu, dict)
        or set(gpu) != {"name", "totalMemoryBytes", "peakReservedBytes"}
        or config["execution"]["gpuSku"] not in gpu["name"]
        or gpu["totalMemoryBytes"] < 47_000_000_000
        or not 0 < gpu["peakReservedBytes"] <= gpu["totalMemoryBytes"]
        or not str(runtime["cuda"]).startswith(config["execution"]["minimumCudaVersion"])
    ):
        raise PreflightError("current stock v3 GPU runtime differs from execution envelope")
    environment = _object(ROOT / config["bindings"]["environment"]["path"])
    expected = {
        "torch": f'{environment["container"]["pytorch"]}+cu128',
        "unsloth": environment["trainingPackages"]["unsloth"],
        "unsloth-zoo": environment["trainingPackages"]["unsloth_zoo"],
        "transformers": environment["trainingPackages"]["transformers"],
    }
    if packages != expected:
        raise PreflightError("current stock v3 package versions differ from locked environment")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise PreflightError(f"{path.name} contains a non-object row")
        values.append(value)
    return values


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must contain one JSON object")
    return value
