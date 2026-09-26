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
LEGACY_PACKET_VERSION = "compact-contract-binding-v1"
CORRECTED_PACKET_VERSION = "targeted-audit-contract-v1"


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


def targeted_audit_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the contract evidence needed to audit every targeted behavior.

    The production bundle remains authoritative. This projection carries its exact tool declaration
    plus explicit dataset-validation semantics that were implicit in the first review packet.
    """
    try:
        tool = contract["tools"][0]
        properties = tool["Parameters"]["properties"]
        prompt = contract["systemPrompt"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BehaviorReviewPreflightError("cannot project malformed planner contract") from exc
    required_prompt_evidence = (
        'KNOWN TITLE → "query" with the title.',
        "If a call returns no candidates, TRY THE OTHER MODE before giving up",
        "A non-empty result ends retrieval.",
        "Select ONLY from ids the tool returns.",
        'SET "confidence" ON EVERY PICK',
        "When finished, reply with ONLY this JSON",
    )
    if any(evidence not in prompt for evidence in required_prompt_evidence):
        raise BehaviorReviewPreflightError("planner contract lacks targeted audit evidence")
    if "query" not in properties or "title" in properties:
        raise BehaviorReviewPreflightError("planner title-search schema differs from audit semantics")
    return {
        "identity": {
            "contractId": contract["contractId"],
            "promptVersion": contract["promptVersion"],
            "systemPromptSha256": contract["systemPromptSha256"],
            "toolSchemaVersion": contract["toolSchemaVersion"],
            "toolSchemaSha256": contract["toolSchemaSha256"],
            "messageTemplateVersion": contract["messageTemplateVersion"],
        },
        "toolDeclaration": tool,
        "auditSemantics": {
            "search": {
                "knownTitleArgument": "query",
                "knownTitleHasNoSeparateTitleArgument": True,
                "discoveryArguments": ["genres", "keywords"],
                "queryCannotMixWithDiscoveryQualifiers": True,
                "emptyOrErroredFirstResultRequiresAlternateModeBeforeAbstention": True,
                "nonEmptyResultEndsRetrieval": True,
            },
            "conversation": {
                "maximumToolOperationsPerAssistantTurn": 1,
                "toolCallAndResultMustAlternate": True,
            },
            "finalProposal": {
                "jsonOnly": True,
                "requiredTopLevelFields": ["channelName", "rationale", "picks", "policy"],
                "picksMayBeEmpty": True,
                "maximumPicks": 8,
                "requiredFieldsForEachExistingPick": [
                    "mediaType",
                    "tmdbId",
                    "name",
                    "rationale",
                    "confidence",
                ],
                "confidenceIsPerPickNotTopLevel": True,
                "emptyPicksThereforeRequireNoConfidenceField": True,
                "selectedIdsMustAppearInToolResults": True,
            },
        },
    }


def request_payload(
    reviewer: dict[str, str],
    traces: list[dict[str, Any]],
    *,
    max_output_tokens: int,
    packet_version: str = LEGACY_PACKET_VERSION,
    contract_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_ids = tuple(trace["traceId"] for trace in traces)
    criteria = [
        {"criterion": criterion, "requirement": CRITERION_DESCRIPTIONS[criterion]}
        for criterion in CRITERIA
    ]
    packet = {
        "criteria": criteria,
        "requiredTraceIds": list(trace_ids),
        "traces": [compact_trace(trace) for trace in traces],
    }
    if packet_version == LEGACY_PACKET_VERSION:
        packet["contractBinding"] = {
            "contractId": "loomarr-planner-contract-v3",
            "fullContractIsHashBoundAndDeterministicallyValidated": True,
        }
    elif packet_version == CORRECTED_PACKET_VERSION:
        if contract_bundle is None:
            raise BehaviorReviewPreflightError("corrected review packet requires the contract bundle")
        packet["auditContract"] = targeted_audit_contract(contract_bundle)
    else:
        raise BehaviorReviewPreflightError("unsupported behavior review packet version")
    user = canonical(packet).decode()
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
    packet_version: str = LEGACY_PACKET_VERSION,
    contract_bundle: dict[str, Any] | None = None,
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
            payload = request_payload(
                reviewer,
                batch,
                max_output_tokens=max_output_tokens,
                packet_version=packet_version,
                contract_bundle=contract_bundle,
            )
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
    if reservation <= 0 or authorization != Decimal("40.00") or projected > authorization:
        raise BehaviorReviewPreflightError("review reservation exceeds its authorization envelope")
    return committed, projected, authorization


def _decimal(value: Decimal) -> str:
    return format(value, "f")
