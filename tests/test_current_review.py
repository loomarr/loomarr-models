from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from loomarr_models.current_review import (
    CRITERIA,
    build_promotion_artifacts,
    jsonl_bytes,
    load_review_state,
    render_review_packet,
)
from loomarr_models.validator import ValidationError


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "reviews/planner-current-v1/review-plan.json"
DECISIONS = ROOT / "reviews/planner-current-v1/decisions.jsonl"


def load_decisions() -> list[dict]:
    return [json.loads(line) for line in DECISIONS.read_text(encoding="utf-8").splitlines()]


def approve(decision: dict, *, reviewer: str = "human:reviewer-1") -> None:
    decision.update(
        {
            "reviewer": reviewer,
            "reviewedAt": "2026-09-17T01:30:00Z",
            "verdict": "approved",
            "criteria": {criterion: True for criterion in CRITERIA},
            "notes": "Reviewed against the bound synthetic evidence.",
        }
    )


class CurrentReviewTests(unittest.TestCase):
    def write_decisions(self, directory: Path, decisions: list[dict]) -> Path:
        path = directory / "decisions.jsonl"
        path.write_bytes(jsonl_bytes(decisions))
        return path

    def test_pending_review_is_exact_and_cannot_promote(self):
        state = load_review_state(ROOT, PLAN)
        self.assertEqual(len(state.drafts), 24)
        self.assertEqual(state.summary, {"approved": 0, "rejected": 0, "pending": 24})
        self.assertEqual(
            [decision["traceId"] for decision in state.decisions],
            [trace["traceId"] for trace in state.drafts],
        )
        packet = render_review_packet(state).decode()
        for trace in state.drafts:
            for message in trace["messages"][1:]:
                if "toolCalls" in message:
                    self.assertIn(
                        json.dumps(
                            message["toolCalls"],
                            indent=2,
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        packet,
                    )
                else:
                    self.assertIn(message["content"].rstrip(), packet)
        with self.assertRaisesRegex(ValidationError, "requires 24 approved"):
            build_promotion_artifacts(state)

    def test_review_evidence_fails_closed(self):
        base = load_decisions()
        cases = []

        stale = copy.deepcopy(base)
        stale[0]["traceSha256"] = "0" * 64
        cases.append((stale, "identity drifted"))

        self_review = copy.deepcopy(base)
        approve(self_review[0], reviewer="codex:draft")
        cases.append((self_review, "not independent"))

        invalid_time = copy.deepcopy(base)
        approve(invalid_time[0])
        invalid_time[0]["reviewedAt"] = "2026-09-17T01:30:00-04:00"
        cases.append((invalid_time, "RFC 3339 UTC"))

        false_approval = copy.deepcopy(base)
        approve(false_approval[0])
        false_approval[0]["criteria"][CRITERIA[0]] = False
        cases.append((false_approval, "approval requires every"))

        false_pending = copy.deepcopy(base)
        false_pending[0]["reviewer"] = "human:reviewer-1"
        cases.append((false_pending, "pending review carries false evidence"))

        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            directory = Path(temporary)
            for index, (decisions, message) in enumerate(cases):
                case_dir = directory / str(index)
                case_dir.mkdir()
                path = self.write_decisions(case_dir, decisions)
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ValidationError, message):
                        load_review_state(ROOT, PLAN, decisions_path=path)

    def test_complete_independent_review_builds_immutable_unauthorized_corpus(self):
        decisions = load_decisions()
        for decision in decisions:
            approve(decision)
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = self.write_decisions(Path(temporary), decisions)
            state = load_review_state(
                ROOT, PLAN, decisions_path=path, require_complete=True
            )
            artifacts = build_promotion_artifacts(state)

        traces = [
            json.loads(line)
            for line in artifacts[Path("corpus/planner-current-v1/traces.jsonl")]
            .decode()
            .splitlines()
        ]
        self.assertEqual(len(traces), 24)
        for source, promoted in zip(state.drafts, traces, strict=True):
            expected = copy.deepcopy(source)
            expected["review"] = promoted["review"]
            self.assertEqual(promoted, expected)
            self.assertEqual(promoted["review"]["status"], "approved")
            self.assertNotEqual(
                promoted["review"]["reviewer"], source["provenance"]["author"]
            )
        manifest = json.loads(
            artifacts[Path("corpus/planner-current-v1/manifest.json")]
        )
        publication = json.loads(
            artifacts[Path("reviews/planner-current-v1/publication.json")]
        )
        self.assertEqual(manifest["reviewStatus"], "independently-approved")
        self.assertFalse(manifest["trainingAuthorized"])
        self.assertEqual(publication["summary"]["approved"], 24)
        self.assertTrue(all(value is False or value == "0" for value in publication["authority"].values()))

    def test_rejection_is_valid_evidence_but_blocks_promotion(self):
        decisions = load_decisions()
        rejected = decisions[0]
        rejected.update(
            {
                "reviewer": "human:reviewer-1",
                "reviewedAt": "2026-09-17T01:30:00Z",
                "verdict": "rejected",
                "criteria": {criterion: True for criterion in CRITERIA},
                "notes": "Constraint behavior needs correction.",
            }
        )
        rejected["criteria"]["constraintBehaviorCorrect"] = False
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = self.write_decisions(Path(temporary), decisions)
            state = load_review_state(ROOT, PLAN, decisions_path=path)
        self.assertEqual(state.summary, {"approved": 0, "rejected": 1, "pending": 23})
        with self.assertRaisesRegex(ValidationError, "requires 24 approved"):
            build_promotion_artifacts(state)


if __name__ == "__main__":
    unittest.main()
