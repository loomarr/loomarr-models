from __future__ import annotations

import copy
import unittest

from loomarr_models.review import (
    ReviewError,
    derive_review,
    empty_decision,
    secondary_review_required,
    trace_review,
)


def approve(block: dict, reviewer: str, timestamp: str, notes: str = "Checked all six criteria.") -> None:
    block.update(
        {"verdict": "approved", "reviewer": reviewer, "reviewedAt": timestamp, "notes": notes}
    )


class ReviewDecisionTests(unittest.TestCase):
    def test_secondary_review_selection_is_exactly_twenty_two(self):
        families = (
            "title-search",
            "genre-discovery",
            "keyword-discovery",
            "must-include",
            "must-exclude",
            "ambiguous-intent",
            "conflicting-intent",
            "empty-results",
            "tool-error-recovery",
            "malformed-final-repair",
        )
        selected = [
            f"planner-smoke-{family}-{variant:02d}"
            for family in families
            for variant in range(1, 6)
            if secondary_review_required(f"planner-smoke-{family}-{variant:02d}")
        ]
        self.assertEqual(len(selected), 22)

    def test_non_sampled_primary_approval_is_complete(self):
        decision = empty_decision("planner-smoke-title-search-02")
        approve(decision["primary"], "github:alice", "2026-09-03T02:00:00Z")
        review = derive_review(decision, require_complete=True)
        self.assertEqual(review.status, "approved")
        self.assertEqual(trace_review(decision)["reviewer"], "github:alice")

    def test_sampled_trace_requires_distinct_ordered_secondary_approval(self):
        decision = empty_decision("planner-smoke-empty-results-03")
        approve(decision["primary"], "github:alice", "2026-09-03T02:00:00Z")
        with self.assertRaisesRegex(ReviewError, "review incomplete"):
            derive_review(decision, require_complete=True)
        approve(decision["secondary"], "github:bob", "2026-09-03T02:01:00Z")
        self.assertEqual(derive_review(decision, require_complete=True).status, "approved")

        same_reviewer = copy.deepcopy(decision)
        same_reviewer["secondary"]["reviewer"] = "github:alice"
        with self.assertRaisesRegex(ReviewError, "must differ"):
            derive_review(same_reviewer)

        predates = copy.deepcopy(decision)
        predates["secondary"]["reviewedAt"] = "2026-09-03T01:59:00Z"
        with self.assertRaisesRegex(ReviewError, "must follow"):
            derive_review(predates)

        simultaneous = copy.deepcopy(decision)
        simultaneous["secondary"]["reviewedAt"] = "2026-09-03T02:00:00Z"
        with self.assertRaisesRegex(ReviewError, "must follow"):
            derive_review(simultaneous)

    def test_disagreement_stays_pending_with_evidence_but_cannot_freeze(self):
        decision = empty_decision("planner-smoke-tool-error-recovery-02")
        approve(decision["primary"], "github:alice", "2026-09-03T02:00:00Z")
        decision["secondary"].update(
            {
                "verdict": "rejected",
                "reviewer": "github:bob",
                "reviewedAt": "2026-09-03T02:01:00Z",
                "notes": "Tool recovery target needs correction.",
            }
        )
        derived = derive_review(decision)
        projected = trace_review(decision)
        self.assertEqual(derived.status, "pending")
        self.assertEqual((projected["reviewer"], projected["reviewedAt"]), ("", None))
        self.assertIn("github:bob", projected["notes"])
        with self.assertRaisesRegex(ReviewError, "disagreement"):
            derive_review(decision, require_complete=True)

    def test_refuses_false_evidence_and_invalid_reviewer_or_timestamp(self):
        pending = empty_decision("planner-smoke-title-search-02")
        pending["primary"]["notes"] = "not actually reviewed"
        with self.assertRaisesRegex(ReviewError, "false evidence"):
            derive_review(pending)

        invalid = empty_decision("planner-smoke-title-search-02")
        approve(invalid["primary"], "person:alice", "2026-09-03T02:00:00Z")
        with self.assertRaisesRegex(ReviewError, "github:<login>"):
            derive_review(invalid)

        invalid["primary"]["reviewer"] = "github:alice"
        invalid["primary"]["reviewedAt"] = "2026-09-03T02:00:00+01:00"
        with self.assertRaisesRegex(ReviewError, "RFC 3339 UTC"):
            derive_review(invalid)


if __name__ == "__main__":
    unittest.main()
