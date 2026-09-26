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


class V4ReviewPreflightError(ValueError):
    pass


@dataclass(frozen=True)
class V4ReviewRequest:
    role: str
    batch_index: int
    trace_ids: tuple[str, ...]
    request_sha256: str
    input_byte_upper_bound: int
    output_token_upper_bound: int
    worst_case_cost_usd: str


@dataclass(frozen=True)
class V4ReviewPreflight:
    trace_count: int
    request_count: int
    batch_size: int
    input_byte_upper_bound: int
    output_token_upper_bound: int
    worst_case_cost_usd: str
    reservation_usd: str
    committed_spend_usd: str
    projected_spend_usd: str
    authorization_usd: str
    request_plan_sha256: str
    requests: tuple[V4ReviewRequest, ...]

    def summary(self) -> dict[str, Any]:
        value = asdict(self)
        del value["requests"]
        return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def v4_audit_contract(contract: dict[str, Any]) -> dict[str, Any]:
    try:
        tool = contract["tools"][0]
        properties = tool["Parameters"]["properties"]
        prompt = contract["systemPrompt"]
    except (KeyError, IndexError, TypeError) as exc:
        raise V4ReviewPreflightError("cannot project malformed planner v4 contract") from exc
    required_properties = {
        "query",
        "genres",
        "keywords",
        "era",
        "media_type",
        "original_language",
        "origin_country",
        "runtime_min",
        "runtime_max",
        "vote_average_min",
        "vote_count_min",
        "network",
        "cast",
        "creators",
    }
    required_prompt_evidence = (
        "For an explicitly named movie performer, director, writer, or creator",
        "For an explicitly named TV network",
        "Do not use person filters for series, a network filter for movies, "
        "or mix network and person filters in one call.",
        "Select ONLY from ids the tool returns",
        "When finished, reply with ONLY this JSON",
    )
    if contract.get("contractId") != "loomarr-planner-contract-v4":
        raise V4ReviewPreflightError("review requires the exact planner v4 contract")
    if set(properties) != required_properties or any(item not in prompt for item in required_prompt_evidence):
        raise V4ReviewPreflightError("planner v4 contract lacks entity-route audit evidence")
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
            "titleSearch": {
                "argument": "query",
                "mayAlsoCarryMediaType": True,
                "cannotMixWithDiscoveryQualifiers": True,
            },
            "tvNetwork": {
                "argument": "network",
                "exactNameRequired": True,
                "requiredMediaType": "series",
                "cannotMixWithPersonArguments": True,
                "originCountryRequiredOnlyWhenIntentSuppliesIt": True,
            },
            "moviePeople": {
                "performerArgument": "cast",
                "directorWriterCrewArgument": "creators",
                "exactNamesRequired": True,
                "requiredMediaType": "movie",
                "castAndCreatorsMayCombine": True,
                "oneToFourNamesPerArgument": True,
            },
            "seriesPersonIntent": {
                "personArgumentsAreForbidden": True,
                "personMayBeSelectedOnlyFromReturnedCandidateEvidence": True,
            },
            "finalProposal": {
                "jsonOnly": True,
                "requiredTopLevelFields": ["channelName", "rationale", "picks", "policy"],
                "maximumPicks": 8,
                "selectedIdsMustAppearInToolResults": True,
                "confidenceRequiredPerPick": True,
            },
        },
    }


def request_payload(
    reviewer: dict[str, str],
    trace: dict[str, Any],
    *,
    contract: dict[str, Any],
    max_output_tokens: int,
) -> dict[str, Any]:
    trace_id = trace["traceId"]
    packet = {
        "criteria": [
            {"criterion": criterion, "requirement": CRITERION_DESCRIPTIONS[criterion]}
            for criterion in CRITERIA
        ],
        "requiredTraceIds": [trace_id],
        "auditContract": v4_audit_contract(contract),
        "traces": [
            {
                "traceId": trace_id,
                "behavior": trace["axes"][0],
                "contract": trace["contract"],
                "intent": trace["messages"][1]["content"],
                "turns": trace["messages"][2:],
            }
        ],
    }
    payload: dict[str, Any] = {
        "model": reviewer["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": canonical(packet).decode()},
        ],
        "max_tokens": max_output_tokens,
        "reasoning": {"effort": "medium", "exclude": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "loomarr_planner_v4_delta_review",
                "strict": True,
                "schema": response_schema((trace_id,)),
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
    contract: dict[str, Any],
    route_snapshot: dict[str, Any],
    budget: dict[str, Any],
    reservation_usd: str = "8.00",
    max_output_tokens: int = 3000,
) -> V4ReviewPreflight:
    trace_list = list(traces)
    if len(trace_list) != 60:
        raise V4ReviewPreflightError("v4 delta review requires exactly 60 traces")
    if max_output_tokens != 3000:
        raise V4ReviewPreflightError("v4 review output ceiling drifted")
    routes = _validate_snapshot(route_snapshot)
    reservation = Decimal(reservation_usd)
    committed, projected, authorization = _validate_budget(budget, reservation)
    requests: list[V4ReviewRequest] = []
    total = Decimal(0)
    input_bytes = 0
    for reviewer, route in zip(REVIEWERS, routes, strict=True):
        prompt_price = Decimal(route["promptPriceUsdPerToken"])
        completion_price = Decimal(route["completionPriceUsdPerToken"])
        for batch_index, trace in enumerate(trace_list):
            payload = request_payload(
                reviewer,
                trace,
                contract=contract,
                max_output_tokens=max_output_tokens,
            )
            request_bytes = canonical(payload)
            worst = Decimal(len(request_bytes)) * prompt_price + Decimal(max_output_tokens) * completion_price
            requests.append(
                V4ReviewRequest(
                    role=reviewer["role"],
                    batch_index=batch_index,
                    trace_ids=(trace["traceId"],),
                    request_sha256=hashlib.sha256(request_bytes).hexdigest(),
                    input_byte_upper_bound=len(request_bytes),
                    output_token_upper_bound=max_output_tokens,
                    worst_case_cost_usd=_decimal(worst),
                )
            )
            total += worst
            input_bytes += len(request_bytes)
    if len(requests) != 120:
        raise V4ReviewPreflightError("v4 review request count drifted")
    if total > reservation:
        raise V4ReviewPreflightError(
            f"worst-case review cost {_decimal(total)} exceeds reservation {_decimal(reservation)}"
        )
    plan_bytes = request_plan_bytes(requests)
    return V4ReviewPreflight(
        trace_count=60,
        request_count=120,
        batch_size=1,
        input_byte_upper_bound=input_bytes,
        output_token_upper_bound=120 * max_output_tokens,
        worst_case_cost_usd=_decimal(total),
        reservation_usd=_decimal(reservation),
        committed_spend_usd=_decimal(committed),
        projected_spend_usd=_decimal(projected),
        authorization_usd=_decimal(authorization),
        request_plan_sha256=hashlib.sha256(plan_bytes).hexdigest(),
        requests=tuple(requests),
    )


def request_plan_bytes(requests: Iterable[V4ReviewRequest]) -> bytes:
    return b"".join(canonical(asdict(request)) + b"\n" for request in requests)


def _validate_snapshot(snapshot: Any) -> list[dict[str, Any]]:
    expected = {"schemaVersion", "capturedAt", "sources", "reviewers", "schemaCompilationProof"}
    if not isinstance(snapshot, dict) or set(snapshot) != expected or snapshot["schemaVersion"] != 1:
        raise V4ReviewPreflightError("route snapshot fields differ from schema v1")
    proof = snapshot["schemaCompilationProof"]
    if (
        not isinstance(proof, dict)
        or proof.get("available") is not False
        or proof.get("selectedBatchSize") != 1
    ):
        raise V4ReviewPreflightError("route snapshot does not prove single-trace batches")
    routes = snapshot["reviewers"]
    if not isinstance(routes, list) or len(routes) != 2:
        raise V4ReviewPreflightError("route snapshot must contain exactly two reviewers")
    for reviewer, route in zip(REVIEWERS, routes, strict=True):
        if any(route.get(key) != reviewer[key] for key in ("role", "family", "model", "providerTag")):
            raise V4ReviewPreflightError("route identity drifted")
        if set(route.get("requiredParameters", [])) != REQUIRED_PARAMETERS:
            raise V4ReviewPreflightError("route lacks strict structured-output parameters")
        try:
            prompt = Decimal(route["promptPriceUsdPerToken"])
            completion = Decimal(route["completionPriceUsdPerToken"])
        except (KeyError, InvalidOperation) as exc:
            raise V4ReviewPreflightError("route pricing is invalid") from exc
        if prompt <= 0 or completion <= 0:
            raise V4ReviewPreflightError("route pricing must be positive")
    return routes


def _validate_budget(budget: Any, reservation: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    try:
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise V4ReviewPreflightError("budget ledger is invalid") from exc
    if posted + outstanding != committed:
        raise V4ReviewPreflightError("budget ledger does not reconcile")
    projected = committed + reservation
    if reservation <= 0 or authorization != Decimal("40.00") or projected > authorization:
        raise V4ReviewPreflightError("v4 review reservation exceeds authorization")
    return committed, projected, authorization


def _decimal(value: Decimal) -> str:
    return format(value, "f")
