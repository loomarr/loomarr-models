#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_stock_baseline_v3 as builder
from loomarr_models.current_baseline_v3 import EXPERIMENT_ID, preflight
from loomarr_models.experiment import PreflightError, sha256_file


CONFIG = ROOT / builder.OUTPUT
AUTHORIZATION = ROOT / "reviews/planner-current-qwen-stock-baseline-v3/authorization.json"
PRIOR_PUBLICATION = ROOT / "runs/planner-current-qwen-stock-baseline-v2/publication.json"
BUDGET = ROOT / "budgets/external-spend-v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Record explicit authorization for the v3 stock baseline")
    parser.add_argument("--authorized-at", required=True)
    parser.add_argument("--authorization-reference", required=True)
    args = parser.parse_args()
    try:
        authorize(args.authorized_at, args.authorization_reference)
    except (PreflightError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


def authorize(authorized_at: str, authorization_reference: str) -> None:
    if not _timestamp(authorized_at):
        raise PreflightError("v3 authorization timestamp must be RFC 3339 UTC")
    if re.fullmatch(
        r"https://github\.com/loomarr/loomarr-models/issues/29#issuecomment-\d+",
        authorization_reference,
    ) is None:
        raise PreflightError("v3 authorization must reference an explicit issue #29 comment")
    plan = preflight(ROOT, CONFIG, require_authorized=False)
    current = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    if current.get("status") != "not-authorized":
        raise PreflightError("v3 authorization is not in the initial state")
    publication = json.loads(PRIOR_PUBLICATION.read_text(encoding="utf-8"))
    ledger = json.loads(BUDGET.read_text(encoding="utf-8"))
    validate_prior_settlement(publication, ledger)
    authorization = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "authorized",
        "maxReservationUsd": "1.50",
        "authorizedBy": "loomarr-maintainer",
        "authorizedAt": authorized_at,
        "authorizedPlanCommit": plan.sourceCommit,
        "authorizationReference": authorization_reference,
        "priorBaselinePublication": {
            "path": str(PRIOR_PUBLICATION.relative_to(ROOT)),
            "sha256": sha256_file(PRIOR_PUBLICATION),
        },
    }
    AUTHORIZATION.write_text(
        json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    CONFIG.write_bytes(builder.content())


def validate_prior_settlement(publication: dict, ledger: dict) -> None:
    budget_after = publication.get("budgetAfterSettlement", {})
    if (
        publication.get("experimentId") != "planner-current-qwen-stock-baseline-v2"
        or publication.get("status") != "baseline-invalid-settled"
        or publication.get("decision", {}).get("qloraJustified") is not False
        or publication.get("decision", {}).get("failureClass")
        != "runtime-configuration-failure"
        or budget_after.get("postedSpendUsd") != ledger.get("postedSpendUsd")
        or budget_after.get("committedSpendUsd") != ledger.get("committedSpendUsd")
        or budget_after.get("authorizationUsd") != ledger.get("authorizationUsd")
    ):
        raise PreflightError("v2 failure publication and current budget do not reconcile")


def _timestamp(value: str) -> bool:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is None:
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    main()
