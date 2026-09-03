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
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_behavior_corpus as corpus
import loomarr_models.behavior_model_review as review_preflight_contract
import loomarr_models.behavior_review as review_contract
import loomarr_models.targeted as targeted_contract
from loomarr_models.behavior_model_review import (
    CORRECTED_PACKET_VERSION,
    preflight,
    request_plan_bytes,
)
from loomarr_models.model_review import CRITERIA
from loomarr_models.targeted import validate_targeted_training
from loomarr_models.validator import load_contract, load_denylist, load_jsonl


REVIEW_ID = "planner-behavior-review-v3"
PAID_REVIEW_AUTHORIZED = False
REVIEW_PLAN_PATH = ROOT / f"experiments/{REVIEW_ID}.json"
REVIEW_ROOT = ROOT / "reviews/planner-behavior-v3"
ROUTE_SNAPSHOT_PATH = REVIEW_ROOT / "route-snapshot.json"
REQUEST_PLAN_PATH = REVIEW_ROOT / "request-plan.jsonl"
PREFLIGHT_REPORT_PATH = REVIEW_ROOT / "preflight-report.json"
INDEX_PATH = ROOT / "runs/planner-behavior-review-v3/index.json"
PRIOR_PUBLICATION_PATH = (
    ROOT / "reviews/planner-behavior-v2/publications/planner-behavior-review-v2/publication.json"
)
PUBLICATION_PATH = ROOT / f"reviews/planner-behavior-v2/publications/{REVIEW_ID}/publication.json"
REVIEW_RUNNER_PATH = ROOT / "scripts/run_planner_behavior_review.py"
REVIEW_PUBLISHER_PATH = ROOT / "scripts/publish_planner_behavior_review.py"
CORPUS_FINALIZER_PATH = ROOT / "scripts/finalize_planner_behavior_corpus.py"


def pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def binding(path: Path, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    if count is not None:
        value["count"] = count
    return value


def _publication(path: Path, *, review_id: str, corpus_sha256: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("reviewId") != review_id
        or value.get("corpusSha256") != corpus_sha256
        or value.get("status") not in {"complete-approved", "complete-with-escalations"}
        or value.get("approved", 0) + value.get("escalations", 0) != 120
    ):
        raise ValueError(f"{review_id}: publication is not an exact terminal result")
    return value


def build_outputs() -> dict[Path, bytes]:
    contract = load_contract(corpus.CONTRACT_PATH)
    denylisted_ids, denylisted_hashes = load_denylist(corpus.DENYLIST_PATH)
    traces = load_jsonl(corpus.TRAINING_PATH)
    training_report = validate_targeted_training(
        traces,
        contract=contract,
        denylisted_identities=denylisted_ids,
        denylisted_sha256=denylisted_hashes,
    )
    prior = _publication(
        PRIOR_PUBLICATION_PATH,
        review_id="planner-behavior-review-v2",
        corpus_sha256=training_report.sha256,
    )
    if prior.get("status") != "complete-with-escalations" or (
        prior.get("approved"), prior.get("escalations")
    ) != (118, 2):
        raise ValueError("corrected review requires the exact 118/2 prior result")

    publication = None
    if PUBLICATION_PATH.exists():
        publication = _publication(
            PUBLICATION_PATH,
            review_id=REVIEW_ID,
            corpus_sha256=training_report.sha256,
        )
    paid_authorized = PAID_REVIEW_AUTHORIZED and publication is None
    status = (
        publication["status"]
        if publication is not None
        else "ready-for-review"
        if paid_authorized
        else "planned-no-paid-calls-authorized"
    )

    route_snapshot = json.loads(ROUTE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    budget = json.loads(corpus.BUDGET_PATH.read_text(encoding="utf-8"))
    checked = preflight(
        traces,
        route_snapshot=route_snapshot,
        budget=budget,
        reservation_usd="16.50",
        packet_version=CORRECTED_PACKET_VERSION,
        contract_bundle=contract,
    )
    request_plan = request_plan_bytes(checked)
    if hashlib.sha256(request_plan).hexdigest() != checked.requestPlanSha256:
        raise AssertionError("corrected request-plan digest calculation diverged")

    bindings = {
        "contract": binding(corpus.CONTRACT_PATH),
        "holdoutDenylist": binding(corpus.DENYLIST_PATH),
        "priorTraining": binding(corpus.PRIOR_TRAINING_PATH),
        "priorDevelopment": binding(corpus.PRIOR_DEVELOPMENT_PATH),
        "reviewDecisions": binding(corpus.REVIEW_DECISIONS_PATH),
        "reviewPolicy": binding(corpus.REVIEW_POLICY_PATH),
        "reviewValidator": binding(Path(review_contract.__file__)),
        "targetedValidator": binding(Path(targeted_contract.__file__)),
        "budget": binding(corpus.BUDGET_PATH),
        "routeSnapshot": binding(ROUTE_SNAPSHOT_PATH),
        "reviewPreflightValidator": binding(Path(review_preflight_contract.__file__)),
        "reviewRunner": binding(REVIEW_RUNNER_PATH),
        "reviewPublisher": binding(REVIEW_PUBLISHER_PATH),
        "corpusFinalizer": binding(CORPUS_FINALIZER_PATH),
        "trainingDrafts": binding(corpus.TRAINING_PATH, count=training_report.records),
        "trainingManifest": binding(corpus.TRAINING_MANIFEST_PATH),
        "developmentCases": binding(corpus.DEVELOPMENT_PATH, count=60),
        "developmentManifest": binding(corpus.DEVELOPMENT_MANIFEST_PATH),
        "disjointnessReport": binding(corpus.DISJOINTNESS_PATH),
        "requestPlan": {
            "path": str(REQUEST_PLAN_PATH.relative_to(ROOT)),
            "sha256": checked.requestPlanSha256,
            "count": checked.requestCount,
        },
        "priorPublication": binding(PRIOR_PUBLICATION_PATH),
    }
    if publication is not None:
        bindings["publication"] = binding(PUBLICATION_PATH)

    plan = {
        "schemaVersion": 1,
        "reviewId": REVIEW_ID,
        "issue": "https://github.com/loomarr/loomarr-models/issues/9",
        "status": status,
        "candidateFamily": "qwen",
        "criteria": list(CRITERIA),
        "reviewers": list(review_preflight_contract.REVIEWERS),
        "execution": {
            "apiBaseUrl": "https://openrouter.ai/api/v1",
            "batchSize": checked.batchSize,
            "maxCalls": checked.requestCount,
            "maxOutputTokensPerCall": 3000,
            "reasoningEffort": "medium",
            "compactTracePacket": False,
            "multiTraceBatchAuthorized": False,
            "outputDir": f".artifacts/{REVIEW_ID}",
            "requestTimeoutSeconds": 180,
            "settlementAttempts": 60,
            "settlementDelaySeconds": 1,
            "requireCleanGit": True,
            "strictStructuredOutput": True,
            "providerFallback": False,
            "providerDataCollection": "deny",
            "automaticInferenceRetry": False,
            "paidReviewAuthorized": paid_authorized,
        },
        "budget": {
            "aggregateAuthorizationUsd": checked.authorizationUsd,
            "currentCommittedUsd": checked.committedSpendUsd,
            "reviewReservationUsd": checked.reservationUsd,
            "projectedMaximumUsd": checked.projectedSpendUsd,
            "remainingAfterMaximumUsd": str(
                Decimal(checked.authorizationUsd) - Decimal(checked.projectedSpendUsd)
            ),
            "worstCaseReviewUsd": checked.worstCaseCostUsd,
        },
        "preflight": checked.summary(),
        "bindings": bindings,
    }
    plan_bytes = pretty(plan)
    preflight_report = {
        "schemaVersion": 1,
        "reportId": f"{REVIEW_ID}-preflight",
        "status": "passed-no-inference",
        "paidReviewAuthorized": False,
        "inferenceCalls": 0,
        "externalCostUsd": "0",
        "routeMetadataCapturedAt": route_snapshot["capturedAt"],
        "schemaCompilationProof": route_snapshot["schemaCompilationProof"],
        "decision": "contract-complete-full-review-fits-remaining-authorization",
        "preflight": checked.summary(),
        "bindings": {
            "reviewPlan": {
                "path": str(REVIEW_PLAN_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(plan_bytes).hexdigest(),
            },
            "requestPlan": binding_bytes(REQUEST_PLAN_PATH, request_plan),
            "routeSnapshot": binding(ROUTE_SNAPSHOT_PATH),
            "budget": binding(corpus.BUDGET_PATH),
            "trainingDrafts": binding(corpus.TRAINING_PATH),
            "priorPublication": binding(PRIOR_PUBLICATION_PATH),
        },
    }
    preflight_bytes = pretty(preflight_report)
    outputs = {
        REVIEW_PLAN_PATH: plan_bytes,
        REQUEST_PLAN_PATH: request_plan,
        PREFLIGHT_REPORT_PATH: preflight_bytes,
    }
    index_inputs = {
        **outputs,
        ROUTE_SNAPSHOT_PATH: ROUTE_SNAPSHOT_PATH.read_bytes(),
        PRIOR_PUBLICATION_PATH: PRIOR_PUBLICATION_PATH.read_bytes(),
    }
    if publication is not None:
        index_inputs[PUBLICATION_PATH] = PUBLICATION_PATH.read_bytes()
    index = {
        "schemaVersion": 1,
        "publicationId": REVIEW_ID,
        "status": status,
        "artifacts": [
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for path, data in sorted(index_inputs.items(), key=lambda item: str(item[0]))
        ],
        "generator": binding(Path(__file__)),
        "nextGate": (
            "promote unanimous review decisions and freeze the training corpus"
            if publication is not None and publication["escalations"] == 0
            else "resolve independent-review escalations"
            if publication is not None
            else "refresh exact routes and pricing, then authorize the paid full review separately"
        ),
        "trainingAuthorized": False,
    }
    outputs[INDEX_PATH] = pretty(index)
    return outputs


def binding_bytes(path: Path, data: bytes) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the corrected targeted behavior review")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, data in outputs.items()
            if not path.exists() or path.read_bytes() != data
        ]
        if stale:
            raise SystemExit("stale corrected review artifacts: " + ", ".join(stale))
        return
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


if __name__ == "__main__":
    main()
