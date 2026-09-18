#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_training import EXPERIMENT_ID, load_config, preflight
from loomarr_models.current_training_failure import (
    EXPECTED_SOURCE_COMMIT,
    settle_budget,
    terminal_config,
    validate_failure_archive,
    validate_provider_evidence,
)
from loomarr_models.experiment import PreflightError, _git_probe, sha256_file


RUNS = ROOT / "runs/planner-current-qwen38-qlora-v1"
CONFIG = ROOT / "experiments/planner-current-qwen38-qlora-v1.json"
AUTHORIZATION = ROOT / "reviews/planner-current-qwen38-qlora-v1/authorization.json"
BUDGET = ROOT / "budgets/external-spend-v1.json"
MODULE = ROOT / "src/loomarr_models/current_training_failure.py"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the terminal current QLoRA failure")
    parser.add_argument("--failure-archive", type=Path, required=True)
    parser.add_argument("--provider-evidence", type=Path, required=True)
    args = parser.parse_args()
    archive = args.failure_archive if args.failure_archive.is_absolute() else ROOT / args.failure_archive
    provider = args.provider_evidence if args.provider_evidence.is_absolute() else ROOT / args.provider_evidence
    try:
        publication = publish(archive, provider)
    except (PreflightError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(publication, sort_keys=True))


def publish(archive_path: Path, provider_path: Path) -> dict:
    if RUNS.exists():
        raise PreflightError(f"refusing to overwrite publication: {RUNS.relative_to(ROOT)}")
    plan = preflight(
        ROOT,
        CONFIG,
        require_authorized=True,
        git_probe=lambda *_: EXPECTED_SOURCE_COMMIT,
    )
    config = load_config(CONFIG)
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if (
        plan.sourceCommit != EXPECTED_SOURCE_COMMIT
        or authorization.get("status") != "training-authorized"
        or authorization.get("authorizedPlanCommit") != "c75e9f00700d94e54ab91dc62089b85686832f45"
    ):
        raise PreflightError("current QLoRA execution authorization is not active and exact")
    failure = validate_failure_archive(archive_path)
    provider = validate_provider_evidence(json.loads(provider_path.read_text(encoding="utf-8")))
    publication_commit = _git_probe(ROOT, [Path(__file__), MODULE])
    budget_before = json.loads(BUDGET.read_text(encoding="utf-8"))
    cost = Decimal(provider["costUsd"]["total"])
    budget_after = settle_budget(budget_before, cost, plan.committedSpendUsd)

    RUNS.mkdir(parents=True)
    source_experiment = RUNS / "source-experiment.json"
    source_experiment.write_bytes(CONFIG.read_bytes())
    copied_archive = RUNS / "failure-evidence.tgz"
    shutil.copy2(archive_path, copied_archive)
    copied_provider = RUNS / "provider-settlement.json"
    shutil.copy2(provider_path, copied_provider)
    publication = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "failed-settled",
        "failureClass": failure["failureClass"],
        "completedAt": provider["capturedAt"],
        "sourceCommit": EXPECTED_SOURCE_COMMIT,
        "publicationCommit": publication_commit,
        "sourceExperiment": {
            "path": str(source_experiment.relative_to(ROOT)),
            "sha256": sha256_file(source_experiment),
        },
        "failureEvidence": {
            "path": str(copied_archive.relative_to(ROOT)),
            "sha256": sha256_file(copied_archive),
            "exitCode": failure["exitCode"],
            "optimizerSteps": failure["optimizerSteps"],
            "adapterProduced": failure["adapterProduced"],
        },
        "providerEvidence": {
            "path": str(copied_provider.relative_to(ROOT)),
            "sha256": sha256_file(copied_provider),
        },
        "providerCostUsd": str(cost),
        "evaluationDisposition": "not-run-no-adapter",
        "authority": {
            "modelDownloadAuthorized": False,
            "gpuAuthorized": False,
            "trainingAuthorized": False,
            "paidEvaluationAuthorized": False,
            "certificationAuthority": False,
            "deploymentAuthority": False,
            "releaseAuthority": False,
        },
        "budgetBeforeSettlement": {
            key: budget_before[key]
            for key in ("postedSpendUsd", "outstandingReservationsUsd", "committedSpendUsd", "authorizationUsd")
        },
        "budgetAfterSettlement": {
            key: budget_after[key]
            for key in ("postedSpendUsd", "outstandingReservationsUsd", "committedSpendUsd", "authorizationUsd")
        },
    }
    publication_path = RUNS / "publication.json"
    publication_path.write_text(
        json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    publication_sha = sha256_file(publication_path)

    budget_after["asOf"] = provider["capturedAt"][:10]
    BUDGET.write_text(json.dumps(budget_after, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    authorization.update(
        {
            "status": "complete-failed",
            "completedAt": provider["capturedAt"],
            "failureClass": failure["failureClass"],
            "actualTrainingCostUsd": str(cost),
            "evaluationDisposition": "not-run-no-adapter",
            "publicationPath": str(publication_path.relative_to(ROOT)),
            "publicationSha256": publication_sha,
        }
    )
    AUTHORIZATION.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    CONFIG.write_bytes(
        terminal_config(
            str(publication_path.relative_to(ROOT)),
            publication_sha,
            str(source_experiment.relative_to(ROOT)),
            sha256_file(source_experiment),
            budget_after,
        )
    )
    return publication


if __name__ == "__main__":
    main()
