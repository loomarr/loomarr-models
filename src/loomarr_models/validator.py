from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ALLOWED_SPLITS = {"smoke", "train", "development"}
ALLOWED_MEDIA_TYPES = {"movie", "series"}
SEARCH_ARGUMENTS = {
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
}
DISCOVERY_ARGUMENTS = SEARCH_ARGUMENTS - {"query"}
TRACE_KEYS = {
    "schemaVersion",
    "traceId",
    "split",
    "axes",
    "contract",
    "tools",
    "messages",
    "review",
    "provenance",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bop://"),
)
PRIVATE_PATH_PATTERNS = (
    re.compile(r"/(?:Users|home)/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\"),
    re.compile(r"(?:^|[/\\])\.env(?:$|[/\\\s])"),
)


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationReport:
    traces: int
    approved: int
    pending: int
    sha256: str


def load_denylist(path: Path) -> tuple[set[str], set[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data["identities"]), set(data["sha256"])


def load_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schemaVersion",
        "contractId",
        "sourceRepository",
        "sourceRevision",
        "promptVersion",
        "systemPromptSha256",
        "systemPrompt",
        "toolSchemaVersion",
        "toolSchemaSha256",
        "tools",
        "messageTemplateVersion",
    }
    if not isinstance(data, dict) or set(data) != required or data["schemaVersion"] != 1:
        raise ValidationError(f"{path}: invalid planner contract bundle")
    if hashlib.sha256(data["systemPrompt"].encode()).hexdigest() != data["systemPromptSha256"]:
        raise ValidationError(f"{path}: system prompt digest mismatch")
    if hashlib.sha256(_go_tool_schema_bytes(data["tools"])).hexdigest() != data["toolSchemaSha256"]:
        raise ValidationError(f"{path}: tool schema digest mismatch")
    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValidationError(f"{path}:{line_number}: trace must be an object")
        traces.append(value)
    if not traces:
        raise ValidationError(f"{path}: corpus is empty")
    return traces


def validate_corpus(
    traces: Iterable[dict[str, Any]],
    *,
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
    contract_bundle: dict[str, Any],
    allow_pending: bool = False,
) -> ValidationReport:
    trace_list = list(traces)
    seen_ids: set[str] = set()
    seen_fingerprints: dict[str, str] = {}
    approved = 0
    pending = 0

    for trace in trace_list:
        trace_id = trace.get("traceId", "<missing>")
        if trace_id in seen_ids:
            raise ValidationError(f"{trace_id}: duplicate traceId")
        seen_ids.add(trace_id)
        _validate_trace(trace, denylisted_identities, denylisted_sha256, contract_bundle, allow_pending)

        status = trace["review"]["status"]
        approved += status == "approved"
        pending += status == "pending"

        fingerprint_source = copy.deepcopy(trace)
        fingerprint_source.pop("traceId", None)
        fingerprint_source.pop("review", None)
        fingerprint_source["split"] = "<split>"
        fingerprint = hashlib.sha256(_canonical(fingerprint_source)).hexdigest()
        if fingerprint in seen_fingerprints:
            raise ValidationError(
                f"{trace_id}: duplicate content also used by {seen_fingerprints[fingerprint]}"
            )
        seen_fingerprints[fingerprint] = trace_id

    corpus_bytes = b"".join(_canonical(trace) + b"\n" for trace in trace_list)
    return ValidationReport(
        traces=len(trace_list),
        approved=approved,
        pending=pending,
        sha256=hashlib.sha256(corpus_bytes).hexdigest(),
    )


def _validate_trace(
    trace: dict[str, Any],
    denylisted_identities: set[str],
    denylisted_sha256: set[str],
    contract_bundle: dict[str, Any],
    allow_pending: bool,
) -> None:
    trace_id = trace.get("traceId", "<missing>")
    if set(trace) != TRACE_KEYS:
        raise ValidationError(f"{trace_id}: top-level fields differ from schema v1")
    if trace["schemaVersion"] != 1:
        raise ValidationError(f"{trace_id}: unsupported schemaVersion")
    if not re.fullmatch(r"planner-[a-z0-9-]+", trace_id):
        raise ValidationError(f"{trace_id}: invalid traceId")
    if trace["split"] not in ALLOWED_SPLITS:
        raise ValidationError(f"{trace_id}: forbidden split {trace['split']!r}")
    if not isinstance(trace["axes"], list) or not trace["axes"]:
        raise ValidationError(f"{trace_id}: axes must be non-empty")
    if len(set(trace["axes"])) != len(trace["axes"]):
        raise ValidationError(f"{trace_id}: duplicate axis")

    serialized = json.dumps(trace, sort_keys=True, ensure_ascii=False)
    for pattern in SECRET_PATTERNS + PRIVATE_PATH_PATTERNS:
        if pattern.search(serialized):
            raise ValidationError(f"{trace_id}: possible secret or household path")
    for identity in denylisted_identities:
        if identity in serialized:
            raise ValidationError(f"{trace_id}: holdout identity {identity!r} leaked")
    for digest in denylisted_sha256:
        if digest in serialized:
            raise ValidationError(f"{trace_id}: holdout digest leaked")

    _validate_contract(trace_id, trace["contract"], contract_bundle)
    _validate_tools(trace_id, trace["tools"], contract_bundle)
    _validate_review(trace_id, trace["review"], allow_pending)
    _validate_provenance(trace_id, trace["provenance"])
    _validate_messages(trace_id, trace["messages"], contract_bundle)


def _validate_contract(trace_id: str, contract: Any, bundle: dict[str, Any]) -> None:
    expected = {
        "promptVersion",
        "systemPromptSha256",
        "toolSchemaVersion",
        "toolSchemaSha256",
        "messageTemplateVersion",
        "fixtureId",
    }
    if not isinstance(contract, dict) or set(contract) != expected:
        raise ValidationError(f"{trace_id}: invalid contract identity")
    if not all(isinstance(contract[key], str) and contract[key] for key in expected):
        raise ValidationError(f"{trace_id}: empty contract identity")
    for key in expected - {"fixtureId"}:
        if contract[key] != bundle[key]:
            raise ValidationError(f"{trace_id}: contract {key} differs from the frozen bundle")


def _validate_tools(trace_id: str, tools: Any, bundle: dict[str, Any]) -> None:
    if tools != bundle["tools"]:
        raise ValidationError(f"{trace_id}: tool declaration differs from the frozen bundle")


def _validate_review(trace_id: str, review: Any, allow_pending: bool) -> None:
    expected = {"status", "reviewer", "reviewedAt", "notes"}
    if not isinstance(review, dict) or set(review) != expected:
        raise ValidationError(f"{trace_id}: invalid review record")
    status = review["status"]
    if status not in {"pending", "approved", "rejected"}:
        raise ValidationError(f"{trace_id}: invalid review status")
    if status != "approved" and not (allow_pending and status == "pending"):
        raise ValidationError(f"{trace_id}: trace is not approved")
    if status == "approved" and (not review["reviewer"] or not review["reviewedAt"]):
        raise ValidationError(f"{trace_id}: approved trace lacks reviewer evidence")
    if status == "pending" and (review["reviewer"] or review["reviewedAt"]):
        raise ValidationError(f"{trace_id}: pending trace carries false review evidence")


def _validate_provenance(trace_id: str, provenance: Any) -> None:
    expected = {"source", "generator", "author"}
    if not isinstance(provenance, dict) or set(provenance) != expected:
        raise ValidationError(f"{trace_id}: invalid provenance")
    if provenance["source"] != "synthetic":
        raise ValidationError(f"{trace_id}: only synthetic source is allowed")
    if not provenance["generator"] or not provenance["author"]:
        raise ValidationError(f"{trace_id}: incomplete provenance")


def _validate_messages(trace_id: str, messages: Any, bundle: dict[str, Any]) -> None:
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValidationError(f"{trace_id}: incomplete conversation")
    if messages[0] != {"role": "system", "content": bundle["systemPrompt"]}:
        raise ValidationError(f"{trace_id}: first message differs from the frozen system prompt")
    if messages[1].get("role") != "user" or not messages[1].get("content"):
        raise ValidationError(f"{trace_id}: second message must be the synthetic intent")

    pending_calls: dict[str, str] = {}
    surfaced: dict[tuple[str, int], str] = {}
    final: dict[str, Any] | None = None

    for index, message in enumerate(messages[2:], 2):
        if not isinstance(message, dict):
            raise ValidationError(f"{trace_id}: message {index} is not an object")
        role = message.get("role")
        if role == "assistant" and "toolCalls" in message:
            if set(message) != {"role", "toolCalls"} or not message["toolCalls"]:
                raise ValidationError(f"{trace_id}: malformed assistant tool-call turn")
            for call in message["toolCalls"]:
                _validate_tool_call(trace_id, call, pending_calls)
        elif role == "tool":
            _validate_tool_result(trace_id, message, pending_calls, surfaced)
        elif role == "assistant" and "content" in message:
            if index != len(messages) - 1:
                # A malformed answer may precede an explicit repair user turn.
                if not isinstance(message["content"], str):
                    raise ValidationError(f"{trace_id}: assistant content must be text")
                continue
            try:
                final = json.loads(message["content"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValidationError(f"{trace_id}: final assistant content is not JSON") from exc
        elif role == "user" and isinstance(message.get("content"), str):
            continue
        else:
            raise ValidationError(f"{trace_id}: invalid message {index}")

    if pending_calls:
        raise ValidationError(f"{trace_id}: unresolved tool calls")
    if final is None:
        raise ValidationError(f"{trace_id}: missing final assistant JSON")
    _validate_final(trace_id, final, surfaced)


def _validate_tool_call(trace_id: str, call: Any, pending_calls: dict[str, str]) -> None:
    if not isinstance(call, dict) or set(call) != {"id", "name", "arguments"}:
        raise ValidationError(f"{trace_id}: malformed tool call")
    if call["name"] != "catalog_search" or not isinstance(call["id"], str) or not call["id"]:
        raise ValidationError(f"{trace_id}: invalid catalog_search call")
    if call["id"] in pending_calls:
        raise ValidationError(f"{trace_id}: duplicate tool call id")
    args = call["arguments"]
    if not isinstance(args, dict) or not args or set(args) - SEARCH_ARGUMENTS:
        raise ValidationError(f"{trace_id}: invalid catalog_search arguments")
    if "query" in args and set(args) & DISCOVERY_ARGUMENTS:
        raise ValidationError(f"{trace_id}: title query mixed with discovery filters")
    if not ({"query", "genres", "keywords"} & set(args)):
        raise ValidationError(f"{trace_id}: catalog_search has no search selector")
    if "query" in args and (not isinstance(args["query"], str) or not args["query"].strip()):
        raise ValidationError(f"{trace_id}: empty title query")
    for key in ("genres", "keywords"):
        if key in args and (
            not isinstance(args[key], list)
            or not args[key]
            or not all(isinstance(value, str) and value for value in args[key])
        ):
            raise ValidationError(f"{trace_id}: invalid {key}")
    if "media_type" in args and args["media_type"] not in ALLOWED_MEDIA_TYPES:
        raise ValidationError(f"{trace_id}: invalid media_type")
    pending_calls[call["id"]] = call["name"]


def _validate_tool_result(
    trace_id: str,
    message: dict[str, Any],
    pending_calls: dict[str, str],
    surfaced: dict[tuple[str, int], str],
) -> None:
    if set(message) != {"role", "toolCallId", "name", "content"}:
        raise ValidationError(f"{trace_id}: malformed tool result")
    call_id = message["toolCallId"]
    if pending_calls.pop(call_id, None) != message["name"]:
        raise ValidationError(f"{trace_id}: tool result does not resolve a call")
    content = message["content"]
    if not isinstance(content, dict) or set(content) - {"candidates", "error"}:
        raise ValidationError(f"{trace_id}: invalid tool result content")
    candidates = content.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValidationError(f"{trace_id}: candidates must be an array")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValidationError(f"{trace_id}: candidate must be an object")
        media_type = candidate.get("mediaType")
        tmdb_id = candidate.get("tmdbId")
        name = candidate.get("name")
        if media_type not in ALLOWED_MEDIA_TYPES or not isinstance(tmdb_id, int) or tmdb_id <= 0:
            raise ValidationError(f"{trace_id}: invalid candidate identity")
        if not isinstance(name, str) or not name:
            raise ValidationError(f"{trace_id}: candidate name required")
        surfaced[(media_type, tmdb_id)] = name


def _validate_final(
    trace_id: str,
    final: Any,
    surfaced: dict[tuple[str, int], str],
) -> None:
    if not isinstance(final, dict) or "picks" not in final or not isinstance(final["picks"], list):
        raise ValidationError(f"{trace_id}: final proposal lacks picks")
    if len(final["picks"]) > 8:
        raise ValidationError(f"{trace_id}: final proposal exceeds eight picks")
    for pick in final["picks"]:
        if not isinstance(pick, dict):
            raise ValidationError(f"{trace_id}: pick must be an object")
        media_type = pick.get("mediaType")
        tmdb_id = pick.get("tmdbId")
        name = pick.get("name")
        confidence = pick.get("confidence")
        key = (media_type, tmdb_id)
        if key not in surfaced:
            raise ValidationError(f"{trace_id}: unsupported selected id {key!r}")
        if name != surfaced[key]:
            raise ValidationError(f"{trace_id}: selected name differs from tool result")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ValidationError(f"{trace_id}: invalid confidence")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _go_tool_schema_bytes(tools: Any) -> bytes:
    if not isinstance(tools, list) or len(tools) != 1 or not isinstance(tools[0], dict):
        raise ValidationError("planner contract must contain exactly one tool")
    tool = tools[0]
    if set(tool) != {"Name", "Description", "Parameters"}:
        raise ValidationError("planner contract tool has invalid fields")
    # Matches encoding/json for []llm.ToolSchema: struct fields retain declaration
    # order, while the Parameters map is key-sorted.
    return (
        "[{\"Name\":"
        + json.dumps(tool["Name"], ensure_ascii=False)
        + ",\"Description\":"
        + json.dumps(tool["Description"], ensure_ascii=False)
        + ",\"Parameters\":"
        + json.dumps(tool["Parameters"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "}]"
    ).encode("utf-8")
