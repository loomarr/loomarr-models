from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TRACE_ID = re.compile(r"^planner-behavior-v2-[a-z0-9-]+-\d{2}$")
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REVIEWERS = {
    "openrouter:google/gemini-3.1-pro-preview",
    "openrouter:openai/gpt-5.4",
}
PERSON_KEYS = {"verdict", "reviewer", "reviewedAt", "notes"}
DECISION_KEYS = {"schemaVersion", "traceId", "primary", "secondary"}


class BehaviorReviewError(ValueError):
    pass


@dataclass(frozen=True)
class DerivedBehaviorReview:
    status: str
    reviewer: str
    reviewedAt: str | None
    notes: str


def empty_decision(trace_id: str) -> dict[str, Any]:
    _validate_trace_id(trace_id)
    return {
        "schemaVersion": 1,
        "traceId": trace_id,
        "primary": {"verdict": "pending", "reviewer": "", "reviewedAt": None, "notes": ""},
        "secondary": {"verdict": "pending", "reviewer": "", "reviewedAt": None, "notes": ""},
    }


def load_review_decisions(path: Path, expected_trace_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
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
        raise BehaviorReviewError("behavior review decisions do not match the exact ordered 120 trace ids")
    return decisions


def derive_review(decision: Any, *, require_complete: bool = False) -> DerivedBehaviorReview:
    trace_id = decision.get("traceId", "<missing>") if isinstance(decision, dict) else "<missing>"
    if not isinstance(decision, dict) or set(decision) != DECISION_KEYS or decision.get("schemaVersion") != 1:
        raise BehaviorReviewError(f"{trace_id}: behavior review fields differ from schema v1")
    _validate_trace_id(trace_id)
    primary = _validate_person(trace_id, "primary", decision["primary"])
    secondary = _validate_person(trace_id, "secondary", decision["secondary"])
    if secondary["verdict"] in {"approved", "rejected"}:
        if primary["verdict"] not in {"approved", "rejected"}:
            raise BehaviorReviewError(f"{trace_id}: secondary review cannot precede primary review")
        if primary["reviewer"] == secondary["reviewer"]:
            raise BehaviorReviewError(f"{trace_id}: reviewers must be independent")
        if _timestamp(secondary["reviewedAt"]) <= _timestamp(primary["reviewedAt"]):
            raise BehaviorReviewError(f"{trace_id}: secondary review must follow primary review")
    verdicts = primary["verdict"], secondary["verdict"]
    if verdicts == ("approved", "approved"):
        status = "approved"
    elif verdicts == ("rejected", "rejected"):
        status = "rejected"
    else:
        status = "pending"
    if require_complete and status != "approved":
        raise BehaviorReviewError(f"{trace_id}: two approvals are required to freeze the trace")
    reviewers = [item["reviewer"] for item in (primary, secondary) if item["reviewer"]]
    notes = " ".join(
        f"{label} {item['reviewer']}: {item['notes']}"
        for label, item in (("Primary", primary), ("Secondary", secondary))
        if item["notes"]
    )
    reviewed_at = secondary["reviewedAt"] or primary["reviewedAt"]
    return DerivedBehaviorReview(
        status=status,
        reviewer="+".join(reviewers) if status == "approved" else "",
        reviewedAt=reviewed_at if status == "approved" else None,
        notes=notes,
    )


def trace_review(decision: dict[str, Any]) -> dict[str, Any]:
    derived = derive_review(decision)
    return {
        "status": derived.status,
        "reviewer": derived.reviewer,
        "reviewedAt": derived.reviewedAt,
        "notes": derived.notes,
    }


def _validate_trace_id(trace_id: Any) -> None:
    if not isinstance(trace_id, str) or not TRACE_ID.fullmatch(trace_id):
        raise BehaviorReviewError(f"invalid planner behavior trace id: {trace_id!r}")


def _validate_person(trace_id: str, label: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PERSON_KEYS:
        raise BehaviorReviewError(f"{trace_id}: invalid {label} review fields")
    verdict = value["verdict"]
    if verdict not in {"pending", "approved", "rejected"}:
        raise BehaviorReviewError(f"{trace_id}: invalid {label} verdict")
    if verdict == "pending":
        if value != {"verdict": "pending", "reviewer": "", "reviewedAt": None, "notes": ""}:
            raise BehaviorReviewError(f"{trace_id}: pending {label} review carries false evidence")
    else:
        if value["reviewer"] not in REVIEWERS:
            raise BehaviorReviewError(f"{trace_id}: {label} reviewer is not an exact pinned model")
        _timestamp(value["reviewedAt"])
        if not isinstance(value["notes"], str) or not value["notes"].strip():
            raise BehaviorReviewError(f"{trace_id}: {label} review requires substantive evidence")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not RFC3339_UTC.fullmatch(value):
        raise BehaviorReviewError("reviewedAt must be RFC 3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise BehaviorReviewError("reviewedAt must be RFC 3339 UTC") from exc
    if parsed.tzinfo != timezone.utc:
        raise BehaviorReviewError("reviewedAt must be RFC 3339 UTC")
    return parsed
