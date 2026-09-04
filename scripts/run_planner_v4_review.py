#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from loomarr_models.experiment import _git_probe, sha256_file
from loomarr_models.model_review import CRITERIA, ModelReviewError, RequestPlan
from loomarr_models.planner_v4 import validate_delta_training
from loomarr_models.v4_model_review import (
    REVIEWERS,
    V4ReviewPreflightError,
    preflight,
    request_payload,
    request_plan_bytes,
)
from loomarr_models.validator import load_contract, load_denylist, load_jsonl
from run_planner_model_review import _verify_live_routes, run


CONFIG_PATH = ROOT / "experiments/planner-v4-delta-review-v1.json"
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
    "budget",
    "routeSnapshot",
    "trainingDrafts",
    "trainingManifest",
    "developmentCases",
    "developmentManifest",
    "disjointnessReport",
    "reviewDecisions",
    "corpusValidator",
    "v4Validator",
    "reviewValidator",
    "reviewPreflightValidator",
    "reviewRunner",
    "corpusGenerator",
    "requestPlan",
}
EXECUTION = {
    "apiBaseUrl": "https://openrouter.ai/api/v1",
    "batchSize": 1,
    "maxCalls": 120,
    "maxOutputTokensPerCall": 3000,
    "reasoningEffort": "medium",
    "outputDir": ".artifacts/planner-v4-delta-review-v1",
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
    parser = argparse.ArgumentParser(description="Fail-closed planner v4 delta dual review")
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
        raise V4ReviewPreflightError("v4 review config fields differ from schema v1")
    if (
        config.get("reviewId") != "planner-v4-delta-review-v1"
        or config.get("issue") != "https://github.com/loomarr/loomarr-models/issues/22"
        or config.get("candidateFamily") != "qwen"
        or config.get("criteria") != list(CRITERIA)
        or config.get("reviewers") != list(REVIEWERS)
    ):
        raise V4ReviewPreflightError("v4 review authority or reviewer identity drifted")
    execution = config["execution"]
    authorized = (
        config.get("status") == "ready-for-review"
        and execution.get("paidReviewAuthorized") is True
    )
    if require_authorized and not authorized:
        raise V4ReviewPreflightError("paid v4 review is not authorized")
    expected_execution = {**EXECUTION, "paidReviewAuthorized": authorized}
    if execution != expected_execution:
        raise V4ReviewPreflightError("v4 review execution envelope drifted")
    if config.get("status") not in ({"ready-for-review"} if authorized else {"planned-no-paid-calls-authorized"}):
        raise V4ReviewPreflightError("v4 review status and authorization disagree")

    bindings = config["bindings"]
    if not isinstance(bindings, dict) or set(bindings) != EXPECTED_BINDINGS:
        raise V4ReviewPreflightError("v4 review bindings differ from the exact plan")
    bound: dict[str, Path] = {}
    for name, binding in bindings.items():
        if not isinstance(binding, dict) or not {"path", "sha256"} <= set(binding):
            raise V4ReviewPreflightError(f"invalid {name} binding")
        path = _input_path(ROOT / binding["path"])
        if sha256_file(path) != binding["sha256"]:
            raise V4ReviewPreflightError(f"{name} digest mismatch")
        bound[name] = path

    contract = load_contract(bound["contract"])
    identities, digests = load_denylist(bound["holdoutDenylist"])
    traces = load_jsonl(bound["trainingDrafts"])
    report = validate_delta_training(
        traces,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    if report.records != 60 or any(trace["review"]["status"] != "pending" for trace in traces):
        raise V4ReviewPreflightError("v4 review input must be exactly 60 pending traces")
    snapshot = _object(bound["routeSnapshot"])
    budget = _object(bound["budget"])
    checked = preflight(
        traces,
        contract=contract,
        route_snapshot=snapshot,
        budget=budget,
        reservation_usd=config["budget"]["reviewReservationUsd"],
        max_output_tokens=execution["maxOutputTokensPerCall"],
    )
    if checked.summary() != config["preflight"]:
        raise V4ReviewPreflightError("committed v4 preflight summary drifted")
    expected_budget = {
        "aggregateAuthorizationUsd": checked.authorization_usd,
        "currentCommittedUsd": checked.committed_spend_usd,
        "reviewReservationUsd": checked.reservation_usd,
        "projectedMaximumUsd": checked.projected_spend_usd,
        "remainingAfterMaximumUsd": str(
            Decimal(checked.authorization_usd) - Decimal(checked.projected_spend_usd)
        ),
        "worstCaseReviewUsd": checked.worst_case_cost_usd,
    }
    if config["budget"] != expected_budget:
        raise V4ReviewPreflightError("v4 review budget projection drifted")
    if request_plan_bytes(checked.requests) != bound["requestPlan"].read_bytes():
        raise V4ReviewPreflightError("committed v4 request plan drifted")

    runtime_requests: list[RequestPlan] = []
    summaries = iter(checked.requests)
    for reviewer, route in zip(REVIEWERS, snapshot["reviewers"], strict=True):
        for batch_index, trace in enumerate(traces):
            summary = next(summaries)
            payload = request_payload(
                reviewer,
                trace,
                contract=contract,
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
                or summary.batch_index != batch_index
                or summary.request_sha256 != hashlib.sha256(payload_bytes).hexdigest()
            ):
                raise V4ReviewPreflightError("runtime request differs from committed v4 plan")
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
                    requestSha256=summary.request_sha256,
                    inputTokenUpperBound=summary.input_byte_upper_bound,
                    worstCaseCostUsd=summary.worst_case_cost_usd,
                    payload=payload,
                )
            )
    critical = [config_path, *bound.values(), Path(__file__)]
    source_commit = (git_probe or _git_probe)(ROOT, critical)
    plan = RunnablePlan(
        reviewId=config["reviewId"],
        configSha256=sha256_file(config_path),
        corpusSha256=report.sha256,
        traceCount=checked.trace_count,
        requestCount=checked.request_count,
        inputTokenUpperBound=checked.input_byte_upper_bound,
        outputTokenUpperBound=checked.output_token_upper_bound,
        worstCaseCostUsd=checked.worst_case_cost_usd,
        reservationUsd=checked.reservation_usd,
        committedSpendUsd=checked.committed_spend_usd,
        projectedSpendUsd=checked.projected_spend_usd,
        authorizationUsd=checked.authorization_usd,
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
        raise V4ReviewPreflightError("v4 review input escapes the repository")
    return resolved


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V4ReviewPreflightError(f"{path.name} must be an object")
    return value


if __name__ == "__main__":
    main()
