#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_stock_baseline

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


RUNS = ROOT / "runs/planner-current-qwen-stock-baseline-v2"
AUTHORIZATION = ROOT / "reviews/planner-current-qwen-stock-baseline/authorization-v2.json"
BUDGET = ROOT / "budgets/external-spend-v1.json"


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
        publication = publish(config_path, evidence_path)
    except (PreflightError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(publication, sort_keys=True))


def publish(config_path: Path, evidence_path: Path) -> dict[str, Any]:
    if RUNS.exists():
        raise PreflightError(f"refusing to overwrite publication: {RUNS.relative_to(ROOT)}")
    plan = preflight(ROOT, config_path, require_authorized=True)
    config = load_config(config_path)
    publication_commit = _publication_commit(config_path)
    artifact_dir = ROOT / plan.outputDir
    manifest, summary, decision = validate_run(artifact_dir, config, plan)
    provider = validate_provider_evidence(
        json.loads(evidence_path.read_text(encoding="utf-8")), config["execution"], plan
    )
    cost = Decimal(provider["costUsd"]["total"])
    settled_budget = settle_budget(json.loads(BUDGET.read_text(encoding="utf-8")), cost, plan)

    completed_at = provider["capturedAt"]
    destination = RUNS / "evidence"
    destination.parent.mkdir(parents=True)
    shutil.copytree(artifact_dir, destination)
    source_experiment = RUNS / "source-experiment.json"
    source_experiment.write_bytes(config_path.read_bytes())
    copied_provider = RUNS / "provider-settlement.json"
    shutil.copy2(evidence_path, copied_provider)
    copied_manifest = destination / "run-manifest.json"
    publication = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": (
            "qlora-justified-settled"
            if decision["qloraJustified"]
            else "qlora-not-justified-settled"
        ),
        "completedAt": completed_at,
        "sourceCommit": plan.sourceCommit,
        "publicationCommit": publication_commit,
        "sourceExperiment": {
            "path": str(source_experiment.relative_to(ROOT)),
            "sha256": sha256_file(source_experiment),
        },
        "runManifest": {
            "path": str(copied_manifest.relative_to(ROOT)),
            "sha256": sha256_file(copied_manifest),
        },
        "providerEvidence": {
            "path": str(copied_provider.relative_to(ROOT)),
            "sha256": sha256_file(copied_provider),
        },
        "providerCostUsd": str(cost),
        "summary": summary,
        "decision": decision,
        "authority": AUTHORITY,
        "budgetAfterSettlement": {
            "postedSpendUsd": settled_budget["postedSpendUsd"],
            "outstandingReservationsUsd": settled_budget["outstandingReservationsUsd"],
            "committedSpendUsd": settled_budget["committedSpendUsd"],
            "authorizationUsd": settled_budget["authorizationUsd"],
        },
    }
    publication_path = RUNS / "publication.json"
    publication_path.write_text(
        json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    settled_budget["asOf"] = completed_at[:10]
    BUDGET.write_text(
        json.dumps(settled_budget, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    authorization.update(
        {
            "status": "complete",
            "completedAt": completed_at,
            "publicationPath": str(publication_path.relative_to(ROOT)),
            "publicationSha256": sha256_file(publication_path),
        }
    )
    AUTHORIZATION.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (ROOT / build_planner_current_stock_baseline.OUTPUT).write_bytes(
        build_planner_current_stock_baseline.content()
    )
    return publication


def _publication_commit(config_path: Path) -> str:
    from loomarr_models.experiment import _git_probe

    return _git_probe(ROOT, [Path(__file__), config_path, AUTHORIZATION, BUDGET])


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
        "zeroActivePods",
        "storageMode",
        "persistentStorageDeletedWithPod",
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
        or evidence["storageMode"] != execution["storageMode"]
        or not evidence["persistentStorageDeletedWithPod"]
        or re.fullmatch(r"[0-9a-f]{64}", evidence["podIdSha256"]) is None
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
    if set(costs) != {"gpu", "disk", "persistentStorage", "total"} or any(value < 0 for value in costs.values()):
        raise PreflightError("current Runpod settlement cost fields are invalid")
    expected_gpu = hourly * duration / Decimal(3600)
    if (
        abs(costs["gpu"] - expected_gpu) > Decimal("0.01")
        or costs["gpu"] + costs["disk"] + costs["persistentStorage"] != costs["total"]
        or costs["total"] > Decimal(plan.reservationUsd)
    ):
        raise PreflightError("current Runpod settlement arithmetic or reservation drifted")
    return evidence


def settle_budget(budget: dict[str, Any], cost: Decimal, plan: Any) -> dict[str, Any]:
    try:
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("current stock baseline budget settlement is invalid") from exc
    if posted + outstanding != committed or str(committed) != plan.committedSpendUsd:
        raise PreflightError("budget changed after the committed current stock preflight")
    if cost < 0 or cost > Decimal(plan.reservationUsd) or committed + cost > authorization:
        raise PreflightError("settled current stock cost exceeds authorization")
    result = dict(budget)
    result["postedSpendUsd"] = str(posted + cost)
    result["committedSpendUsd"] = str(posted + cost + outstanding)
    return result


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
