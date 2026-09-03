#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_behavior_corpus as corpus
from loomarr_models.behavior_review import derive_review, empty_decision, load_review_decisions
from loomarr_models.model_review import (
    ModelReviewContentError,
    ModelReviewError,
    canonical,
    validate_completion,
    validate_settlement,
)
from run_planner_behavior_review import CONFIG_PATH, build_plan


PUBLIC_ROOT = ROOT / "reviews/planner-behavior-v2/publications"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish targeted planner review evidence")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--promote-approved", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        if args.promote_approved:
            result = promote_approved(config_path)
        else:
            _config, plan, _snapshot = build_plan(config_path, require_authorized=True)
            result = publish(plan)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


def publish(plan: Any) -> dict[str, Any]:
    artifacts = ROOT / plan.outputDir
    public = PUBLIC_ROOT / plan.reviewId
    if public.exists():
        raise ModelReviewError("published behavior-review directory already exists")
    manifest_path = artifacts / "run-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected_manifest_fields = {
        "schemaVersion",
        "reviewId",
        "status",
        "startedAt",
        "completedAt",
        "sourceCommit",
        "configSha256",
        "corpusSha256",
        "requestCount",
        "attestationCount",
        "attestationsSha256",
        "invalidReviewCount",
        "invalidReviewsSha256",
        "actualCostUsd",
        "reservationUsd",
        "callArtifacts",
    }
    if set(manifest) != expected_manifest_fields or manifest.get("status") != "complete":
        raise ModelReviewError("run manifest is not an exact complete behavior-review manifest")
    expected_identity = {
        "reviewId": plan.reviewId,
        "sourceCommit": plan.sourceCommit,
        "configSha256": plan.configSha256,
        "corpusSha256": plan.corpusSha256,
        "requestCount": plan.requestCount,
        "reservationUsd": plan.reservationUsd,
    }
    if any(manifest.get(key) != value for key, value in expected_identity.items()):
        raise ModelReviewError("run manifest differs from the committed behavior-review plan")

    attestation_bytes = (artifacts / "attestations.jsonl").read_bytes()
    invalid_bytes = (artifacts / "invalid-reviews.jsonl").read_bytes()
    if hashlib.sha256(attestation_bytes).hexdigest() != manifest["attestationsSha256"]:
        raise ModelReviewError("behavior-review attestation digest mismatch")
    if hashlib.sha256(invalid_bytes).hexdigest() != manifest["invalidReviewsSha256"]:
        raise ModelReviewError("behavior-review invalid-observation digest mismatch")
    attestations = [json.loads(line) for line in attestation_bytes.splitlines() if line]
    invalid_reviews = [json.loads(line) for line in invalid_bytes.splitlines() if line]
    if (
        len(attestations) != manifest["attestationCount"]
        or len(invalid_reviews) != manifest["invalidReviewCount"]
        or len(attestations) + len(invalid_reviews) != 240
    ):
        raise ModelReviewError("published run must contain exactly 240 review observations")

    entries = manifest["callArtifacts"]
    if not isinstance(entries, list) or len(entries) != len(plan.requests):
        raise ModelReviewError("behavior-review call artifact manifest is incomplete")
    actual_cost = Decimal(0)
    ordered_attestations: list[dict[str, Any]] = []
    ordered_invalid: list[dict[str, Any]] = []
    for request, entry in zip(plan.requests, entries, strict=True):
        stem = f"{request.role}-{request.batchIndex:02d}"
        if not isinstance(entry, dict) or entry.get("stem") != stem:
            raise ModelReviewError("behavior-review call artifact order differs from the plan")
        summary_bytes = (artifacts / "calls" / f"{stem}.json").read_bytes()
        response_bytes = (artifacts / "calls" / f"{stem}.response.json").read_bytes()
        settlement_bytes = (artifacts / "calls" / f"{stem}.settlement.json").read_bytes()
        for label, content in (
            ("summary", summary_bytes),
            ("response", response_bytes),
            ("settlement", settlement_bytes),
        ):
            if hashlib.sha256(content).hexdigest() != entry.get(f"{label}Sha256"):
                raise ModelReviewError(f"{stem}: {label} artifact digest mismatch")
        summary = json.loads(summary_bytes)
        response = json.loads(response_bytes)
        settlement = json.loads(settlement_bytes)
        cost = validate_settlement(settlement, request, response)
        actual_cost += cost
        batch_attestations = _batch(attestations, request)
        batch_invalid = _batch(invalid_reviews, request)
        try:
            parsed = validate_completion(response, request, entry["responseSha256"])
        except ModelReviewContentError as exc:
            if batch_attestations or len(batch_invalid) != 1:
                raise ModelReviewError(f"{stem}: invalid observation coverage differs") from exc
            if summary.get("status") != "invalid" or summary.get("contentError") != str(exc):
                raise ModelReviewError(f"{stem}: invalid summary differs from raw response")
            _validate_invalid_observation(batch_invalid[0], request, entry, response, cost, exc)
            ordered_invalid.extend(batch_invalid)
        else:
            if batch_invalid or len(batch_attestations) != 1:
                raise ModelReviewError(f"{stem}: valid attestation coverage differs")
            if summary.get("status") != "valid" or "contentError" in summary:
                raise ModelReviewError(f"{stem}: valid summary differs from raw response")
            _validate_attestation(batch_attestations[0], parsed[0], entry, cost, stem)
            ordered_attestations.extend(batch_attestations)
        if (
            summary.get("requestSha256") != request.requestSha256
            or summary.get("settledCostUsd") != str(cost)
        ):
            raise ModelReviewError(f"{stem}: summary differs from request or settlement")
    if ordered_attestations != attestations or ordered_invalid != invalid_reviews:
        raise ModelReviewError("review observations differ from exact call order")
    if str(actual_cost) != manifest["actualCostUsd"] or actual_cost > Decimal(plan.reservationUsd):
        raise ModelReviewError("review cost differs from settlements or exceeds reservation")

    decisions, escalations = derive_decisions(attestations, invalid_reviews, plan)
    decision_bytes = b"".join(canonical(decision) + b"\n" for decision in decisions)
    current = load_review_decisions(corpus.REVIEW_DECISIONS_PATH, corpus.trace_ids())
    if list(current.values()) != [empty_decision(trace_id) for trace_id in corpus.trace_ids()]:
        raise ModelReviewError("canonical behavior decisions are not pristine")
    budget = _object(corpus.BUDGET_PATH)
    settled_budget = settle_budget(budget, actual_cost, plan)

    shutil.copytree(artifacts, public)
    (public / "decisions.jsonl").write_bytes(decision_bytes)
    escalation_bytes = _pretty(
        {
            "schemaVersion": 1,
            "reviewId": plan.reviewId,
            "count": len(escalations),
            "traces": escalations,
        }
    )
    (public / "escalations.json").write_bytes(escalation_bytes)
    result = {
        "schemaVersion": 1,
        "reviewId": plan.reviewId,
        "status": "complete-approved" if not escalations else "complete-with-escalations",
        "sourceCommit": plan.sourceCommit,
        "configSha256": plan.configSha256,
        "corpusSha256": plan.corpusSha256,
        "actualCostUsd": str(actual_cost),
        "approved": 120 - len(escalations),
        "escalations": len(escalations),
        "runManifestPath": str((public / "run-manifest.json").relative_to(ROOT)),
        "runManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "attestationsPath": str((public / "attestations.jsonl").relative_to(ROOT)),
        "attestationsSha256": manifest["attestationsSha256"],
        "invalidReviewsPath": str((public / "invalid-reviews.jsonl").relative_to(ROOT)),
        "invalidReviewsSha256": manifest["invalidReviewsSha256"],
        "decisionsPath": str((public / "decisions.jsonl").relative_to(ROOT)),
        "decisionsSha256": hashlib.sha256(decision_bytes).hexdigest(),
        "escalationsPath": str((public / "escalations.json").relative_to(ROOT)),
        "escalationsSha256": hashlib.sha256(escalation_bytes).hexdigest(),
    }
    (public / "publication.json").write_bytes(_pretty(result))
    corpus.BUDGET_PATH.write_bytes(_pretty(settled_budget))
    return result


def promote_approved(config_path: Path) -> dict[str, Any]:
    config = _object(config_path)
    review_id = config.get("reviewId")
    if review_id != "planner-behavior-review-v2":
        raise ModelReviewError("unexpected behavior-review publication identity")
    public = PUBLIC_ROOT / review_id
    publication = _object(public / "publication.json")
    if publication.get("approved") != 120 or publication.get("escalations") != 0:
        raise ModelReviewError("only a unanimous 120-trace publication may be promoted")
    decision_path = public / "decisions.jsonl"
    decision_bytes = decision_path.read_bytes()
    if hashlib.sha256(decision_bytes).hexdigest() != publication.get("decisionsSha256"):
        raise ModelReviewError("published behavior decisions digest mismatch")
    decisions = load_review_decisions(decision_path, corpus.trace_ids())
    if any(derive_review(decision, require_complete=True).status != "approved" for decision in decisions.values()):
        raise ModelReviewError("published behavior decisions are not unanimously approved")
    current = load_review_decisions(corpus.REVIEW_DECISIONS_PATH, corpus.trace_ids())
    if list(current.values()) != [empty_decision(trace_id) for trace_id in corpus.trace_ids()]:
        raise ModelReviewError("canonical behavior decisions are not pristine")
    corpus.REVIEW_DECISIONS_PATH.write_bytes(decision_bytes)
    subprocess.run([sys.executable, "scripts/build_planner_behavior_corpus.py"], cwd=ROOT, check=True)
    return {
        "reviewId": review_id,
        "status": "canonical-decisions-promoted",
        "decisionsSha256": hashlib.sha256(decision_bytes).hexdigest(),
    }


def derive_decisions(
    attestations: list[dict[str, Any]],
    invalid_reviews: list[dict[str, Any]],
    plan: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {(item["role"], item["traceId"]): item for item in attestations}
    invalid_by_key = {(item["role"], item["traceId"]): item for item in invalid_reviews}
    trace_ids = [request.traceIds[0] for request in plan.requests if request.role == "primary"]
    if len(trace_ids) != 120 or len(set(trace_ids)) != 120:
        raise ModelReviewError("primary plan does not cover exactly 120 behavior traces")
    decisions: list[dict[str, Any]] = []
    escalations: list[dict[str, Any]] = []
    for trace_id in trace_ids:
        decision = empty_decision(trace_id)
        evidence: dict[str, Any] = {}
        trace_has_invalid = any(
            (role, trace_id) in invalid_by_key for role in ("primary", "secondary")
        )
        for role in ("primary", "secondary"):
            invalid = invalid_by_key.get((role, trace_id))
            if invalid is not None:
                evidence[role] = {
                    "reviewer": invalid["reviewer"],
                    "verdict": "invalid",
                    "error": invalid["error"],
                    "responseSha256": invalid["responseSha256"],
                }
                continue
            attestation = by_key.get((role, trace_id))
            if attestation is None:
                raise ModelReviewError(f"{trace_id}: missing {role} behavior review")
            attestation_sha = hashlib.sha256(canonical(attestation)).hexdigest()
            failed = [item["criterion"] for item in attestation["criteria"] if not item["passed"]]
            if not trace_has_invalid:
                decision[role].update(
                    {
                        "verdict": attestation["verdict"],
                        "reviewer": attestation["reviewer"],
                        "reviewedAt": attestation["reviewedAt"],
                        "notes": f"Attestation sha256:{attestation_sha}. {attestation['summary']}",
                    }
                )
            evidence[role] = {
                "reviewer": attestation["reviewer"],
                "verdict": attestation["verdict"],
                "failedCriteria": failed,
                "attestationSha256": attestation_sha,
            }
        derived = derive_review(decision)
        if derived.status != "approved":
            escalations.append({"traceId": trace_id, "derivedStatus": derived.status, **evidence})
        decisions.append(decision)
    return decisions, escalations


def settle_budget(budget: dict[str, Any], cost: Decimal, plan: Any) -> dict[str, Any]:
    posted = Decimal(budget["postedSpendUsd"])
    outstanding = Decimal(budget["outstandingReservationsUsd"])
    committed = Decimal(budget["committedSpendUsd"])
    authorization = Decimal(budget["authorizationUsd"])
    if posted + outstanding != committed or str(committed) != plan.committedSpendUsd:
        raise ModelReviewError("budget changed after the committed preflight")
    if cost > Decimal(plan.reservationUsd) or committed + cost > authorization:
        raise ModelReviewError("settled review cost exceeds authorization")
    result = dict(budget)
    result["postedSpendUsd"] = str(posted + cost)
    result["committedSpendUsd"] = str(posted + cost + outstanding)
    return result


def _validate_invalid_observation(
    actual: dict[str, Any],
    request: Any,
    entry: dict[str, Any],
    response: dict[str, Any],
    cost: Decimal,
    exc: Exception,
) -> None:
    expected = {
        "schemaVersion": 1,
        "traceId": request.traceIds[0],
        "role": request.role,
        "reviewer": f"openrouter:{request.model}",
        "reviewerFamily": request.family,
        "providerTag": request.providerTag,
        "requestSha256": request.requestSha256,
        "responseId": response["id"],
        "responseSha256": entry["responseSha256"],
        "batchIndex": request.batchIndex,
        "settledCostUsd": str(cost),
        "settlementSha256": entry["settlementSha256"],
        "error": str(exc),
    }
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ModelReviewError("invalid observation differs from raw evidence")
    if set(actual) != {*expected, "reviewedAt"} or not isinstance(actual.get("reviewedAt"), str):
        raise ModelReviewError("invalid observation fields are not exact")


def _validate_attestation(
    actual: dict[str, Any], parsed: dict[str, Any], entry: dict[str, Any], cost: Decimal, stem: str
) -> None:
    if any(actual.get(key) != value for key, value in parsed.items()):
        raise ModelReviewError(f"{stem}: attestation differs from raw response")
    if (
        actual.get("settlementSha256") != entry["settlementSha256"]
        or actual.get("settledCostUsd") != str(cost)
        or not isinstance(actual.get("reviewedAt"), str)
    ):
        raise ModelReviewError(f"{stem}: attestation settlement evidence is invalid")


def _batch(records: list[dict[str, Any]], request: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in records
        if item.get("role") == request.role and item.get("batchIndex") == request.batchIndex
    ]


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ModelReviewError(f"{path.name} must be an object")
    return value


def _pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


if __name__ == "__main__":
    main()
