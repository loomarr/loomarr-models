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

from loomarr_models.current_baseline import MODEL, SCORING
from loomarr_models.current_baseline_v3 import (
    AUTHORITY,
    COMPARISON,
    EXECUTION,
    EXPERIMENT_ID,
    HOSTED_COMPARISON,
    ISSUE,
    PROMPT_CAPACITY_CONFIG_SHA256,
)


OUTPUT = Path("experiments/planner-current-qwen-stock-baseline-v3.json")


def _sha(path: Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _binding(path: str, **extra: Any) -> dict[str, Any]:
    value = {"path": path, "sha256": _sha(Path(path))}
    value.update(extra)
    return value


def content() -> bytes:
    budget = json.loads((ROOT / "budgets/external-spend-v1.json").read_text(encoding="utf-8"))
    committed = Decimal(budget["committedSpendUsd"])
    aggregate = Decimal(budget["authorizationUsd"])
    reservation = Decimal("1.50")
    value = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "issue": ISSUE,
        "status": "planned-billing-settlement-required",
        "bindings": {
            "authorization": _binding("reviews/planner-current-qwen-stock-baseline-v3/authorization.json"),
            "budgetLedger": _binding("budgets/external-spend-v1.json"),
            "cases": _binding("evaluation/planner-current-v1/cases.jsonl", records=24),
            "casesManifest": _binding("evaluation/planner-current-v1/manifest.json"),
            "contract": _binding("contracts/planner-contract-v5.json"),
            "environment": _binding("environments/qwen38-a40-v1.json"),
            "generator": _binding("scripts/build_planner_current_stock_baseline_v3.py"),
            "holdoutDenylist": _binding("contracts/planner-holdout-denylist-v2.json"),
            "preflight": _binding("src/loomarr_models/current_baseline_v3.py"),
            "promptCapacityChecker": _binding("scripts/check_planner_current_prompt_capacity.py"),
            "promptCapacityModule": _binding("src/loomarr_models/prompt_capacity.py"),
            "promptCapacityReport": _binding("reviews/planner-current-qwen-stock-baseline-v3/prompt-capacity-report.json"),
        },
        "model": MODEL,
        "execution": EXECUTION,
        "comparison": COMPARISON,
        "scoring": SCORING,
        "decision": {
            "passingStockStopsTraining": True,
            "runtimeOrInfrastructureFailureJustifiesTraining": False,
            "requiresObservedRecoveryFault": True,
            "applicationRecoveryBlocker": "https://github.com/loomarr/loomarr/issues/1195",
        },
        "hostedProductionComparison": HOSTED_COMPARISON,
        "promptCapacity": {
            "status": "passed",
            "exactPinnedProcessorRequired": True,
            "fullGenerationBudgetRequiredAtEveryStage": True,
            "preflightConfigSha256": PROMPT_CAPACITY_CONFIG_SHA256,
            "report": _binding("reviews/planner-current-qwen-stock-baseline-v3/prompt-capacity-report.json"),
        },
        "budget": {
            "aggregateAuthorizationUsd": str(aggregate),
            "currentCommittedUsd": str(committed),
            "outstandingReservationsUsd": budget["outstandingReservationsUsd"],
            "proposedReservationUsd": str(reservation),
            "projectedCommitmentUsd": str(committed + reservation),
            "remainingAuthorizationUsd": str(aggregate - committed - reservation),
        },
        "authority": AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the unauthorized current stock v3 plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = content()
    target = ROOT / OUTPUT
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            raise SystemExit(f"generated artifact drift: {OUTPUT}")
        return
    target.write_bytes(expected)


if __name__ == "__main__":
    main()
