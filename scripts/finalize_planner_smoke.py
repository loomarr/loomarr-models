#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_smoke_drafts as drafts
import loomarr_models.review as review_contract
from loomarr_models.review import ReviewError, derive_review
from loomarr_models.validator import (
    ValidationError,
    load_contract,
    load_denylist,
    validate_corpus,
)


TRACES_PATH = ROOT / "corpus/planner-smoke-v1/traces.jsonl"
MANIFEST_PATH = ROOT / "corpus/planner-smoke-v1/manifest.json"
REPORT_PATH = ROOT / "corpus/planner-smoke-v1/validation-report.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
ENVIRONMENT_PATH = ROOT / "environments/qwen38-a40-v1.json"
VALIDATOR_PATH = ROOT / "src/loomarr_models/validator.py"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_outputs() -> tuple[bytes, bytes, bytes]:
    contract = load_contract(drafts.CONTRACT_PATH)
    decisions = drafts.load_reviews()
    derived = {
        trace_id: derive_review(decision, require_complete=True)
        for trace_id, decision in decisions.items()
    }
    traces = drafts.build_traces(contract, decisions)
    trace_bytes = b"".join(canonical(trace) + b"\n" for trace in traces)
    identities, denylisted_digests = load_denylist(DENYLIST_PATH)
    validation = validate_corpus(
        traces,
        denylisted_identities=identities,
        denylisted_sha256=denylisted_digests,
        contract_bundle=contract,
        allow_pending=False,
    )
    if validation.traces != 50 or validation.approved != 50 or validation.pending != 0:
        raise SystemExit("frozen corpus must contain exactly 50 approved traces")

    family_counts = {
        family: sum(trace["axes"] == [family] for trace in traces) for family in drafts.FAMILIES
    }
    manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-smoke-v1",
        "status": "reviewed-frozen",
        "traceCount": validation.traces,
        "familyCounts": family_counts,
        "tracesPath": str(TRACES_PATH.relative_to(ROOT)),
        "tracesSha256": hashlib.sha256(trace_bytes).hexdigest(),
        "draftPath": str(drafts.OUT_PATH.relative_to(ROOT)),
        "draftSha256": digest(drafts.OUT_PATH),
        "draftManifestPath": str(drafts.MANIFEST_PATH.relative_to(ROOT)),
        "draftManifestSha256": digest(drafts.MANIFEST_PATH),
        "reviewDecisionsPath": str(drafts.REVIEW_PATH.relative_to(ROOT)),
        "reviewDecisionsSha256": digest(drafts.REVIEW_PATH),
        "reviewContract": "planner-smoke-review-decision-v1",
        "reviewValidatorPath": str(Path(review_contract.__file__).relative_to(ROOT)),
        "reviewValidatorSha256": digest(Path(review_contract.__file__)),
        "primaryReviewers": sorted({review.primaryReviewer for review in derived.values()}),
        "secondaryReviewers": sorted(
            {review.secondaryReviewer for review in derived.values() if review.secondaryReviewer}
        ),
        "secondaryReviewCount": sum(bool(review.secondaryReviewer) for review in derived.values()),
        "contractPath": str(drafts.CONTRACT_PATH.relative_to(ROOT)),
        "contractSha256": digest(drafts.CONTRACT_PATH),
        "denylistPath": str(DENYLIST_PATH.relative_to(ROOT)),
        "denylistSha256": digest(DENYLIST_PATH),
        "environmentPath": str(ENVIRONMENT_PATH.relative_to(ROOT)),
        "environmentSha256": digest(ENVIRONMENT_PATH),
        "generatorPath": str(Path(drafts.__file__).relative_to(ROOT)),
        "generatorSha256": digest(Path(drafts.__file__)),
        "finalizerPath": str(Path(__file__).relative_to(ROOT)),
        "finalizerSha256": digest(Path(__file__)),
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    report = {
        "schemaVersion": 1,
        "corpusId": "planner-smoke-v1",
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "tracesSha256": validation.sha256,
        "traces": validation.traces,
        "approved": validation.approved,
        "pending": validation.pending,
        "validatorPath": str(VALIDATOR_PATH.relative_to(ROOT)),
        "validatorSha256": digest(VALIDATOR_PATH),
        "result": "pass",
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    return trace_bytes, manifest_bytes, report_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the fully reviewed planner smoke corpus")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--check-if-present", action="store_true")
    args = parser.parse_args()
    outputs = (TRACES_PATH, MANIFEST_PATH, REPORT_PATH)
    present = [path.exists() for path in outputs]
    if args.check_if_present and not any(present):
        return
    if any(present) and not all(present):
        raise SystemExit("frozen corpus artifact set is partial")

    try:
        expected = build_outputs()
    except (ReviewError, ValidationError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.check or all(present):
        for path, content in zip(outputs, expected, strict=True):
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(f"{path.relative_to(ROOT)} differs from reviewed inputs")
        return

    for path, content in zip(outputs, expected, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)


if __name__ == "__main__":
    main()
