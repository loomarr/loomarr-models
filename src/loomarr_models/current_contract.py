from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .validator import PRIVATE_PATH_PATTERNS, SECRET_PATTERNS, ValidationError


CURRENT_CAPABILITIES = (
    "exact-key-final",
    "date-movie-release",
    "date-series-premiere",
    "date-series-airing",
    "date-disjoint-intervals",
    "date-ambiguity",
    "collection-evidence",
    "franchise-boundary",
    "network-editorial-epoch",
    "cast-routing",
    "creator-routing",
    "exact-title-unfamiliar",
    "constraint-conflict-abstention",
    "ownership-acquisition-balance",
    "refinement-preservation",
    "audience-ceiling",
    "season-window",
    "medium-constraint",
    "language-constraint",
    "region-constraint",
    "thin-results",
    "empty-results",
    "malformed-tool-result",
    "observed-fault-recovery",
)

CONTRACT_KEYS = {
    "fixtureId",
    "messageTemplateVersion",
    "promptVersion",
    "systemPromptSha256",
    "toolSchemaVersion",
    "toolSchemaSha256",
    "sourceVersion",
}
TOOL_ARGUMENT_KEYS = {
    "dateMeaning",
    "mode",
    "titles",
    "query",
    "keywords",
    "genres",
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
POLICY_KEYS = {"audience", "era", "genres", "ordering", "seasonal", "rules"}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_current_denylist(path: Path) -> tuple[set[str], set[str], int, set[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("schemaVersion") != 2
        or data.get("contractId") != "loomarr-planner-holdout-denylist-v2"
        or data.get("protection", {}).get("rawApplicationContentStored") is not False
    ):
        raise ValidationError(f"{path}: invalid current holdout denylist")
    protection = data["protection"]
    return (
        set(protection["exactValueSha256"]),
        set(protection["normalizedTextSha256"]),
        protection["minimumTextLength"],
        set(protection["protectedKeys"]),
    )


def _protected_record_payload(record: Mapping[str, Any]) -> Any:
    if isinstance(record.get("intent"), dict):
        return {
            "caseId": record.get("caseId"),
            "intent": record.get("intent"),
            "script": record.get("script"),
            "expectation": record.get("expectation"),
        }
    messages = []
    for message in record.get("messages", []):
        if message.get("role") == "system":
            continue
        if message.get("role") == "user" and str(message.get("content", "")).startswith("Retrieval is complete"):
            continue
        messages.append(message)
    return {"traceId": record.get("traceId"), "messages": messages}


def assert_not_denylisted(
    context: str,
    record: Mapping[str, Any],
    exact_digests: set[str],
    normalized_digests: set[str],
    minimum_text_length: int,
    protected_keys: set[str],
) -> None:
    payload = _protected_record_payload(record)

    def visit(value: Any, protected: bool = False) -> None:
        if isinstance(value, str):
            if not protected or len(value.strip()) < minimum_text_length:
                try:
                    decoded = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return
                visit(decoded)
                return
            if sha256_bytes(value.encode()) in exact_digests:
                raise ValidationError(f"{context}: exact application evaluation value leaked")
            normalized = " ".join(value.casefold().split())
            if sha256_bytes(normalized.encode()) in normalized_digests:
                raise ValidationError(f"{context}: normalized application evaluation text leaked")
            return
        if isinstance(value, list):
            for item in value:
                visit(item, protected)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, protected or key in protected_keys)

    visit(payload)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def contract_reference(contract: Mapping[str, Any], fixture_id: str) -> dict[str, str]:
    return {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "sourceVersion": contract["sourceVersion"],
        "fixtureId": fixture_id,
    }


def validate_date_meaning(context: str, value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"kind", "anchors", "axes"}:
        raise ValidationError(f"{context}: dateMeaning fields drifted")
    kind, anchors, axes = value["kind"], value["anchors"], value["axes"]
    if kind not in {"none", "constraints", "ambiguous"} or not isinstance(anchors, list) or not isinstance(axes, list):
        raise ValidationError(f"{context}: invalid dateMeaning shape")
    if kind == "none" and (anchors or axes):
        raise ValidationError(f"{context}: kind=none must have empty anchors and axes")
    if kind == "ambiguous" and (not anchors or axes):
        raise ValidationError(f"{context}: ambiguous dates require anchors and no axes")
    if kind == "constraints" and (not anchors or not axes):
        raise ValidationError(f"{context}: constrained dates require anchors and axes")
    for anchor in anchors:
        if not isinstance(anchor, dict) or not {"field", "start", "end"} <= set(anchor) or set(anchor) - {"field", "index", "start", "end"}:
            raise ValidationError(f"{context}: invalid date anchor")
        if anchor["field"] not in {"description", "era", "refineText", "mustInclude", "mustExclude"}:
            raise ValidationError(f"{context}: invalid date anchor field")
        if not isinstance(anchor["start"], int) or not isinstance(anchor["end"], int) or anchor["start"] >= anchor["end"]:
            raise ValidationError(f"{context}: invalid date anchor bounds")
        if anchor["field"] in {"mustInclude", "mustExclude"} and not isinstance(anchor.get("index"), int):
            raise ValidationError(f"{context}: array date anchor requires an index")
        if anchor["field"] not in {"mustInclude", "mustExclude"} and "index" in anchor:
            raise ValidationError(f"{context}: scalar date anchor cannot have an index")
    for axis in axes:
        if not isinstance(axis, dict) or set(axis) != {"kind", "combine", "intervals"}:
            raise ValidationError(f"{context}: invalid date axis")
        if axis["kind"] not in {"movie_release", "series_premiere", "series_airing"}:
            raise ValidationError(f"{context}: invalid date axis kind")
        if axis["combine"] not in {"any", "all"} or not isinstance(axis["intervals"], list) or not axis["intervals"]:
            raise ValidationError(f"{context}: invalid date axis intervals")
        for interval in axis["intervals"]:
            if not isinstance(interval, dict) or set(interval) != {"anchor", "start", "end"}:
                raise ValidationError(f"{context}: invalid date interval")
            if not isinstance(interval["anchor"], int) or not 0 <= interval["anchor"] < len(anchors):
                raise ValidationError(f"{context}: date interval anchor is out of range")
            if not 1900 <= interval["start"] <= interval["end"] <= 2099:
                raise ValidationError(f"{context}: date interval bounds are invalid")


def validate_tool_arguments(context: str, arguments: Any) -> None:
    if not isinstance(arguments, dict):
        raise ValidationError(f"{context}: tool arguments must be an object")
    if "dateMeaning" not in arguments:
        raise ValidationError(f"{context}: dateMeaning is required")
    if "era" in arguments:
        raise ValidationError(f"{context}: retired era argument is forbidden")
    if "tmdbId" in arguments or "tvdbId" in arguments:
        raise ValidationError(f"{context}: external IDs are not tool arguments")
    unknown = set(arguments) - TOOL_ARGUMENT_KEYS
    if unknown:
        raise ValidationError(f"{context}: unsupported tool arguments: {sorted(unknown)}")
    validate_date_meaning(context, arguments["dateMeaning"])
    if arguments.get("mode") == "collection":
        if not isinstance(arguments.get("titles"), list) or not arguments["titles"]:
            raise ValidationError(f"{context}: collection mode requires titles")
        if arguments.get("media_type") not in {"movie", "series"}:
            raise ValidationError(f"{context}: collection mode requires media_type")
        forbidden = set(arguments) - {"mode", "media_type", "titles", "dateMeaning"}
        if forbidden:
            raise ValidationError(f"{context}: collection mode includes discovery filters")
    elif "titles" in arguments or "mode" in arguments:
        raise ValidationError(f"{context}: collection fields require mode=collection")
    if "network" in arguments and arguments.get("media_type") != "series":
        raise ValidationError(f"{context}: network requires media_type=series")
    if ("cast" in arguments or "creators" in arguments) and arguments.get("media_type") != "movie":
        raise ValidationError(f"{context}: person filters require media_type=movie")
    if "network" in arguments and ({"cast", "creators"} & set(arguments)):
        raise ValidationError(f"{context}: network and person filters cannot be combined")


def validate_policy(context: str, policy: Any) -> None:
    if not isinstance(policy, dict) or set(policy) - POLICY_KEYS:
        raise ValidationError(f"{context}: final policy contains stale or unsupported fields")
    nested = {
        "audience": {"ceiling", "unrated"},
        "era": {"from", "to"},
        "genres": {"include", "exclude"},
        "seasonal": {"mode", "holidays"},
    }
    for field, allowed in nested.items():
        if field in policy and (not isinstance(policy[field], dict) or set(policy[field]) - allowed):
            raise ValidationError(f"{context}: final policy {field} contains stale or unsupported fields")
    if "rules" in policy:
        if not isinstance(policy["rules"], list) or any(
            not isinstance(rule, dict) or set(rule) - {"when", "what", "how", "priority"}
            for rule in policy["rules"]
        ):
            raise ValidationError(f"{context}: final policy rules are invalid")


def _tool_payload(context: str, content: Any) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(content, str):
        raise ValidationError(f"{context}: tool content must preserve the production JSON string")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{context}: malformed tool JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        fault = payload.get("fault")
        observed = isinstance(fault, dict) and fault.get("injected") is True and fault.get("observed") is True
        return [], observed
    if not isinstance(payload, list):
        raise ValidationError(f"{context}: tool result must be a candidate array or declared error")
    for candidate in payload:
        if not isinstance(candidate, dict) or candidate.get("mediaType") not in {"movie", "series"}:
            raise ValidationError(f"{context}: invalid candidate")
        key = candidate.get("key")
        if not isinstance(key, str) or not re.fullmatch(r"(?:movie|series):[a-z0-9_-]+:[A-Za-z0-9._-]+", key):
            raise ValidationError(f"{context}: candidate lacks an exact catalog key")
        if candidate.get("name") in {None, ""}:
            raise ValidationError(f"{context}: candidate name is empty")
    return payload, False


def validate_final(context: str, content: Any, candidate_keys: set[str], accepted_meaning: dict[str, Any]) -> None:
    if not isinstance(content, str):
        raise ValidationError(f"{context}: final response must be a JSON string")
    try:
        final = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{context}: final response is not JSON") from exc
    if not isinstance(final, dict):
        raise ValidationError(f"{context}: final response must be an object")
    if set(final) != {"channelName", "rationale", "dateMeaning", "picks", "policy"}:
        raise ValidationError(f"{context}: final response contains missing or unsupported fields")
    for field in ("channelName", "rationale", "dateMeaning", "picks", "policy"):
        if field not in final:
            raise ValidationError(f"{context}: final response lacks {field}")
    if final["dateMeaning"] != accepted_meaning:
        raise ValidationError(f"{context}: final dateMeaning changed after retrieval")
    validate_date_meaning(context, final["dateMeaning"])
    if not isinstance(final["picks"], list):
        raise ValidationError(f"{context}: final picks/policy shape is invalid")
    validate_policy(context, final["policy"])
    for pick in final["picks"]:
        if not isinstance(pick, dict) or "tmdbId" in pick or "tvdbId" in pick:
            raise ValidationError(f"{context}: final uses obsolete external-ID fields")
        if set(pick) - {"mediaType", "key", "name", "year", "rationale", "confidence", "seasonMin", "seasonMax"}:
            raise ValidationError(f"{context}: final pick contains stale or unsupported fields")
        if pick.get("key") not in candidate_keys:
            raise ValidationError(f"{context}: final pick is not grounded by an exact surfaced key")
        if pick.get("mediaType") not in {"movie", "series"}:
            raise ValidationError(f"{context}: final pick media type is invalid")


def validate_current_trace(trace: Mapping[str, Any], contract: Mapping[str, Any], fixture_id: str) -> None:
    trace_id = trace.get("traceId", "<missing>")
    if trace.get("schemaVersion") != 1 or trace.get("split") != "train":
        raise ValidationError(f"{trace_id}: invalid current training envelope")
    axes = trace.get("axes")
    if not isinstance(axes, list) or len(axes) != 1 or axes[0] not in CURRENT_CAPABILITIES:
        raise ValidationError(f"{trace_id}: invalid capability")
    if set(trace.get("contract", {})) != CONTRACT_KEYS or trace["contract"] != contract_reference(contract, fixture_id):
        raise ValidationError(f"{trace_id}: contract drifted")
    if trace.get("tools") != contract["tools"]:
        raise ValidationError(f"{trace_id}: tool schema drifted")
    messages = trace.get("messages")
    if not isinstance(messages, list) or len(messages) < 6:
        raise ValidationError(f"{trace_id}: current trace is missing production turns")
    if messages[0] != {"role": "system", "content": contract["systemPrompt"]}:
        raise ValidationError(f"{trace_id}: system prompt drifted")
    if messages[-2].get("role") != "user" or not str(messages[-2].get("content", "")).startswith("Retrieval is complete"):
        raise ValidationError(f"{trace_id}: finalization turn is missing")
    candidate_keys: set[str] = set()
    accepted_meaning: dict[str, Any] | None = None
    observed_fault = False
    tool_calls = 0
    for index, message in enumerate(messages[:-2]):
        if message.get("role") != "assistant" or "toolCalls" not in message:
            continue
        calls = message["toolCalls"]
        if not isinstance(calls, list) or len(calls) != 1 or index + 1 >= len(messages):
            raise ValidationError(f"{trace_id}: each assistant tool turn must contain one call")
        call = calls[0]
        if call.get("name") != "catalog_search" or not isinstance(call.get("id"), str):
            raise ValidationError(f"{trace_id}: invalid tool call")
        validate_tool_arguments(trace_id, call.get("arguments"))
        meaning = call["arguments"]["dateMeaning"]
        if accepted_meaning is not None and meaning != accepted_meaning:
            raise ValidationError(f"{trace_id}: tool calls changed dateMeaning")
        accepted_meaning = meaning
        result = messages[index + 1]
        if result.get("role") != "tool" or result.get("toolCallId") != call["id"]:
            raise ValidationError(f"{trace_id}: tool result correlation drifted")
        candidates, fault = _tool_payload(trace_id, result.get("content"))
        candidate_keys.update(candidate["key"] for candidate in candidates)
        observed_fault = observed_fault or fault
        tool_calls += 1
    if tool_calls == 0 or accepted_meaning is None:
        raise ValidationError(f"{trace_id}: trace has no catalog operation")
    validate_final(trace_id, messages[-1].get("content"), candidate_keys, accepted_meaning)
    if axes[0] == "observed-fault-recovery" and (not observed_fault or tool_calls < 2):
        raise ValidationError(f"{trace_id}: recovery requires an injected, observed fault and retry")
    if axes[0] != "observed-fault-recovery" and observed_fault:
        raise ValidationError(f"{trace_id}: fault evidence appears outside the recovery capability")
    review = trace.get("review")
    if review != {"status": "pending", "reviewer": "", "reviewedAt": None, "notes": ""}:
        raise ValidationError(f"{trace_id}: new trace must remain pending independent review")
    _reject_private_content(trace_id, trace)


def validate_approved_current_trace(
    trace: Mapping[str, Any], contract: Mapping[str, Any], fixture_id: str
) -> None:
    trace_id = trace.get("traceId", "<missing>")
    review = trace.get("review")
    if (
        not isinstance(review, dict)
        or set(review) != {"status", "reviewer", "reviewedAt", "notes"}
        or review.get("status") != "approved"
        or not isinstance(review.get("reviewer"), str)
        or not review["reviewer"]
        or not isinstance(review.get("reviewedAt"), str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", review["reviewedAt"])
        is None
        or not isinstance(review.get("notes"), str)
    ):
        raise ValidationError(f"{trace_id}: approved current trace review evidence is invalid")
    pending = dict(trace)
    pending["review"] = {"status": "pending", "reviewer": "", "reviewedAt": None, "notes": ""}
    validate_current_trace(pending, contract, fixture_id)


def validate_current_development_case(case: Mapping[str, Any], contract: Mapping[str, Any], fixture_id: str) -> None:
    case_id = case.get("caseId", "<missing>")
    if case.get("schemaVersion") != 1 or case.get("split") != "development-eval":
        raise ValidationError(f"{case_id}: invalid development envelope")
    capability = case.get("axis")
    if capability not in CURRENT_CAPABILITIES:
        raise ValidationError(f"{case_id}: invalid development capability")
    if set(case.get("contract", {})) != CONTRACT_KEYS or case["contract"] != contract_reference(contract, fixture_id):
        raise ValidationError(f"{case_id}: contract drifted")
    script = case.get("script")
    if not isinstance(script, list) or not script:
        raise ValidationError(f"{case_id}: development script is empty")
    candidate_keys: set[str] = set()
    observed_fault = False
    accepted_meaning: dict[str, Any] | None = None
    for step in script:
        validate_tool_arguments(case_id, step.get("arguments"))
        meaning = step["arguments"]["dateMeaning"]
        if accepted_meaning is not None and meaning != accepted_meaning:
            raise ValidationError(f"{case_id}: script changed dateMeaning")
        accepted_meaning = meaning
        candidates, fault = _tool_payload(case_id, step.get("result"))
        candidate_keys.update(candidate["key"] for candidate in candidates)
        observed_fault = observed_fault or fault
    expectation = case.get("expectation")
    if not isinstance(expectation, dict) or expectation.get("dateMeaning") != accepted_meaning:
        raise ValidationError(f"{case_id}: expectation dateMeaning drifted")
    selected = expectation.get("selectedKeys")
    forbidden = expectation.get("forbiddenKeys")
    if not isinstance(selected, list) or not isinstance(forbidden, list):
        raise ValidationError(f"{case_id}: expected key sets are invalid")
    if not set(selected) <= candidate_keys or set(selected) & set(forbidden):
        raise ValidationError(f"{case_id}: expected keys are ungrounded or contradictory")
    if capability == "observed-fault-recovery":
        if not observed_fault or len(script) < 2 or expectation.get("faultInjected") is not True or expectation.get("faultObserved") is not True:
            raise ValidationError(f"{case_id}: recovery case lacks observed fault evidence")
    elif observed_fault or "faultInjected" in expectation or "faultObserved" in expectation:
        raise ValidationError(f"{case_id}: fault evidence appears outside the recovery capability")
    _reject_private_content(case_id, case)


def _reject_private_content(context: str, value: Any) -> None:
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
    for pattern in SECRET_PATTERNS + PRIVATE_PATH_PATTERNS:
        if pattern.search(serialized):
            raise ValidationError(f"{context}: possible secret or household path")


def normalized_semantic_digest(record: Mapping[str, Any]) -> str:
    provenance = record.get("provenance", {})
    if isinstance(provenance, dict) and isinstance(provenance.get("intent"), dict):
        intent = provenance["intent"]
        if isinstance(record.get("script"), list):
            steps = [step.get("arguments") for step in record["script"]]
        else:
            steps = [
                call.get("arguments")
                for message in record.get("messages", [])
                if message.get("role") == "assistant"
                for call in message.get("toolCalls", [])
            ]
    elif isinstance(record.get("intent"), dict):
        intent = record["intent"].get("description", "")
        steps = record.get("script", [])
    else:
        messages = record.get("messages", [])
        user = next((message for message in messages if message.get("role") == "user"), {})
        intent = user.get("content", "").split("\nSubmitted Intent source coordinates", 1)[0]
        if intent.startswith("Build a channel: "):
            intent = intent.removeprefix("Build a channel: ").rstrip()
        steps = [
            call.get("arguments")
            for message in messages
            if message.get("role") == "assistant"
            for call in message.get("toolCalls", [])
        ]
    normalized = {"intent": " ".join(str(intent).lower().split()), "steps": _without_catalog_keys(steps)}
    return sha256_bytes(canonical(normalized))


def _without_catalog_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "<catalog-key>" if key == "key" else _without_catalog_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_catalog_keys(item) for item in value]
    if isinstance(value, str) and re.fullmatch(r"(?:movie|series):[a-z0-9_-]+:[A-Za-z0-9._-]+", value):
        return "<catalog-key>"
    return value


def record_catalog_keys(record: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    values: list[Any] = []
    if isinstance(record.get("script"), list):
        values.extend(step.get("result") for step in record["script"] if isinstance(step, dict))
    if isinstance(record.get("messages"), list):
        values.extend(message.get("content") for message in record["messages"] if message.get("role") == "tool")
    for value in values:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                continue
        if isinstance(value, list):
            keys.update(item["key"] for item in value if isinstance(item, dict) and isinstance(item.get("key"), str))
    return keys


def validate_disjoint_splits(splits: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    summaries: dict[str, tuple[set[str], set[str], set[str]]] = {}
    for name, records in splits.items():
        identities: set[str] = set()
        keys: set[str] = set()
        semantics: set[str] = set()
        for record in records:
            identity = record.get("traceId", record.get("caseId"))
            if not isinstance(identity, str) or identity in identities:
                raise ValidationError(f"{name}: missing or duplicate record identity")
            identities.add(identity)
            keys.update(record_catalog_keys(record))
            semantics.add(normalized_semantic_digest(record))
        if not identities:
            raise ValidationError(f"{name}: split is empty")
        summaries[name] = identities, keys, semantics
    pairs = 0
    names = list(summaries)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            pairs += 1
            for left_values, right_values, label in zip(
                summaries[left], summaries[right], ("record identity", "catalog key", "normalized semantic"), strict=True
            ):
                if left_values & right_values:
                    raise ValidationError(f"{left} and {right}: {label} overlap")
    return {"splitCounts": {name: len(summary[0]) for name, summary in summaries.items()}, "pairCount": pairs}


def classify_legacy_record(record: Mapping[str, Any]) -> set[str]:
    reasons: set[str] = set()
    contract = record.get("contract", {})
    if contract.get("promptVersion") != "suggester-prompt-v15" or contract.get("toolSchemaVersion") != "catalog-search-v9":
        reasons.add("stale-contract")
    messages = record.get("messages")
    if isinstance(messages, list):
        for message in messages:
            for call in message.get("toolCalls", []) if isinstance(message, dict) else []:
                arguments = call.get("arguments", {})
                if set(arguments) - TOOL_ARGUMENT_KEYS:
                    reasons.add("unsupported-tool-operation")
                if "dateMeaning" not in arguments:
                    reasons.add("tool-call-missing-dateMeaning")
                if "era" in arguments:
                    reasons.add("retired-era-tool-argument")
        final_message = next((message for message in reversed(messages) if message.get("role") == "assistant" and "toolCalls" not in message), None)
        if final_message is not None:
            try:
                final = json.loads(final_message.get("content", ""))
            except (json.JSONDecodeError, TypeError):
                reasons.add("invalid-final-json")
            else:
                if "dateMeaning" not in final:
                    reasons.add("final-missing-dateMeaning")
                if set(final) - {"channelName", "rationale", "dateMeaning", "picks", "policy"}:
                    reasons.add("unsupported-final-fields")
                policy = final.get("policy", {})
                if isinstance(policy, dict) and set(policy) - POLICY_KEYS:
                    reasons.add("stale-policy-fields")
                for pick in final.get("picks", []):
                    if "tmdbId" in pick or "tvdbId" in pick:
                        reasons.add("obsolete-final-external-ids")
                    if "key" not in pick:
                        reasons.add("final-missing-exact-key")
    if isinstance(record.get("script"), list):
        for step in record["script"]:
            arguments = step.get("arguments", {})
            if set(arguments) - TOOL_ARGUMENT_KEYS:
                reasons.add("unsupported-tool-operation")
            if "dateMeaning" not in arguments:
                reasons.add("tool-call-missing-dateMeaning")
            if "era" in arguments:
                reasons.add("retired-era-tool-argument")
        expectation = record.get("expectation", {})
        if "selectedIds" in expectation:
            reasons.add("obsolete-expectation-external-ids")
        if "dateMeaning" not in expectation:
            reasons.add("expectation-missing-dateMeaning")
    return reasons


def legacy_artifact_report(path: Path, *, display_path: Path | None = None) -> dict[str, Any]:
    records = read_jsonl(path)
    counts: Counter[str] = Counter()
    compatible = 0
    for record in records:
        reasons = classify_legacy_record(record)
        if reasons:
            counts.update(reasons)
        else:
            compatible += 1
    return {
        "path": (display_path or path).as_posix(),
        "sha256": sha256_bytes(path.read_bytes()),
        "records": len(records),
        "currentContractCompatibleRecords": compatible,
        "excludedFromActiveMixture": True,
        "reasonCounts": dict(sorted(counts.items())),
    }
