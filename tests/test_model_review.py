from __future__ import annotations

import copy
import hashlib
import json
import unittest
from decimal import Decimal
from pathlib import Path

from loomarr_models.model_review import (
    CRITERIA,
    ModelReviewContentError,
    ModelReviewError,
    _validate_budget,
    canonical,
    preflight,
    project_live_endpoint,
    validate_completion,
    validate_settlement,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-model-review-v7.json"


def clean_git(_root: Path, _paths: object) -> str:
    return "a" * 40


def valid_output(request) -> dict:
    return {
        "schemaVersion": 1,
        "reviews": {
            trace_id: {
                "verdict": "approved",
                "criteria": {
                    criterion: {
                        "passed": True,
                        "evidence": f"Concrete evidence for {criterion} appears in this trace.",
                    }
                    for criterion in CRITERIA
                },
                "summary": "All six criteria are supported by the complete synthetic trace.",
            }
            for trace_id in request.traceIds
        },
    }


def valid_response(request) -> dict:
    return {
        "id": "gen-test",
        "model": request.model,
        "provider": request.providerDisplayName,
        "choices": [
            {
                "finish_reason": "stop",
                "native_finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(valid_output(request))},
            }
        ],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "cost": 0.01,
        },
    }


class ModelReviewPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = preflight(ROOT, CONFIG, git_probe=clean_git)

    def test_exact_hundred_call_plan_fits_reservation_and_aggregate_cap(self):
        self.assertEqual((self.plan.traceCount, self.plan.requestCount), (50, 100))
        self.assertEqual(self.plan.outputTokenUpperBound, 200000)
        self.assertLessEqual(Decimal(self.plan.worstCaseCostUsd), Decimal("6.00"))
        self.assertEqual(self.plan.projectedSpendUsd, "10.851869891125471")
        self.assertEqual(self.plan.authorizationUsd, "40")
        self.assertEqual(
            [(item.role, item.batchIndex, len(item.traceIds)) for item in self.plan.requests],
            [("primary", index, 1) for index in range(50)]
            + [("secondary", index, 1) for index in range(50)],
        )

    def test_every_request_is_blind_strict_single_route_and_no_fallback(self):
        for request in self.plan.requests:
            provider = request.payload["provider"]
            self.assertEqual(provider["only"], [request.providerTag])
            self.assertEqual(
                provider,
                {
                    "only": [request.providerTag],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                    "data_collection": "deny",
                },
            )
            self.assertNotIn("zdr", provider)
            self.assertEqual(request.payload["response_format"]["type"], "json_schema")
            self.assertTrue(request.payload["response_format"]["json_schema"]["strict"])
            schema = request.payload["response_format"]["json_schema"]["schema"]
            reviews = schema["properties"]["reviews"]
            self.assertFalse(reviews["additionalProperties"])
            self.assertEqual(reviews["required"], list(request.traceIds))
            self.assertEqual(set(reviews["properties"]), set(request.traceIds))
            self.assertTrue(
                all(
                    "traceId" not in definition["properties"]
                    for definition in reviews["properties"].values()
                )
            )
            for definition in reviews["properties"].values():
                criteria = definition["properties"]["criteria"]
                self.assertFalse(criteria["additionalProperties"])
                self.assertEqual(criteria["required"], list(CRITERIA))
                self.assertEqual(set(criteria["properties"]), set(CRITERIA))
            self.assertNotIn("reviewer output", request.payload["messages"][1]["content"].lower())

    def test_budget_refuses_overflow_or_unreconciled_ledger(self):
        ledger = json.loads((ROOT / "budgets/external-spend-v1.json").read_text())
        overflow = copy.deepcopy(ledger)
        overflow["postedSpendUsd"] = "35.00"
        overflow["outstandingReservationsUsd"] = "0.00"
        overflow["committedSpendUsd"] = "35.00"
        with self.assertRaisesRegex(ModelReviewError, "exceed aggregate"):
            _validate_budget(overflow, Decimal("6.00"))
        unreconciled = copy.deepcopy(ledger)
        unreconciled["committedSpendUsd"] = "5.00"
        with self.assertRaisesRegex(ModelReviewError, "does not reconcile"):
            _validate_budget(unreconciled, Decimal("6.00"))


class ModelReviewEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request = preflight(ROOT, CONFIG, git_probe=clean_git).requests[0]

    def test_accepts_exact_grounded_shape(self):
        response = valid_response(self.request)
        raw = canonical(response)
        attestations = validate_completion(response, self.request, hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(attestations), 1)
        self.assertTrue(all(item["verdict"] == "approved" for item in attestations))

    def test_rejects_wrong_coverage_criteria_or_verdict(self):
        for sabotage, message in (
            ("trace", "exact batch"),
            ("criterion", "exact ordered six"),
            ("verdict", "does not match"),
        ):
            with self.subTest(sabotage=sabotage):
                response = valid_response(self.request)
                output = json.loads(response["choices"][0]["message"]["content"])
                if sabotage == "trace":
                    first = self.request.traceIds[0]
                    output["reviews"]["planner-smoke-injected-99"] = output["reviews"].pop(first)
                elif sabotage == "criterion":
                    criteria = output["reviews"][self.request.traceIds[0]]["criteria"]
                    criteria["injected"] = criteria.pop("intent")
                else:
                    output["reviews"][self.request.traceIds[0]]["criteria"]["intent"]["passed"] = False
                response["choices"][0]["message"]["content"] = json.dumps(output)
                with self.assertRaisesRegex(ModelReviewError, message):
                    validate_completion(response, self.request, "b" * 64)

    def test_distinguishes_model_authored_content_failure_from_envelope_failure(self):
        response = valid_response(self.request)
        response["choices"][0]["message"]["content"] = "not-json"
        with self.assertRaises(ModelReviewContentError):
            validate_completion(response, self.request, "b" * 64)
        response = valid_response(self.request)
        response["provider"] = "Other"
        with self.assertRaises(ModelReviewError) as raised:
            validate_completion(response, self.request, "b" * 64)
        self.assertNotIsInstance(raised.exception, ModelReviewContentError)

    def test_rejects_model_provider_finish_and_usage_drift(self):
        cases = (
            ("model", "other/model", "model differs"),
            ("provider", "Other", "provider differs"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                response = valid_response(self.request)
                response[field] = value
                with self.assertRaisesRegex(ModelReviewError, message):
                    validate_completion(response, self.request, "b" * 64)
        response = valid_response(self.request)
        response["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(ModelReviewContentError, "finish reason is 'length'"):
            validate_completion(response, self.request, "b" * 64)
        response = valid_response(self.request)
        del response["usage"]["cost"]
        with self.assertRaisesRegex(ModelReviewError, "invalid cost"):
            validate_completion(response, self.request, "b" * 64)

    def test_settlement_binds_generation_provider_model_finish_and_cost(self):
        response = valid_response(self.request)
        settlement = {
            "data": {
                "id": "gen-test",
                "provider_name": self.request.providerDisplayName,
                "model": self.request.model,
                "finish_reason": "stop",
                "native_finish_reason": "stop",
                "total_cost": 0.01,
            }
        }
        self.assertEqual(validate_settlement(settlement, self.request, response), Decimal("0.01"))
        settlement["data"]["provider_name"] = "Other"
        with self.assertRaisesRegex(ModelReviewError, "provider differs"):
            validate_settlement(settlement, self.request, response)
        response = valid_response(self.request)
        response["choices"][0]["finish_reason"] = "length"
        response["choices"][0]["native_finish_reason"] = "max_tokens"
        settlement = {
            "data": {
                "id": "gen-test",
                "provider_name": self.request.providerDisplayName,
                "model": self.request.model,
                "finish_reason": "length",
                "native_finish_reason": "max_tokens",
                "total_cost": 0.01,
            }
        }
        self.assertEqual(validate_settlement(settlement, self.request, response), Decimal("0.01"))
        settlement["data"]["finish_reason"] = "stop"
        with self.assertRaisesRegex(ModelReviewError, "finish reason differs"):
            validate_settlement(settlement, self.request, response)
        settlement = {
            "data": {
                "id": "gen-test",
                "provider_name": self.request.providerDisplayName,
                "model": self.request.model,
                "finish_reason": "length",
                "native_finish_reason": "end_turn",
                "total_cost": 0.01,
            }
        }
        with self.assertRaisesRegex(ModelReviewError, "native finish reason differs"):
            validate_settlement(settlement, self.request, response)

    def test_live_endpoint_projection_has_only_stable_pinned_fields(self):
        endpoint = {
            "tag": "anthropic",
            "provider_name": "Anthropic",
            "name": "Anthropic | anthropic/claude-sonnet-5-20260630",
            "pricing": {"prompt": "0.000002", "completion": "0.00001"},
            "supported_parameters": ["structured_outputs", "response_format", "reasoning", "max_tokens"],
            "latency_last_30m": 123,
        }
        projected = project_live_endpoint(
            endpoint, "primary", "anthropic", "anthropic/claude-sonnet-5"
        )
        self.assertNotIn("latency_last_30m", projected)
        self.assertEqual(projected["providerTag"], "anthropic")


if __name__ == "__main__":
    unittest.main()
