#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_baseline import (
    AUTHORITY,
    EXPERIMENT_ID,
    CurrentCaseResult,
    baseline_decision,
    load_config,
    preflight,
    summarize_current_candidate,
)
from loomarr_models.experiment import PreflightError, sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a current-contract stock baseline publication")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/planner-current-qwen-stock-baseline-v2.json"),
    )
    parser.add_argument(
        "--provider-evidence",
        type=Path,
        default=Path(".artifacts/planner-current-qwen-stock-baseline-v2/provider-settlement.json"),
    )
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    evidence_path = args.provider_evidence if args.provider_evidence.is_absolute() else ROOT / args.provider_evidence
    try:
        plan = preflight(ROOT, config_path, require_authorized=True)
        config = load_config(config_path)
        artifact_dir = ROOT / plan.outputDir
        manifest, summary, decision = validate_run(artifact_dir, config, plan)
        provider = validate_provider_evidence(
            json.loads(evidence_path.read_text(encoding="utf-8")), config["execution"], plan
        )
    except (PreflightError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"manifest": manifest, "summary": summary, "decision": decision, "provider": provider}, sort_keys=True))


def validate_run(
    directory: Path, config: dict[str, Any], plan: Any
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = json.loads((directory / "run-manifest.json").read_text(encoding="utf-8"))
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
        raise PreflightError("current stock run manifest fields differ from schema v2")
    if (
        manifest["schemaVersion"] != 2
        or manifest["experimentId"] != EXPERIMENT_ID
        or manifest["status"] != "complete-unsettled"
        or manifest["completionClass"] != "complete-model-quality"
        or manifest["preflight"] != plan.as_dict()
        or manifest["providerCostUsd"] is not None
        or manifest["authority"] != AUTHORITY
        or not isinstance(manifest["elapsedSeconds"], (int, float))
        or not 0 < manifest["elapsedSeconds"] <= config["execution"]["maxWallClockSeconds"]
    ):
        raise PreflightError("current stock run identity or status drifted")
    _validate_runtime(manifest["runtime"], manifest["packages"], config)
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"results", "generations"}:
        raise PreflightError("current stock artifact bindings drifted")
    paths: dict[str, Path] = {}
    for name, binding in artifacts.items():
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise PreflightError(f"current stock {name} binding is invalid")
        path = (directory / binding["path"]).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or sha256_file(path) != binding["sha256"]:
            raise PreflightError(f"current stock {name} digest mismatch")
        paths[name] = path
    try:
        results = [CurrentCaseResult(**row) for row in _jsonl(paths["results"])]
    except TypeError as exc:
        raise PreflightError("current stock result fields differ from scorer") from exc
    peak = manifest["runtime"]["gpu"]["peakReservedBytes"]
    summary = summarize_current_candidate(plan.candidateId, results, peak_vram_bytes=peak)
    if summary != manifest["summary"]:
        raise PreflightError("current stock summary does not replay")
    decision = baseline_decision(summary, config["scoring"], run_status=manifest["completionClass"])
    if decision != manifest["decision"]:
        raise PreflightError("current stock decision does not replay")
    generations = _jsonl(paths["generations"])
    if len(generations) != sum(result.modelCalls for result in results):
        raise PreflightError("current stock generation coverage differs from results")
    for generation in generations:
        if "raw" in generation or re.fullmatch(r"[0-9a-f]{64}", generation.get("rawSha256", "")) is None:
            raise PreflightError("current stock generation is not safely redacted")
    return manifest, summary, decision


def validate_provider_evidence(evidence: dict[str, Any], execution: dict[str, Any], plan: Any) -> dict[str, Any]:
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
        "networkVolumeIdSha256",
        "zeroActivePods",
        "networkVolumeDeleted",
        "costUsd",
    }
    if set(evidence) != required or evidence.get("schemaVersion") != 2:
        raise PreflightError("current Runpod settlement fields differ from schema v2")
    if (
        evidence["experimentId"] != EXPERIMENT_ID
        or evidence["provider"] != "runpod"
        or evidence["status"] != "settled-resources-deleted"
        or evidence["cloud"] != execution["cloud"]
        or evidence["gpuSku"] != execution["gpuSku"]
        or not evidence["zeroActivePods"]
        or not evidence["networkVolumeDeleted"]
        or re.fullmatch(r"[0-9a-f]{64}", evidence["podIdSha256"]) is None
        or re.fullmatch(r"[0-9a-f]{64}", evidence["networkVolumeIdSha256"]) is None
    ):
        raise PreflightError("current Runpod settlement identity or teardown evidence drifted")
    try:
        created = dt.datetime.fromisoformat(evidence["createdAt"].replace("Z", "+00:00"))
        deleted = dt.datetime.fromisoformat(evidence["deletedAt"].replace("Z", "+00:00"))
        captured = dt.datetime.fromisoformat(evidence["capturedAt"].replace("Z", "+00:00"))
        hourly = Decimal(evidence["gpuHourlyUsd"])
        costs = {key: Decimal(value) for key, value in evidence["costUsd"].items()}
    except (AttributeError, ValueError, InvalidOperation) as exc:
        raise PreflightError("current Runpod settlement values are invalid") from exc
    duration = Decimal(str((deleted - created).total_seconds()))
    if any(value.tzinfo is None for value in (created, deleted, captured)) or duration <= 0 or duration > execution["maxWallClockSeconds"] or captured < deleted:
        raise PreflightError("current Runpod settlement exceeds the provider-creation deadline")
    if set(costs) != {"gpu", "disk", "networkVolume", "total"} or any(value < 0 for value in costs.values()):
        raise PreflightError("current Runpod settlement cost fields are invalid")
    expected_gpu = hourly * duration / Decimal(3600)
    if (
        abs(costs["gpu"] - expected_gpu) > Decimal("0.01")
        or costs["gpu"] + costs["disk"] + costs["networkVolume"] != costs["total"]
        or costs["total"] > Decimal(plan.reservationUsd)
    ):
        raise PreflightError("current Runpod settlement arithmetic or reservation drifted")
    return evidence


def _validate_runtime(runtime: Any, packages: Any, config: dict[str, Any]) -> None:
    if not isinstance(runtime, dict) or set(runtime) != {"python", "cuda", "gpu"}:
        raise PreflightError("current stock runtime fields drifted")
    gpu = runtime["gpu"]
    if (
        not isinstance(gpu, dict)
        or set(gpu) != {"name", "totalMemoryBytes", "peakReservedBytes"}
        or config["execution"]["gpuSku"] not in gpu["name"]
        or gpu["totalMemoryBytes"] < 47_000_000_000
        or not 0 < gpu["peakReservedBytes"] <= gpu["totalMemoryBytes"]
        or not str(runtime["cuda"]).startswith(config["execution"]["minimumCudaVersion"])
    ):
        raise PreflightError("current stock GPU runtime differs from execution envelope")
    environment = json.loads(
        (ROOT / config["bindings"]["environment"]["path"]).read_text(encoding="utf-8")
    )
    expected = {
        "torch": f'{environment["container"]["pytorch"]}+cu128',
        "unsloth": environment["trainingPackages"]["unsloth"],
        "unsloth-zoo": environment["trainingPackages"]["unsloth_zoo"],
        "transformers": environment["trainingPackages"]["transformers"],
    }
    if packages != expected:
        raise PreflightError("current stock package versions differ from locked environment")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise PreflightError(f"{path.name} contains a non-object row")
        values.append(value)
    return values


if __name__ == "__main__":
    main()
