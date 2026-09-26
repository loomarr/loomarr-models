from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .evaluation import CONTRACT_KEYS, EXPECTATION_KEYS, PROVENANCE_KEYS
from .targeted import BEHAVIORS as FOUNDATIONAL_BEHAVIORS
from .validator import (
    ALLOWED_MEDIA_TYPES,
    PRIVATE_PATH_PATTERNS,
    SECRET_PATTERNS,
    ValidationError,
    validate_catalog_search_arguments,
    validate_corpus,
)


ENTITY_BEHAVIORS = (
    "network-routing",
    "cast-routing",
    "creator-routing",
    "combined-person-routing",
    "network-country-routing",
    "series-person-evidence-routing",
)
DEVELOPMENT_BEHAVIORS = FOUNDATIONAL_BEHAVIORS + ENTITY_BEHAVIORS
TRAINING_PER_BEHAVIOR = 10
DEVELOPMENT_PER_BEHAVIOR = 10
TRAINING_FIXTURE_ID = "planner-v4-delta-training-catalog-v1"
DEVELOPMENT_FIXTURE_ID = "planner-v4-development-catalog-v1"
TRAINING_GENERATOR_ID = "planner-v4-delta-generator-v1"
DEVELOPMENT_GENERATOR_ID = "planner-v4-development-generator-v1"

CASE_KEYS = {
    "schemaVersion",
    "caseId",
    "split",
    "axis",
    "contract",
    "intent",
    "script",
    "repairPrompt",
    "expectation",
    "provenance",
}


@dataclass(frozen=True)
class V4Report:
    records: int
    behavior_counts: dict[str, int]
    sha256: str


@dataclass(frozen=True)
class SplitDisjointnessReport:
    splits: dict[str, int]
    pair_count: int


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def validate_delta_training(
    traces: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> V4Report:
    items = list(traces)
    validate_corpus(
        items,
        denylisted_identities=denylisted_identities,
        denylisted_sha256=denylisted_sha256,
        contract_bundle=contract,
        allow_pending=True,
    )
    counts: Counter[str] = Counter()
    for trace in items:
        trace_id = trace["traceId"]
        if not re.fullmatch(r"planner-v4-delta-[a-z0-9-]+-\d{2}", trace_id):
            raise ValidationError(f"{trace_id}: invalid v4 delta trace identity")
        if trace["split"] != "train" or len(trace["axes"]) != 1:
            raise ValidationError(f"{trace_id}: invalid v4 delta split or axes")
        behavior = trace["axes"][0]
        if behavior not in ENTITY_BEHAVIORS:
            raise ValidationError(f"{trace_id}: unknown v4 delta behavior")
        if trace["contract"]["fixtureId"] != TRAINING_FIXTURE_ID:
            raise ValidationError(f"{trace_id}: v4 delta fixture drifted")
        if trace["provenance"] != {
            "source": "synthetic",
            "generator": TRAINING_GENERATOR_ID,
            "author": "codex:draft",
        }:
            raise ValidationError(f"{trace_id}: invalid v4 delta provenance")
        _validate_entity_trace(trace_id, behavior, trace["messages"])
        counts[behavior] += 1
    expected = {behavior: TRAINING_PER_BEHAVIOR for behavior in ENTITY_BEHAVIORS}
    if len(items) != 60 or dict(counts) != expected:
        raise ValidationError("v4 delta training must contain exactly 10 traces per six behaviors")
    payload = b"".join(canonical(item) + b"\n" for item in items)
    return V4Report(len(items), dict(counts), hashlib.sha256(payload).hexdigest())


def validate_development(
    cases: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> V4Report:
    items = list(cases)
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for case in items:
        case_id = case.get("caseId", "<missing>")
        if case_id in seen:
            raise ValidationError(f"{case_id}: duplicate v4 development identity")
        seen.add(case_id)
        _validate_development_case(
            case,
            contract=contract,
            denylisted_identities=denylisted_identities,
            denylisted_sha256=denylisted_sha256,
        )
        counts[case["axis"]] += 1
    expected = {behavior: DEVELOPMENT_PER_BEHAVIOR for behavior in DEVELOPMENT_BEHAVIORS}
    if len(items) != 120 or dict(counts) != expected:
        raise ValidationError("v4 development must contain exactly 10 cases per twelve behaviors")
    payload = b"".join(canonical(item) + b"\n" for item in items)
    return V4Report(len(items), dict(counts), hashlib.sha256(payload).hexdigest())


def validate_disjoint_splits(
    splits: Mapping[str, Iterable[dict[str, Any]]],
) -> SplitDisjointnessReport:
    summaries: dict[str, tuple[set[str], set[tuple[str, int]], set[str]]] = {}
    for split_name, records in splits.items():
        record_ids: set[str] = set()
        content_ids: set[tuple[str, int]] = set()
        content_digests: set[str] = set()
        count = 0
        for record in records:
            count += 1
            record_id = record.get("traceId", record.get("caseId"))
            if not isinstance(record_id, str) or not record_id or record_id in record_ids:
                raise ValidationError(f"{split_name}: missing or duplicate record identity")
            record_ids.add(record_id)
            content_digests.add(_normalized_record_digest(record))
            content_ids.update(_candidate_identities(record))
        if count == 0:
            raise ValidationError(f"{split_name}: split is empty")
        summaries[split_name] = record_ids, content_ids, content_digests

    pair_count = 0
    names = list(summaries)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            pair_count += 1
            for left_values, right_values, label in zip(
                summaries[left],
                summaries[right],
                ("record identity", "content identity", "normalized content"),
                strict=True,
            ):
                if left_values & right_values:
                    raise ValidationError(f"{left} and {right}: {label} overlap")
    return SplitDisjointnessReport(
        splits={name: len(values[0]) for name, values in summaries.items()},
        pair_count=pair_count,
    )


def _validate_entity_trace(trace_id: str, behavior: str, messages: list[dict[str, Any]]) -> None:
    if len(messages) != 5 or messages[2].get("role") != "assistant" or messages[3].get("role") != "tool":
        raise ValidationError(f"{trace_id}: v4 delta must use one tool operation and one final")
    calls = messages[2].get("toolCalls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValidationError(f"{trace_id}: v4 delta must use exactly one tool call")
    args = calls[0]["arguments"]
    candidates = messages[3]["content"].get("candidates", [])
    _validate_entity_route(trace_id, behavior, args, candidates)


def _validate_entity_route(
    context: str,
    behavior: str,
    arguments: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> None:
    if not candidates:
        raise ValidationError(f"{context}: entity route requires synthetic candidates")
    if behavior == "network-routing":
        if set(arguments) != {"media_type", "network"}:
            raise ValidationError(f"{context}: network route arguments drifted")
    elif behavior == "cast-routing":
        if set(arguments) != {"media_type", "cast"}:
            raise ValidationError(f"{context}: cast route arguments drifted")
    elif behavior == "creator-routing":
        if set(arguments) != {"media_type", "creators"}:
            raise ValidationError(f"{context}: creator route arguments drifted")
    elif behavior == "combined-person-routing":
        if set(arguments) != {"media_type", "cast", "creators"}:
            raise ValidationError(f"{context}: combined person route arguments drifted")
    elif behavior == "network-country-routing":
        if set(arguments) != {"media_type", "network", "origin_country"}:
            raise ValidationError(f"{context}: network-country route arguments drifted")
    elif behavior == "series-person-evidence-routing":
        if set(arguments) != {"media_type", "network"} or len(candidates) < 2:
            raise ValidationError(f"{context}: series-person evidence route drifted")
        if "cast" in arguments or "creators" in arguments:
            raise ValidationError(f"{context}: series person was sent as an unsupported filter")
    else:
        return


def _validate_development_case(
    case: dict[str, Any],
    *,
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> None:
    case_id = case.get("caseId", "<missing>")
    if set(case) != CASE_KEYS or case.get("schemaVersion") != 1:
        raise ValidationError(f"{case_id}: fields differ from v4 development schema")
    if not re.fullmatch(r"planner-v4-development-[a-z0-9-]+-\d{2}", case_id):
        raise ValidationError(f"{case_id}: invalid v4 development identity")
    behavior = case.get("axis")
    if case.get("split") != "development-eval" or behavior not in DEVELOPMENT_BEHAVIORS:
        raise ValidationError(f"{case_id}: invalid v4 development split or behavior")
    expected_contract = {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": DEVELOPMENT_FIXTURE_ID,
    }
    if set(case["contract"]) != CONTRACT_KEYS or case["contract"] != expected_contract:
        raise ValidationError(f"{case_id}: v4 development contract drifted")
    if set(case["provenance"]) != PROVENANCE_KEYS or case["provenance"] != {
        "source": "synthetic",
        "generator": DEVELOPMENT_GENERATOR_ID,
        "author": "codex:fixture",
    }:
        raise ValidationError(f"{case_id}: invalid v4 development provenance")
    serialized = json.dumps(case, sort_keys=True, ensure_ascii=False)
    for pattern in SECRET_PATTERNS + PRIVATE_PATH_PATTERNS:
        if pattern.search(serialized):
            raise ValidationError(f"{case_id}: possible secret or household path")
    for identity in denylisted_identities:
        if identity in serialized:
            raise ValidationError(f"{case_id}: holdout identity leaked")
    for digest in denylisted_sha256:
        if digest in serialized:
            raise ValidationError(f"{case_id}: holdout digest leaked")
    if case["repairPrompt"] is not None:
        raise ValidationError(f"{case_id}: v4 development cannot contain repair answers")
    script = case["script"]
    if not isinstance(script, list) or not 1 <= len(script) <= 2:
        raise ValidationError(f"{case_id}: invalid v4 development script")
    surfaced: set[tuple[str, int]] = set()
    for step in script:
        if not isinstance(step, dict) or set(step) != {"arguments", "result"}:
            raise ValidationError(f"{case_id}: malformed v4 development tool step")
        validate_catalog_search_arguments(
            step["arguments"], contract_bundle=contract, context=case_id
        )
        result = step["result"]
        if not isinstance(result, dict) or set(result) - {"candidates", "error"}:
            raise ValidationError(f"{case_id}: invalid v4 development tool result")
        candidates = result.get("candidates", [])
        if not isinstance(candidates, list):
            raise ValidationError(f"{case_id}: candidates must be an array")
        for candidate in candidates:
            surfaced.add(_candidate_identity(case_id, candidate))
    expectation = case["expectation"]
    if not isinstance(expectation, dict) or set(expectation) != EXPECTATION_KEYS:
        raise ValidationError(f"{case_id}: invalid v4 development expectation")
    selected = {_expected_identity(case_id, item) for item in expectation["selectedIds"]}
    forbidden = {_expected_identity(case_id, item) for item in expectation["forbiddenIds"]}
    if not selected <= surfaced or not forbidden <= surfaced or selected & forbidden:
        raise ValidationError(f"{case_id}: expectation and scripted candidates disagree")
    if expectation["abstain"] is not (not selected) or expectation["maxToolCalls"] != len(script):
        raise ValidationError(f"{case_id}: abstention or tool-call expectation drifted")
    if not isinstance(expectation["expectedPolicy"], dict):
        raise ValidationError(f"{case_id}: expected policy must be an object")
    if behavior in ENTITY_BEHAVIORS:
        _validate_entity_route(case_id, behavior, script[0]["arguments"], script[0]["result"].get("candidates", []))


def _candidate_identity(context: str, candidate: Any) -> tuple[str, int]:
    if not isinstance(candidate, dict):
        raise ValidationError(f"{context}: candidate must be an object")
    media_type, tmdb_id = candidate.get("mediaType"), candidate.get("tmdbId")
    if media_type not in ALLOWED_MEDIA_TYPES or not isinstance(tmdb_id, int) or tmdb_id <= 0:
        raise ValidationError(f"{context}: invalid candidate identity")
    if not isinstance(candidate.get("name"), str) or not candidate["name"]:
        raise ValidationError(f"{context}: candidate name is empty")
    return media_type, tmdb_id


def _expected_identity(context: str, identity: Any) -> tuple[str, int]:
    if not isinstance(identity, dict) or set(identity) != {"mediaType", "tmdbId"}:
        raise ValidationError(f"{context}: invalid expected identity")
    return _candidate_identity(context, {**identity, "name": "expected"})


def _intent(record: dict[str, Any]) -> str:
    if isinstance(record.get("intent"), str):
        return record["intent"]
    messages = record.get("messages")
    if isinstance(messages, list) and len(messages) > 1 and isinstance(messages[1].get("content"), str):
        return messages[1]["content"]
    raise ValidationError("record lacks a synthetic intent")


def _normalized_record_digest(record: dict[str, Any]) -> str:
    if isinstance(record.get("script"), list):
        steps = record["script"]
    else:
        messages = record.get("messages", [])
        results = {
            message.get("toolCallId"): message.get("content")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "tool"
        }
        steps = [
            {"arguments": call.get("arguments"), "result": results.get(call.get("id"))}
            for message in messages
            if isinstance(message, dict) and message.get("role") == "assistant"
            for call in message.get("toolCalls", [])
        ]
    normalized = {
        "intent": " ".join(_intent(record).lower().split()),
        "steps": _without_external_ids(steps),
    }
    return hashlib.sha256(canonical(normalized)).hexdigest()


def _without_external_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<external-id>" if key in {"tmdbId", "tvdbId"} else _without_external_ids(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_without_external_ids(item) for item in value]
    return value


def _candidate_identities(record: dict[str, Any]) -> set[tuple[str, int]]:
    results: list[dict[str, Any]] = []
    if isinstance(record.get("script"), list):
        results.extend(step.get("result", {}) for step in record["script"] if isinstance(step, dict))
    if isinstance(record.get("messages"), list):
        results.extend(
            message.get("content", {})
            for message in record["messages"]
            if isinstance(message, dict) and message.get("role") == "tool"
        )
    return {
        (candidate["mediaType"], candidate["tmdbId"])
        for result in results
        if isinstance(result, dict)
        for candidate in result.get("candidates", [])
        if isinstance(candidate, dict)
        and candidate.get("mediaType") in ALLOWED_MEDIA_TYPES
        and isinstance(candidate.get("tmdbId"), int)
    }
