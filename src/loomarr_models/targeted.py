from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from .evaluation import CONTRACT_KEYS, EXPECTATION_KEYS, PROVENANCE_KEYS
from .validator import (
    ALLOWED_MEDIA_TYPES,
    PRIVATE_PATH_PATTERNS,
    SEARCH_ARGUMENTS,
    SECRET_PATTERNS,
    ValidationError,
    validate_corpus,
)


BEHAVIORS = (
    "canonical-argument-preservation",
    "one-tool-operation-per-turn",
    "complete-proposal-json",
    "structured-json-abstention",
    "synthetic-tool-error-recovery",
    "ambiguous-intent-mapping",
)
TRAINING_PER_BEHAVIOR = 20
DEVELOPMENT_PER_BEHAVIOR = 10
TRAINING_FIXTURE_ID = "planner-behavior-training-catalog-v2"
DEVELOPMENT_FIXTURE_ID = "planner-behavior-development-catalog-v2"
TRAINING_GENERATOR_ID = "planner-behavior-corpus-generator-v2"
DEVELOPMENT_GENERATOR_ID = "planner-behavior-development-generator-v2"

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
FINAL_KEYS = {"channelName", "rationale", "picks", "policy"}
CANONICAL_INTENT = re.compile(
    r"^Build a synthetic (?P<genre>[A-Za-z ]+) channel from (?P<era>\d{4}s), "
    r"media type (?P<media_type>movie|series), original language (?P<language>[a-z]{2}), "
    r"origin country (?P<country>[A-Z]{2}), runtime (?P<runtime_min>\d+)-"
    r"(?P<runtime_max>\d+) minutes, minimum rating (?P<rating>\d+(?:\.\d)?), and "
    r"minimum (?P<votes>\d+) votes; do not add other qualifiers\.$"
)


@dataclass(frozen=True)
class TargetedReport:
    records: int
    behaviorCounts: dict[str, int]
    sha256: str


@dataclass(frozen=True)
class DisjointnessReport:
    splits: dict[str, dict[str, int]]
    pairCount: int


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def validate_targeted_training(
    traces: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> TargetedReport:
    trace_list = list(traces)
    validate_corpus(
        trace_list,
        denylisted_identities=denylisted_identities,
        denylisted_sha256=denylisted_sha256,
        contract_bundle=contract,
        allow_pending=True,
    )
    counts: Counter[str] = Counter()
    for trace in trace_list:
        trace_id = trace["traceId"]
        if not re.fullmatch(r"planner-behavior-v2-[a-z0-9-]+-\d{2}", trace_id):
            raise ValidationError(f"{trace_id}: invalid targeted trace identity")
        if trace["split"] != "train" or len(trace["axes"]) != 1:
            raise ValidationError(f"{trace_id}: invalid targeted training split or axes")
        behavior = trace["axes"][0]
        if behavior not in BEHAVIORS:
            raise ValidationError(f"{trace_id}: unknown targeted behavior")
        if trace["contract"]["fixtureId"] != TRAINING_FIXTURE_ID:
            raise ValidationError(f"{trace_id}: targeted training fixture drifted")
        if trace["provenance"] != {
            "source": "synthetic",
            "generator": TRAINING_GENERATOR_ID,
            "author": "codex:draft",
        }:
            raise ValidationError(f"{trace_id}: invalid targeted training provenance")
        if trace["review"]["status"] not in {"pending", "approved"}:
            raise ValidationError(f"{trace_id}: rejected trace cannot remain in targeted corpus")
        _validate_synthetic_record(trace_id, trace)
        _validate_training_behavior(trace_id, behavior, trace["messages"])
        counts[behavior] += 1

    expected = {behavior: TRAINING_PER_BEHAVIOR for behavior in BEHAVIORS}
    if len(trace_list) != len(BEHAVIORS) * TRAINING_PER_BEHAVIOR or dict(counts) != expected:
        raise ValidationError("targeted training must contain exactly 20 traces per six behaviors")
    payload = b"".join(canonical(trace) + b"\n" for trace in trace_list)
    return TargetedReport(len(trace_list), dict(counts), hashlib.sha256(payload).hexdigest())


def validate_targeted_development(
    cases: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> TargetedReport:
    case_list = list(cases)
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for case in case_list:
        case_id = case.get("caseId", "<missing>")
        if case_id in seen:
            raise ValidationError(f"{case_id}: duplicate targeted development caseId")
        seen.add(case_id)
        _validate_development_case(case, contract, denylisted_identities, denylisted_sha256)
        counts[case["axis"]] += 1

    expected = {behavior: DEVELOPMENT_PER_BEHAVIOR for behavior in BEHAVIORS}
    if len(case_list) != len(BEHAVIORS) * DEVELOPMENT_PER_BEHAVIOR or dict(counts) != expected:
        raise ValidationError("targeted development must contain exactly 10 cases per six behaviors")
    payload = b"".join(canonical(case) + b"\n" for case in case_list)
    return TargetedReport(len(case_list), dict(counts), hashlib.sha256(payload).hexdigest())


def validate_disjoint_splits(
    *,
    prior_training: Iterable[dict[str, Any]],
    prior_development: Iterable[dict[str, Any]],
    targeted_training: Iterable[dict[str, Any]],
    targeted_development: Iterable[dict[str, Any]],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> DisjointnessReport:
    split_records = {
        "planner-smoke-v1": list(prior_training),
        "planner-development-v1": list(prior_development),
        "planner-behavior-v2": list(targeted_training),
        "planner-behavior-development-v2": list(targeted_development),
    }
    summaries: dict[str, dict[str, set[Any]]] = {}
    for name, records in split_records.items():
        record_ids: set[str] = set()
        content_ids: set[tuple[str, int]] = set()
        digests: set[str] = set()
        for record in records:
            record_id = record.get("traceId", record.get("caseId"))
            if not isinstance(record_id, str) or not record_id:
                raise ValidationError(f"{name}: record identity is missing")
            if record_id in record_ids:
                raise ValidationError(f"{name}: duplicate record identity {record_id}")
            record_ids.add(record_id)
            content_ids.update(_content_identities(record))
            digest = _normalized_record_digest(record)
            if digest in digests:
                raise ValidationError(f"{name}: duplicate normalized content digest {digest}")
            digests.add(digest)
        leaked_identities = record_ids & denylisted_identities
        leaked_digests = digests & denylisted_sha256
        if leaked_identities or leaked_digests:
            raise ValidationError(f"{name}: certification identity or digest leaked")
        summaries[name] = {
            "recordIds": record_ids,
            "contentIds": content_ids,
            "normalizedDigests": digests,
        }

    names = list(summaries)
    pair_count = 0
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            pair_count += 1
            for field, label in (
                ("recordIds", "record identity"),
                ("contentIds", "content identity"),
                ("normalizedDigests", "normalized digest"),
            ):
                overlap = summaries[left][field] & summaries[right][field]
                if overlap:
                    raise ValidationError(f"{left} and {right}: {label} overlap")

    return DisjointnessReport(
        splits={
            name: {
                "records": len(values["recordIds"]),
                "contentIdentities": len(values["contentIds"]),
                "normalizedDigests": len(values["normalizedDigests"]),
            }
            for name, values in summaries.items()
        },
        pairCount=pair_count,
    )


def _validate_training_behavior(trace_id: str, behavior: str, messages: list[dict[str, Any]]) -> None:
    intent = messages[1]["content"]
    turns = messages[2:]
    calls = [message for message in turns if message.get("role") == "assistant" and "toolCalls" in message]
    results = [message for message in turns if message.get("role") == "tool"]
    if any(len(message["toolCalls"]) != 1 for message in calls):
        raise ValidationError(f"{trace_id}: assistant turn must contain exactly one tool operation")
    if len(turns) != 2 * len(calls) + 1 or any(
        turns[index].get("role") != "assistant"
        or "toolCalls" not in turns[index]
        or turns[index + 1].get("role") != "tool"
        for index in range(0, len(turns) - 1, 2)
    ):
        raise ValidationError(f"{trace_id}: tool operations must alternate one call and one result")
    final = _load_final(trace_id, messages[-1])

    if behavior == "canonical-argument-preservation":
        match = CANONICAL_INTENT.fullmatch(intent)
        if not match or len(calls) != 1 or len(results) != 1:
            raise ValidationError(f"{trace_id}: canonical argument trace shape drifted")
        values = match.groupdict()
        expected = {
            "genres": [values["genre"]],
            "era": values["era"],
            "media_type": values["media_type"],
            "original_language": values["language"],
            "origin_country": values["country"],
            "runtime_min": int(values["runtime_min"]),
            "runtime_max": int(values["runtime_max"]),
            "vote_average_min": float(values["rating"]),
            "vote_count_min": int(values["votes"]),
        }
        if calls[0]["toolCalls"][0]["arguments"] != expected:
            raise ValidationError(f"{trace_id}: canonical tool arguments were narrowed or altered")
        if not final["picks"]:
            raise ValidationError(f"{trace_id}: canonical argument trace refused its fixture result")
    elif behavior == "one-tool-operation-per-turn":
        if len(calls) != 2 or len(results) != 2:
            raise ValidationError(f"{trace_id}: retry trace must use two separate tool turns")
        first = calls[0]["toolCalls"][0]["arguments"]
        second = calls[1]["toolCalls"][0]["arguments"]
        if set(first) != {"keywords"} or set(second) != {"query"} or first["keywords"] != [second["query"]]:
            raise ValidationError(f"{trace_id}: retry selectors or arguments drifted")
        if results[0]["content"].get("candidates") or not results[1]["content"].get("candidates"):
            raise ValidationError(f"{trace_id}: retry result order drifted")
        if not final["picks"]:
            raise ValidationError(f"{trace_id}: successful retry did not produce a grounded pick")
    elif behavior == "complete-proposal-json":
        if len(calls) != 1 or final["policy"] != {} or not final["picks"]:
            raise ValidationError(f"{trace_id}: complete proposal must preserve an empty policy object")
    elif behavior == "structured-json-abstention":
        if len(calls) != 1 or final["picks"] != [] or final["policy"] != {}:
            raise ValidationError(f"{trace_id}: abstention must be structured proposal JSON")
    elif behavior == "synthetic-tool-error-recovery":
        if len(calls) != 2 or len(results) != 2:
            raise ValidationError(f"{trace_id}: tool-error recovery must use two ordered calls")
        if "error" not in results[0]["content"] or results[1]["content"].get("error"):
            raise ValidationError(f"{trace_id}: tool-error recovery order drifted")
        first_args = calls[0]["toolCalls"][0]["arguments"]
        second_args = calls[1]["toolCalls"][0]["arguments"]
        if set(first_args) != {"query"} or set(second_args) != {"genres"} or not final["picks"]:
            raise ValidationError(f"{trace_id}: synthetic fixture was refused or recovered incorrectly")
    elif behavior == "ambiguous-intent-mapping":
        if len(calls) != 1 or len(results) != 1:
            raise ValidationError(f"{trace_id}: ambiguous intent trace shape drifted")
        candidates = results[0]["content"].get("candidates", [])
        if not candidates or not final["picks"]:
            raise ValidationError(f"{trace_id}: ambiguous intent mapping refused its fixture result")
        genre = candidates[0]["genres"][0]
        if calls[0]["toolCalls"][0]["arguments"] != {"genres": [genre]}:
            raise ValidationError(f"{trace_id}: ambiguous intent mapped to the wrong tool arguments")
        if final["policy"] != {"genres": {"include": [genre]}}:
            raise ValidationError(f"{trace_id}: ambiguous intent policy mapping drifted")
    else:  # pragma: no cover - guarded by the public validator
        raise ValidationError(f"{trace_id}: unknown targeted behavior")


def _validate_development_case(
    case: dict[str, Any],
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> None:
    case_id = case.get("caseId", "<missing>")
    if set(case) != CASE_KEYS or case.get("schemaVersion") != 1:
        raise ValidationError(f"{case_id}: fields differ from targeted development schema v1")
    if not re.fullmatch(r"planner-behavior-development-v2-[a-z0-9-]+-\d{2}", case_id):
        raise ValidationError(f"{case_id}: invalid targeted development identity")
    behavior = case.get("axis")
    if case.get("split") != "development-eval" or behavior not in BEHAVIORS:
        raise ValidationError(f"{case_id}: invalid targeted development split or behavior")
    expected_contract = {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": DEVELOPMENT_FIXTURE_ID,
    }
    if set(case["contract"]) != CONTRACT_KEYS or case["contract"] != expected_contract:
        raise ValidationError(f"{case_id}: targeted development contract drifted")
    if set(case["provenance"]) != PROVENANCE_KEYS or case["provenance"] != {
        "source": "synthetic",
        "generator": DEVELOPMENT_GENERATOR_ID,
        "author": "codex:fixture",
    }:
        raise ValidationError(f"{case_id}: invalid targeted development provenance")
    _validate_synthetic_record(case_id, case)
    serialized = json.dumps(case, sort_keys=True, ensure_ascii=False)
    for pattern in SECRET_PATTERNS + PRIVATE_PATH_PATTERNS:
        if pattern.search(serialized):
            raise ValidationError(f"{case_id}: possible secret or household path")
    for identity in denylisted_identities:
        if identity in serialized:
            raise ValidationError(f"{case_id}: holdout identity {identity!r} leaked")
    for digest in denylisted_sha256:
        if digest in serialized:
            raise ValidationError(f"{case_id}: holdout digest leaked")
    if case["repairPrompt"] is not None:
        raise ValidationError(f"{case_id}: targeted development cannot contain repair answers")
    _validate_script_and_expectation(case_id, behavior, case["intent"], case["script"], case["expectation"])


def _validate_script_and_expectation(
    case_id: str,
    behavior: str,
    intent: str,
    script: Any,
    expectation: Any,
) -> None:
    if not isinstance(script, list) or not 1 <= len(script) <= 2:
        raise ValidationError(f"{case_id}: invalid targeted development script")
    surfaced: set[tuple[str, int]] = set()
    for step in script:
        if not isinstance(step, dict) or set(step) != {"arguments", "result"}:
            raise ValidationError(f"{case_id}: malformed scripted tool operation")
        arguments, result = step["arguments"], step["result"]
        if not isinstance(arguments, dict) or not arguments or set(arguments) - SEARCH_ARGUMENTS:
            raise ValidationError(f"{case_id}: malformed scripted tool arguments")
        selectors = {"query", "genres", "keywords"} & set(arguments)
        if len(selectors) != 1 or ("query" in arguments and len(arguments) != 1):
            raise ValidationError(f"{case_id}: scripted selector is ambiguous")
        if not isinstance(result, dict) or set(result) - {"candidates", "error"}:
            raise ValidationError(f"{case_id}: malformed scripted tool result")
        candidates = result.get("candidates", [])
        if not isinstance(candidates, list):
            raise ValidationError(f"{case_id}: scripted candidates must be an array")
        for candidate in candidates:
            surfaced.add(_candidate_identity(case_id, candidate))
    if not isinstance(expectation, dict) or set(expectation) != EXPECTATION_KEYS:
        raise ValidationError(f"{case_id}: invalid targeted expectation")
    selected = {_expected_identity(case_id, item) for item in expectation["selectedIds"]}
    forbidden = {_expected_identity(case_id, item) for item in expectation["forbiddenIds"]}
    if not selected <= surfaced or not forbidden <= surfaced:
        raise ValidationError(f"{case_id}: expectation references an unscripted id")
    if selected & forbidden:
        raise ValidationError(f"{case_id}: selected and forbidden ids overlap")
    if expectation["abstain"] is not (not selected):
        raise ValidationError(f"{case_id}: abstention differs from selected ids")
    if expectation["maxToolCalls"] != len(script):
        raise ValidationError(f"{case_id}: tool-call budget differs from script")
    if not isinstance(expectation["expectedPolicy"], dict):
        raise ValidationError(f"{case_id}: expected policy must be an object")

    if behavior == "canonical-argument-preservation":
        match = CANONICAL_INTENT.fullmatch(intent)
        if not match or len(script) != 1:
            raise ValidationError(f"{case_id}: canonical development case drifted")
        values = match.groupdict()
        expected_args = {
            "genres": [values["genre"]],
            "era": values["era"],
            "media_type": values["media_type"],
            "original_language": values["language"],
            "origin_country": values["country"],
            "runtime_min": int(values["runtime_min"]),
            "runtime_max": int(values["runtime_max"]),
            "vote_average_min": float(values["rating"]),
            "vote_count_min": int(values["votes"]),
        }
        if script[0]["arguments"] != expected_args:
            raise ValidationError(f"{case_id}: canonical scripted arguments drifted")
    elif behavior == "one-tool-operation-per-turn":
        if len(script) != 2 or script[0]["result"].get("candidates") or not script[1]["result"].get("candidates"):
            raise ValidationError(f"{case_id}: retry script order drifted")
        first, second = script[0]["arguments"], script[1]["arguments"]
        if set(first) != {"keywords"} or set(second) != {"query"} or first["keywords"] != [second["query"]]:
            raise ValidationError(f"{case_id}: retry selectors or arguments drifted")
    elif behavior == "complete-proposal-json":
        if len(script) != 1 or expectation["expectedPolicy"] != {} or expectation["abstain"]:
            raise ValidationError(f"{case_id}: complete proposal expectation drifted")
    elif behavior == "structured-json-abstention":
        if len(script) != 1 or not expectation["abstain"] or not forbidden or expectation["expectedPolicy"] != {}:
            raise ValidationError(f"{case_id}: structured abstention expectation drifted")
    elif behavior == "synthetic-tool-error-recovery":
        if len(script) != 2 or "error" not in script[0]["result"] or script[1]["result"].get("error") or not selected:
            raise ValidationError(f"{case_id}: synthetic fixture recovery expectation drifted")
        if set(script[0]["arguments"]) != {"query"} or set(script[1]["arguments"]) != {"genres"}:
            raise ValidationError(f"{case_id}: synthetic fixture recovery order drifted")
    elif behavior == "ambiguous-intent-mapping":
        candidates = script[0]["result"].get("candidates", [])
        if len(script) != 1 or not candidates or not selected:
            raise ValidationError(f"{case_id}: ambiguous development mapping refused its fixture result")
        genre = candidates[0]["genres"][0]
        if script[0]["arguments"] != {"genres": [genre]} or expectation["expectedPolicy"] != {"genres": {"include": [genre]}}:
            raise ValidationError(f"{case_id}: ambiguous development mapping drifted")


def _load_final(trace_id: str, message: dict[str, Any]) -> dict[str, Any]:
    if message.get("role") != "assistant" or set(message) != {"role", "content"}:
        raise ValidationError(f"{trace_id}: missing final assistant JSON")
    try:
        final = json.loads(message["content"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{trace_id}: final assistant content is prose or malformed JSON") from exc
    if not isinstance(final, dict) or set(final) != FINAL_KEYS:
        raise ValidationError(f"{trace_id}: final proposal required fields differ")
    if not isinstance(final["channelName"], str) or not final["channelName"].strip():
        raise ValidationError(f"{trace_id}: final channelName is empty")
    if not isinstance(final["rationale"], str) or not final["rationale"].strip():
        raise ValidationError(f"{trace_id}: final rationale is empty")
    if not isinstance(final["policy"], dict):
        raise ValidationError(f"{trace_id}: final policy must be an object")
    return final


def _validate_synthetic_record(record_id: str, record: dict[str, Any]) -> None:
    intent = record["messages"][1]["content"] if "messages" in record else record["intent"]
    if not isinstance(intent, str) or "synthetic" not in intent.lower():
        raise ValidationError(f"{record_id}: household-like intent is not an explicit synthetic fixture")
    serialized = json.dumps(record, sort_keys=True, ensure_ascii=False).lower()
    if "@" in intent or "my library" in serialized or "watch history" in serialized:
        raise ValidationError(f"{record_id}: possible household-like data")


def _candidate_identity(record_id: str, candidate: Any) -> tuple[str, int]:
    if not isinstance(candidate, dict):
        raise ValidationError(f"{record_id}: candidate must be an object")
    media_type, tmdb_id = candidate.get("mediaType"), candidate.get("tmdbId")
    if media_type not in ALLOWED_MEDIA_TYPES or not isinstance(tmdb_id, int) or tmdb_id <= 0:
        raise ValidationError(f"{record_id}: invalid candidate identity")
    if not isinstance(candidate.get("name"), str) or not candidate["name"]:
        raise ValidationError(f"{record_id}: candidate name is empty")
    if not isinstance(candidate.get("genres"), list) or not candidate["genres"]:
        raise ValidationError(f"{record_id}: candidate genres are empty")
    if "synthetic" not in str(candidate.get("overview", "")).lower():
        raise ValidationError(f"{record_id}: candidate is not marked as a synthetic fixture")
    return media_type, tmdb_id


def _expected_identity(record_id: str, value: Any) -> tuple[str, int]:
    if not isinstance(value, dict) or set(value) != {"mediaType", "tmdbId"}:
        raise ValidationError(f"{record_id}: invalid expected content identity")
    media_type, tmdb_id = value["mediaType"], value["tmdbId"]
    if media_type not in ALLOWED_MEDIA_TYPES or not isinstance(tmdb_id, int) or tmdb_id <= 0:
        raise ValidationError(f"{record_id}: invalid expected content identity")
    return media_type, tmdb_id


def _content_identities(record: dict[str, Any]) -> set[tuple[str, int]]:
    if "messages" in record:
        candidates = (
            candidate
            for message in record["messages"]
            if message.get("role") == "tool"
            for candidate in message["content"].get("candidates", [])
        )
    else:
        candidates = (
            candidate
            for step in record["script"]
            for candidate in step["result"].get("candidates", [])
        )
    return {(candidate["mediaType"], candidate["tmdbId"]) for candidate in candidates}


def _normalized_record_digest(record: dict[str, Any]) -> str:
    if "messages" in record:
        intent = record["messages"][1]["content"]
        turns = record["messages"][2:-1]
        results = {
            message["toolCallId"]: message["content"]
            for message in turns
            if message.get("role") == "tool" and isinstance(message.get("toolCallId"), str)
        }
        steps = [
            {
                "arguments": call["arguments"],
                "result": results.get(call["id"], {"unresolved": True}),
            }
            for message in turns
            if message.get("role") == "assistant" and isinstance(message.get("toolCalls"), list)
            for call in message["toolCalls"]
        ]
    else:
        intent = record["intent"]
        steps = record["script"]
    normalized = {
        "intent": " ".join(intent.lower().split()),
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
