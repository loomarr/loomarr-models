from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from loomarr_models.behavior_model_review import (
    CORRECTED_PACKET_VERSION,
    REVIEWERS,
    BehaviorReviewPreflightError,
    canonical,
    preflight,
    request_payload,
    request_plan_bytes,
    targeted_audit_contract,
)
from loomarr_models.validator import load_contract, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
TRACES_PATH = ROOT / "corpus/planner-behavior-v2/drafts.jsonl"
SNAPSHOT_PATH = ROOT / "reviews/planner-behavior-v2/route-snapshot.json"
BUDGET_PATH = ROOT / "budgets/external-spend-v1.json"
REQUEST_PLAN_PATH = ROOT / "reviews/planner-behavior-v2/request-plan.jsonl"
REPORT_PATH = ROOT / "reviews/planner-behavior-v2/preflight-report.json"
CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
CORRECTED_REQUEST_PLAN_PATH = ROOT / "reviews/planner-behavior-v3/request-plan.jsonl"
CORRECTED_REPORT_PATH = ROOT / "reviews/planner-behavior-v3/preflight-report.json"


class BehaviorReviewPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.traces = load_jsonl(TRACES_PATH)
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        cls.budget = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))

    def test_exact_compact_plan_fits_reservation_without_authorizing_inference(self):
        plan = preflight(self.traces, route_snapshot=self.snapshot, budget=self.budget)
        self.assertEqual(plan.traceCount, 120)
        self.assertEqual(plan.requestCount, 240)
        self.assertEqual(plan.batchSize, 1)
        self.assertEqual(plan.inputByteUpperBound, 1675120)
        self.assertEqual(plan.outputTokenUpperBound, 720000)
        self.assertEqual(plan.worstCaseCostUsd, "13.906540")
        self.assertEqual(plan.reservationUsd, "15.00")
        self.assertEqual(plan.projectedSpendUsd, "38.3611685675672820")
        payload = request_plan_bytes(plan)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), plan.requestPlanSha256)
        self.assertEqual(payload, REQUEST_PLAN_PATH.read_bytes())
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(report["inferenceCalls"], 0)
        self.assertEqual(report["externalCostUsd"], "0")
        self.assertFalse(report["paidReviewAuthorized"])

    def test_packet_is_compact_but_preserves_every_audited_turn_and_strict_route(self):
        payload = request_payload(REVIEWERS[0], [self.traces[0]], max_output_tokens=3000)
        production_contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        serialized = canonical(payload).decode()
        self.assertNotIn(production_contract["systemPrompt"], serialized)
        self.assertNotIn(json.dumps(production_contract["tools"]), serialized)
        packet = json.loads(payload["messages"][1]["content"])
        compact = packet["traces"][0]
        self.assertEqual(compact["traceId"], self.traces[0]["traceId"])
        self.assertEqual(compact["intent"], self.traces[0]["messages"][1]["content"])
        self.assertEqual(compact["turns"], self.traces[0]["messages"][2:])
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["provider"]["only"], ["google-ai-studio"])
        self.assertFalse(payload["provider"]["allow_fallbacks"])
        self.assertEqual(payload["provider"]["data_collection"], "deny")

    def test_corrected_packet_supplies_the_missing_authoritative_semantics(self):
        contract = load_contract(CONTRACT_PATH)
        with self.assertRaisesRegex(BehaviorReviewPreflightError, "requires the contract bundle"):
            request_payload(
                REVIEWERS[0],
                [self.traces[0]],
                max_output_tokens=3000,
                packet_version=CORRECTED_PACKET_VERSION,
            )
        payload = request_payload(
            REVIEWERS[0],
            [self.traces[0]],
            max_output_tokens=3000,
            packet_version=CORRECTED_PACKET_VERSION,
            contract_bundle=contract,
        )
        packet = json.loads(payload["messages"][1]["content"])
        self.assertNotIn("contractBinding", packet)
        audit = packet["auditContract"]
        self.assertEqual(audit, targeted_audit_contract(contract))
        self.assertEqual(audit["toolDeclaration"], contract["tools"][0])
        properties = audit["toolDeclaration"]["Parameters"]["properties"]
        self.assertIn("query", properties)
        self.assertNotIn("title", properties)
        search = audit["auditSemantics"]["search"]
        self.assertEqual(search["knownTitleArgument"], "query")
        self.assertTrue(search["knownTitleHasNoSeparateTitleArgument"])
        final = audit["auditSemantics"]["finalProposal"]
        self.assertTrue(final["picksMayBeEmpty"])
        self.assertIn("confidence", final["requiredFieldsForEachExistingPick"])
        self.assertTrue(final["emptyPicksThereforeRequireNoConfidenceField"])

        plan = preflight(
            self.traces,
            route_snapshot=self.snapshot,
            budget=self.budget,
            reservation_usd="16.50",
            packet_version=CORRECTED_PACKET_VERSION,
            contract_bundle=contract,
        )
        self.assertEqual(plan.traceCount, 120)
        self.assertEqual(plan.requestCount, 240)
        self.assertEqual(plan.inputByteUpperBound, 2359600)
        self.assertEqual(plan.worstCaseCostUsd, "15.617740")
        self.assertEqual(plan.projectedSpendUsd, "39.8611685675672820")
        self.assertEqual(request_plan_bytes(plan), CORRECTED_REQUEST_PLAN_PATH.read_bytes())
        report = json.loads(CORRECTED_REPORT_PATH.read_text(encoding="utf-8"))
        self.assertFalse(report["paidReviewAuthorized"])
        self.assertEqual(report["inferenceCalls"], 0)

    def test_multi_trace_batch_stays_disabled_without_exact_compile_proof(self):
        with self.assertRaisesRegex(BehaviorReviewPreflightError, "batch size|multi-trace"):
            preflight(
                self.traces,
                route_snapshot=self.snapshot,
                budget=self.budget,
                batch_size=3,
            )

    def test_route_price_and_budget_drift_fail_closed(self):
        route = copy.deepcopy(self.snapshot)
        route["reviewers"][1]["providerTag"] = "claude-on-aws"
        with self.assertRaisesRegex(BehaviorReviewPreflightError, "route identity drifted"):
            preflight(self.traces, route_snapshot=route, budget=self.budget)

        expensive = copy.deepcopy(self.snapshot)
        expensive["reviewers"][1]["completionPriceUsdPerToken"] = "0.00015"
        with self.assertRaisesRegex(BehaviorReviewPreflightError, "exceeds reservation"):
            preflight(self.traces, route_snapshot=expensive, budget=self.budget)

        budget = copy.deepcopy(self.budget)
        budget["committedSpendUsd"] = "30.10"
        budget["postedSpendUsd"] = "30.00"
        with self.assertRaisesRegex(BehaviorReviewPreflightError, "authorization envelope"):
            preflight(self.traces, route_snapshot=self.snapshot, budget=budget)


if __name__ == "__main__":
    unittest.main()
