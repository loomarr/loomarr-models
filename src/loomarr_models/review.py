from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REVIEW_SCHEMA_VERSION = 1
TRACE_ID = re.compile(r"^planner-smoke-(?P<family>[a-z-]+)-(?P<variant>\d{2})$")
GITHUB_REVIEWER_ID = re.compile(r"^github:[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
MODEL_REVIEWER_IDS = {
    "openrouter:anthropic/claude-sonnet-5",
    "openrouter:google/gemini-3.1-pro-preview",
    "openrouter:openai/gpt-5.4",
}
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
PERSON_KEYS = {"verdict", "reviewer", "reviewedAt", "notes"}
DECISION_KEYS = {"schemaVersion", "traceId", "primary", "secondary"}


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class DerivedReview:
    status: str
    primaryReviewer: str
    secondaryReviewer: str
    reviewedAt: str | None
    notes: str


def secondary_review_required(trace_id: str) -> bool:
    if not TRACE_ID.fullmatch(trace_id):
        raise ReviewError(f"invalid planner smoke trace id: {trace_id!r}")
    return True


def empty_decision(trace_id: str) -> dict[str, Any]:
    required = secondary_review_required(trace_id)
    return {
        "schemaVersion": REVIEW_SCHEMA_VERSION,
        "traceId": trace_id,
        "primary": {"verdict": "pending", "reviewer": "", "reviewedAt": None, "notes": ""},
        "secondary": {
            "required": required,
            "verdict": "pending" if required else "not-required",
            "reviewer": "",
            "reviewedAt": None,
            "notes": "",
        },
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
            raise ReviewError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ReviewError(f"{path}:{line_number}: review decision must be an object")
        trace_id = value.get("traceId", "<missing>")
        if trace_id in decisions:
            raise ReviewError(f"{path}:{line_number}: duplicate {trace_id}")
        derive_review(value)
        decisions[trace_id] = value
    if list(decisions) != expected:
        raise ReviewError("review decisions do not match the exact ordered 50 trace ids")
    return decisions


def derive_review(decision: dict[str, Any], *, require_complete: bool = False) -> DerivedReview:
    trace_id = decision.get("traceId", "<missing>") if isinstance(decision, dict) else "<missing>"
    if not isinstance(decision, dict) or set(decision) != DECISION_KEYS:
        raise ReviewError(f"{trace_id}: review decision fields differ from schema v1")
    if decision["schemaVersion"] != REVIEW_SCHEMA_VERSION:
        raise ReviewError(f"{trace_id}: unsupported review schemaVersion")
    required = secondary_review_required(trace_id)
    primary = _validate_person(trace_id, "primary", decision["primary"], {"pending", "approved", "rejected"})
    secondary_raw = decision["secondary"]
    if not isinstance(secondary_raw, dict) or set(secondary_raw) != PERSON_KEYS | {"required"}:
        raise ReviewError(f"{trace_id}: invalid secondary review fields")
    if secondary_raw["required"] is not required:
        raise ReviewError(f"{trace_id}: secondary-review requirement drifted")
    allowed = {"pending", "approved", "rejected"} if required else {"not-required"}
    secondary = _validate_person(trace_id, "secondary", secondary_raw, allowed, extra_key="required")

    if not required and any(
        (secondary["reviewer"], secondary["reviewedAt"], secondary["notes"])
    ):
        raise ReviewError(f"{trace_id}: non-required secondary review carries evidence")
    if (
        required
        and secondary["verdict"] in {"approved", "rejected"}
        and primary["reviewer"] == secondary["reviewer"]
    ):
        raise ReviewError(f"{trace_id}: primary and secondary reviewers must differ")
    if required and secondary["verdict"] in {"approved", "rejected"}:
        primary_time = _parse_timestamp(trace_id, "primary", primary["reviewedAt"])
        secondary_time = _parse_timestamp(trace_id, "secondary", secondary["reviewedAt"])
        if secondary_time <= primary_time:
            raise ReviewError(f"{trace_id}: secondary review must follow primary review")

    if required and primary["verdict"] == secondary["verdict"] == "approved":
        status = "approved"
    elif required and primary["verdict"] == secondary["verdict"] == "rejected":
        status = "rejected"
    elif required:
        status = "pending"
    elif primary["verdict"] == "rejected":
        status = "rejected"
    elif primary["verdict"] == "pending":
        status = "pending"
    else:
        status = "approved"
    if require_complete and status != "approved":
        complete_verdicts = primary["verdict"] in {"approved", "rejected"} and secondary[
            "verdict"
        ] in {"approved", "rejected"}
        detail = "review disagreement or rejection" if complete_verdicts else "review incomplete"
        raise ReviewError(f"{trace_id}: {detail}; frozen corpus requires approval")

    reviewed_at = (
        secondary["reviewedAt"]
        if secondary["verdict"] in {"approved", "rejected"}
        else primary["reviewedAt"]
    )
    notes = " ".join(
        f"{label} {item['reviewer']}: {item['notes']}"
        for label, item in (("Primary", primary), ("Secondary", secondary))
        if item["notes"]
    )
    return DerivedReview(
        status=status,
        primaryReviewer=primary["reviewer"],
        secondaryReviewer=secondary["reviewer"],
        reviewedAt=reviewed_at,
        notes=notes,
    )


def trace_review(decision: dict[str, Any]) -> dict[str, Any]:
    derived = derive_review(decision)
    reviewers = [name for name in (derived.primaryReviewer, derived.secondaryReviewer) if name]
    return {
        "status": derived.status,
        "reviewer": "+".join(reviewers) if derived.status == "approved" else "",
        "reviewedAt": derived.reviewedAt if derived.status == "approved" else None,
        "notes": derived.notes,
    }


def _validate_person(
    trace_id: str,
    label: str,
    value: Any,
    allowed_verdicts: set[str],
    *,
    extra_key: str | None = None,
) -> dict[str, Any]:
    expected = PERSON_KEYS | ({extra_key} if extra_key else set())
    if not isinstance(value, dict) or set(value) != expected:
        raise ReviewError(f"{trace_id}: invalid {label} review fields")
    verdict = value["verdict"]
    if verdict not in allowed_verdicts:
        raise ReviewError(f"{trace_id}: invalid {label} verdict {verdict!r}")
    reviewer, reviewed_at, notes = value["reviewer"], value["reviewedAt"], value["notes"]
    if verdict in {"pending", "not-required"}:
        if reviewer != "" or reviewed_at is not None or notes != "":
            raise ReviewError(f"{trace_id}: {label} {verdict} review carries false evidence")
    else:
        if not isinstance(reviewer, str) or (
            not GITHUB_REVIEWER_ID.fullmatch(reviewer) and reviewer not in MODEL_REVIEWER_IDS
        ):
            raise ReviewError(
                f"{trace_id}: {label} reviewer must be github:<login> or a pinned model reviewer"
            )
        _parse_timestamp(trace_id, label, reviewed_at)
        if not isinstance(notes, str) or not notes.strip():
            raise ReviewError(f"{trace_id}: {label} decision requires a note")
    return value


def _parse_timestamp(trace_id: str, label: str, value: Any) -> datetime:
    if not isinstance(value, str) or not RFC3339_UTC.fullmatch(value):
        raise ReviewError(f"{trace_id}: {label} reviewedAt must be RFC 3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReviewError(f"{trace_id}: {label} reviewedAt must be RFC 3339 UTC") from exc
    if parsed.tzinfo != timezone.utc:
        raise ReviewError(f"{trace_id}: {label} reviewedAt must be RFC 3339 UTC")
    return parsed
