#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_review import (
    AUTHORITY,
    CRITERIA,
    ISSUE,
    PLAN_ID,
    binding,
    build_promotion_artifacts,
    json_bytes,
    jsonl_bytes,
    load_draft_rows,
    load_review_state,
    pending_decisions,
    render_review_packet,
)
from loomarr_models.validator import ValidationError


PLAN_PATH = Path("reviews/planner-current-v1/review-plan.json")
DECISIONS_PATH = Path("reviews/planner-current-v1/decisions.jsonl")
PACKET_PATH = Path("reviews/planner-current-v1/review-packet.md")
DRAFTS_PATH = Path("corpus/planner-current-v1/drafts.jsonl")


def plan() -> dict:
    return {
        "schemaVersion": 1,
        "planId": PLAN_ID,
        "issue": ISSUE,
        "status": "pending-independent-review",
        "bindings": {
            "contract": binding(ROOT, Path("contracts/planner-contract-v5.json")),
            "development": binding(ROOT, Path("evaluation/planner-current-v1/cases.jsonl")),
            "developmentManifest": binding(
                ROOT, Path("evaluation/planner-current-v1/manifest.json")
            ),
            "draftManifest": binding(
                ROOT, Path("corpus/planner-current-v1/draft-manifest.json")
            ),
            "drafts": binding(ROOT, DRAFTS_PATH),
            "holdoutDenylist": binding(
                ROOT, Path("contracts/planner-holdout-denylist-v2.json")
            ),
            "reviewGenerator": binding(
                ROOT, Path("scripts/build_planner_current_review.py")
            ),
            "reviewValidator": binding(
                ROOT, Path("src/loomarr_models/current_review.py")
            ),
        },
        "decisionPath": DECISIONS_PATH.as_posix(),
        "packetPath": PACKET_PATH.as_posix(),
        "criteria": list(CRITERIA),
        "requiredRecords": 24,
        "reviewPolicy": {
            "reviewerMustDifferFromDraftAuthor": True,
            "approvalRequiresAllCriteria": True,
            "rejectionRequiresNotes": True,
            "timestampsRequireRfc3339Utc": True,
            "partialPromotionAllowed": False,
        },
        "outputs": {
            "training": "corpus/planner-current-v1/traces.jsonl",
            "manifest": "corpus/planner-current-v1/manifest.json",
            "publication": "reviews/planner-current-v1/publication.json",
        },
        "authority": AUTHORITY,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--init-review", action="store_true")
    args = parser.parse_args()
    if args.check and args.init_review:
        parser.error("--check and --init-review cannot be combined")
    expected_plan = json_bytes(plan())
    plan_target = ROOT / PLAN_PATH
    decisions_target = ROOT / DECISIONS_PATH
    packet_target = ROOT / PACKET_PATH
    try:
        if args.check:
            if not plan_target.is_file() or plan_target.read_bytes() != expected_plan:
                raise ValidationError("current review plan drifted; regenerate it")
        else:
            plan_target.parent.mkdir(parents=True, exist_ok=True)
            plan_target.write_bytes(expected_plan)
        if args.init_review:
            if decisions_target.exists():
                raise ValidationError("refusing to overwrite current review decisions")
            drafts, hashes = load_draft_rows(ROOT / DRAFTS_PATH)
            decisions_target.write_bytes(jsonl_bytes(pending_decisions(drafts, hashes)))
        state = load_review_state(ROOT, plan_target)
        expected_packet = render_review_packet(state)
        if args.check:
            if not packet_target.is_file() or packet_target.read_bytes() != expected_packet:
                raise ValidationError("current review packet drifted; regenerate it")
            promoted = build_promotion_artifacts(state) if state.summary["approved"] == 24 else {}
            for relative in (Path(value) for value in state.plan["outputs"].values()):
                target = ROOT / relative
                if relative in promoted:
                    if not target.is_file() or target.read_bytes() != promoted[relative]:
                        raise ValidationError(f"promoted current review artifact drifted: {relative}")
                elif target.exists():
                    raise ValidationError(f"current review output exists before complete approval: {relative}")
        else:
            packet_target.write_bytes(expected_packet)
    except (OSError, ValidationError) as exc:
        parser.error(str(exc))
    if not args.check:
        print(json.dumps(state.summary, sort_keys=True))


if __name__ == "__main__":
    main()
