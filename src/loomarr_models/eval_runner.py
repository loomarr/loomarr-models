from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Callable, Iterable

from .validator import ALLOWED_MEDIA_TYPES, DISCOVERY_ARGUMENTS, SEARCH_ARGUMENTS


RECOVERY_AXES = {"empty-results", "tool-error-recovery", "malformed-final-repair"}
FORBIDDEN_AUTHORITY_KEYS = {
    "approved",
    "authorized",
    "channelId",
    "acquisitionApproved",
    "admissionApproved",
    "playbackAuthorized",
}
QUALITY_FIELDS = (
    "groundedCompletionRate",
    "correctToolOperationRate",
    "schemaValidityRate",
    "policyAccuracyRate",
    "proposalQualityRate",
    "recoveryRate",
)

TurnGenerator = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


@dataclass(frozen=True)
class CaseResult:
    caseId: str
    axis: str
    groundedCompletion: bool
    correctToolOperation: bool
    argumentValidity: bool
    schemaValidity: bool
    policyAccuracy: bool
    proposalQuality: bool
    recoveryExpected: bool
    recoverySuccessful: bool
    unsupportedIdCount: int
    authorityViolationCount: int
    modelCalls: int
    toolCalls: int
    latencyNanos: int
    hardFailures: list[str]
    transcript: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_case(
    case: dict[str, Any],
    *,
    system_prompt: str,
    tools: list[dict[str, Any]],
    generate: TurnGenerator,
    max_model_calls: int = 5,
) -> CaseResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": case["intent"]},
    ]
    script_index = 0
    tool_calls = 0
    model_calls = 0
    latency_nanos = 0
    calls_match = True
    arguments_valid = True
    repair_injected = False
    final: Any = None

    while model_calls < max_model_calls:
        started = time.monotonic_ns()
        turn = generate(copy.deepcopy(messages), copy.deepcopy(tools))
        latency_nanos += time.monotonic_ns() - started
        model_calls += 1
        if not isinstance(turn, dict) or turn.get("role") != "assistant":
            messages.append({"role": "assistant", "content": ""})
            break

        if "toolCalls" in turn:
            messages.append(copy.deepcopy(turn))
            calls = turn["toolCalls"]
            if not isinstance(calls, list) or len(calls) != 1:
                calls_match = False
                break
            call = calls[0]
            tool_calls += 1
            valid_arguments = _valid_tool_call(call)
            arguments_valid = arguments_valid and valid_arguments
            expected = case["script"][script_index] if script_index < len(case["script"]) else None
            matched = (
                valid_arguments
                and expected is not None
                and call["name"] == "catalog_search"
                and call["arguments"] == expected["arguments"]
            )
            calls_match = calls_match and matched
            if matched:
                result = copy.deepcopy(expected["result"])
                script_index += 1
            else:
                result = {
                    "candidates": [],
                    "error": "synthetic fixture rejected unexpected tool arguments",
                }
            messages.append(
                {
                    "role": "tool",
                    "toolCallId": str(call.get("id", "invalid-call")),
                    "name": "catalog_search",
                    "content": result,
                }
            )
            if (
                case["axis"] == "malformed-final-repair"
                and matched
                and script_index == len(case["script"])
                and not repair_injected
            ):
                messages.extend(
                    [
                        {"role": "assistant", "content": "{not-json"},
                        {"role": "user", "content": case["repairPrompt"]},
                    ]
                )
                repair_injected = True
            continue

        if set(turn) != {"role", "content"} or not isinstance(turn["content"], str):
            messages.append({"role": "assistant", "content": ""})
            break
        messages.append(copy.deepcopy(turn))
        try:
            final = json.loads(turn["content"])
        except json.JSONDecodeError:
            final = None
        break

    expected_call_count = len(case["script"])
    correct_operation = calls_match and script_index == expected_call_count and tool_calls == expected_call_count
    schema_valid = _valid_final(final)
    surfaced = {
        (candidate["mediaType"], candidate["tmdbId"])
        for message in messages
        if message.get("role") == "tool"
        for candidate in message["content"].get("candidates", [])
    }
    selected = _selected_keys(final) if schema_valid else []
    unsupported = sum(key not in surfaced for key in selected)
    authority_violations = _authority_violation_count(final)
    expected_abstention = case["expectation"]["abstain"]
    grounded = (
        schema_valid
        and unsupported == 0
        and (len(selected) == 0 if expected_abstention else len(selected) > 0)
    )
    expected_selected = {
        (item["mediaType"], item["tmdbId"])
        for item in case["expectation"]["selectedIds"]
    }
    forbidden = {
        (item["mediaType"], item["tmdbId"])
        for item in case["expectation"]["forbiddenIds"]
    }
    actual_selected = set(selected)
    proposal_quality = (
        schema_valid
        and unsupported == 0
        and actual_selected == expected_selected
        and not actual_selected & forbidden
        and 2 <= len(final["channelName"].split()) <= 4
        and bool(final["rationale"].strip())
    )
    policy_accuracy = schema_valid and final["policy"] == case["expectation"]["expectedPolicy"]
    recovery_expected = case["axis"] in RECOVERY_AXES
    recovery_successful = (
        not recovery_expected
        or (
            correct_operation
            and grounded
            and proposal_quality
            and (case["axis"] != "malformed-final-repair" or repair_injected)
        )
    )
    hard_failures: list[str] = []
    if not schema_valid:
        hard_failures.append("schema_invalid")
    if unsupported:
        hard_failures.append("unsupported_id")
    if authority_violations:
        hard_failures.append("authority_violation")
    if selected and not surfaced:
        hard_failures.append("grounding_bypass")

    return CaseResult(
        caseId=case["caseId"],
        axis=case["axis"],
        groundedCompletion=grounded,
        correctToolOperation=correct_operation,
        argumentValidity=arguments_valid,
        schemaValidity=schema_valid,
        policyAccuracy=policy_accuracy,
        proposalQuality=proposal_quality,
        recoveryExpected=recovery_expected,
        recoverySuccessful=recovery_successful,
        unsupportedIdCount=unsupported,
        authorityViolationCount=authority_violations,
        modelCalls=model_calls,
        toolCalls=tool_calls,
        latencyNanos=latency_nanos,
        hardFailures=hard_failures,
        transcript=messages,
    )


def summarize_candidate(
    candidate_id: str,
    results: Iterable[CaseResult],
    scoring: dict[str, Any],
    *,
    peak_vram_bytes: int = 0,
) -> dict[str, Any]:
    items = list(results)
    if not items:
        raise ValueError("candidate result set is empty")
    recovery = [item for item in items if item.recoveryExpected]
    summary = {
        "candidateId": candidate_id,
        "caseCount": len(items),
        "caseIds": [item.caseId for item in items],
        "groundedCompletionRate": _rate(items, "groundedCompletion"),
        "correctToolOperationRate": _rate(items, "correctToolOperation"),
        "argumentValidityRate": _rate(items, "argumentValidity"),
        "schemaValidityRate": _rate(items, "schemaValidity"),
        "policyAccuracyRate": _rate(items, "policyAccuracy"),
        "proposalQualityRate": _rate(items, "proposalQuality"),
        "recoveryRate": _rate(recovery, "recoverySuccessful"),
        "hardFailureCount": sum(len(item.hardFailures) for item in items),
        "unsupportedIdCount": sum(item.unsupportedIdCount for item in items),
        "authorityViolationCount": sum(item.authorityViolationCount for item in items),
        "latencyP50Nanos": int(median(item.latencyNanos for item in items)),
        "latencyP95Nanos": _nearest_rank([item.latencyNanos for item in items], 0.95),
        "p95ToolCalls": _nearest_rank([item.toolCalls for item in items], 0.95),
        "peakVramBytes": peak_vram_bytes,
        "caseMetrics": [
            {key: value for key, value in item.as_dict().items() if key != "transcript"}
            for item in items
        ],
    }
    summary["caseIdsSha256"] = hashlib.sha256(
        json.dumps(summary["caseIds"], separators=(",", ":")).encode()
    ).hexdigest()
    weights = scoring["weights"]
    summary["qualityScore"] = sum(
        summary[field] * weights[weight]
        for field, weight in (
            ("groundedCompletionRate", "groundedCompletion"),
            ("correctToolOperationRate", "correctToolOperation"),
            ("schemaValidityRate", "schemaValidity"),
            ("policyAccuracyRate", "policyAccuracy"),
            ("proposalQualityRate", "proposalQuality"),
            ("recoveryRate", "recovery"),
        )
    )
    return summary


def compare_candidates(
    stock: dict[str, Any],
    adapter: dict[str, Any],
    scoring: dict[str, Any],
) -> dict[str, Any]:
    if stock["caseCount"] != adapter["caseCount"]:
        raise ValueError("candidate case counts differ")
    if stock["caseIds"] != adapter["caseIds"] or stock["caseIdsSha256"] != adapter["caseIdsSha256"]:
        raise ValueError("candidate case identities or order differ")
    deltas = {field: adapter[field] - stock[field] for field in QUALITY_FIELDS}
    quality_delta = adapter["qualityScore"] - stock["qualityScore"]
    thresholds = scoring["thresholds"]
    failures: list[str] = []
    if adapter["hardFailureCount"] != 0:
        failures.append("adapter has hard-gate failures")
    if adapter["hardFailureCount"] > stock["hardFailureCount"]:
        failures.append("adapter regresses hard-gate failures")
    if quality_delta + 1e-12 < scoring["qualityMargin"]:
        failures.append("adapter does not clear the quality margin")
    if deltas["policyAccuracyRate"] <= 0 and deltas["recoveryRate"] <= 0:
        failures.append("adapter improves neither policy accuracy nor recovery")
    for field, delta in deltas.items():
        if field not in {"policyAccuracyRate", "recoveryRate"} and delta < -0.02 - 1e-12:
            failures.append(f"adapter regresses {field} by more than 0.02")
    threshold_fields = {
        "groundedCompletionRate": "minGroundedCompletionRate",
        "correctToolOperationRate": "minCorrectToolOperationRate",
        "schemaValidityRate": "minSchemaValidityRate",
        "policyAccuracyRate": "minPolicyAccuracyRate",
        "proposalQualityRate": "minProposalQualityRate",
        "recoveryRate": "minRecoveryRate",
    }
    for field, threshold in threshold_fields.items():
        if adapter[field] + 1e-12 < thresholds[threshold]:
            failures.append(f"adapter misses {threshold}")
    if adapter["p95ToolCalls"] > thresholds["maxP95ToolCalls"]:
        failures.append("adapter exceeds maxP95ToolCalls")
    return {
        "schemaVersion": 1,
        "decision": (
            "adapter-advances-to-single-certification-run"
            if not failures
            else "adapter-rejected-no-release"
        ),
        "qualityMargin": scoring["qualityMargin"],
        "qualityDelta": quality_delta,
        "metricDeltas": deltas,
        "failures": failures,
        "stock": stock,
        "adapter": adapter,
    }


def _valid_tool_call(call: Any) -> bool:
    if not isinstance(call, dict) or set(call) != {"id", "name", "arguments"}:
        return False
    if call["name"] != "catalog_search" or not isinstance(call["id"], str) or not call["id"]:
        return False
    arguments = call["arguments"]
    if not isinstance(arguments, dict) or not arguments or set(arguments) - SEARCH_ARGUMENTS:
        return False
    selectors = {"query", "genres", "keywords"} & set(arguments)
    if len(selectors) != 1 or ("query" in arguments and set(arguments) & DISCOVERY_ARGUMENTS):
        return False
    if "query" in arguments and (
        not isinstance(arguments["query"], str) or not arguments["query"].strip()
    ):
        return False
    for key in ("genres", "keywords"):
        if key in arguments and (
            not isinstance(arguments[key], list)
            or not arguments[key]
            or not all(isinstance(value, str) and value for value in arguments[key])
        ):
            return False
    if "media_type" in arguments and arguments["media_type"] not in ALLOWED_MEDIA_TYPES:
        return False
    if "era" in arguments and (
        not isinstance(arguments["era"], str) or not arguments["era"].strip()
    ):
        return False
    for key in ("original_language", "origin_country"):
        if key in arguments and (
            not isinstance(arguments[key], str) or not re.fullmatch(r"[A-Za-z]{2}", arguments[key])
        ):
            return False
    for key in ("runtime_min", "runtime_max", "vote_count_min"):
        if key in arguments and (
            not isinstance(arguments[key], int)
            or isinstance(arguments[key], bool)
            or arguments[key] <= 0
        ):
            return False
    if "vote_average_min" in arguments:
        value = arguments["vote_average_min"]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 0 < value <= 10
        ):
            return False
    return True


def _valid_final(final: Any) -> bool:
    if not isinstance(final, dict) or set(final) != {"channelName", "rationale", "picks", "policy"}:
        return False
    if not isinstance(final["channelName"], str) or not final["channelName"].strip():
        return False
    if not isinstance(final["rationale"], str) or not final["rationale"].strip():
        return False
    if not isinstance(final["picks"], list) or len(final["picks"]) > 8:
        return False
    if not isinstance(final["policy"], dict):
        return False
    seen_ids: set[tuple[str, int]] = set()
    for pick in final["picks"]:
        required = {"mediaType", "tmdbId", "name", "rationale", "confidence"}
        optional = {"tvdbId", "seasonMin", "seasonMax"}
        if not isinstance(pick, dict) or not required <= set(pick) or set(pick) - required - optional:
            return False
        if pick["mediaType"] not in ALLOWED_MEDIA_TYPES:
            return False
        if not isinstance(pick["tmdbId"], int) or pick["tmdbId"] <= 0:
            return False
        key = (pick["mediaType"], pick["tmdbId"])
        if key in seen_ids:
            return False
        seen_ids.add(key)
        if not all(isinstance(pick[key], str) and pick[key].strip() for key in ("name", "rationale")):
            return False
        confidence = pick["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return False
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return False
    return True


def _selected_keys(final: dict[str, Any]) -> list[tuple[str, int]]:
    return [(pick["mediaType"], pick["tmdbId"]) for pick in final["picks"]]


def _authority_violation_count(value: Any) -> int:
    if isinstance(value, dict):
        return sum(key in FORBIDDEN_AUTHORITY_KEYS for key in value) + sum(
            _authority_violation_count(child) for child in value.values()
        )
    if isinstance(value, list):
        return sum(_authority_violation_count(child) for child in value)
    return 0


def _rate(items: list[CaseResult], field: str) -> float:
    if not items:
        return 1.0
    return sum(bool(getattr(item, field)) for item in items) / len(items)


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]
