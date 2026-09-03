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

import build_planner_behavior_corpus as corpus
from loomarr_models.behavior_review import derive_review, load_review_decisions
from loomarr_models.targeted import validate_targeted_training
from loomarr_models.validator import load_contract, load_denylist, load_jsonl


TRACES_PATH = ROOT / "corpus/planner-behavior-v2/traces.jsonl"
MANIFEST_PATH = ROOT / "corpus/planner-behavior-v2/manifest.json"
REPORT_PATH = ROOT / "corpus/planner-behavior-v2/validation-report.json"
PUBLICATION_PATH = (
    ROOT / "reviews/planner-behavior-v2/publications/planner-behavior-review-v2/publication.json"
)
PUBLISHED_DECISIONS_PATH = PUBLICATION_PATH.with_name("decisions.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze unanimously reviewed planner behavior traces")
    parser.add_argument("--check-if-present", action="store_true")
    args = parser.parse_args()
    frozen = (TRACES_PATH, MANIFEST_PATH, REPORT_PATH)
    if args.check_if_present and not any(path.exists() for path in frozen):
        return
    outputs = build_outputs()
    if args.check_if_present:
        stale = [
            str(path.relative_to(ROOT))
            for path, expected in outputs.items()
            if not path.exists() or path.read_bytes() != expected
        ]
        if stale:
            raise SystemExit("stale frozen behavior artifacts: " + ", ".join(stale))
        return
    for path, content in outputs.items():
        path.write_bytes(content)


def build_outputs() -> dict[Path, bytes]:
    contract = load_contract(corpus.CONTRACT_PATH)
    identities, digests = load_denylist(corpus.DENYLIST_PATH)
    traces = load_jsonl(corpus.TRAINING_PATH)
    report = validate_targeted_training(
        traces,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    decisions = load_review_decisions(corpus.REVIEW_DECISIONS_PATH, corpus.trace_ids())
    if any(derive_review(decision, require_complete=True).status != "approved" for decision in decisions.values()):
        raise ValueError("all 120 behavior traces require two approvals before freeze")
    if any(trace["review"]["status"] != "approved" for trace in traces):
        raise ValueError("generated behavior traces do not contain unanimous review evidence")

    publication = _object(PUBLICATION_PATH)
    if publication.get("approved") != 120 or publication.get("escalations") != 0:
        raise ValueError("only a unanimous behavior-review publication can freeze training data")
    decision_bytes = corpus.REVIEW_DECISIONS_PATH.read_bytes()
    if (
        hashlib.sha256(decision_bytes).hexdigest() != publication.get("decisionsSha256")
        or PUBLISHED_DECISIONS_PATH.read_bytes() != decision_bytes
    ):
        raise ValueError("canonical decisions differ from the published review evidence")

    trace_bytes = corpus.TRAINING_PATH.read_bytes()
    validation = {
        "schemaVersion": 1,
        "corpusId": "planner-behavior-v2",
        "status": "passed",
        "traceCount": report.records,
        "approved": report.records,
        "pending": 0,
        "behaviorCounts": report.behaviorCounts,
        "tracesSha256": report.sha256,
        "checks": [
            "targeted-behavior-contract",
            "grounded-selected-identities",
            "one-tool-operation-per-turn",
            "complete-final-proposal-json",
            "synthetic-only",
            "holdout-denylist",
            "dual-independent-review",
            "published-decision-identity",
        ],
    }
    validation_bytes = _pretty(validation)
    manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-behavior-v2",
        "status": "reviewed-frozen-training-only",
        "traceCount": report.records,
        "behaviorCounts": report.behaviorCounts,
        "tracesPath": str(TRACES_PATH.relative_to(ROOT)),
        "tracesSha256": report.sha256,
        "validationReportPath": str(REPORT_PATH.relative_to(ROOT)),
        "validationReportSha256": hashlib.sha256(validation_bytes).hexdigest(),
        "developmentCorpusPath": str(corpus.DEVELOPMENT_PATH.relative_to(ROOT)),
        "developmentCorpusSha256": hashlib.sha256(corpus.DEVELOPMENT_PATH.read_bytes()).hexdigest(),
        "reviewPublicationPath": str(PUBLICATION_PATH.relative_to(ROOT)),
        "reviewPublicationSha256": hashlib.sha256(PUBLICATION_PATH.read_bytes()).hexdigest(),
        "reviewDecisionsPath": str(corpus.REVIEW_DECISIONS_PATH.relative_to(ROOT)),
        "reviewDecisionsSha256": hashlib.sha256(decision_bytes).hexdigest(),
        "draftManifestPath": str(corpus.TRAINING_MANIFEST_PATH.relative_to(ROOT)),
        "draftManifestSha256": hashlib.sha256(corpus.TRAINING_MANIFEST_PATH.read_bytes()).hexdigest(),
        "contractPath": str(corpus.CONTRACT_PATH.relative_to(ROOT)),
        "contractSha256": hashlib.sha256(corpus.CONTRACT_PATH.read_bytes()).hexdigest(),
        "holdoutDenylistPath": str(corpus.DENYLIST_PATH.relative_to(ROOT)),
        "holdoutDenylistSha256": hashlib.sha256(corpus.DENYLIST_PATH.read_bytes()).hexdigest(),
        "finalizerPath": str(Path(__file__).relative_to(ROOT)),
        "finalizerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "trainingAuthorized": False,
    }
    return {
        TRACES_PATH: trace_bytes,
        MANIFEST_PATH: _pretty(manifest),
        REPORT_PATH: validation_bytes,
    }


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be an object")
    return value


def _pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


if __name__ == "__main__":
    main()
