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

import build_planner_smoke_drafts as drafts
from loomarr_models.model_review import (
    CRITERIA,
    ModelReviewContentError,
    ModelReviewError,
    canonical,
    load_config,
    preflight,
    validate_completion,
    validate_settlement,
)
from loomarr_models.review import derive_review, empty_decision


CONFIG = ROOT / "experiments/planner-model-review-v9.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and publish dual-model review evidence")
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        repaired = _repair_partial_publication(config_path)
        if repaired is not None:
            print(json.dumps(repaired, sort_keys=True))
            return
        plan = preflight(ROOT, config_path)
        result = publish(plan)
    except (OSError, ModelReviewError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


def publish(plan: Any) -> dict[str, Any]:
    artifacts = ROOT / plan.outputDir
    public = ROOT / "reviews/planner-smoke-v1" / plan.reviewId
    if public.exists():
        raise ModelReviewError("published model-review directory already exists")
    manifest_path = artifacts / "run-manifest.json"
    attestation_path = artifacts / "attestations.jsonl"
    invalid_review_path = artifacts / "invalid-reviews.jsonl"
    manifest = _object(manifest_path)
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
        raise ModelReviewError("run manifest is not an exact complete model-review manifest")
    expected_identity = {
        "reviewId": plan.reviewId,
        "sourceCommit": plan.sourceCommit,
        "configSha256": plan.configSha256,
        "corpusSha256": plan.corpusSha256,
        "requestCount": plan.requestCount,
        "reservationUsd": plan.reservationUsd,
    }
    if any(manifest.get(key) != value for key, value in expected_identity.items()):
        raise ModelReviewError("run manifest differs from the committed preflight identity")
    attestation_bytes = attestation_path.read_bytes()
    if hashlib.sha256(attestation_bytes).hexdigest() != manifest["attestationsSha256"]:
        raise ModelReviewError("attestation digest mismatch")
    attestations = [json.loads(line) for line in attestation_bytes.splitlines() if line]
    invalid_review_bytes = invalid_review_path.read_bytes()
    if hashlib.sha256(invalid_review_bytes).hexdigest() != manifest["invalidReviewsSha256"]:
        raise ModelReviewError("invalid-review digest mismatch")
    invalid_reviews = [json.loads(line) for line in invalid_review_bytes.splitlines() if line]
    if (
        len(attestations) != manifest["attestationCount"]
        or len(invalid_reviews) != manifest["invalidReviewCount"]
        or len(attestations) + len(invalid_reviews) != 100
    ):
        raise ModelReviewError("published run must contain exactly 100 review observations")

    artifact_entries = manifest["callArtifacts"]
    if not isinstance(artifact_entries, list) or len(artifact_entries) != len(plan.requests):
        raise ModelReviewError("call artifact manifest is incomplete")
    actual_cost = Decimal(0)
    expected_attestations: list[dict[str, Any]] = []
    expected_invalid_reviews: list[dict[str, Any]] = []
    for request, entry in zip(plan.requests, artifact_entries, strict=True):
        stem = f"{request.role}-{request.batchIndex:02d}"
        if not isinstance(entry, dict) or entry.get("stem") != stem:
            raise ModelReviewError("call artifact order or identity differs from the plan")
        summary_bytes = (artifacts / "calls" / f"{stem}.json").read_bytes()
        response_bytes = (artifacts / "calls" / f"{stem}.response.json").read_bytes()
        settlement_bytes = (artifacts / "calls" / f"{stem}.settlement.json").read_bytes()
        for label, content in (
            ("summary", summary_bytes),
            ("response", response_bytes),
            ("settlement", settlement_bytes),
        ):
            if hashlib.sha256(content).hexdigest() != entry[f"{label}Sha256"]:
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
            if batch_attestations or len(batch_invalid) != len(request.traceIds):
                raise ModelReviewError(f"{stem}: invalid-review coverage is incomplete") from exc
            if summary.get("status") != "invalid" or summary.get("contentError") != str(exc):
                raise ModelReviewError(f"{stem}: invalid call summary differs from raw response")
            for actual, trace_id in zip(batch_invalid, request.traceIds, strict=True):
                expected = {
                    "schemaVersion": 1,
                    "traceId": trace_id,
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
                for key, value in expected.items():
                    if actual.get(key) != value:
                        raise ModelReviewError(f"{stem}: invalid review differs from raw evidence")
                if set(actual) != {*expected, "reviewedAt"} or not isinstance(
                    actual.get("reviewedAt"), str
                ):
                    raise ModelReviewError(f"{stem}: invalid review fields are not exact")
            expected_invalid_reviews.extend(batch_invalid)
        else:
            if batch_invalid or len(batch_attestations) != len(request.traceIds):
                raise ModelReviewError(f"{stem}: attestation coverage is incomplete")
            if summary.get("status") != "valid" or "contentError" in summary:
                raise ModelReviewError(f"{stem}: valid call summary differs from raw response")
            for actual, base in zip(batch_attestations, parsed, strict=True):
                for key, value in base.items():
                    if actual.get(key) != value:
                        raise ModelReviewError(f"{stem}: attestation differs from raw response")
                if (
                    actual.get("settlementSha256") != entry["settlementSha256"]
                    or actual.get("settledCostUsd") != str(cost)
                    or not isinstance(actual.get("reviewedAt"), str)
                ):
                    raise ModelReviewError(f"{stem}: attestation settlement evidence is invalid")
            expected_attestations.extend(batch_attestations)
        if (
            summary.get("requestSha256") != request.requestSha256
            or summary.get("settledCostUsd") != str(cost)
        ):
            raise ModelReviewError(f"{stem}: call summary differs from request or settlement")
    if expected_attestations != attestations:
        raise ModelReviewError("attestations differ from exact call order")
    if expected_invalid_reviews != invalid_reviews:
        raise ModelReviewError("invalid reviews differ from exact call order")
    if str(actual_cost) != manifest["actualCostUsd"] or actual_cost > Decimal(plan.reservationUsd):
        raise ModelReviewError("run cost differs from settled calls or exceeds reservation")

    decisions, escalations = _decisions(attestations, invalid_reviews, plan)
    decision_bytes = b"".join(canonical(decision) + b"\n" for decision in decisions)
    current = drafts.load_reviews()
    pristine = [empty_decision(trace_id) for trace_id in drafts.expected_trace_ids()]
    if list(current.values()) != pristine:
        raise ModelReviewError("refusing to replace review decisions that contain prior evidence")

    shutil.copytree(artifacts, public)
    (public / "decisions.jsonl").write_bytes(decision_bytes)
    _settle_budget(actual_cost)
    escalation_path = public / "escalations.json"
    escalation_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "reviewId": plan.reviewId,
                "count": len(escalations),
                "traces": escalations,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    result = {
        "reviewId": plan.reviewId,
        "actualCostUsd": str(actual_cost),
        "approved": 50 - len(escalations),
        "escalations": len(escalations),
        "decisionsSha256": hashlib.sha256(decision_bytes).hexdigest(),
    }
    (public / "publication.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _repair_partial_publication(config_path: Path) -> dict[str, Any] | None:
    """Stage decisions from the old partial-publish behavior and restore pristine drafts."""
    config = load_config(config_path)
    public = ROOT / "reviews/planner-smoke-v1" / config["reviewId"]
    if not public.exists():
        return None
    decision_path = public / "decisions.jsonl"
    if decision_path.exists():
        raise ModelReviewError("published model-review directory already exists")
    publication = _object(public / "publication.json")
    decision_bytes = drafts.REVIEW_PATH.read_bytes()
    if hashlib.sha256(decision_bytes).hexdigest() != publication.get("decisionsSha256"):
        raise ModelReviewError("cannot repair partial publication: canonical decisions differ")
    decision_path.write_bytes(decision_bytes)
    pristine = [empty_decision(trace_id) for trace_id in drafts.expected_trace_ids()]
    drafts.REVIEW_PATH.write_bytes(b"".join(canonical(item) + b"\n" for item in pristine))
    subprocess.run([sys.executable, "scripts/build_planner_smoke_drafts.py"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/render_review_packet.py"], cwd=ROOT, check=True)
    restored_config = load_config(config_path)
    bindings = restored_config["bindings"]
    for name, path in (
        ("corpus", ROOT / bindings["corpus"]["path"]),
        ("corpusManifest", ROOT / bindings["corpusManifest"]["path"]),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != bindings[name]["sha256"]:
            raise ModelReviewError(f"partial publication repair did not restore {name}")
    return {"reviewId": config["reviewId"], "status": "partial-decisions-staged"}


def _batch(records: list[dict[str, Any]], request: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in records
        if item.get("role") == request.role and item.get("batchIndex") == request.batchIndex
    ]


def _decisions(
    attestations: list[dict[str, Any]],
    invalid_reviews: list[dict[str, Any]],
    plan: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_key = {(item["role"], item["traceId"]): item for item in attestations}
    invalid_by_key = {(item["role"], item["traceId"]): item for item in invalid_reviews}
    trace_ids = [
        trace_id
        for request in plan.requests
        if request.role == "primary"
        for trace_id in request.traceIds
    ]
    if len(trace_ids) != 50:
        raise ModelReviewError("primary review plan does not cover exactly 50 traces")
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
                invalid_sha = hashlib.sha256(canonical(invalid)).hexdigest()
                evidence[role] = {
                    "reviewer": invalid["reviewer"],
                    "verdict": "invalid",
                    "error": invalid["error"],
                    "responseSha256": invalid["responseSha256"],
                    "invalidReviewSha256": invalid_sha,
                }
                continue
            attestation = by_key.get((role, trace_id))
            if attestation is None:
                raise ModelReviewError(f"{trace_id}: missing {role} review observation")
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


def _settle_budget(cost: Decimal) -> None:
    path = ROOT / "budgets/external-spend-v1.json"
    budget = _object(path)
    posted = Decimal(budget["postedSpendUsd"]) + cost
    outstanding = Decimal(budget["outstandingReservationsUsd"])
    budget["postedSpendUsd"] = str(posted)
    budget["committedSpendUsd"] = str(posted + outstanding)
    path.write_text(json.dumps(budget, indent=2) + "\n", encoding="utf-8")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ModelReviewError(f"{path.relative_to(ROOT)} must be an object")
    return value


if __name__ == "__main__":
    main()
