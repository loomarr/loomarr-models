from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .behavior_review import (
    BehaviorReviewError,
    DerivedBehaviorReview,
    derive_review as derive_behavior_review,
    empty_decision as empty_behavior_decision,
)


TRACE_ID = re.compile(r"^planner-v4-delta-[a-z0-9-]+-\d{2}$")


def empty_decision(trace_id: str) -> dict[str, Any]:
    mapped = empty_behavior_decision(_mapped_id(trace_id))
    mapped["traceId"] = trace_id
    return mapped


def derive_review(decision: Any, *, require_complete: bool = False) -> DerivedBehaviorReview:
    trace_id = decision.get("traceId", "<missing>") if isinstance(decision, dict) else "<missing>"
    mapped = copy.deepcopy(decision)
    if isinstance(mapped, dict):
        mapped["traceId"] = _mapped_id(trace_id)
    return derive_behavior_review(mapped, require_complete=require_complete)


def trace_review(decision: dict[str, Any]) -> dict[str, Any]:
    derived = derive_review(decision)
    return {
        "status": derived.status,
        "reviewer": derived.reviewer,
        "reviewedAt": derived.reviewedAt,
        "notes": derived.notes,
    }


def load_review_decisions(
    path: Path,
    expected_trace_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    expected = list(expected_trace_ids)
    decisions: dict[str, dict[str, Any]] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BehaviorReviewError(f"{path}:{line_number}: invalid JSON") from exc
        trace_id = value.get("traceId", "<missing>") if isinstance(value, dict) else "<missing>"
        if trace_id in decisions:
            raise BehaviorReviewError(f"{path}:{line_number}: duplicate {trace_id}")
        derive_review(value)
        decisions[trace_id] = value
    if list(decisions) != expected:
        raise BehaviorReviewError("v4 review decisions do not match the exact ordered 60 trace ids")
    return decisions


def _mapped_id(trace_id: Any) -> str:
    if not isinstance(trace_id, str) or TRACE_ID.fullmatch(trace_id) is None:
        raise BehaviorReviewError(f"invalid planner v4 delta trace id: {trace_id!r}")
    return "planner-behavior-v2-v4-" + trace_id.removeprefix("planner-v4-")
