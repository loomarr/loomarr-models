#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_qwen38_qlora_v2 as builder
from loomarr_models.current_training_v2 import EXPERIMENT_ID, preflight
from loomarr_models.experiment import PreflightError


AUTHORIZATION = ROOT / "reviews/planner-current-qwen38-qlora-v2/authorization.json"
CONFIG = ROOT / "experiments/planner-current-qwen38-qlora-v2.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize the exact corrected current QLoRA plan")
    parser.add_argument("--authorized-plan-commit", required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--authorized-at", required=True)
    args = parser.parse_args()
    try:
        authorize(args.authorized_plan_commit, args.authorization_reference, args.authorized_at)
    except (PreflightError, ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))


def authorize(plan_commit: str, reference: str, authorized_at: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", plan_commit) is None:
        raise ValueError("authorized plan commit must be lowercase 40-hex")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    if head != plan_commit:
        raise ValueError("authorized plan commit differs from HEAD")
    if re.fullmatch(
        r"https://github\.com/loomarr/loomarr-models/issues/20#issuecomment-\d+", reference
    ) is None:
        raise ValueError("authorization reference must be an issue #20 comment")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", authorized_at) is None:
        raise ValueError("authorized timestamp must be RFC3339 UTC seconds")
    dt.datetime.fromisoformat(authorized_at.replace("Z", "+00:00"))
    plan = preflight(ROOT, CONFIG, require_authorized=False)
    if plan.sourceCommit != plan_commit or plan.trainingAuthorized:
        raise ValueError("corrected current QLoRA plan is not the exact clean unauthorized commit")
    AUTHORIZATION.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "experimentId": EXPERIMENT_ID,
                "status": "training-authorized",
                "trainingReservationUsd": "1.50",
                "evaluationReservationUsd": "1.50",
                "maxCombinedReservationUsd": "3.00",
                "authorizedBy": "loomarr-maintainer",
                "authorizedAt": authorized_at,
                "authorizedPlanCommit": plan_commit,
                "authorizationReference": reference,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    CONFIG.write_bytes(builder.content())


if __name__ == "__main__":
    main()
