from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .model_review import CRITERIA, CRITERION_DESCRIPTIONS, SYSTEM_PROMPT, response_schema
REVIEWERS = (
    {
        "role": "primary",
        "family": "google-gemini",
        "model": "google/gemini-3.1-pro-preview",
        "providerTag": "google-ai-studio",
    },
    {
        "role": "secondary",
        "family": "anthropic-claude",
        "model": "anthropic/claude-sonnet-4.6",
        "providerTag": "anthropic",
    },
)
REQUIRED_PARAMETERS = {"max_tokens", "reasoning", "response_format", "structured_outputs"}


class BehaviorReviewPreflightError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewRequest:
    role: str
    batchIndex: int
    traceIds: tuple[str, ...]
    requestSha256: str
    inputByteUpperBound: int
    outputTokenUpperBound: int
    worstCaseCostUsd: str


@dataclass(frozen=True)
class BehaviorReviewPreflight:
    traceCount: int
    requestCount: int
    batchSize: int
    inputByteUpperBound: int
    outputTokenUpperBound: int
    worstCaseCostUsd: str
    reservationUsd: str
    committedSpendUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    requestPlanSha256: str
    requests: tuple[ReviewRequest, ...]

    def summary(self) -> dict[str, Any]:
        value = asdict(self)
        del value["requests"]
        return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def compact_trace(trace: dict[str, Any]) -> dict[str, Any]:
    try:
        return {
            "traceId": trace["traceId"],
            "behavior": trace["axes"][0],
            "contract": trace["contract"],
            "intent": trace["messages"][1]["content"],
            "turns": trace["messages"][2:],
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise BehaviorReviewPreflightError("cannot compact malformed behavior trace") from exc


def request_payload(
    reviewer: dict[str, str],
    traces: list[dict[str, Any]],
    *,
    max_output_tokens: int,
) -> dict[str, Any]:
    trace_ids = tuple(trace["traceId"] for trace in traces)
    criteria = [
        {"criterion": criterion, "requirement": CRITERION_DESCRIPTIONS[criterion]}
        for criterion in CRITERIA
    ]
    user = canonical(
        {
            "criteria": criteria,
            "contractBinding": {
                "contractId": "loomarr-planner-contract-v3",
                "fullContractIsHashBoundAndDeterministicallyValidated": True,
            },
            "requiredTraceIds": list(trace_ids),
            "traces": [compact_trace(trace) for trace in traces],
        }
    ).decode()
    payload: dict[str, Any] = {
        "model": reviewer["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_output_tokens,
        "reasoning": {"effort": "medium", "exclude": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "loomarr_planner_behavior_review",
                "strict": True,
                "schema": response_schema(trace_ids),
            },
        },
        "provider": {
            "only": [reviewer["providerTag"]],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        },
    }
    if reviewer["family"] == "google-gemini":
        payload["seed"] = 3407
    return payload


def preflight(
    traces: Iterable[dict[str, Any]],
    *,
    route_snapshot: dict[str, Any],
    budget: dict[str, Any],
    batch_size: int = 1,
    max_output_tokens: int = 3000,
    reservation_usd: str = "15.00",
) -> BehaviorReviewPreflight:
    trace_list = list(traces)
    if len(trace_list) != 120:
        raise BehaviorReviewPreflightError("behavior review requires exactly 120 traces")
    routes = _validate_snapshot(route_snapshot, batch_size)
    committed, projected, authorization = _validate_budget(budget, Decimal(reservation_usd))
    if batch_size != 1:
        raise BehaviorReviewPreflightError("multi-trace batches lack exact no-inference schema proof")
    if max_output_tokens != 3000:
        raise BehaviorReviewPreflightError("behavior review output ceiling drifted")

    requests: list[ReviewRequest] = []
    total = Decimal(0)
    input_bytes = 0
    output_tokens = 0
    for reviewer, route in zip(REVIEWERS, routes, strict=True):
        prompt_price = Decimal(route["promptPriceUsdPerToken"])
        completion_price = Decimal(route["completionPriceUsdPerToken"])
        for batch_index in range(0, len(trace_list), batch_size):
            batch = trace_list[batch_index : batch_index + batch_size]
            payload = request_payload(reviewer, batch, max_output_tokens=max_output_tokens)
            request_bytes = canonical(payload)
            worst = Decimal(len(request_bytes)) * prompt_price + Decimal(max_output_tokens) * completion_price
            request = ReviewRequest(
                role=reviewer["role"],
                batchIndex=batch_index // batch_size,
                traceIds=tuple(trace["traceId"] for trace in batch),
                requestSha256=hashlib.sha256(request_bytes).hexdigest(),
                inputByteUpperBound=len(request_bytes),
                outputTokenUpperBound=max_output_tokens,
                worstCaseCostUsd=_decimal(worst),
            )
            requests.append(request)
            total += worst
            input_bytes += len(request_bytes)
            output_tokens += max_output_tokens
    reservation = Decimal(reservation_usd)
    if total > reservation:
        raise BehaviorReviewPreflightError(
            f"worst-case review cost {_decimal(total)} exceeds reservation {_decimal(reservation)}"
        )
    request_bytes = b"".join(canonical(asdict(request)) + b"\n" for request in requests)
    return BehaviorReviewPreflight(
        traceCount=len(trace_list),
        requestCount=len(requests),
        batchSize=batch_size,
        inputByteUpperBound=input_bytes,
        outputTokenUpperBound=output_tokens,
        worstCaseCostUsd=_decimal(total),
        reservationUsd=_decimal(reservation),
        committedSpendUsd=_decimal(committed),
        projectedSpendUsd=_decimal(projected),
        authorizationUsd=_decimal(authorization),
        requestPlanSha256=hashlib.sha256(request_bytes).hexdigest(),
        requests=tuple(requests),
    )


def request_plan_bytes(plan: BehaviorReviewPreflight) -> bytes:
    return b"".join(canonical(asdict(request)) + b"\n" for request in plan.requests)


def _validate_snapshot(snapshot: Any, batch_size: int) -> list[dict[str, Any]]:
    expected = {"schemaVersion", "capturedAt", "sources", "reviewers", "schemaCompilationProof"}
    if not isinstance(snapshot, dict) or set(snapshot) != expected or snapshot["schemaVersion"] != 1:
        raise BehaviorReviewPreflightError("route snapshot fields differ from schema v1")
    proof = snapshot["schemaCompilationProof"]
    if not isinstance(proof, dict) or set(proof) != {"available", "reason", "selectedBatchSize"}:
        raise BehaviorReviewPreflightError("schema compilation proof fields differ")
    if proof["available"] is not False or proof["selectedBatchSize"] != 1 or batch_size != 1:
        raise BehaviorReviewPreflightError("route snapshot does not prove the selected batch size")
    routes = snapshot["reviewers"]
    if not isinstance(routes, list) or len(routes) != 2:
        raise BehaviorReviewPreflightError("route snapshot must contain exactly two reviewers")
    for reviewer, route in zip(REVIEWERS, routes, strict=True):
        for key in ("role", "family", "model", "providerTag"):
            if route.get(key) != reviewer[key]:
                raise BehaviorReviewPreflightError("route identity drifted")
        if set(route.get("requiredParameters", [])) != REQUIRED_PARAMETERS:
            raise BehaviorReviewPreflightError("route lacks a required structured-output parameter")
        try:
            prompt = Decimal(route["promptPriceUsdPerToken"])
            completion = Decimal(route["completionPriceUsdPerToken"])
        except (KeyError, InvalidOperation) as exc:
            raise BehaviorReviewPreflightError("route pricing is invalid") from exc
        if prompt <= 0 or completion <= 0:
            raise BehaviorReviewPreflightError("route pricing must be positive")
    return routes


def _validate_budget(budget: Any, reservation: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    try:
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise BehaviorReviewPreflightError("budget ledger is invalid") from exc
    if posted + outstanding != committed:
        raise BehaviorReviewPreflightError("budget ledger does not reconcile")
    projected = committed + reservation
    if reservation != Decimal("15.00") or authorization != Decimal("40.00") or projected > authorization:
        raise BehaviorReviewPreflightError("review reservation exceeds its authorization envelope")
    return committed, projected, authorization


def _decimal(value: Decimal) -> str:
    return format(value, "f")
