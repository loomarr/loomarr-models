from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .validator import (
    ALLOWED_MEDIA_TYPES,
    PRIVATE_PATH_PATTERNS,
    SEARCH_ARGUMENTS,
    SECRET_PATTERNS,
    ValidationError,
)


FAMILIES = (
    "title-search",
    "genre-discovery",
    "keyword-discovery",
    "must-include",
    "must-exclude",
    "ambiguous-intent",
    "conflicting-intent",
    "empty-results",
    "tool-error-recovery",
    "malformed-final-repair",
)
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
CONTRACT_KEYS = {
    "promptVersion",
    "systemPromptSha256",
    "toolSchemaVersion",
    "toolSchemaSha256",
    "messageTemplateVersion",
    "fixtureId",
}
EXPECTATION_KEYS = {
    "selectedIds",
    "forbiddenIds",
    "expectedPolicy",
    "abstain",
    "maxToolCalls",
}
PROVENANCE_KEYS = {"source", "generator", "author"}


@dataclass(frozen=True)
class DevelopmentCorpusReport:
    cases: int
    familyCounts: dict[str, int]
    sha256: str


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValidationError(f"{path}:{line_number}: case must be an object")
        cases.append(value)
    if not cases:
        raise ValidationError(f"{path}: corpus is empty")
    return cases


def validate_development_corpus(
    cases: Iterable[dict[str, Any]],
    *,
    contract: dict[str, Any],
    training_traces: Iterable[dict[str, Any]],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> DevelopmentCorpusReport:
    case_list = list(cases)
    training_list = list(training_traces)
    seen_ids: set[str] = set()
    family_counts: Counter[str] = Counter()
    eval_intents: set[str] = set()
    eval_candidate_ids: set[tuple[str, int]] = set()

    for case in case_list:
        case_id = case.get("caseId", "<missing>")
        if case_id in seen_ids:
            raise ValidationError(f"{case_id}: duplicate caseId")
        seen_ids.add(case_id)
        _validate_case(case, contract, denylisted_identities, denylisted_sha256)
        family_counts[case["axis"]] += 1
        intent_fingerprint = hashlib.sha256(
            " ".join(case["intent"].lower().split()).encode()
        ).hexdigest()
        if intent_fingerprint in eval_intents:
            raise ValidationError(f"{case_id}: duplicate normalized intent")
        eval_intents.add(intent_fingerprint)
        for step in case["script"]:
            for candidate in step["result"].get("candidates", []):
                key = (candidate["mediaType"], candidate["tmdbId"])
                if key in eval_candidate_ids:
                    raise ValidationError(f"{case_id}: duplicate development candidate {key!r}")
                eval_candidate_ids.add(key)

    expected_counts = {family: 5 for family in FAMILIES}
    if len(case_list) != 50 or dict(family_counts) != expected_counts:
        raise ValidationError("development corpus must contain exactly five cases per ten axes")

    training_ids = {trace["traceId"] for trace in training_list}
    if seen_ids & training_ids:
        raise ValidationError("development case identity overlaps training")
    training_intents = {
        hashlib.sha256(" ".join(trace["messages"][1]["content"].lower().split()).encode()).hexdigest()
        for trace in training_list
    }
    if eval_intents & training_intents:
        raise ValidationError("development intent overlaps training")
    training_candidate_ids = {
        (candidate["mediaType"], candidate["tmdbId"])
        for trace in training_list
        for message in trace["messages"]
        if message.get("role") == "tool"
        for candidate in message["content"].get("candidates", [])
    }
    if eval_candidate_ids & training_candidate_ids:
        raise ValidationError("development candidate identity overlaps training")

    corpus_bytes = b"".join(canonical(case) + b"\n" for case in case_list)
    return DevelopmentCorpusReport(
        cases=len(case_list),
        familyCounts=dict(family_counts),
        sha256=hashlib.sha256(corpus_bytes).hexdigest(),
    )


def _validate_case(
    case: dict[str, Any],
    contract: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
) -> None:
    case_id = case.get("caseId", "<missing>")
    if set(case) != CASE_KEYS or case.get("schemaVersion") != 1:
        raise ValidationError(f"{case_id}: fields differ from development case schema v1")
    if not re.fullmatch(r"planner-development-[a-z0-9-]+-[0-9]{2}", case_id):
        raise ValidationError(f"{case_id}: invalid caseId")
    if case["split"] != "development-eval" or case["axis"] not in FAMILIES:
        raise ValidationError(f"{case_id}: invalid development split or axis")
    if not isinstance(case["intent"], str) or not case["intent"].strip():
        raise ValidationError(f"{case_id}: intent is empty")

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

    expected_contract = {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": "planner-development-catalog-v1",
    }
    if set(case["contract"]) != CONTRACT_KEYS or case["contract"] != expected_contract:
        raise ValidationError(f"{case_id}: development contract identity drifted")
    if set(case["provenance"]) != PROVENANCE_KEYS or case["provenance"] != {
        "source": "synthetic",
        "generator": "planner-development-eval-generator-v1",
        "author": "codex:fixture",
    }:
        raise ValidationError(f"{case_id}: invalid development provenance")
    _validate_script(case_id, case["script"])
    _validate_expectation(case_id, case["expectation"], case["script"])

    repair = case["repairPrompt"]
    if case["axis"] == "malformed-final-repair":
        if repair != "Return only valid proposal JSON using the already surfaced id.":
            raise ValidationError(f"{case_id}: repair prompt drifted")
    elif repair is not None:
        raise ValidationError(f"{case_id}: unexpected repair prompt")


def _validate_script(case_id: str, script: Any) -> None:
    if not isinstance(script, list) or not 1 <= len(script) <= 2:
        raise ValidationError(f"{case_id}: script must contain one or two tool steps")
    candidate_ids: set[tuple[str, int]] = set()
    for step in script:
        if not isinstance(step, dict) or set(step) != {"arguments", "result"}:
            raise ValidationError(f"{case_id}: invalid scripted tool step")
        arguments = step["arguments"]
        if not isinstance(arguments, dict) or not arguments or set(arguments) - SEARCH_ARGUMENTS:
            raise ValidationError(f"{case_id}: invalid scripted arguments")
        selectors = {"query", "genres", "keywords"} & set(arguments)
        if len(selectors) != 1 or ("query" in arguments and len(arguments) != 1):
            raise ValidationError(f"{case_id}: scripted search selector is ambiguous")
        result = step["result"]
        if not isinstance(result, dict) or set(result) - {"candidates", "error"}:
            raise ValidationError(f"{case_id}: invalid scripted result")
        candidates = result.get("candidates", [])
        if not isinstance(candidates, list):
            raise ValidationError(f"{case_id}: scripted candidates must be an array")
        for candidate in candidates:
            key = _candidate_key(case_id, candidate)
            if key in candidate_ids:
                raise ValidationError(f"{case_id}: duplicate scripted candidate {key!r}")
            candidate_ids.add(key)


def _validate_expectation(case_id: str, expectation: Any, script: list[dict[str, Any]]) -> None:
    if not isinstance(expectation, dict) or set(expectation) != EXPECTATION_KEYS:
        raise ValidationError(f"{case_id}: invalid expectation")
    selected = expectation["selectedIds"]
    forbidden = expectation["forbiddenIds"]
    if not isinstance(selected, list) or not isinstance(forbidden, list):
        raise ValidationError(f"{case_id}: expected ids must be arrays")
    selected_keys = {_identity_key(case_id, item) for item in selected}
    forbidden_keys = {_identity_key(case_id, item) for item in forbidden}
    if len(selected_keys) != len(selected) or len(forbidden_keys) != len(forbidden):
        raise ValidationError(f"{case_id}: duplicate expected identity")
    if selected_keys & forbidden_keys:
        raise ValidationError(f"{case_id}: selected and forbidden ids overlap")
    surfaced = {
        _candidate_key(case_id, candidate)
        for step in script
        for candidate in step["result"].get("candidates", [])
    }
    if not selected_keys <= surfaced or not forbidden_keys <= surfaced:
        raise ValidationError(f"{case_id}: expectation references an unscripted id")
    if expectation["abstain"] is not (len(selected) == 0):
        raise ValidationError(f"{case_id}: abstention differs from selected ids")
    if expectation["maxToolCalls"] != len(script):
        raise ValidationError(f"{case_id}: tool-call budget differs from script")
    if not isinstance(expectation["expectedPolicy"], dict):
        raise ValidationError(f"{case_id}: expected policy must be an object")


def _candidate_key(case_id: str, candidate: Any) -> tuple[str, int]:
    if not isinstance(candidate, dict):
        raise ValidationError(f"{case_id}: candidate must be an object")
    required = {"mediaType", "tmdbId", "name", "year", "inLibrary", "genres", "overview"}
    if set(candidate) != required:
        raise ValidationError(f"{case_id}: candidate fields differ from fixture schema v1")
    media_type, tmdb_id = candidate["mediaType"], candidate["tmdbId"]
    if media_type not in ALLOWED_MEDIA_TYPES or not isinstance(tmdb_id, int) or tmdb_id <= 0:
        raise ValidationError(f"{case_id}: invalid candidate identity")
    key = media_type, tmdb_id
    if not isinstance(candidate["name"], str) or not candidate["name"]:
        raise ValidationError(f"{case_id}: candidate name is empty")
    if not isinstance(candidate["genres"], list) or not candidate["genres"]:
        raise ValidationError(f"{case_id}: candidate genres are empty")
    if not isinstance(candidate["overview"], str) or not candidate["overview"]:
        raise ValidationError(f"{case_id}: candidate overview is empty")
    if not isinstance(candidate["year"], int) or not isinstance(candidate["inLibrary"], bool):
        raise ValidationError(f"{case_id}: candidate metadata is invalid")
    return key


def _identity_key(case_id: str, identity: Any) -> tuple[str, int]:
    if not isinstance(identity, dict) or not {"mediaType", "tmdbId"} <= set(identity):
        raise ValidationError(f"{case_id}: invalid content identity")
    if set(identity) - {"mediaType", "tmdbId"}:
        raise ValidationError(f"{case_id}: expected identity has extra fields")
    media_type, tmdb_id = identity["mediaType"], identity["tmdbId"]
    if media_type not in ALLOWED_MEDIA_TYPES or not isinstance(tmdb_id, int) or tmdb_id <= 0:
        raise ValidationError(f"{case_id}: invalid content identity")
    return media_type, tmdb_id
