from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .current_contract import (
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_current_development_case,
    validate_current_trace,
    validate_disjoint_splits,
)
from .validator import ValidationError


PLAN_ID = "planner-current-training-review-v1"
ISSUE = "https://github.com/loomarr/loomarr-models/issues/27"
FIXTURE_ID = "planner-current-training-catalog-v1"
DEVELOPMENT_FIXTURE_ID = "planner-current-development-catalog-v1"
CRITERIA = (
    "contractConformant",
    "toolAndFinalGrounded",
    "constraintBehaviorCorrect",
    "recoveryEvidenceCorrect",
    "syntheticAndPrivateSafe",
)
AUTHORITY = {
    "externalSpendUsd": "0",
    "providerInferenceAuthorized": False,
    "modelDownloadAuthorized": False,
    "gpuAuthorized": False,
    "trainingAuthorized": False,
    "certificationAuthority": False,
    "deploymentAuthority": False,
    "releaseAuthority": False,
}
PLAN_BINDINGS = {
    "contract",
    "development",
    "developmentManifest",
    "draftManifest",
    "drafts",
    "holdoutDenylist",
    "reviewGenerator",
    "reviewValidator",
}
EXPECTED_BINDING_PATHS = {
    "contract": "contracts/planner-contract-v5.json",
    "development": "evaluation/planner-current-v1/cases.jsonl",
    "developmentManifest": "evaluation/planner-current-v1/manifest.json",
    "draftManifest": "corpus/planner-current-v1/draft-manifest.json",
    "drafts": "corpus/planner-current-v1/drafts.jsonl",
    "holdoutDenylist": "contracts/planner-holdout-denylist-v2.json",
    "reviewGenerator": "scripts/build_planner_current_review.py",
    "reviewValidator": "src/loomarr_models/current_review.py",
}
DECISION_KEYS = {
    "schemaVersion",
    "traceId",
    "traceSha256",
    "draftAuthor",
    "reviewer",
    "reviewedAt",
    "verdict",
    "criteria",
    "notes",
}
REVIEWER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+\-]{2,127}")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")


@dataclass(frozen=True)
class CurrentReviewState:
    root: Path
    plan_path: Path
    decisions_path: Path
    plan: dict[str, Any]
    drafts: list[dict[str, Any]]
    draft_hashes: list[str]
    decisions: list[dict[str, Any]]
    summary: dict[str, int]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def jsonl_bytes(values: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        + b"\n"
        for value in values
    )


def binding(root: Path, relative: Path) -> dict[str, str]:
    return {"path": relative.as_posix(), "sha256": sha256_file(root / relative)}


def load_draft_rows(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    payload = path.read_bytes()
    if not payload or not payload.endswith(b"\n"):
        raise ValidationError(f"{path}: draft JSONL must end with a newline")
    rows: list[dict[str, Any]] = []
    hashes: list[str] = []
    for number, raw in enumerate(payload.splitlines(keepends=True), start=1):
        if not raw.strip():
            raise ValidationError(f"{path}: blank draft row {number}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"{path}: invalid draft row {number}") from exc
        if not isinstance(value, dict):
            raise ValidationError(f"{path}: draft row {number} is not an object")
        rows.append(value)
        hashes.append(hashlib.sha256(raw).hexdigest())
    return rows, hashes


def pending_decisions(drafts: list[dict[str, Any]], hashes: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "schemaVersion": 1,
            "traceId": trace["traceId"],
            "traceSha256": digest,
            "draftAuthor": trace["provenance"]["author"],
            "reviewer": "",
            "reviewedAt": None,
            "verdict": "pending",
            "criteria": {criterion: None for criterion in CRITERIA},
            "notes": "",
        }
        for trace, digest in zip(drafts, hashes, strict=True)
    ]


def load_review_state(
    root: Path,
    plan_path: Path,
    *,
    decisions_path: Path | None = None,
    require_complete: bool = False,
) -> CurrentReviewState:
    root = root.resolve(strict=True)
    plan_path = _safe_path(root, plan_path)
    plan = _object(plan_path)
    if set(plan) != {
        "schemaVersion",
        "planId",
        "issue",
        "status",
        "bindings",
        "decisionPath",
        "packetPath",
        "criteria",
        "requiredRecords",
        "reviewPolicy",
        "outputs",
        "authority",
    }:
        raise ValidationError("current review plan fields drifted")
    if (
        plan["schemaVersion"] != 1
        or plan["planId"] != PLAN_ID
        or plan["issue"] != ISSUE
        or plan["status"] != "pending-independent-review"
        or plan["criteria"] != list(CRITERIA)
        or plan["requiredRecords"] != 24
        or plan["authority"] != AUTHORITY
        or set(plan["bindings"]) != PLAN_BINDINGS
        or plan["decisionPath"] != "reviews/planner-current-v1/decisions.jsonl"
        or plan["packetPath"] != "reviews/planner-current-v1/review-packet.md"
        or plan["reviewPolicy"]
        != {
            "reviewerMustDifferFromDraftAuthor": True,
            "approvalRequiresAllCriteria": True,
            "rejectionRequiresNotes": True,
            "timestampsRequireRfc3339Utc": True,
            "partialPromotionAllowed": False,
        }
        or plan["outputs"]
        != {
            "training": "corpus/planner-current-v1/traces.jsonl",
            "manifest": "corpus/planner-current-v1/manifest.json",
            "publication": "reviews/planner-current-v1/publication.json",
        }
    ):
        raise ValidationError("current review plan identity or policy drifted")
    bound: dict[str, Path] = {}
    for name, item in plan["bindings"].items():
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or item["path"] != EXPECTED_BINDING_PATHS[name]
        ):
            raise ValidationError(f"current review {name} binding is invalid")
        bound[name] = _safe_path(root, root / item["path"])
        if sha256_file(bound[name]) != item["sha256"]:
            raise ValidationError(f"current review {name} digest mismatch")

    contract = _object(bound["contract"])
    drafts, draft_hashes = load_draft_rows(bound["drafts"])
    development = read_jsonl(bound["development"])
    exact, normalized, minimum, protected_keys = load_current_denylist(bound["holdoutDenylist"])
    for trace in drafts:
        validate_current_trace(trace, contract, FIXTURE_ID)
        assert_not_denylisted(
            trace["traceId"], trace, exact, normalized, minimum, protected_keys
        )
    for case in development:
        validate_current_development_case(case, contract, DEVELOPMENT_FIXTURE_ID)
        assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected_keys)
    validate_disjoint_splits({"current-training": drafts, "current-development": development})
    if len(drafts) != plan["requiredRecords"]:
        raise ValidationError("current review draft count drifted")
    _validate_source_manifests(root, plan, drafts, development)

    selected_decisions = decisions_path or root / plan["decisionPath"]
    selected_decisions = _safe_path(root, selected_decisions)
    decisions = _jsonl(selected_decisions)
    if len(decisions) != len(drafts):
        raise ValidationError("current review decision coverage drifted")
    counts = {"approved": 0, "rejected": 0, "pending": 0}
    for trace, digest, decision in zip(drafts, draft_hashes, decisions, strict=True):
        _validate_decision(trace, digest, decision)
        counts[decision["verdict"]] += 1
    if require_complete and counts != {"approved": len(drafts), "rejected": 0, "pending": 0}:
        raise ValidationError("current training promotion requires 24 approved independent reviews")
    return CurrentReviewState(
        root=root,
        plan_path=plan_path,
        decisions_path=selected_decisions,
        plan=plan,
        drafts=drafts,
        draft_hashes=draft_hashes,
        decisions=decisions,
        summary=counts,
    )


def render_review_packet(state: CurrentReviewState) -> bytes:
    lines = [
        "# Current planner training review packet",
        "",
        "Review the synthetic behavior in each trace, then edit `reviews/planner-current-v1/decisions.jsonl`.",
        "This generated packet omits the repeated system prompt and tool schema; their exact bytes remain hash-bound.",
        "",
    ]
    for trace, digest, decision in zip(
        state.drafts, state.draft_hashes, state.decisions, strict=True
    ):
        user = trace["messages"][1]["content"].split(
            "\nSubmitted Intent source coordinates", 1
        )[0]
        flow: list[str] = []
        for message in trace["messages"][2:]:
            if message["role"] == "assistant" and "toolCalls" in message:
                call = message["toolCalls"][0]
                flow.append(
                    f"call `{call['name']}` `{json.dumps(call['arguments'], sort_keys=True, separators=(',', ':'))}`"
                )
            elif message["role"] == "tool":
                payload = json.loads(message["content"])
                if isinstance(payload, list):
                    values = [f"{item['name']} [{item['key']}]" for item in payload]
                    flow.append("result " + (", ".join(values) or "empty"))
                else:
                    flow.append(f"result error `{payload.get('error', '<missing>')}`")
            elif message["role"] == "assistant":
                final = json.loads(message["content"])
                picks = [f"{item['name']} [{item['key']}]" for item in final["picks"]]
                flow.append(
                    "final "
                    + (", ".join(picks) or "structured abstention")
                    + f"; dateMeaning `{json.dumps(final['dateMeaning'], sort_keys=True, separators=(',', ':'))}`"
                )
        criteria = ", ".join(
            f"{name}={decision['criteria'][name]}" for name in CRITERIA
        )
        lines.extend(
            [
                f"## {trace['traceId']}",
                "",
                f"- Draft SHA-256: `{digest}`",
                f"- Capability: `{trace['axes'][0]}`",
                f"- Intent: {user}",
                f"- Flow: {' → '.join(flow)}",
                f"- Verdict: **{decision['verdict']}** by `{decision['reviewer'] or '—'}` at `{decision['reviewedAt'] or '—'}`",
                f"- Criteria: {criteria}",
                f"- Notes: {decision['notes'] or '—'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip().encode() + b"\n"


def build_promotion_artifacts(state: CurrentReviewState) -> dict[Path, bytes]:
    if state.summary != {"approved": len(state.drafts), "rejected": 0, "pending": 0}:
        raise ValidationError("current training promotion requires 24 approved independent reviews")
    promoted: list[dict[str, Any]] = []
    for source, decision in zip(state.drafts, state.decisions, strict=True):
        trace = copy.deepcopy(source)
        trace["review"] = {
            "status": "approved",
            "reviewer": decision["reviewer"],
            "reviewedAt": decision["reviewedAt"],
            "notes": decision["notes"],
        }
        promoted.append(trace)
    training_blob = jsonl_bytes(promoted)
    training_path = Path(state.plan["outputs"]["training"])
    manifest_path = Path(state.plan["outputs"]["manifest"])
    publication_path = Path(state.plan["outputs"]["publication"])
    manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-current-training-v1",
        "records": len(promoted),
        "sha256": hashlib.sha256(training_blob).hexdigest(),
        "sourceDrafts": state.plan["bindings"]["drafts"],
        "contract": state.plan["bindings"]["contract"],
        "holdoutDenylist": state.plan["bindings"]["holdoutDenylist"],
        "reviewPlan": {
            "path": state.plan_path.relative_to(state.root).as_posix(),
            "sha256": sha256_file(state.plan_path),
        },
        "reviewDecisions": {
            "path": state.decisions_path.relative_to(state.root).as_posix(),
            "sha256": sha256_file(state.decisions_path),
        },
        "reviewStatus": "independently-approved",
        "trainingAuthorized": False,
    }
    manifest_blob = json_bytes(manifest)
    publication = {
        "schemaVersion": 1,
        "publicationId": "planner-current-training-review-v1",
        "status": "complete-independent-review",
        "summary": state.summary,
        "bindings": {
            "training": {
                "path": training_path.as_posix(),
                "sha256": hashlib.sha256(training_blob).hexdigest(),
            },
            "manifest": {
                "path": manifest_path.as_posix(),
                "sha256": hashlib.sha256(manifest_blob).hexdigest(),
            },
            "decisions": manifest["reviewDecisions"],
            "plan": manifest["reviewPlan"],
        },
        "authority": AUTHORITY,
    }
    return {
        training_path: training_blob,
        manifest_path: manifest_blob,
        publication_path: json_bytes(publication),
    }


def _validate_decision(trace: dict[str, Any], digest: str, decision: Any) -> None:
    trace_id = trace["traceId"]
    if not isinstance(decision, dict) or set(decision) != DECISION_KEYS:
        raise ValidationError(f"{trace_id}: review decision fields drifted")
    if (
        decision["schemaVersion"] != 1
        or decision["traceId"] != trace_id
        or decision["traceSha256"] != digest
        or decision["draftAuthor"] != trace["provenance"]["author"]
        or not isinstance(decision["criteria"], dict)
        or set(decision["criteria"]) != set(CRITERIA)
        or decision["verdict"] not in {"pending", "approved", "rejected"}
        or not isinstance(decision["notes"], str)
    ):
        raise ValidationError(f"{trace_id}: review decision identity drifted")
    values = list(decision["criteria"].values())
    if decision["verdict"] == "pending":
        if (
            decision["reviewer"] != ""
            or decision["reviewedAt"] is not None
            or decision["notes"] != ""
            or any(value is not None for value in values)
        ):
            raise ValidationError(f"{trace_id}: pending review carries false evidence")
        return
    reviewer = decision["reviewer"]
    if (
        not isinstance(reviewer, str)
        or REVIEWER_PATTERN.fullmatch(reviewer) is None
        or reviewer == decision["draftAuthor"]
        or reviewer in {"codex:draft", "planner-current-contract-generator-v1"}
    ):
        raise ValidationError(f"{trace_id}: reviewer is not independent of the draft generator")
    _validate_timestamp(trace_id, decision["reviewedAt"])
    if any(type(value) is not bool for value in values):
        raise ValidationError(f"{trace_id}: completed review criteria must be booleans")
    if decision["verdict"] == "approved" and not all(values):
        raise ValidationError(f"{trace_id}: approval requires every review criterion")
    if decision["verdict"] == "rejected" and (all(values) or not decision["notes"].strip()):
        raise ValidationError(f"{trace_id}: rejection requires a failed criterion and notes")


def _validate_timestamp(trace_id: str, value: Any) -> None:
    if not isinstance(value, str) or TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValidationError(f"{trace_id}: review timestamp must be RFC 3339 UTC")
    try:
        parsed = dt.datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValidationError(f"{trace_id}: review timestamp must be RFC 3339 UTC") from exc
    if parsed.tzinfo != dt.timezone.utc:
        raise ValidationError(f"{trace_id}: review timestamp must be RFC 3339 UTC")


def _validate_source_manifests(
    root: Path,
    plan: dict[str, Any],
    drafts: list[dict[str, Any]],
    development: list[dict[str, Any]],
) -> None:
    draft_manifest = _object(root / plan["bindings"]["draftManifest"]["path"])
    development_manifest = _object(root / plan["bindings"]["developmentManifest"]["path"])
    if (
        draft_manifest.get("records") != len(drafts)
        or draft_manifest.get("sha256") != plan["bindings"]["drafts"]["sha256"]
        or draft_manifest.get("contract") != plan["bindings"]["contract"]
        or draft_manifest.get("holdoutDenylist") != plan["bindings"]["holdoutDenylist"]
        or draft_manifest.get("reviewStatus") != "pending"
        or draft_manifest.get("trainingAuthorized") is not False
    ):
        raise ValidationError("current review draft manifest drifted")
    if (
        development_manifest.get("records") != len(development)
        or development_manifest.get("sha256") != plan["bindings"]["development"]["sha256"]
        or development_manifest.get("contract") != plan["bindings"]["contract"]
        or development_manifest.get("holdoutDenylist")
        != plan["bindings"]["holdoutDenylist"]
        or development_manifest.get("modelExposure") != "none"
        or development_manifest.get("certificationAuthority") is not False
    ):
        raise ValidationError("current review development manifest drifted")


def _safe_path(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValidationError(f"review path escapes repository: {path}")
    return resolved


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load review object {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected an object")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load review decisions {path}") from exc
    if not values or any(not isinstance(value, dict) for value in values):
        raise ValidationError(f"{path}: review decisions must be JSON objects")
    return values
