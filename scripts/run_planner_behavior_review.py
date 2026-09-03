#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from loomarr_models.behavior_model_review import (
    REVIEWERS,
    BehaviorReviewPreflightError,
    preflight,
    request_payload,
    request_plan_bytes,
)
from loomarr_models.experiment import _git_probe, sha256_file
from loomarr_models.model_review import CRITERIA, ModelReviewError, RequestPlan
from loomarr_models.targeted import validate_targeted_training
from loomarr_models.validator import load_contract, load_denylist, load_jsonl
from run_planner_model_review import _verify_live_routes, run


CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v2.json"
CONFIG_KEYS = {
    "schemaVersion",
    "reviewId",
    "issue",
    "status",
    "candidateFamily",
    "criteria",
    "reviewers",
    "execution",
    "budget",
    "preflight",
    "bindings",
}
EXPECTED_BINDINGS = {
    "contract",
    "holdoutDenylist",
    "priorTraining",
    "priorDevelopment",
    "reviewDecisions",
    "reviewPolicy",
    "reviewValidator",
    "targetedValidator",
    "budget",
    "routeSnapshot",
    "reviewPreflightValidator",
    "reviewRunner",
    "trainingDrafts",
    "trainingManifest",
    "developmentCases",
    "developmentManifest",
    "disjointnessReport",
    "requestPlan",
}
EXPECTED_EXECUTION = {
    "apiBaseUrl": "https://openrouter.ai/api/v1",
    "batchSize": 1,
    "maxCalls": 240,
    "maxOutputTokensPerCall": 3000,
    "reasoningEffort": "medium",
    "compactTracePacket": True,
    "multiTraceBatchAuthorized": False,
    "outputDir": ".artifacts/planner-behavior-review-v2",
    "requestTimeoutSeconds": 180,
    "settlementAttempts": 60,
    "settlementDelaySeconds": 1,
    "requireCleanGit": True,
    "strictStructuredOutput": True,
    "providerFallback": False,
    "providerDataCollection": "deny",
    "automaticInferenceRetry": False,
}


@dataclass(frozen=True)
class RunnablePlan:
    reviewId: str
    configSha256: str
    corpusSha256: str
    traceCount: int
    requestCount: int
    inputTokenUpperBound: int
    outputTokenUpperBound: int
    worstCaseCostUsd: str
    reservationUsd: str
    committedSpendUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    sourceCommit: str
    outputDir: str
    requests: tuple[RequestPlan, ...]
    paidReviewAuthorized: bool

    def report(self) -> dict[str, Any]:
        value = asdict(self)
        del value["requests"]
        return value


GitProbe = Callable[[Path, Iterable[Path]], str]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed targeted planner dual review")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        config, plan, snapshot = build_plan(
            config_path,
            require_authorized=not args.preflight_only,
        )
        if args.preflight_only:
            print(json.dumps(plan.report(), sort_keys=True))
            return
        api_key = _api_key()
        _verify_live_routes(config, snapshot)
        result = run(config, plan, api_key)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


def build_plan(
    config_path: Path,
    *,
    require_authorized: bool,
    git_probe: GitProbe | None = None,
) -> tuple[dict[str, Any], RunnablePlan, dict[str, Any]]:
    config_path = _input_path(config_path)
    config = _object(config_path)
    if set(config) != CONFIG_KEYS or config.get("schemaVersion") != 1:
        raise BehaviorReviewPreflightError("behavior review config fields differ from schema v1")
    if config.get("reviewId") != "planner-behavior-review-v2":
        raise BehaviorReviewPreflightError("behavior review identity drifted")
    execution = config["execution"]
    authorized = (
        config.get("status") == "ready-for-review"
        and execution.get("paidReviewAuthorized") is True
    )
    if require_authorized and not authorized:
        raise BehaviorReviewPreflightError("paid behavior review is not authorized")
    expected_execution = {**EXPECTED_EXECUTION, "paidReviewAuthorized": authorized}
    if execution != expected_execution:
        raise BehaviorReviewPreflightError("behavior review execution envelope drifted")
    expected_status = "ready-for-review" if authorized else "planned-no-paid-calls-authorized"
    if config.get("status") != expected_status:
        raise BehaviorReviewPreflightError("behavior review status and authorization disagree")
    if (
        config.get("issue") != "https://github.com/loomarr/loomarr-models/issues/9"
        or config.get("candidateFamily") != "qwen"
        or config.get("criteria") != list(CRITERIA)
        or config.get("reviewers") != list(REVIEWERS)
    ):
        raise BehaviorReviewPreflightError("behavior review authority or reviewer identity drifted")

    bindings = config["bindings"]
    if set(bindings) != EXPECTED_BINDINGS:
        raise BehaviorReviewPreflightError("behavior review bindings differ from the exact plan")
    bound: dict[str, Path] = {}
    for name, binding in bindings.items():
        if not isinstance(binding, dict) or not {"path", "sha256"} <= set(binding):
            raise BehaviorReviewPreflightError(f"invalid {name} binding")
        path = _input_path(ROOT / binding["path"])
        if sha256_file(path) != binding["sha256"]:
            raise BehaviorReviewPreflightError(f"{name} digest mismatch")
        bound[name] = path

    contract = load_contract(bound["contract"])
    identities, digests = load_denylist(bound["holdoutDenylist"])
    traces = load_jsonl(bound["trainingDrafts"])
    report = validate_targeted_training(
        traces,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    snapshot = _object(bound["routeSnapshot"])
    budget = _object(bound["budget"])
    checked = preflight(
        traces,
        route_snapshot=snapshot,
        budget=budget,
        batch_size=execution["batchSize"],
        max_output_tokens=execution["maxOutputTokensPerCall"],
        reservation_usd=config["budget"]["reviewReservationUsd"],
    )
    if checked.summary() != config["preflight"]:
        raise BehaviorReviewPreflightError("committed preflight summary drifted")
    expected_budget = {
        "aggregateAuthorizationUsd": checked.authorizationUsd,
        "currentCommittedUsd": checked.committedSpendUsd,
        "reviewReservationUsd": checked.reservationUsd,
        "projectedMaximumUsd": checked.projectedSpendUsd,
        "remainingAfterMaximumUsd": "5.7194634324327180",
        "worstCaseReviewUsd": checked.worstCaseCostUsd,
    }
    if config["budget"] != expected_budget:
        raise BehaviorReviewPreflightError("behavior review budget projection drifted")
    if request_plan_bytes(checked) != bound["requestPlan"].read_bytes():
        raise BehaviorReviewPreflightError("committed request plan drifted")

    routes = snapshot["reviewers"]
    runtime_requests: list[RequestPlan] = []
    summaries = iter(checked.requests)
    for reviewer, route in zip(REVIEWERS, routes, strict=True):
        for batch_index, trace in enumerate(traces):
            summary = next(summaries)
            payload = request_payload(
                reviewer,
                [trace],
                max_output_tokens=execution["maxOutputTokensPerCall"],
            )
            payload_bytes = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
            if (
                summary.role != reviewer["role"]
                or summary.batchIndex != batch_index
                or summary.requestSha256 != hashlib.sha256(payload_bytes).hexdigest()
            ):
                raise BehaviorReviewPreflightError(
                    "runtime request differs from committed request plan"
                )
            runtime_requests.append(
                RequestPlan(
                    role=reviewer["role"],
                    model=reviewer["model"],
                    family=reviewer["family"],
                    providerTag=reviewer["providerTag"],
                    providerDisplayName=route["providerDisplayName"],
                    upstreamModel=route["upstreamModel"],
                    batchIndex=batch_index,
                    traceIds=(trace["traceId"],),
                    requestSha256=summary.requestSha256,
                    inputTokenUpperBound=summary.inputByteUpperBound,
                    worstCaseCostUsd=summary.worstCaseCostUsd,
                    payload=payload,
                )
            )
    try:
        next(summaries)
    except StopIteration:
        pass
    else:  # pragma: no cover - guarded by exact request-plan count
        raise BehaviorReviewPreflightError("request plan has unconsumed entries")

    critical = [
        config_path,
        *bound.values(),
        Path(__file__),
        ROOT / "src/loomarr_models/behavior_model_review.py",
    ]
    source_commit = (git_probe or _git_probe)(ROOT, critical)
    plan = RunnablePlan(
        reviewId=config["reviewId"],
        configSha256=sha256_file(config_path),
        corpusSha256=report.sha256,
        traceCount=checked.traceCount,
        requestCount=checked.requestCount,
        inputTokenUpperBound=checked.inputByteUpperBound,
        outputTokenUpperBound=checked.outputTokenUpperBound,
        worstCaseCostUsd=checked.worstCaseCostUsd,
        reservationUsd=checked.reservationUsd,
        committedSpendUsd=checked.committedSpendUsd,
        projectedSpendUsd=checked.projectedSpendUsd,
        authorizationUsd=checked.authorizationUsd,
        sourceCommit=source_commit,
        outputDir=execution["outputDir"],
        requests=tuple(runtime_requests),
        paidReviewAuthorized=authorized,
    )
    return config, plan, snapshot


def _api_key() -> str:
    value = os.environ.get("OPENROUTER_API_KEY", "")
    if value:
        return value
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            key, separator, candidate = raw.partition("=")
            if separator and key.strip() == "OPENROUTER_API_KEY":
                value = candidate.strip().strip('"').strip("'")
                break
    if not value:
        raise ModelReviewError("OPENROUTER_API_KEY is not set in the environment or .env")
    return value


def _input_path(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve(strict=True)):
        raise BehaviorReviewPreflightError("review input escapes the repository")
    return resolved


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BehaviorReviewPreflightError(f"{path.name} must be an object")
    return value


if __name__ == "__main__":
    main()
