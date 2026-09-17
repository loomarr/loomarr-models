from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

from .current_contract import (
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_current_development_case,
    validate_final,
    validate_tool_arguments,
)
from .experiment import HEAVY_MODULE_PREFIXES, PreflightError, _git_probe, _input_path, _output_path, sha256_file


EXPERIMENT_ID = "planner-current-qwen-stock-baseline-v2"
ISSUE = "https://github.com/loomarr/loomarr-models/issues/25"
CANDIDATE_ID = "qwen38-27b-unsloth-bnb-4bit"
FIXTURE_ID = "planner-current-development-catalog-v1"
FORBIDDEN_AUTHORITY_KEYS = {
    "approved",
    "authorized",
    "channelId",
    "acquisitionApproved",
    "admissionApproved",
    "playbackAuthorized",
}
CONFIG_KEYS = {
    "schemaVersion",
    "experimentId",
    "issue",
    "status",
    "bindings",
    "model",
    "execution",
    "comparison",
    "scoring",
    "decision",
    "hostedProductionComparison",
    "budget",
    "authority",
}
BINDING_KEYS = {
    "authorization",
    "budgetLedger",
    "cases",
    "casesManifest",
    "contract",
    "environment",
    "generator",
    "holdoutDenylist",
    "preflight",
    "publisher",
    "runner",
    "runtime",
}
AUTHORITY = {
    "paidBaselineAuthorized": True,
    "modelDownloadAuthorized": True,
    "gpuAuthorized": True,
    "trainingAuthorized": False,
    "certificationAuthority": False,
    "deploymentAuthority": False,
    "releaseAuthority": False,
}
MODEL = {
    "candidateId": CANDIDATE_ID,
    "repository": "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
    "revision": "8aa5f05d26b7205477066e1449e0af13f762a299",
    "quantization": "unsloth-bnb-4bit",
}
EXECUTION = {
    "platform": "linux-amd64",
    "cloud": "SECURE",
    "gpuSku": "NVIDIA A40",
    "gpuCount": 1,
    "minimumVramGb": 48,
    "minimumCudaVersion": "12.8",
    "containerImage": "runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851",
    "containerDiskGb": 40,
    "networkVolumeGb": 40,
    "maxWallClockSeconds": 9000,
    "outputDir": ".artifacts/planner-current-qwen-stock-baseline-v2",
    "requireCleanGit": True,
    "automaticRetry": False,
}
COMPARISON = {
    "seed": 3407,
    "maxSeqLength": 4096,
    "maxNewTokens": 2048,
    "maxModelCallsPerCase": 3,
    "disableCompile": True,
    "offloadEmbedding": False,
    "reasoningEffort": "low",
    "doSample": False,
    "temperature": None,
    "topP": None,
    "trials": 1,
    "sameCasesAndOrderRequiredForAdapter": True,
}
SCORING = {
    "scorerVersion": "planner-current-development-scorer-v2",
    "thresholds": {
        "maxP95ToolCalls": 2,
        "minCorrectToolOperationRate": 0.90,
        "minGroundedCompletionRate": 0.95,
        "minSchemaValidityRate": 0.98,
        "minDateMeaningAccuracyRate": 1.0,
        "minPolicyAccuracyRate": 0.95,
        "minProposalQualityRate": 0.90,
        "minRecoveryRate": 1.0,
    },
}
HOSTED_COMPARISON = {
    "status": "preregistered-no-provider-inference-authorized",
    "exactCurrentContractRequired": True,
    "sameCasesAndOrderRequired": True,
    "historicalScoresComparable": False,
    "certificationAuthority": False,
}

TurnGenerator = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]
GitProbe = Callable[[Path, Iterable[Path]], str]


@dataclass(frozen=True)
class CurrentCaseResult:
    caseId: str
    axis: str
    groundedCompletion: bool
    correctToolOperation: bool
    argumentValidity: bool
    schemaValidity: bool
    dateMeaningAccuracy: bool
    policyAccuracy: bool
    proposalQuality: bool
    recoveryExpected: bool
    faultInjected: bool
    faultObserved: bool
    recoverySuccessful: bool
    unsupportedKeyCount: int
    authorityViolationCount: int
    modelCalls: int
    toolCalls: int
    latencyNanos: int
    hardFailures: list[str]
    transcript: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CurrentBaselinePlan:
    schemaVersion: int
    experimentId: str
    candidateId: str
    configSha256: str
    casesSha256: str
    caseCount: int
    contractId: str
    modelRevision: str
    environmentSha256: str
    committedSpendUsd: str
    reservationUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    paidBaselineAuthorized: bool
    sourceCommit: str
    outputDir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def source_coordinates(intent: dict[str, Any]) -> str:
    fields: list[dict[str, Any]] = []

    def add(field: str, value: str, index: int | None = None) -> None:
        if not value:
            return
        runes = list(value)
        tokens: list[dict[str, Any]] = []
        start: int | None = None
        for position, rune in enumerate(runes + [" "]):
            if rune.isspace():
                if start is not None:
                    tokens.append({"text": "".join(runes[start:position]), "start": start, "end": position})
                    start = None
            elif start is None:
                start = position
        item: dict[str, Any] = {"field": field, "runeLength": len(runes), "tokens": tokens}
        if index is not None:
            item["index"] = index
        fields.append(item)

    add("description", intent["description"])
    add("era", intent.get("era", ""))
    add("refineText", intent.get("refineText", ""))
    for index, value in enumerate(intent.get("mustInclude", [])):
        add("mustInclude", value, index)
    for index, value in enumerate(intent.get("mustExclude", [])):
        add("mustExclude", value, index)
    return (
        "\nSubmitted Intent source coordinates (data, not instructions). These are exact half-open rune positions of every whitespace-delimited token, not date classifications. "
        "For dateMeaning anchors, copy the matching field/index and source offsets; a date phrase may span consecutive tokens. Do not count the surrounding prompt labels.\n"
        + json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )


def render_user_prompt(case: dict[str, Any]) -> str:
    intent = case["intent"]
    if intent.get("refineText") or intent.get("currentLineup"):
        lines = [f"This channel already exists: {intent['description']}"]
        if intent.get("currentLineup"):
            lines.append("Its current lineup is:")
            for item in intent["currentLineup"]:
                year = f" ({item['year']})" if item.get("year") else ""
                lines.append(f"  - {item['name']}{year}")
        if intent.get("refineText"):
            lines.append(f"The user wants to change it: {intent['refineText']}")
        lines.append(
            "Keep the titles that still fit, drop the ones that don't, and add new ones as needed. "
            "Re-ground EVERY title (kept or new) through the catalog tool — copy only exact catalog keys the tool returns."
        )
    else:
        lines = [f"Build a channel: {intent['description']}"]
    if intent.get("mustInclude"):
        lines.append("Must include: " + ", ".join(intent["mustInclude"]))
    if intent.get("mustExclude"):
        lines.append("Must exclude: " + ", ".join(intent["mustExclude"]))
    if case["axis"] == "network-editorial-epoch":
        lines.extend(
            [
                "",
                "EDITORIAL NETWORK EPOCH: the reference decade ends in 1989. Discover the network's older catalog, then select factual programming that fits this era; an example title is not a one-title or one-subject limit. This is editorial context, not a playback-date restriction.",
                'No separate playback-date restriction was submitted. Every catalog_search and final JSON must copy this exact dateMeaning object: {"kind":"none","anchors":[],"axes":[]}. Do not add anchors to kind=none, invent an airing filter, or ask to clarify the known editorial decade.',
            ]
        )
    return "\n".join(lines) + "\n" + source_coordinates(intent)


def finalization_prompt(date_meaning: dict[str, Any]) -> str:
    return (
        "Retrieval is complete and no further tools are available. Produce the final JSON now using only the catalog candidates already provided; "
        "an incomplete catalog result does not authorize another search. Copy this accepted dateMeaning object unchanged into your final JSON: "
        + json.dumps(date_meaning, separators=(",", ":"))
    )


def _selected_keys(final: Any) -> list[str]:
    if not isinstance(final, dict) or not isinstance(final.get("picks"), list):
        return []
    return [
        pick["key"]
        for pick in final["picks"]
        if isinstance(pick, dict) and isinstance(pick.get("key"), str)
    ]


def evaluate_current_case(
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
            matched = valid_arguments and expected is not None and call["arguments"] == expected["arguments"]
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
            date_accuracy = final["dateMeaning"] == case["expectation"]["dateMeaning"]
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
    expected_policy = (
        {"audience": {"ceiling": "TV-14"}}
        if case["axis"] == "audience-ceiling"
        else {}
    )
    policy_accuracy = schema_valid and final["policy"] == expected_policy
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


def summarize_current_candidate(
    candidate_id: str,
    results: Iterable[CurrentCaseResult],
    *,
    peak_vram_bytes: int = 0,
) -> dict[str, Any]:
    items = list(results)
    if not items:
        raise ValueError("candidate result set is empty")
    recovery = [item for item in items if item.recoveryExpected]
    fields = {
        "groundedCompletionRate": "groundedCompletion",
        "correctToolOperationRate": "correctToolOperation",
        "argumentValidityRate": "argumentValidity",
        "schemaValidityRate": "schemaValidity",
        "dateMeaningAccuracyRate": "dateMeaningAccuracy",
        "policyAccuracyRate": "policyAccuracy",
        "proposalQualityRate": "proposalQuality",
    }
    summary: dict[str, Any] = {
        "candidateId": candidate_id,
        "caseCount": len(items),
        "caseIds": [item.caseId for item in items],
        **{name: _rate(items, field) for name, field in fields.items()},
        "recoveryRate": _rate(recovery, "recoverySuccessful"),
        "hardFailureCount": sum(len(item.hardFailures) for item in items),
        "unsupportedKeyCount": sum(item.unsupportedKeyCount for item in items),
        "authorityViolationCount": sum(item.authorityViolationCount for item in items),
        "latencyP50Nanos": int(median(item.latencyNanos for item in items)),
        "latencyP95Nanos": _nearest_rank([item.latencyNanos for item in items], 0.95),
        "p95ToolCalls": _nearest_rank([item.toolCalls for item in items], 0.95),
        "peakVramBytes": peak_vram_bytes,
        "capabilities": {
            item.axis: {
                "passed": not item.hardFailures and item.proposalQuality and item.correctToolOperation,
                "hardFailures": item.hardFailures,
            }
            for item in items
        },
        "caseMetrics": [
            {key: value for key, value in item.as_dict().items() if key != "transcript"}
            for item in items
        ],
    }
    summary["caseIdsSha256"] = hashlib.sha256(
        json.dumps(summary["caseIds"], separators=(",", ":")).encode()
    ).hexdigest()
    return summary


def baseline_decision(
    summary: dict[str, Any], scoring: dict[str, Any], *, run_status: str = "complete-model-quality"
) -> dict[str, Any]:
    if run_status != "complete-model-quality":
        return {
            "outcome": "baseline-invalid-no-training-decision",
            "failureClass": run_status,
            "thresholdFailures": [],
            "qloraJustified": False,
            "trainingAuthorized": False,
            "releaseAuthorized": False,
            "certificationAuthority": False,
        }
    thresholds = scoring["thresholds"]
    checks = (
        ("groundedCompletionRate", "minGroundedCompletionRate", lambda actual, limit: actual >= limit),
        ("correctToolOperationRate", "minCorrectToolOperationRate", lambda actual, limit: actual >= limit),
        ("schemaValidityRate", "minSchemaValidityRate", lambda actual, limit: actual >= limit),
        ("dateMeaningAccuracyRate", "minDateMeaningAccuracyRate", lambda actual, limit: actual >= limit),
        ("policyAccuracyRate", "minPolicyAccuracyRate", lambda actual, limit: actual >= limit),
        ("proposalQualityRate", "minProposalQualityRate", lambda actual, limit: actual >= limit),
        ("recoveryRate", "minRecoveryRate", lambda actual, limit: actual >= limit),
        ("p95ToolCalls", "maxP95ToolCalls", lambda actual, limit: actual <= limit),
    )
    failures = [metric for metric, threshold, accepted in checks if not accepted(summary[metric], thresholds[threshold])]
    if summary["hardFailureCount"]:
        failures.append("hardFailureCount")
    justified = bool(failures)
    return {
        "outcome": (
            "qlora-justified-by-completed-stock-quality-miss"
            if justified
            else "qlora-not-justified-stock-clears-current-development-gate"
        ),
        "failureClass": "model-quality" if justified else None,
        "thresholdFailures": failures,
        "qloraJustified": justified,
        "trainingAuthorized": False,
        "releaseAuthorized": False,
        "certificationAuthority": False,
    }


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load current stock baseline config {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS or value.get("schemaVersion") != 2:
        raise PreflightError("current stock baseline config fields differ from schema v2")
    return value


def preflight(
    root: Path,
    config_path: Path,
    *,
    require_authorized: bool = True,
    git_probe: GitProbe | None = None,
) -> CurrentBaselinePlan:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_config(config_path)
    _validate_config_shape(config, require_authorized=require_authorized)
    bound: dict[str, Path] = {}
    for name, binding in config["bindings"].items():
        allowed = {"path", "sha256", "records"} if name == "cases" else {"path", "sha256"}
        if not isinstance(binding, dict) or set(binding) != allowed:
            raise PreflightError(f"invalid current stock baseline {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"current stock baseline {name} digest mismatch")

    contract = _object(bound["contract"])
    if contract.get("schemaVersion") != 2 or contract.get("contractId") != "loomarr-planner-contract-v5":
        raise PreflightError("current stock baseline contract drifted")
    exact, normalized, minimum, protected_keys = load_current_denylist(bound["holdoutDenylist"])
    cases = read_jsonl(bound["cases"])
    for case in cases:
        try:
            validate_current_development_case(case, contract, FIXTURE_ID)
            assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected_keys)
        except ValueError as exc:
            raise PreflightError(str(exc)) from exc
    if len(cases) != 24 or config["bindings"]["cases"]["records"] != 24:
        raise PreflightError("current stock baseline requires the exact 24-case development gate")
    case_sha = sha256_file(bound["cases"])
    manifest = _object(bound["casesManifest"])
    if (
        manifest.get("evaluationId") != "planner-current-development-v1"
        or manifest.get("records") != 24
        or manifest.get("sha256") != case_sha
        or manifest.get("modelExposure") != "none"
        or manifest.get("certificationAuthority") is not False
        or manifest.get("contract") != config["bindings"]["contract"]
        or manifest.get("holdoutDenylist") != config["bindings"]["holdoutDenylist"]
    ):
        raise PreflightError("current development manifest drifted")
    _validate_environment(_object(bound["environment"]), config)
    _validate_authorization(_object(bound["authorization"]), config)
    committed, reservation, projected, authorization = _validate_budget(config, _object(bound["budgetLedger"]))
    output = _output_path(root, Path(config["execution"]["outputDir"]))
    source_commit = (git_probe or _git_probe)(root, [config_path, *bound.values()])
    imported = sorted(name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES)
    if imported:
        raise PreflightError(f"heavyweight modules imported before current baseline preflight: {imported[0]}")
    return CurrentBaselinePlan(
        schemaVersion=2,
        experimentId=EXPERIMENT_ID,
        candidateId=CANDIDATE_ID,
        configSha256=sha256_file(config_path),
        casesSha256=case_sha,
        caseCount=len(cases),
        contractId=contract["contractId"],
        modelRevision=config["model"]["revision"],
        environmentSha256=sha256_file(bound["environment"]),
        committedSpendUsd=str(committed),
        reservationUsd=str(reservation),
        projectedSpendUsd=str(projected),
        authorizationUsd=str(authorization),
        paidBaselineAuthorized=config["authority"]["paidBaselineAuthorized"],
        sourceCommit=source_commit,
        outputDir=str(output.relative_to(root)),
    )


def _validate_config_shape(config: dict[str, Any], *, require_authorized: bool) -> None:
    if config["experimentId"] != EXPERIMENT_ID or config["issue"] != ISSUE:
        raise PreflightError("current stock baseline identity drifted")
    if set(config["bindings"]) != BINDING_KEYS:
        raise PreflightError("current stock baseline bindings drifted")
    if config["status"] == "complete-settled":
        raise PreflightError("current stock baseline is terminal and cannot run again")
    if config["authority"] != AUTHORITY:
        raise PreflightError("current stock baseline authority drifted")
    if config["status"] != "ready-for-paid-baseline":
        raise PreflightError("current stock baseline status drifted")
    if require_authorized and not config["authority"]["paidBaselineAuthorized"]:
        raise PreflightError("paid current stock baseline is not authorized")
    if config["model"] != MODEL:
        raise PreflightError("current stock baseline candidate drifted")
    if config["execution"] != EXECUTION:
        raise PreflightError("current stock baseline execution envelope drifted")
    if config["comparison"] != COMPARISON:
        raise PreflightError("current stock baseline comparison protocol drifted")
    if config["scoring"] != SCORING:
        raise PreflightError("current stock baseline scoring protocol drifted")
    if config["hostedProductionComparison"] != HOSTED_COMPARISON:
        raise PreflightError("hosted production comparison contract drifted")
    if config["decision"] != {
        "passingStockStopsTraining": True,
        "runtimeOrInfrastructureFailureJustifiesTraining": False,
        "requiresObservedRecoveryFault": True,
        "applicationRecoveryBlocker": "https://github.com/loomarr/loomarr/issues/1195",
    }:
        raise PreflightError("current stock baseline decision contract drifted")


def _validate_environment(environment: dict[str, Any], config: dict[str, Any]) -> None:
    artifact = environment.get("trainingArtifact", {})
    model = config["model"]
    execution = config["execution"]
    if (
        environment.get("environmentId") != "qwen38-a40-v1"
        or environment.get("platform", {}).get("validatedSku") != execution["gpuSku"]
        or artifact.get("repository") != model.get("repository")
        or artifact.get("revision") != model.get("revision")
        or artifact.get("quantization") != model.get("quantization")
    ):
        raise PreflightError("current stock baseline environment or model drifted")


def _validate_authorization(authorization: dict[str, Any], config: dict[str, Any]) -> None:
    expected = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "authorized",
        "maxReservationUsd": "1.50",
        "authorizedBy": "loomarr-maintainer",
        "authorizedAt": "2026-09-17T02:32:20Z",
        "authorizedPlanCommit": "1bd481c2cabd48a9fade02c2c750508cf4905de2",
    }
    if authorization != expected or config["budget"]["proposedReservationUsd"] != expected["maxReservationUsd"]:
        raise PreflightError("current stock baseline authorization evidence drifted")


def _validate_budget(
    config: dict[str, Any], ledger: dict[str, Any]
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    try:
        authorization = Decimal(ledger["authorizationUsd"])
        posted = Decimal(ledger["postedSpendUsd"])
        outstanding = Decimal(ledger["outstandingReservationsUsd"])
        committed = Decimal(ledger["committedSpendUsd"])
        reservation = Decimal(config["budget"]["proposedReservationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("invalid current stock baseline budget") from exc
    if posted + outstanding != committed or reservation != Decimal("1.50"):
        raise PreflightError("current stock baseline budget or reservation does not reconcile")
    projected = committed + reservation
    if config["budget"] != {
        "aggregateAuthorizationUsd": str(authorization),
        "currentCommittedUsd": str(committed),
        "outstandingReservationsUsd": str(outstanding),
        "proposedReservationUsd": "1.50",
        "projectedCommitmentUsd": str(projected),
        "remainingAuthorizationUsd": str(authorization - projected),
    }:
        raise PreflightError("current stock baseline budget projection drifted")
    if projected > authorization:
        raise PreflightError("current stock baseline would exceed aggregate authorization")
    return committed, reservation, projected, authorization


def _tool_payload(content: str) -> tuple[list[dict[str, Any]], bool, bool]:
    payload = json.loads(content)
    if isinstance(payload, list):
        return payload, False, False
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        fault = payload.get("fault", {})
        return [], fault.get("injected") is True, fault.get("observed") is True
    raise ValueError("invalid current tool result")


def _authority_violation_count(value: Any) -> int:
    if isinstance(value, dict):
        return sum(key in FORBIDDEN_AUTHORITY_KEYS for key in value) + sum(
            _authority_violation_count(child) for child in value.values()
        )
    if isinstance(value, list):
        return sum(_authority_violation_count(child) for child in value)
    return 0


def _rate(items: list[CurrentCaseResult], field: str) -> float:
    if not items:
        return 1.0
    return sum(bool(getattr(item, field)) for item in items) / len(items)


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must be an object")
    return value
