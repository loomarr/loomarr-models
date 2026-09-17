#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_stock_baseline
from loomarr_models.current_baseline import AUTHORITY, EXPERIMENT_ID, baseline_decision, load_config, preflight
from loomarr_models.experiment import PreflightError, _git_probe, sha256_file
from publish_planner_current_stock_baseline import validate_provider_evidence, settle_budget


RUNS = ROOT / "runs/planner-current-qwen-stock-baseline-v2"
CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v2.json"
AUTHORIZATION = ROOT / "reviews/planner-current-qwen-stock-baseline/authorization-v2.json"
BUDGET = ROOT / "budgets/external-spend-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish and settle an invalid current stock attempt")
    parser.add_argument(
        "--failure-evidence",
        type=Path,
        default=Path(".artifacts/planner-current-qwen-stock-baseline-v2-failure/failure-manifest.json"),
    )
    parser.add_argument(
        "--provider-evidence",
        type=Path,
        default=Path(".artifacts/planner-current-qwen-stock-baseline-v2-failure/provider-settlement.json"),
    )
    args = parser.parse_args()
    failure_path = args.failure_evidence if args.failure_evidence.is_absolute() else ROOT / args.failure_evidence
    provider_path = args.provider_evidence if args.provider_evidence.is_absolute() else ROOT / args.provider_evidence
    try:
        publication = publish(failure_path, provider_path)
    except (PreflightError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(publication, sort_keys=True))


def publish(failure_path: Path, provider_path: Path) -> dict[str, Any]:
    if RUNS.exists():
        raise PreflightError(f"refusing to overwrite publication: {RUNS.relative_to(ROOT)}")
    failure = validate_failure(failure_path)
    config = load_config(CONFIG)
    plan = preflight(
        ROOT,
        CONFIG,
        require_authorized=True,
        git_probe=lambda _root, _paths: failure["sourceCommit"],
    )
    if plan.sourceCommit != failure["sourceCommit"] or plan.configSha256 != failure["sourceConfigSha256"]:
        raise PreflightError("failure evidence source identity differs from the authorized plan")
    publication_commit = _git_probe(ROOT, [Path(__file__), CONFIG, AUTHORIZATION, BUDGET])
    provider = validate_provider_evidence(
        json.loads(provider_path.read_text(encoding="utf-8")), config["execution"], plan
    )
    cost = Decimal(provider["costUsd"]["total"])
    settled_budget = settle_budget(json.loads(BUDGET.read_text(encoding="utf-8")), cost, plan)
    decision = baseline_decision({}, config["scoring"], run_status=failure["completionClass"])

    completed_at = provider["capturedAt"]
    evidence_dir = failure_path.parent
    destination = RUNS / "evidence"
    destination.parent.mkdir(parents=True)
    shutil.copytree(evidence_dir, destination)
    source_experiment = RUNS / "source-experiment.json"
    source_experiment.write_bytes(CONFIG.read_bytes())
    copied_provider = RUNS / "provider-settlement.json"
    shutil.copy2(provider_path, copied_provider)
    copied_failure = destination / failure_path.name
    publication = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "baseline-invalid-settled",
        "completedAt": completed_at,
        "sourceCommit": plan.sourceCommit,
        "publicationCommit": publication_commit,
        "sourceExperiment": {
            "path": str(source_experiment.relative_to(ROOT)),
            "sha256": sha256_file(source_experiment),
        },
        "failureManifest": {
            "path": str(copied_failure.relative_to(ROOT)),
            "sha256": sha256_file(copied_failure),
        },
        "providerEvidence": {
            "path": str(copied_provider.relative_to(ROOT)),
            "sha256": sha256_file(copied_provider),
        },
        "providerCostUsd": str(cost),
        "summary": None,
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
    publication_path.write_text(json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    settled_budget["asOf"] = completed_at[:10]
    BUDGET.write_text(json.dumps(settled_budget, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    authorization.update(
        {
            "status": "complete",
            "completedAt": completed_at,
            "publicationPath": str(publication_path.relative_to(ROOT)),
            "publicationSha256": sha256_file(publication_path),
        }
    )
    AUTHORIZATION.write_text(json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / build_planner_current_stock_baseline.OUTPUT).write_bytes(
        build_planner_current_stock_baseline.content()
    )
    return publication


def validate_failure(path: Path) -> dict[str, Any]:
    failure = json.loads(path.read_text(encoding="utf-8"))
    if set(failure) != {
        "schemaVersion",
        "experimentId",
        "status",
        "completionClass",
        "sourceCommit",
        "sourceConfigSha256",
        "providerCostUsd",
        "error",
        "artifacts",
        "authority",
    }:
        raise PreflightError("current stock failure manifest fields differ from schema v1")
    if (
        failure["schemaVersion"] != 1
        or failure["experimentId"] != EXPERIMENT_ID
        or failure["status"] != "failed-unsettled"
        or failure["completionClass"] != "runtime-configuration-failure"
        or failure["providerCostUsd"] is not None
        or failure["authority"] != AUTHORITY
        or re.fullmatch(r"[0-9a-f]{40}", failure["sourceCommit"]) is None
        or re.fullmatch(r"[0-9a-f]{64}", failure["sourceConfigSha256"]) is None
        or failure["error"] != {
            "exitCode": 2,
            "message": "evaluation prompt leaves only -729 generation tokens within context",
        }
    ):
        raise PreflightError("current stock failure identity or classification drifted")
    artifacts = failure["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"archive", "baselineLog", "setupLog"}:
        raise PreflightError("current stock failure artifact bindings drifted")
    directory = path.parent.resolve(strict=True)
    for name, binding in artifacts.items():
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            raise PreflightError(f"current stock failure {name} binding is invalid")
        artifact = (directory / binding["path"]).resolve(strict=True)
        if not artifact.is_relative_to(directory) or sha256_file(artifact) != binding["sha256"]:
            raise PreflightError(f"current stock failure {name} digest mismatch")
    return failure


if __name__ == "__main__":
    main()
