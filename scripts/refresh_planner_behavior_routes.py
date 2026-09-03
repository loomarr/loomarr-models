#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from loomarr_models.behavior_model_review import REQUIRED_PARAMETERS, BehaviorReviewPreflightError
from loomarr_models.model_review import ModelReviewError, project_live_endpoint
from run_planner_behavior_review import _api_key
from run_planner_model_review import _request_json


CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v3.json"
ROUTE_PATH = ROOT / "reviews/planner-behavior-v3/route-snapshot.json"
Fetch = Callable[[str, str, str, dict[str, Any] | None, int], tuple[bytes, dict[str, Any]]]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_refresh_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(config, dict)
        or config.get("reviewId") != "planner-behavior-review-v3"
        or config.get("status") != "planned-no-paid-calls-authorized"
        or config.get("execution", {}).get("paidReviewAuthorized") is not False
        or config.get("bindings", {}).get("routeSnapshot", {}).get("path")
        != str(ROUTE_PATH.relative_to(ROOT))
    ):
        raise BehaviorReviewPreflightError("only the disabled corrected review may refresh routes")
    return config


def fetch_snapshot(
    config: dict[str, Any],
    api_key: str,
    *,
    fetch: Fetch = _request_json,
    captured_at: str | None = None,
) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    sources: list[str] = []
    for reviewer in config["reviewers"]:
        author, model = reviewer["model"].split("/", 1)
        url = f"{config['execution']['apiBaseUrl']}/models/{author}/{model}/endpoints"
        _raw, response = fetch(
            "GET",
            url,
            api_key,
            None,
            config["execution"]["requestTimeoutSeconds"],
        )
        endpoints = response.get("data", {}).get("endpoints", [])
        matches = [
            endpoint
            for endpoint in endpoints
            if endpoint.get("tag") == reviewer["providerTag"] and endpoint.get("status") == 0
        ]
        if len(matches) != 1:
            raise ModelReviewError(
                f"live route {reviewer['providerTag']} is unavailable or ambiguous"
            )
        route = project_live_endpoint(
            matches[0], reviewer["role"], reviewer["family"], reviewer["model"]
        )
        if set(route["requiredParameters"]) != REQUIRED_PARAMETERS:
            raise ModelReviewError(
                f"live route {reviewer['providerTag']} lacks a required structured-output parameter"
            )
        try:
            prices = (
                Decimal(route["promptPriceUsdPerToken"]),
                Decimal(route["completionPriceUsdPerToken"]),
            )
        except (InvalidOperation, TypeError) as exc:
            raise ModelReviewError(f"live route {reviewer['providerTag']} has invalid pricing") from exc
        if any(price <= 0 for price in prices):
            raise ModelReviewError(f"live route {reviewer['providerTag']} has invalid pricing")
        routes.append(route)
        sources.append(url)
    return {
        "schemaVersion": 1,
        "capturedAt": captured_at or timestamp(),
        "sources": sources,
        "reviewers": routes,
        "schemaCompilationProof": {
            "available": False,
            "reason": (
                "OpenRouter endpoint metadata advertises structured-output parameters but provides "
                "no no-inference proof that an exact multi-trace schema compiles."
            ),
            "selectedBatchSize": 1,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh corrected-review OpenRouter route metadata")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        config = load_refresh_config(config_path)
        live = fetch_snapshot(config, _api_key())
        if args.write:
            ROUTE_PATH.write_text(
                json.dumps(live, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            result = {"status": "updated", "capturedAt": live["capturedAt"]}
        else:
            frozen = json.loads(ROUTE_PATH.read_text(encoding="utf-8"))
            if live["reviewers"] != frozen.get("reviewers"):
                raise ModelReviewError("live corrected-review routes differ from the frozen snapshot")
            result = {"status": "matched", "capturedAt": live["capturedAt"]}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
