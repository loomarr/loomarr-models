from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


_SHA256 = re.compile(r"[0-9a-f]{64}")
_BUCKET_FIELDS = {
    "allocation",
    "cpuUsd",
    "diskUsd",
    "endTime",
    "gpuUsd",
    "resourceIdSha256",
    "startTime",
    "totalUsd",
}
_ALLOCATIONS = {
    "prior-planner-setup-and-repair": "priorPlannerSetupAndRepair",
    "qlora-smoke": "qloraSmoke",
    "adapter-evaluation": "adapterEvaluation",
    "current-stock-baseline-v2": "currentStockBaselineV2",
    "current-stock-baseline-v3": "currentStockBaselineV3",
}
_COMPONENT_ROUNDING_TOLERANCE = Decimal("0.0000000000000001")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read canonical JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is not a decimal string") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be a finite non-negative decimal")
    return result


def _require_equal(actual: Decimal, expected: Decimal, field: str) -> None:
    if actual != expected:
        raise ValueError(f"{field} = {actual}, want {expected}")


def _require_component_sum(actual: Decimal, expected: Decimal, field: str) -> None:
    if abs(actual - expected) > _COMPONENT_ROUNDING_TOLERANCE:
        raise ValueError(
            f"{field} = {actual}, component sum {expected} exceeds "
            f"{_COMPONENT_ROUNDING_TOLERANCE} display-rounding tolerance"
        )


def _publication_sha256(root: Path, entry: dict[str, Any], field: str) -> None:
    path_value = entry.get("publicationPath")
    digest = entry.get("publicationSha256")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError(f"{field}.publicationPath must be a non-empty string")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{field}.publicationSha256 must be a lowercase SHA-256")
    path = root / path_value
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"cannot read {field} publication {path}: {exc}") from exc
    if actual != digest:
        raise ValueError(f"{field}.publicationSha256 = {digest}, actual {actual}")


def validate_budget_reconciliation(
    reconciliation_path: Path,
    ledger_path: Path,
    repository_root: Path,
) -> None:
    reconciliation = _load(reconciliation_path)
    ledger = _load(ledger_path)
    if reconciliation.get("schemaVersion") != 1:
        raise ValueError("reconciliation schemaVersion must be 1")
    if reconciliation.get("provider") != "runpod" or reconciliation.get("source") != "runpod-mcp-rest-v2":
        raise ValueError("reconciliation must identify the Runpod REST v2 billing source")

    provider = reconciliation.get("providerBilling")
    if not isinstance(provider, dict):
        raise ValueError("providerBilling must be an object")
    buckets = provider.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        raise ValueError("providerBilling.buckets must be a non-empty array")

    component_totals = {name: Decimal(0) for name in ("cpuUsd", "diskUsd", "gpuUsd", "totalUsd")}
    allocation_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    used_allocations: set[str] = set()
    resources: set[str] = set()
    for index, bucket in enumerate(buckets):
        field = f"providerBilling.buckets[{index}]"
        if not isinstance(bucket, dict) or set(bucket) != _BUCKET_FIELDS:
            raise ValueError(f"{field} has unknown or missing fields")
        allocation = bucket["allocation"]
        if allocation not in _ALLOCATIONS:
            raise ValueError(f"{field}.allocation is not declared")
        used_allocations.add(allocation)
        resource_hash = bucket["resourceIdSha256"]
        if not isinstance(resource_hash, str) or _SHA256.fullmatch(resource_hash) is None:
            raise ValueError(f"{field}.resourceIdSha256 must be a lowercase SHA-256")
        resources.add(resource_hash)
        cpu = _decimal(bucket["cpuUsd"], f"{field}.cpuUsd")
        disk = _decimal(bucket["diskUsd"], f"{field}.diskUsd")
        gpu = _decimal(bucket["gpuUsd"], f"{field}.gpuUsd")
        total = _decimal(bucket["totalUsd"], f"{field}.totalUsd")
        _require_component_sum(total, cpu + disk + gpu, f"{field}.totalUsd")
        for name, value in (("cpuUsd", cpu), ("diskUsd", disk), ("gpuUsd", gpu), ("totalUsd", total)):
            component_totals[name] += value
        allocation_totals[allocation] += total

    totals = provider.get("totals")
    if not isinstance(totals, dict) or set(totals) != {"cpuUsd", "diskUsd", "gpuUsd", "totalUsd"}:
        raise ValueError("providerBilling.totals has unknown or missing fields")
    for name, calculated in component_totals.items():
        _require_equal(_decimal(totals[name], f"providerBilling.totals.{name}"), calculated, f"providerBilling.totals.{name}")
    _require_component_sum(
        component_totals["totalUsd"],
        component_totals["cpuUsd"] + component_totals["diskUsd"] + component_totals["gpuUsd"],
        "providerBilling.totals.totalUsd",
    )
    _require_equal(
        _decimal(provider.get("metadataRoundedTotalUsd"), "providerBilling.metadataRoundedTotalUsd"),
        component_totals["totalUsd"].quantize(Decimal("0.00000000000001")),
        "providerBilling.metadataRoundedTotalUsd",
    )
    if provider.get("uniqueResourceCount") != len(resources):
        raise ValueError("providerBilling.uniqueResourceCount does not match hashed resources")
    if provider.get("zeroActivePods") is not True:
        raise ValueError("providerBilling.zeroActivePods must be true")

    history = reconciliation.get("historicalAccounting")
    expected_history = {_ALLOCATIONS[allocation] for allocation in used_allocations}
    if not isinstance(history, dict) or set(history) != expected_history:
        raise ValueError("historicalAccounting has unknown or missing allocations")
    runtime_estimates = Decimal(0)
    for allocation in sorted(used_allocations):
        history_name = _ALLOCATIONS[allocation]
        entry = history[history_name]
        if not isinstance(entry, dict):
            raise ValueError(f"historicalAccounting.{history_name} must be an object")
        _require_equal(
            _decimal(entry.get("billedAllocationUsd"), f"historicalAccounting.{history_name}.billedAllocationUsd"),
            allocation_totals[allocation],
            f"historicalAccounting.{history_name}.billedAllocationUsd",
        )
        runtime_estimates += _decimal(
            entry.get("recordedRuntimeEstimateUsd"),
            f"historicalAccounting.{history_name}.recordedRuntimeEstimateUsd",
        )
        if "publicationPath" in entry or "publicationSha256" in entry:
            _publication_sha256(repository_root, entry, f"historicalAccounting.{history_name}")

    before = reconciliation.get("ledgerBefore")
    corrected = reconciliation.get("correctedLedger")
    if not isinstance(before, dict) or not isinstance(corrected, dict):
        raise ValueError("ledgerBefore and correctedLedger must be objects")
    old_runpod = _decimal(before.get("postedRunpodRuntimeEstimatesUsd"), "ledgerBefore.postedRunpodRuntimeEstimatesUsd")
    _require_equal(old_runpod, runtime_estimates, "ledgerBefore.postedRunpodRuntimeEstimatesUsd")
    non_runpod = _decimal(before.get("nonRunpodPostedSpendUsd"), "ledgerBefore.nonRunpodPostedSpendUsd")
    old_posted = _decimal(before.get("postedSpendUsd"), "ledgerBefore.postedSpendUsd")
    old_outstanding = _decimal(before.get("outstandingReservationsUsd"), "ledgerBefore.outstandingReservationsUsd")
    _require_equal(old_posted, non_runpod + old_runpod, "ledgerBefore.postedSpendUsd")
    _require_equal(
        _decimal(before.get("committedSpendUsd"), "ledgerBefore.committedSpendUsd"),
        old_posted + old_outstanding,
        "ledgerBefore.committedSpendUsd",
    )

    corrected_posted = _decimal(corrected.get("postedSpendUsd"), "correctedLedger.postedSpendUsd")
    corrected_outstanding = _decimal(
        corrected.get("outstandingReservationsUsd"), "correctedLedger.outstandingReservationsUsd"
    )
    corrected_committed = _decimal(corrected.get("committedSpendUsd"), "correctedLedger.committedSpendUsd")
    _require_equal(corrected_posted, non_runpod + component_totals["totalUsd"], "correctedLedger.postedSpendUsd")
    _require_equal(corrected_committed, corrected_posted + corrected_outstanding, "correctedLedger.committedSpendUsd")
    authorization = _decimal(ledger.get("authorizationUsd"), "ledger.authorizationUsd")
    _require_equal(
        _decimal(corrected.get("remainingAuthorizationUsd"), "correctedLedger.remainingAuthorizationUsd"),
        authorization - corrected_committed,
        "correctedLedger.remainingAuthorizationUsd",
    )
    for name in ("postedSpendUsd", "outstandingReservationsUsd", "committedSpendUsd"):
        _require_equal(
            _decimal(ledger.get(name), f"ledger.{name}"),
            _decimal(corrected.get(name), f"correctedLedger.{name}"),
            f"ledger.{name}",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the canonical external-spend reconciliation")
    parser.add_argument("reconciliation", type=Path)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    validate_budget_reconciliation(args.reconciliation, args.ledger, args.repository_root)


if __name__ == "__main__":
    main()
