#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_stock_baseline_v3 as builder
from loomarr_models.current_baseline_v3 import AUTHORITY, EXPERIMENT_ID, load_config, preflight
from loomarr_models.current_publication_v3 import (
    settle_budget,
    validate_provider_evidence,
    validate_run,
)
from loomarr_models.experiment import PreflightError, _git_probe, sha256_file


RUNS = ROOT / "runs/planner-current-qwen-stock-baseline-v3"
CONFIG = ROOT / builder.OUTPUT
AUTHORIZATION = ROOT / "reviews/planner-current-qwen-stock-baseline-v3/authorization.json"
BUDGET = ROOT / "budgets/external-spend-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish and settle the current stock baseline v3")
    parser.add_argument(
        "--provider-evidence",
        type=Path,
        default=Path(".artifacts/planner-current-qwen-stock-baseline-v3/provider-settlement.json"),
    )
    args = parser.parse_args()
    evidence = args.provider_evidence if args.provider_evidence.is_absolute() else ROOT / args.provider_evidence
    try:
        publication = publish(evidence)
    except (PreflightError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(publication, sort_keys=True))


def publish(evidence_path: Path) -> dict[str, Any]:
    if RUNS.exists():
        raise PreflightError(f"refusing to overwrite publication: {RUNS.relative_to(ROOT)}")
    plan = preflight(ROOT, CONFIG, require_authorized=True)
    config = load_config(CONFIG)
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if authorization.get("status") != "authorized":
        raise PreflightError("current stock v3 authorization is not active")
    publication_commit = _git_probe(ROOT, [Path(__file__), CONFIG, AUTHORIZATION, BUDGET])
    artifact_dir = ROOT / plan.outputDir
    manifest, summary, decision = validate_run(artifact_dir, config, plan)
    provider = validate_provider_evidence(
        json.loads(evidence_path.read_text(encoding="utf-8")), config["execution"], plan
    )
    cost = Decimal(provider["costUsd"]["total"])
    settled_budget = settle_budget(json.loads(BUDGET.read_text(encoding="utf-8")), cost, plan)

    completed_at = provider["capturedAt"]
    evidence_destination = RUNS / "evidence"
    evidence_destination.parent.mkdir(parents=True)
    shutil.copytree(artifact_dir, evidence_destination)
    source_experiment = RUNS / "source-experiment.json"
    source_experiment.write_bytes(CONFIG.read_bytes())
    copied_provider = RUNS / "provider-settlement.json"
    shutil.copy2(evidence_path, copied_provider)
    copied_manifest = evidence_destination / "run-manifest.json"
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
        "runAuthority": config["authority"],
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
    CONFIG.write_bytes(builder.content())
    return publication


if __name__ == "__main__":
    main()
