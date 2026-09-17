#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.budget_reconciliation import validate_budget_reconciliation
from loomarr_models.experiment import sha256_file


ALLOCATIONS = {
    "current-stock-baseline-v2": {
        "experimentId": "planner-current-qwen-stock-baseline-v2",
        "historyName": "currentStockBaselineV2",
        "trackingIssue": "https://github.com/loomarr/loomarr-models/issues/25",
    },
    "current-stock-baseline-v3": {
        "experimentId": "planner-current-qwen-stock-baseline-v3",
        "historyName": "currentStockBaselineV3",
        "trackingIssue": "https://github.com/loomarr/loomarr-models/issues/29",
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extend canonical Runpod billing reconciliation")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--provider-evidence", type=Path, required=True)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=Path("budgets/external-spend-v1.json"))
    parser.add_argument("--allocation", choices=sorted(ALLOCATIONS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {
        name: path if path.is_absolute() else ROOT / path
        for name, path in {
            "base": args.base,
            "provider": args.provider_evidence,
            "publication": args.publication,
            "ledger": args.ledger,
            "output": args.output,
        }.items()
    }
    value = extend(
        _object(paths["base"]),
        _object(paths["provider"]),
        _object(paths["publication"]),
        _object(paths["ledger"]),
        allocation=args.allocation,
        publication_path=paths["publication"],
        provider_path=paths["provider"],
    )
    paths["output"].parent.mkdir(parents=True, exist_ok=True)
    paths["output"].write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate_budget_reconciliation(paths["output"], paths["ledger"], ROOT)


def extend(
    base: dict[str, Any],
    provider: dict[str, Any],
    publication: dict[str, Any],
    ledger: dict[str, Any],
    *,
    allocation: str,
    publication_path: Path,
    provider_path: Path,
) -> dict[str, Any]:
    metadata = ALLOCATIONS[allocation]
    history_name = metadata["historyName"]
    buckets = base.get("providerBilling", {}).get("buckets")
    history = base.get("historicalAccounting")
    if base.get("schemaVersion") != 1 or not isinstance(buckets, list) or not isinstance(history, dict):
        raise ValueError("base reconciliation is not schema v1")
    if any(bucket.get("allocation") == allocation for bucket in buckets) or history_name in history:
        raise ValueError(f"reconciliation already contains {allocation}")
    costs = _costs(provider)
    if (
        provider.get("experimentId") != metadata["experimentId"]
        or provider.get("provider") != "runpod"
        or provider.get("status") != "settled-resources-deleted"
        or provider.get("zeroActivePods") is not True
        or provider.get("persistentStorageDeletedWithPod") is not True
        or publication.get("experimentId") != metadata["experimentId"]
        or publication.get("providerCostUsd") != str(costs["total"])
        or publication.get("providerEvidence", {}).get("sha256") != sha256_file(provider_path)
    ):
        raise ValueError("provider settlement and publication identities do not match")
    budget_after = publication.get("budgetAfterSettlement", {})
    if any(
        budget_after.get(name) != ledger.get(name)
        for name in (
            "postedSpendUsd",
            "outstandingReservationsUsd",
            "committedSpendUsd",
            "authorizationUsd",
        )
    ):
        raise ValueError("publication settlement differs from the canonical ledger")
    created = _timestamp(provider.get("createdAt"), "provider.createdAt")
    deleted = _timestamp(provider.get("deletedAt"), "provider.deletedAt")
    captured = _timestamp(provider.get("capturedAt"), "provider.capturedAt")
    if not created < deleted <= captured:
        raise ValueError("provider settlement timestamps are not ordered")

    result = copy.deepcopy(base)
    disk = costs["disk"] + costs["persistentStorage"]
    result["providerBilling"]["buckets"].append(
        {
            "allocation": allocation,
            "cpuUsd": "0",
            "diskUsd": str(disk),
            "endTime": provider["deletedAt"],
            "gpuUsd": str(costs["gpu"]),
            "resourceIdSha256": provider["podIdSha256"],
            "startTime": provider["createdAt"],
            "totalUsd": str(costs["total"]),
        }
    )
    totals = _sum_buckets(result["providerBilling"]["buckets"])
    result["providerBilling"]["totals"] = totals
    result["providerBilling"]["metadataRoundedTotalUsd"] = str(
        Decimal(totals["totalUsd"]).quantize(Decimal("0.00000000000001"))
    )
    result["providerBilling"]["uniqueResourceCount"] = len(
        {bucket["resourceIdSha256"] for bucket in result["providerBilling"]["buckets"]}
    )
    result["providerBilling"]["zeroActivePods"] = True
    result["providerBilling"]["query"]["endTime"] = _ceil_hour(captured).isoformat().replace(
        "+00:00", "Z"
    )
    result["historicalAccounting"][history_name] = {
        "billedAllocationUsd": str(costs["total"]),
        "publicationPath": str(publication_path.resolve().relative_to(ROOT)),
        "publicationSha256": sha256_file(publication_path),
        "recordedRuntimeEstimateUsd": "0",
    }
    result["capturedAt"] = provider["capturedAt"]
    result["correctedLedger"] = {
        "postedSpendUsd": ledger["postedSpendUsd"],
        "outstandingReservationsUsd": ledger["outstandingReservationsUsd"],
        "committedSpendUsd": ledger["committedSpendUsd"],
        "remainingAuthorizationUsd": str(
            _decimal(ledger["authorizationUsd"], "ledger.authorizationUsd")
            - _decimal(ledger["committedSpendUsd"], "ledger.committedSpendUsd")
        ),
    }
    result["reconciliationId"] = f"runpod-pod-billing-{allocation}-v1"
    result["trackingIssue"] = metadata["trackingIssue"]
    return result


def _costs(provider: dict[str, Any]) -> dict[str, Decimal]:
    value = provider.get("costUsd")
    if not isinstance(value, dict) or set(value) != {
        "gpu",
        "disk",
        "persistentStorage",
        "total",
    }:
        raise ValueError("provider cost fields are invalid")
    result = {name: _decimal(amount, f"provider.costUsd.{name}") for name, amount in value.items()}
    if result["gpu"] + result["disk"] + result["persistentStorage"] != result["total"]:
        raise ValueError("provider cost components do not equal total")
    return result


def _sum_buckets(buckets: list[dict[str, Any]]) -> dict[str, str]:
    totals = {name: Decimal(0) for name in ("cpuUsd", "diskUsd", "gpuUsd", "totalUsd")}
    for index, bucket in enumerate(buckets):
        for name in totals:
            totals[name] += _decimal(bucket[name], f"buckets[{index}].{name}")
    return {name: str(value) for name, value in totals.items()}


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(value) if isinstance(value, str) else Decimal("NaN")
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not a decimal string") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be a finite non-negative decimal string")
    return result


def _timestamp(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be RFC 3339 UTC")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be RFC 3339 UTC") from exc
    return result


def _ceil_hour(value: dt.datetime) -> dt.datetime:
    floor = value.replace(minute=0, second=0, microsecond=0)
    return floor if value == floor else floor + dt.timedelta(hours=1)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


if __name__ == "__main__":
    main()
