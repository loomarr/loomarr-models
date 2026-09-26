#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_v4_delta as corpus_generator
import loomarr_models.planner_v4 as v4_validator
import loomarr_models.v4_model_review as review_preflight
import loomarr_models.v4_review as review_validator
import loomarr_models.validator as corpus_validator
import publish_planner_v4_review as review_publisher
import run_planner_v4_review as review_runner
from loomarr_models.model_review import CRITERIA
from loomarr_models.v4_model_review import REVIEWERS, preflight, request_plan_bytes
from loomarr_models.validator import load_contract, load_jsonl


CONFIG_PATH = ROOT / "experiments/planner-v4-delta-review-v1.json"
REQUEST_PLAN_PATH = ROOT / "reviews/planner-v4-delta/request-plan.jsonl"
CONTRACT_PATH = ROOT / "contracts/planner-contract-v4.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
BUDGET_PATH = ROOT / "budgets/external-spend-v1.json"
ROUTE_SNAPSHOT_PATH = ROOT / "reviews/planner-behavior-v3/route-snapshot.json"
TRAINING_PATH = ROOT / "corpus/planner-v4-delta/drafts.jsonl"
TRAINING_MANIFEST_PATH = ROOT / "corpus/planner-v4-delta/draft-manifest.json"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-development-v4/cases.jsonl"
DEVELOPMENT_MANIFEST_PATH = ROOT / "evaluation/planner-development-v4/manifest.json"
DISJOINTNESS_PATH = ROOT / "reports/planner-v4-disjointness.json"
REVIEW_DECISIONS_PATH = ROOT / "reviews/planner-v4-delta.jsonl"
RESERVATION_USD = "8.00"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path: Path, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
    if count is not None:
        value["count"] = count
    return value


def generated_binding(path: Path, content: bytes, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    if count is not None:
        value["count"] = count
    return value


def pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def build_outputs() -> dict[Path, bytes]:
    contract = load_contract(CONTRACT_PATH)
    traces = load_jsonl(TRAINING_PATH)
    route_snapshot = json.loads(ROUTE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    budget = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    checked = preflight(
        traces,
        contract=contract,
        route_snapshot=route_snapshot,
        budget=budget,
        reservation_usd=RESERVATION_USD,
        max_output_tokens=review_runner.EXECUTION["maxOutputTokensPerCall"],
    )
    request_bytes = request_plan_bytes(checked.requests)
    config = {
        "schemaVersion": 1,
        "reviewId": "planner-v4-delta-review-v1",
        "issue": "https://github.com/loomarr/loomarr-models/issues/22",
        "status": "planned-no-paid-calls-authorized",
        "candidateFamily": "qwen",
        "criteria": list(CRITERIA),
        "reviewers": list(REVIEWERS),
        "execution": {**review_runner.EXECUTION, "paidReviewAuthorized": False},
        "budget": {
            "aggregateAuthorizationUsd": checked.authorization_usd,
            "currentCommittedUsd": checked.committed_spend_usd,
            "reviewReservationUsd": checked.reservation_usd,
            "projectedMaximumUsd": checked.projected_spend_usd,
            "remainingAfterMaximumUsd": str(
                Decimal(checked.authorization_usd) - Decimal(checked.projected_spend_usd)
            ),
            "worstCaseReviewUsd": checked.worst_case_cost_usd,
        },
        "preflight": checked.summary(),
        "bindings": {
            "contract": binding(CONTRACT_PATH),
            "holdoutDenylist": binding(DENYLIST_PATH),
            "budget": binding(BUDGET_PATH),
            "routeSnapshot": binding(ROUTE_SNAPSHOT_PATH),
            "trainingDrafts": binding(TRAINING_PATH, count=60),
            "trainingManifest": binding(TRAINING_MANIFEST_PATH),
            "developmentCases": binding(DEVELOPMENT_PATH, count=120),
            "developmentManifest": binding(DEVELOPMENT_MANIFEST_PATH),
            "disjointnessReport": binding(DISJOINTNESS_PATH),
            "reviewDecisions": binding(REVIEW_DECISIONS_PATH, count=60),
            "corpusValidator": binding(Path(corpus_validator.__file__)),
            "v4Validator": binding(Path(v4_validator.__file__)),
            "reviewValidator": binding(Path(review_validator.__file__)),
            "reviewPreflightValidator": binding(Path(review_preflight.__file__)),
            "reviewRunner": binding(Path(review_runner.__file__)),
            "reviewPublisher": binding(Path(review_publisher.__file__)),
            "corpusGenerator": binding(Path(corpus_generator.__file__)),
            "requestPlan": generated_binding(REQUEST_PLAN_PATH, request_bytes, count=120),
        },
    }
    return {REQUEST_PLAN_PATH: request_bytes, CONFIG_PATH: pretty(config)}


def main() -> None:
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("usage: build_planner_v4_review.py [--check]")
    check = sys.argv[1:] == ["--check"]
    outputs = build_outputs()
    if check:
        stale = [
            str(path.relative_to(ROOT))
            for path, content in outputs.items()
            if not path.exists() or path.read_bytes() != content
        ]
        if stale:
            raise SystemExit("stale planner v4 review artifacts: " + ", ".join(stale))
        return
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


if __name__ == "__main__":
    main()
