from __future__ import annotations

import hashlib
import json
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v3.json"
REPORT_PATH = ROOT / "reviews/planner-behavior-v3/preflight-report.json"
INDEX_PATH = ROOT / "runs/planner-behavior-review-v3/index.json"


class CorrectedBehaviorReviewTests(unittest.TestCase):
    def test_plan_is_hash_bound_no_spend_and_inside_the_aggregate_cap(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

        self.assertEqual(config["reviewId"], "planner-behavior-review-v3")
        self.assertEqual(config["status"], "planned-no-paid-calls-authorized")
        self.assertFalse(config["execution"]["paidReviewAuthorized"])
        self.assertFalse(config["execution"]["compactTracePacket"])
        self.assertEqual(config["preflight"]["traceCount"], 120)
        self.assertEqual(config["preflight"]["requestCount"], 240)
        self.assertEqual(config["budget"]["worstCaseReviewUsd"], "15.617740")
        self.assertEqual(config["budget"]["reviewReservationUsd"], "16.50")
        self.assertLessEqual(
            Decimal(config["budget"]["projectedMaximumUsd"]),
            Decimal(config["budget"]["aggregateAuthorizationUsd"]),
        )
        self.assertEqual(report["inferenceCalls"], 0)
        self.assertEqual(report["externalCostUsd"], "0")
        self.assertFalse(report["paidReviewAuthorized"])
        self.assertEqual(index["status"], "planned-no-paid-calls-authorized")
        self.assertFalse(index["trainingAuthorized"])
        self.assertIn("authorize", index["nextGate"])

        prior = config["bindings"]["priorPublication"]
        prior_publication = json.loads((ROOT / prior["path"]).read_text(encoding="utf-8"))
        self.assertEqual(prior_publication["approved"], 118)
        self.assertEqual(prior_publication["escalations"], 2)
        self.assertEqual(
            prior["sha256"], hashlib.sha256((ROOT / prior["path"]).read_bytes()).hexdigest()
        )
        for artifact in index["artifacts"]:
            path = ROOT / artifact["path"]
            self.assertEqual(artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
