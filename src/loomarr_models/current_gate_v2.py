"""Current-contract development gate v2: tolerant tool-call matching and prompt-aligned policy.

The v1 scorer accepted a tool call only when it equalled the fixture author's exact arguments and
required every final policy to be empty unless the case was the audience-ceiling case. The
production prompt tells the planner to infer policy (genres, ordering, and so on) from the intent,
so v1 scored every prompt-following model at 0% policy accuracy. It also failed reasonable
equivalent searches such as extra keywords or an omitted optional media_type.

In v2 each scripted step carries an explicit `accept` rule, and each case carries an explicit
`policy` expectation. Both are generated data that reviewers can read. Everything else about
scoring is unchanged from `evaluate_current_case`.
"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Any

from .current_baseline import (
    CurrentCaseResult,
    TurnGenerator,
    _authority_violation_count,
    _selected_keys,
    _tool_payload,
    finalization_prompt,
    render_user_prompt,
)
from .current_contract import validate_final, validate_tool_arguments


SCORER_VERSION = "planner-current-development-scorer-v3"
MATCHES = {"exact", "ci", "containsAll", "tokens"}
ORDERINGS = {"syndication", "sequential", "shuffle"}


def _tokens(value: Any) -> set[str]:
    items = value if isinstance(value, list) else [value]
    found: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            continue
        for token in re.split(r"[^a-z0-9]+", item.lower()):
            if token:
                found.add(token[:-1] if len(token) > 3 and token.endswith("s") else token)
    return found


def _field_matches(spec: dict[str, Any], value: Any) -> bool:
    match, expected = spec["match"], spec["value"]
    if match == "exact":
        return value == expected
    if match == "ci":
        return isinstance(value, str) and value.strip().casefold() == expected.strip().casefold()
    if match == "containsAll":
        if not isinstance(value, list):
            return False
        provided = {item.strip().casefold() for item in value if isinstance(item, str)}
        return all(item.strip().casefold() in provided for item in expected)
    if match == "tokens":
        return _tokens(expected) <= _tokens(value)
    raise ValueError(f"unknown accept match {match!r}")


def _anchor_spans(meaning: dict[str, Any]) -> list[tuple[str, Any, int, int]]:
    return [(a.get("field"), a.get("index"), a.get("start"), a.get("end")) for a in meaning.get("anchors", [])]


def _overlaps(spans: list[tuple[str, Any, int, int]], others: list[tuple[str, Any, int, int]]) -> bool:
    return all(
        any(f == g and i == j and s < e2 and s2 < e for g, j, s2, e2 in others) for f, i, s, e in spans
    )


def meanings_equivalent(meaning: Any, canonical: dict[str, Any]) -> bool:
    """Same interpretation, allowing a different choice of anchor spans over the same date text.

    Kind, axis kinds, combine modes, and interval years must match exactly. Every anchor must
    overlap a canonical anchor in the same field, and every canonical anchor must be covered.
    """
    if meaning == canonical:
        return True
    if not isinstance(meaning, dict) or meaning.get("kind") != canonical["kind"] or canonical["kind"] == "none":
        return False
    try:
        def axes(value: dict[str, Any]) -> list[tuple[Any, Any, tuple[tuple[int, int], ...]]]:
            return sorted(
                (axis["kind"], axis["combine"], tuple(sorted((iv["start"], iv["end"]) for iv in axis["intervals"])))
                for axis in value.get("axes", [])
            )

        mine, theirs = _anchor_spans(meaning), _anchor_spans(canonical)
        return bool(mine) and axes(meaning) == axes(canonical) and _overlaps(mine, theirs) and _overlaps(theirs, mine)
    except (KeyError, TypeError):
        return False


def step_accepts(step: dict[str, Any], arguments: Any) -> bool:
    """Return whether a model tool call is an acceptable equivalent of a scripted step."""
    if not isinstance(arguments, dict):
        return False
    if not meanings_equivalent(arguments.get("dateMeaning"), step["arguments"]["dateMeaning"]):
        return False
    accept = step["accept"]
    fields = accept["fields"]
    allowed = accept["allowed"]
    provided = set(arguments) - {"dateMeaning"}
    if allowed != "*" and not provided <= set(fields) | set(allowed):
        return False
    for name, spec in fields.items():
        if name not in arguments:
            if spec["required"]:
                return False
            continue
        if not _field_matches(spec, arguments[name]):
            return False
    require_any = accept.get("requireAny", [])
    if require_any and not any(name in arguments for name in require_any):
        return False
    across = accept.get("termsAcross")
    return not across or _tokens(across["value"]) <= set().union(*(_tokens(arguments.get(f)) for f in across["fields"]))


def policy_matches(expected: dict[str, Any], policy: Any) -> bool:
    """Score only the objective policy obligations stated by the production prompt."""
    if not isinstance(policy, dict):
        return False
    ceiling = policy.get("audience", {}).get("ceiling") if isinstance(policy.get("audience"), dict) else None
    if ceiling != expected["audienceCeiling"]:
        return False
    if "rules" in policy and not expected["rulesAllowed"]:
        return False
    if "seasonal" in policy and policy["seasonal"] != {"mode": "auto"}:
        return False
    return "ordering" not in policy or policy["ordering"] in ORDERINGS


def evaluate_current_case_v2(
    case: dict[str, Any],
    *,
    system_prompt: str,
    tools: list[dict[str, Any]],
    generate: TurnGenerator,
    max_model_calls: int = 3,
) -> CurrentCaseResult:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": render_user_prompt(case)},
    ]
    script_index = 0
    model_calls = 0
    tool_calls = 0
    latency_nanos = 0
    calls_match = True
    arguments_valid = True
    candidate_keys: set[str] = set()
    accepted_meaning: dict[str, Any] | None = None
    fault_injected = False
    fault_observed = False
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
            try:
                validate_tool_arguments(case["caseId"], call.get("arguments"))
                valid_arguments = (
                    set(call) == {"id", "name", "arguments"}
                    and isinstance(call["id"], str)
                    and bool(call["id"])
                    and call["name"] == "catalog_search"
                )
            except (ValueError, TypeError):
                valid_arguments = False
            arguments_valid = arguments_valid and valid_arguments
            expected = case["script"][script_index] if script_index < len(case["script"]) else None
            matched = valid_arguments and expected is not None and step_accepts(expected, call["arguments"])
            calls_match = calls_match and matched
            if matched:
                result = expected["result"]
                script_index += 1
                meaning = call["arguments"]["dateMeaning"]
                accepted_meaning = accepted_meaning or meaning
                if accepted_meaning != meaning:
                    calls_match = False
                candidates, injected, observed = _tool_payload(result)
                candidate_keys.update(candidate["key"] for candidate in candidates)
                fault_injected = fault_injected or injected
                fault_observed = fault_observed or observed
            else:
                result = json.dumps({"error": "synthetic_fixture_rejected_unexpected_tool_arguments"})
            messages.append(
                {
                    "role": "tool",
                    "toolCallId": str(call.get("id", "invalid-call")),
                    "name": "catalog_search",
                    "content": result,
                }
            )
            if matched and script_index == len(case["script"]):
                messages.append({"role": "user", "content": finalization_prompt(accepted_meaning)})
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

    expected_calls = len(case["script"])
    correct_operation = calls_match and script_index == expected_calls and tool_calls == expected_calls
    schema_valid = False
    date_accuracy = False
    selected = _selected_keys(final)
    if accepted_meaning is not None:
        try:
            validate_final(case["caseId"], json.dumps(final), candidate_keys, accepted_meaning)
            schema_valid = True
            date_accuracy = meanings_equivalent(final["dateMeaning"], case["expectation"]["dateMeaning"])
            selected = [pick["key"] for pick in final["picks"]]
        except (ValueError, TypeError):
            pass
    unsupported = sum(key not in candidate_keys for key in selected)
    authority_violations = _authority_violation_count(final)
    expectation = case["expectation"]
    grounded = schema_valid and unsupported == 0 and (
        len(selected) == 0 if expectation["abstain"] else len(selected) > 0
    )
    actual_selected = set(selected)
    expected_selected = set(expectation["selectedKeys"])
    forbidden = set(expectation["forbiddenKeys"])
    proposal_quality = (
        schema_valid
        and unsupported == 0
        and actual_selected == expected_selected
        and not actual_selected & forbidden
        and bool(final["channelName"].strip())
        and bool(final["rationale"].strip())
    )
    policy_accuracy = schema_valid and policy_matches(expectation["policy"], final["policy"])
    recovery_expected = case["axis"] == "observed-fault-recovery"
    recovery_successful = (
        not recovery_expected
        or (
            expectation.get("faultInjected") is True
            and expectation.get("faultObserved") is True
            and fault_injected
            and fault_observed
            and correct_operation
            and proposal_quality
            and tool_calls >= 2
        )
    )
    hard_failures: list[str] = []
    if not schema_valid:
        hard_failures.append("schema_invalid")
    if not arguments_valid:
        hard_failures.append("invalid_tool_arguments")
    if not correct_operation:
        hard_failures.append("incorrect_tool_operation")
    if unsupported:
        hard_failures.append("unsupported_key")
    if authority_violations:
        hard_failures.append("authority_violation")
    if accepted_meaning is not None and not date_accuracy:
        hard_failures.append("date_meaning_mismatch")
    if recovery_expected and not recovery_successful:
        hard_failures.append("recovery_without_observed_fault")

    return CurrentCaseResult(
        caseId=case["caseId"],
        axis=case["axis"],
        groundedCompletion=grounded,
        correctToolOperation=correct_operation,
        argumentValidity=arguments_valid,
        schemaValidity=schema_valid,
        dateMeaningAccuracy=date_accuracy,
        policyAccuracy=policy_accuracy,
        proposalQuality=proposal_quality,
        recoveryExpected=recovery_expected,
        faultInjected=fault_injected,
        faultObserved=fault_observed,
        recoverySuccessful=recovery_successful,
        unsupportedKeyCount=unsupported,
        authorityViolationCount=authority_violations,
        modelCalls=model_calls,
        toolCalls=tool_calls,
        latencyNanos=latency_nanos,
        hardFailures=hard_failures,
        transcript=messages,
    )
