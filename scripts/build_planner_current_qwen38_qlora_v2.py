#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_baseline import MODEL
from loomarr_models.current_training import EVALUATION, NO_AUTHORITY, TRAINING_AUTHORITY
from loomarr_models.current_training_v2 import EXECUTION, EXPERIMENT_ID, ISSUE, RUN
from loomarr_models.current_training_failure_v2 import (
    EXPECTED_PLAN_COMMIT,
    terminal_config,
)


OUTPUT = Path("experiments/planner-current-qwen38-qlora-v2.json")
AUTHORIZATION = Path("reviews/planner-current-qwen38-qlora-v2/authorization.json")
BUDGET = Path("budgets/external-spend-v1.json")


def _sha(path: Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _binding(path: str, **extra: Any) -> dict[str, Any]:
    return {"path": path, "sha256": _sha(Path(path)), **extra}


def _authorization_state() -> tuple[str, dict[str, Any]]:
    value = json.loads((ROOT / AUTHORIZATION).read_text(encoding="utf-8"))
    base = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "trainingReservationUsd": "1.50",
        "evaluationReservationUsd": "1.50",
        "maxCombinedReservationUsd": "3.00",
    }
    if value == {
        **base,
        "status": "not-authorized",
        "authorizedBy": None,
        "authorizedAt": None,
        "authorizedPlanCommit": None,
        "authorizationReference": None,
    }:
        return "planned", value
    if (
        set(value) == set(base) | {
            "status", "authorizedBy", "authorizedAt", "authorizedPlanCommit", "authorizationReference"
        }
        and all(value.get(key) == expected for key, expected in base.items())
        and value.get("status") == "training-authorized"
        and value.get("authorizedBy") == "loomarr-maintainer"
        and re.fullmatch(r"[0-9a-f]{40}", value.get("authorizedPlanCommit", ""))
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value.get("authorizedAt", ""))
        and re.fullmatch(
            r"https://github\.com/loomarr/loomarr-models/issues/20#issuecomment-\d+",
            value.get("authorizationReference", ""),
        )
    ):
        return "authorized", value
    terminal_fields = set(base) | {
        "status", "authorizedBy", "authorizedAt", "authorizedPlanCommit",
        "authorizationReference", "completedAt", "failureClass",
        "actualTrainingCostUsd", "evaluationDisposition", "publicationPath",
        "publicationSha256",
    }
    if (
        set(value) == terminal_fields
        and all(value.get(key) == expected for key, expected in base.items())
        and value.get("status") == "complete-failed"
        and value.get("authorizedBy") == "loomarr-maintainer"
        and value.get("authorizedPlanCommit") == EXPECTED_PLAN_COMMIT
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value.get("authorizedAt", ""))
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value.get("completedAt", ""))
        and value.get("failureClass") == "live-rendered-capacity-mismatch"
        and Decimal(value.get("actualTrainingCostUsd", "NaN")) <= Decimal("1.50")
        and value.get("evaluationDisposition") == "not-run-no-adapter"
        and value.get("publicationPath") == "runs/planner-current-qwen38-qlora-v2/publication.json"
        and re.fullmatch(r"[0-9a-f]{64}", value.get("publicationSha256", ""))
    ):
        return "terminal", value
    raise ValueError("corrected current QLoRA authorization lifecycle is invalid")


def content() -> bytes:
    budget = json.loads((ROOT / BUDGET).read_text(encoding="utf-8"))
    posted = Decimal(budget["postedSpendUsd"])
    outstanding = Decimal(budget["outstandingReservationsUsd"])
    committed = Decimal(budget["committedSpendUsd"])
    aggregate = Decimal(budget["authorizationUsd"])
    combined = Decimal("3.00")
    if posted + outstanding != committed or committed + combined > aggregate:
        raise ValueError("corrected current QLoRA aggregate budget is invalid")
    state, authorization = _authorization_state()
    if state == "terminal":
        publication_path = Path(authorization["publicationPath"])
        if _sha(publication_path) != authorization["publicationSha256"]:
            raise ValueError("corrected current QLoRA terminal publication drifted")
        publication = json.loads((ROOT / publication_path).read_text(encoding="utf-8"))
        source = publication.get("sourceExperiment", {})
        terminal_budget = publication.get("budgetAfterSettlement", {})
        if (
            publication.get("status") != "failed-settled"
            or publication.get("providerCostUsd") != authorization["actualTrainingCostUsd"]
            or set(terminal_budget) != {
                "postedSpendUsd", "outstandingReservationsUsd", "committedSpendUsd", "authorizationUsd"
            }
            or Decimal(terminal_budget["postedSpendUsd"])
            + Decimal(terminal_budget["outstandingReservationsUsd"])
            != Decimal(terminal_budget["committedSpendUsd"])
            or terminal_budget["authorizationUsd"] != "40.00"
            or source.get("path") != "runs/planner-current-qwen38-qlora-v2/source-experiment.json"
            or source.get("sha256") != _sha(Path(source.get("path", "missing")))
        ):
            raise ValueError("corrected current QLoRA terminal evidence drifted")
        return terminal_config(
            str(publication_path),
            authorization["publicationSha256"],
            source["path"],
            source["sha256"],
            terminal_budget,
        )
    authorized = state == "authorized"
    value = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "issue": ISSUE,
        "status": "ready-for-training" if authorized else "planned-no-paid-run-authorized",
        "bindings": {
            "authorization": _binding(str(AUTHORIZATION)),
            "authorizationTool": _binding("scripts/authorize_planner_current_qwen38_qlora_v2.py"),
            "budgetLedger": _binding(str(BUDGET)),
            "budgetReconciliation": _binding("budgets/runpod-pod-billing-current-qwen38-qlora-v1-failure-v1.json"),
            "capacityReport": _binding("reviews/planner-current-qwen38-qlora-v1/training-capacity-report.json"),
            "contract": _binding("contracts/planner-contract-v5.json"),
            "corpus": _binding("corpus/planner-current-v1/traces.jsonl", records=24),
            "corpusManifest": _binding("corpus/planner-current-v1/manifest.json"),
            "development": _binding("evaluation/planner-current-v1/cases.jsonl", records=24),
            "developmentManifest": _binding("evaluation/planner-current-v1/manifest.json"),
            "documentation": _binding("docs/planner-current-qwen38-qlora-v2.md"),
            "environment": _binding("environments/qwen38-a40-v1.json"),
            "failurePublication": _binding("runs/planner-current-qwen38-qlora-v1/publication.json"),
            "generator": _binding("scripts/build_planner_current_qwen38_qlora_v2.py"),
            "holdoutDenylist": _binding("contracts/planner-holdout-denylist-v2.json"),
            "preflight": _binding("src/loomarr_models/current_training_v2.py"),
            "reviewPublication": _binding("reviews/planner-current-v1/publication.json"),
            "runbook": _binding("docs/planner-current-qwen38-qlora-v2-runbook.md"),
            "runner": _binding("scripts/run_planner_current_qwen38_qlora_v2.py"),
            "runtime": _binding("src/loomarr_models/current_training_runtime.py"),
            "stockPublication": _binding("runs/planner-current-qwen-stock-baseline-v3/publication.json"),
            "trainingData": _binding("src/loomarr_models/training_data.py"),
            "verifier": _binding("scripts/verify_planner_current_qwen38_qlora_v2_artifact.py"),
        },
        "model": MODEL,
        "execution": EXECUTION,
        "runs": [RUN],
        "evaluation": EVALUATION,
        "budget": {
            "aggregateAuthorizationUsd": str(aggregate),
            "currentCommittedUsd": str(committed),
            "outstandingReservationsUsd": str(outstanding),
            "trainingReservationUsd": "1.50",
            "evaluationReservationUsd": "1.50",
            "maxCombinedReservationUsd": "3.00",
            "projectedCombinedSpendUsd": str(committed + combined),
            "remainingAfterCombinedUsd": str(aggregate - committed - combined),
        },
        "authority": TRAINING_AUTHORITY if authorized else NO_AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the corrected current-contract QLoRA v2 plan")
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
