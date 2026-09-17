from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from loomarr_models.v4_model_review import (
    REVIEWERS,
    V4ReviewPreflightError,
    canonical,
    preflight,
    request_payload,
    request_plan_bytes,
    v4_audit_contract,
)
from loomarr_models.validator import load_contract, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_planner_v4_review as runner


CONTRACT_PATH = ROOT / "contracts/planner-contract-v4.json"
TRAINING_PATH = ROOT / "corpus/planner-v4-delta/drafts.jsonl"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-development-v4/cases.jsonl"
SNAPSHOT_PATH = ROOT / "reviews/planner-behavior-v3/route-snapshot.json"
BUDGET_PATH = ROOT / "budgets/external-spend-v1.json"
CONFIG_PATH = ROOT / "experiments/planner-v4-delta-review-v1.json"
REQUEST_PLAN_PATH = ROOT / "reviews/planner-v4-delta/request-plan.jsonl"


class V4ModelReviewPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(CONTRACT_PATH)
        cls.traces = load_jsonl(TRAINING_PATH)
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        cls.budget = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
        cls.plan = preflight(
            cls.traces,
            contract=cls.contract,
            route_snapshot=cls.snapshot,
            budget=cls.budget,
        )

    def test_exact_dual_review_plan_fits_the_bounded_reservation(self):
        self.assertEqual((self.plan.trace_count, self.plan.request_count), (60, 120))
        self.assertEqual(self.plan.batch_size, 1)
        self.assertEqual(self.plan.output_token_upper_bound, 360000)
        self.assertEqual(self.plan.reservation_usd, "8.00")
        self.assertLessEqual(Decimal(self.plan.worst_case_cost_usd), Decimal("8.00"))
        self.assertEqual(self.plan.projected_spend_usd, "36.8046085599664530175")
        self.assertEqual(self.plan.authorization_usd, "40.00")
        payload = request_plan_bytes(self.plan.requests)
        self.assertEqual(payload, REQUEST_PLAN_PATH.read_bytes())
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            self.plan.request_plan_sha256,
        )

    def test_payload_carries_exact_v4_audit_semantics_and_strict_routes(self):
        payload = request_payload(
            REVIEWERS[0],
            self.traces[0],
            contract=self.contract,
            max_output_tokens=3000,
        )
        packet = json.loads(payload["messages"][1]["content"])
        audit = packet["auditContract"]
        self.assertEqual(audit, v4_audit_contract(self.contract))
        self.assertEqual(audit["toolDeclaration"], self.contract["tools"][0])
        self.assertEqual(audit["auditSemantics"]["tvNetwork"]["requiredMediaType"], "series")
        self.assertEqual(audit["auditSemantics"]["moviePeople"]["requiredMediaType"], "movie")
        self.assertTrue(
            audit["auditSemantics"]["seriesPersonIntent"][
                "personMayBeSelectedOnlyFromReturnedCandidateEvidence"
            ]
        )
        self.assertEqual(payload["provider"]["only"], ["google-ai-studio"])
        self.assertFalse(payload["provider"]["allow_fallbacks"])
        self.assertEqual(payload["provider"]["data_collection"], "deny")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(packet["requiredTraceIds"], [self.traces[0]["traceId"]])

    def test_development_gate_is_bound_but_never_sent_for_review(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        development = load_jsonl(DEVELOPMENT_PATH)
        self.assertEqual(config["bindings"]["developmentCases"]["count"], 120)
        self.assertEqual(
            config["bindings"]["developmentCases"]["sha256"],
            hashlib.sha256(DEVELOPMENT_PATH.read_bytes()).hexdigest(),
        )
        serialized = b"".join(
            canonical(
                request_payload(
                    reviewer,
                    trace,
                    contract=self.contract,
                    max_output_tokens=3000,
                )
            )
            for reviewer in REVIEWERS
            for trace in self.traces
        ).decode()
        self.assertNotIn(development[0]["caseId"], serialized)
        self.assertNotIn(development[-1]["caseId"], serialized)
        self.assertNotIn("fresh v4 development slate", serialized)

    def test_contract_route_budget_and_count_drift_fail_closed(self):
        contract = copy.deepcopy(self.contract)
        del contract["tools"][0]["Parameters"]["properties"]["network"]
        with self.assertRaisesRegex(V4ReviewPreflightError, "entity-route audit evidence"):
            v4_audit_contract(contract)

        route = copy.deepcopy(self.snapshot)
        route["reviewers"][1]["providerTag"] = "claude-on-aws"
        with self.assertRaisesRegex(V4ReviewPreflightError, "route identity drifted"):
            preflight(
                self.traces,
                contract=self.contract,
                route_snapshot=route,
                budget=self.budget,
            )

        budget = copy.deepcopy(self.budget)
        budget["postedSpendUsd"] = "39.90"
        budget["outstandingReservationsUsd"] = "0.10"
        budget["committedSpendUsd"] = "40.00"
        with self.assertRaisesRegex(V4ReviewPreflightError, "exceeds authorization"):
            preflight(
                self.traces,
                contract=self.contract,
                route_snapshot=self.snapshot,
                budget=budget,
            )

        with self.assertRaisesRegex(V4ReviewPreflightError, "exactly 60"):
            preflight(
                self.traces[:-1],
                contract=self.contract,
                route_snapshot=self.snapshot,
                budget=self.budget,
            )


class V4ModelReviewRunnerTests(unittest.TestCase):
    def test_reconstructs_exact_requests_without_authorizing_paid_calls(self):
        config, plan, snapshot = runner.build_plan(
            CONFIG_PATH,
            require_authorized=False,
            git_probe=lambda _root, _paths: "a" * 40,
        )
        self.assertEqual(config["status"], "planned-no-paid-calls-authorized")
        self.assertFalse(plan.paidReviewAuthorized)
        self.assertEqual((plan.traceCount, plan.requestCount), (60, 120))
        self.assertEqual(len(plan.requests), 120)
        self.assertEqual(
            [(request.role, request.batchIndex) for request in plan.requests],
            [("primary", index) for index in range(60)]
            + [("secondary", index) for index in range(60)],
        )
        self.assertEqual(plan.sourceCommit, "a" * 40)
        self.assertEqual(plan.requests[-1].providerTag, "anthropic")
        self.assertEqual(snapshot["reviewers"][1]["providerTag"], "anthropic")

    def test_paid_execution_refuses_before_key_or_network(self):
        with self.assertRaisesRegex(V4ReviewPreflightError, "not authorized"):
            runner.build_plan(
                CONFIG_PATH,
                require_authorized=True,
                git_probe=lambda _root, _paths: "a" * 40,
            )

    def test_request_plan_binding_and_content_drift_fail_closed(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["bindings"]["requestPlan"]["sha256"] = "0" * 64
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=ROOT, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(config, handle)
            config_path = Path(handle.name)
        try:
            with self.assertRaisesRegex(V4ReviewPreflightError, "requestPlan digest mismatch"):
                runner.build_plan(
                    config_path,
                    require_authorized=False,
                    git_probe=lambda _root, _paths: "a" * 40,
                )
        finally:
            config_path.unlink(missing_ok=True)

        with tempfile.NamedTemporaryFile(dir=ROOT, delete=False) as handle:
            handle.write(REQUEST_PLAN_PATH.read_bytes() + b"{}\n")
            request_path = Path(handle.name)
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        config["bindings"]["requestPlan"].update(
            {
                "path": str(request_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "count": 121,
            }
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=ROOT, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(config, handle)
            config_path = Path(handle.name)
        try:
            with self.assertRaisesRegex(V4ReviewPreflightError, "request plan drifted"):
                runner.build_plan(
                    config_path,
                    require_authorized=False,
                    git_probe=lambda _root, _paths: "a" * 40,
                )
        finally:
            request_path.unlink(missing_ok=True)
            config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
