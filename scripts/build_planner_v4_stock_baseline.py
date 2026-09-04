#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.stock_baseline import AUTHORITY, COMPARISON, EXECUTION, EXPERIMENT_ID, ISSUE
from loomarr_models.local_screen import SCORING


OUTPUT = ROOT / "experiments/planner-v4-qwen-stock-baseline-v1.json"
PATHS = {
    "cases": ROOT / "evaluation/planner-development-v4/cases.jsonl",
    "casesManifest": ROOT / "evaluation/planner-development-v4/manifest.json",
    "contract": ROOT / "contracts/planner-contract-v4.json",
    "holdoutDenylist": ROOT / "contracts/holdout-denylist-v1.json",
    "environment": ROOT / "environments/qwen38-a40-v1.json",
    "localScreenPublication": ROOT / "runs/planner-v4-local-screen-v1/publication.json",
    "runpodCatalogSnapshot": ROOT
    / "reviews/planner-v4-qwen-stock-baseline/runpod-catalog-snapshot.json",
    "generator": Path(__file__).resolve(),
    "preflight": ROOT / "src/loomarr_models/stock_baseline.py",
    "runtime": ROOT / "src/loomarr_models/stock_runtime.py",
    "runner": ROOT / "scripts/run_planner_v4_stock_baseline.py",
}
BUDGET = ROOT / "budgets/external-spend-v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path: Path, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
    if count is not None:
        value["count"] = count
    return value


def content() -> bytes:
    ledger = json.loads(BUDGET.read_text(encoding="utf-8"))
    environment = json.loads(PATHS["environment"].read_text(encoding="utf-8"))
    committed = Decimal(ledger["committedSpendUsd"])
    authorization = Decimal(ledger["authorizationUsd"])
    reservation = Decimal(EXECUTION["maxReservationUsd"])
    projected = committed + reservation
    artifact = environment["trainingArtifact"]
    config = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "issue": ISSUE,
        "status": "planned-no-paid-baseline-authorized",
        "paidBaselineAuthorized": False,
        "bindings": {
            "cases": binding(PATHS["cases"], count=120),
            "casesManifest": binding(PATHS["casesManifest"]),
            "contract": binding(PATHS["contract"]),
            "holdoutDenylist": binding(PATHS["holdoutDenylist"]),
            "environment": binding(PATHS["environment"]),
            "localScreenPublication": binding(PATHS["localScreenPublication"]),
            "runpodCatalogSnapshot": binding(PATHS["runpodCatalogSnapshot"]),
            "budgetLedger": {"path": str(BUDGET.relative_to(ROOT))},
            "generator": binding(PATHS["generator"]),
            "preflight": binding(PATHS["preflight"]),
            "runtime": binding(PATHS["runtime"]),
            "runner": binding(PATHS["runner"]),
        },
        "model": {
            "candidateId": "qwen38-27b-unsloth-bnb-4bit",
            "repository": artifact["repository"],
            "revision": artifact["revision"],
            "quantization": artifact["quantization"],
        },
        "execution": EXECUTION,
        "comparison": COMPARISON,
        "scoring": SCORING,
        "budget": {
            "aggregateAuthorizationUsd": str(authorization),
            "currentCommittedUsd": str(committed),
            "proposedReservationUsd": str(reservation),
            "projectedCommitmentUsd": str(projected),
            "remainingAfterMaximumUsd": str(authorization - projected),
        },
        "authority": AUTHORITY,
    }
    return json.dumps(config, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Qwen v4 stock baseline plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = content()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != expected:
            raise SystemExit(f"generated artifact drift: {OUTPUT.relative_to(ROOT)}")
        return
    OUTPUT.write_bytes(expected)


if __name__ == "__main__":
    main()
