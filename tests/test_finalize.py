from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import finalize_planner_smoke as finalizer
from loomarr_models.review import empty_decision


def approve(block: dict, reviewer: str, timestamp: str) -> None:
    block.update(
        {
            "verdict": "approved",
            "reviewer": reviewer,
            "reviewedAt": timestamp,
            "notes": "Checked the complete synthetic trace against all review criteria.",
        }
    )


class FinalizeTests(unittest.TestCase):
    def test_builds_hash_linked_fifty_trace_artifact_after_complete_review(self):
        decisions = []
        for trace_id in finalizer.drafts.expected_trace_ids():
            decision = empty_decision(trace_id)
            approve(decision["primary"], "github:primary-reviewer", "2026-09-03T02:00:00Z")
            if decision["secondary"]["required"]:
                approve(
                    decision["secondary"],
                    "github:secondary-reviewer",
                    "2026-09-03T02:01:00Z",
                )
            decisions.append(decision)

        # Keep the synthetic decision file under the repository root because the
        # frozen manifest intentionally refuses to bind inputs from elsewhere.
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            review_path = Path(directory) / "reviews.jsonl"
            review_path.write_text(
                "".join(
                    json.dumps(decision, sort_keys=True, separators=(",", ":")) + "\n"
                    for decision in decisions
                ),
                encoding="utf-8",
            )
            with mock.patch.object(finalizer.drafts, "REVIEW_PATH", review_path):
                trace_bytes, manifest_bytes, report_bytes = finalizer.build_outputs()

        manifest = json.loads(manifest_bytes)
        report = json.loads(report_bytes)
        self.assertEqual(len(trace_bytes.splitlines()), 50)
        self.assertEqual(manifest["status"], "reviewed-frozen")
        self.assertEqual(manifest["secondaryReviewCount"], 50)
        self.assertEqual(report["result"], "pass")
        self.assertEqual((report["traces"], report["approved"], report["pending"]), (50, 50, 0))
        self.assertEqual(report["tracesSha256"], hashlib.sha256(trace_bytes).hexdigest())
        self.assertEqual(report["manifestSha256"], hashlib.sha256(manifest_bytes).hexdigest())


if __name__ == "__main__":
    unittest.main()
