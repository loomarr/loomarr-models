#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.model_review import (
    ModelReviewContentError,
    ModelReviewError,
    RequestPlan,
    canonical,
    load_config,
    preflight,
    project_live_endpoint,
    settlement_cost,
    validate_completion,
    validate_settlement,
)


DEFAULT_CONFIG = ROOT / "experiments/planner-model-review-v10.json"


class OpenRouterHTTPError(ModelReviewError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(f"OpenRouter HTTP {status_code}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded dual-model planner corpus review")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        plan = preflight(ROOT, config_path)
        if args.preflight_only:
            print(json.dumps(plan.report(), sort_keys=True))
            return
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ModelReviewError("OPENROUTER_API_KEY is not set")
        config = load_config(config_path)
        snapshot_path = ROOT / config["bindings"]["routeSnapshot"]["path"]
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        _verify_live_routes(config, snapshot)
        result = run(config, plan, api_key)
    except (OSError, ModelReviewError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


def run(config: dict[str, Any], plan: Any, api_key: str) -> dict[str, Any]:
    output = ROOT / plan.outputDir
    output.mkdir(parents=True, exist_ok=False)
    calls_dir = output / "calls"
    calls_dir.mkdir()
    started_at = _timestamp()
    state = {
        "schemaVersion": 1,
        "reviewId": plan.reviewId,
        "status": "running",
        "startedAt": started_at,
        "completedCalls": 0,
        "actualCostUsd": "0",
        "reservationUsd": plan.reservationUsd,
        "preflight": plan.report(),
    }
    _write_atomic(output / "run-state.json", _pretty(state))
    attestations: list[dict[str, Any]] = []
    invalid_reviews: list[dict[str, Any]] = []
    call_artifacts: list[dict[str, Any]] = []
    total_cost = Decimal(0)
    try:
        for request in plan.requests:
            stem = f"{request.role}-{request.batchIndex:02d}"
            response_path = calls_dir / f"{stem}.response.json"
            settlement_path = calls_dir / f"{stem}.settlement.json"
            summary_path = calls_dir / f"{stem}.json"
            state["currentCall"] = {
                "stem": stem,
                "requestSha256": request.requestSha256,
                "traceIds": list(request.traceIds),
            }
            _write_atomic(output / "run-state.json", _pretty(state))
            response_bytes, response = _request_json(
                "POST",
                f"{config['execution']['apiBaseUrl']}/chat/completions",
                api_key,
                request.payload,
                config["execution"]["requestTimeoutSeconds"],
            )
            response_sha = hashlib.sha256(response_bytes).hexdigest()
            _write_exclusive(response_path, response_bytes)
            response_id = response.get("id")
            response_usage = response.get("usage")
            reported_cost = (
                response_usage.get("cost", "unknown")
                if isinstance(response_usage, dict)
                else "unknown"
            )
            response_state = {
                "responseSha256": response_sha,
                "responseReportedCostUsd": str(reported_cost),
            }
            if isinstance(response_id, str) and response_id:
                response_state["responseId"] = response_id
            state["currentCall"].update(response_state)
            _write_atomic(output / "run-state.json", _pretty(state))
            provider_error = response.get("error")
            if isinstance(provider_error, dict):
                code = provider_error.get("code", "unknown")
                message = provider_error.get("message", "provider returned an error envelope")
                raise ModelReviewError(f"completion provider error {code}: {message}")
            if not isinstance(response_id, str) or not response_id:
                raise ModelReviewError("completion response has no generation id")
            settlement_bytes, settlement = _settle(config, api_key, response_id)
            settlement_sha = hashlib.sha256(settlement_bytes).hexdigest()
            _write_exclusive(settlement_path, settlement_bytes)
            cost = settlement_cost(settlement)
            total_cost += cost
            state["actualCostUsd"] = str(total_cost)
            state["currentCall"].update(
                {
                    "settlementSha256": settlement_sha,
                    "settledCostUsd": str(cost),
                }
            )
            _write_atomic(output / "run-state.json", _pretty(state))
            if total_cost > Decimal(plan.reservationUsd):
                raise ModelReviewError("settled review cost exceeded the hard reservation")
            if validate_settlement(settlement, request, response) != cost:
                raise ModelReviewError("generation settlement cost changed during validation")
            reviewed_at = _timestamp()
            try:
                parsed = validate_completion(response, request, response_sha)
            except ModelReviewContentError as exc:
                parsed = []
                content_error = str(exc)
                for trace_id in request.traceIds:
                    invalid_reviews.append(
                        {
                            "schemaVersion": 1,
                            "traceId": trace_id,
                            "role": request.role,
                            "reviewer": f"openrouter:{request.model}",
                            "reviewerFamily": request.family,
                            "providerTag": request.providerTag,
                            "requestSha256": request.requestSha256,
                            "responseId": response_id,
                            "responseSha256": response_sha,
                            "reviewedAt": reviewed_at,
                            "batchIndex": request.batchIndex,
                            "settledCostUsd": str(cost),
                            "settlementSha256": settlement_sha,
                            "error": content_error,
                        }
                    )
                call_status = "invalid"
            else:
                for attestation in parsed:
                    attestation.update(
                        {
                            "reviewedAt": reviewed_at,
                            "batchIndex": request.batchIndex,
                            "settledCostUsd": str(cost),
                            "settlementSha256": settlement_sha,
                        }
                    )
                attestations.extend(parsed)
                content_error = None
                call_status = "valid"
            call = {
                "schemaVersion": 1,
                "status": call_status,
                "role": request.role,
                "batchIndex": request.batchIndex,
                "traceIds": list(request.traceIds),
                "requestSha256": request.requestSha256,
                "responseSha256": response_sha,
                "settlementSha256": settlement_sha,
                "settledCostUsd": str(cost),
            }
            if content_error is not None:
                call["contentError"] = content_error
            summary_bytes = _pretty(call)
            _write_exclusive(summary_path, summary_bytes)
            call_artifacts.append(
                {
                    "stem": stem,
                    "summarySha256": hashlib.sha256(summary_bytes).hexdigest(),
                    "responseSha256": response_sha,
                    "settlementSha256": hashlib.sha256(settlement_bytes).hexdigest(),
                }
            )
            state["completedCalls"] += 1
            state["invalidReviewCount"] = len(invalid_reviews)
            del state["currentCall"]
            _write_atomic(output / "run-state.json", _pretty(state))

        _validate_observation_coverage(attestations, invalid_reviews, plan)
        attestation_bytes = b"".join(canonical(item) + b"\n" for item in attestations)
        invalid_review_bytes = b"".join(
            canonical(item) + b"\n" for item in invalid_reviews
        )
        _write_exclusive(output / "attestations.jsonl", attestation_bytes)
        _write_exclusive(output / "invalid-reviews.jsonl", invalid_review_bytes)
        completed_at = _timestamp()
        manifest = {
            "schemaVersion": 1,
            "reviewId": plan.reviewId,
            "status": "complete",
            "startedAt": started_at,
            "completedAt": completed_at,
            "sourceCommit": plan.sourceCommit,
            "configSha256": plan.configSha256,
            "corpusSha256": plan.corpusSha256,
            "requestCount": plan.requestCount,
            "attestationCount": len(attestations),
            "attestationsSha256": hashlib.sha256(attestation_bytes).hexdigest(),
            "invalidReviewCount": len(invalid_reviews),
            "invalidReviewsSha256": hashlib.sha256(invalid_review_bytes).hexdigest(),
            "actualCostUsd": str(total_cost),
            "reservationUsd": plan.reservationUsd,
            "callArtifacts": call_artifacts,
        }
        _write_exclusive(output / "run-manifest.json", _pretty(manifest))
        state.update({"status": "complete", "completedAt": completed_at})
        _write_atomic(output / "run-state.json", _pretty(state))
        return manifest
    except Exception as exc:
        state.update({"status": "failed", "failedAt": _timestamp(), "error": str(exc)[:1000]})
        _write_atomic(output / "run-state.json", _pretty(state))
        raise


def _verify_live_routes(config: dict[str, Any], snapshot: dict[str, Any]) -> None:
    for reviewer, frozen in zip(config["reviewers"], snapshot["reviewers"], strict=True):
        author, model = reviewer["model"].split("/", 1)
        url = f"{config['execution']['apiBaseUrl']}/models/{author}/{model}/endpoints"
        _raw, response = _request_json(
            "GET", url, "", None, config["execution"]["requestTimeoutSeconds"]
        )
        endpoints = response.get("data", {}).get("endpoints", [])
        matches = [
            endpoint
            for endpoint in endpoints
            if endpoint.get("tag") == reviewer["providerTag"] and endpoint.get("status") == 0
        ]
        if len(matches) != 1:
            raise ModelReviewError(f"live route {reviewer['providerTag']} is unavailable or ambiguous")
        live = project_live_endpoint(matches[0], reviewer["role"], reviewer["family"], reviewer["model"])
        if live != frozen:
            raise ModelReviewError(f"live route {reviewer['providerTag']} differs from frozen snapshot")


def _settle(
    config: dict[str, Any], api_key: str, generation_id: str
) -> tuple[bytes, dict[str, Any]]:
    query = urllib.parse.urlencode({"id": generation_id})
    url = f"{config['execution']['apiBaseUrl']}/generation?{query}"
    last: tuple[bytes, dict[str, Any]] | None = None
    for attempt in range(config["execution"]["settlementAttempts"]):
        try:
            last = _request_json(
                "GET", url, api_key, None, config["execution"]["requestTimeoutSeconds"]
            )
        except OpenRouterHTTPError as exc:
            if exc.status_code != 404:
                raise
        else:
            data = last[1].get("data")
            if isinstance(data, dict) and data.get("total_cost") is not None:
                return last
        if attempt + 1 < config["execution"]["settlementAttempts"]:
            time.sleep(config["execution"]["settlementDelaySeconds"])
    raise ModelReviewError(f"generation {generation_id} did not settle within the fixed poll window")


def _request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict[str, Any] | None,
    timeout: int,
) -> tuple[bytes, dict[str, Any]]:
    data = canonical(payload) if payload is not None else None
    headers = {"Accept": "application/json", "User-Agent": "loomarr-model-review/1"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "https://github.com/loomarr/loomarr-models"
        headers["X-Title"] = "Loomarr model review"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", errors="replace")
        raise OpenRouterHTTPError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise ModelReviewError(f"OpenRouter transport error: {exc.reason}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelReviewError("OpenRouter returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ModelReviewError("OpenRouter response must be an object")
    return raw, value


def _validate_observation_coverage(
    attestations: list[dict[str, Any]], invalid_reviews: list[dict[str, Any]], plan: Any
) -> None:
    expected = [
        (request.role, trace_id)
        for request in plan.requests
        for trace_id in request.traceIds
    ]
    actual = [
        (item.get("role"), item.get("traceId"))
        for item in [*attestations, *invalid_reviews]
    ]
    if len(actual) != len(expected) or len(set(actual)) != len(actual) or set(actual) != set(expected):
        raise ModelReviewError("review observations do not cover the exact dual-review set")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def _write_exclusive(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
