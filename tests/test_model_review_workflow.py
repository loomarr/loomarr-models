from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_planner_model_review as publisher
import run_planner_model_review as runner
from loomarr_models.model_review import CRITERIA, ModelReviewError, load_config, preflight


def clean_git(_root: Path, _paths: object) -> str:
    return "a" * 40


class ModelReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ROOT / "experiments/planner-model-review-v10.json")
        cls.snapshot = json.loads(
            (ROOT / "reviews/planner-smoke-v1/model-review-v10-route-snapshot.json").read_text()
        )
        cls.plan = preflight(
            ROOT, ROOT / "experiments/planner-model-review-v10.json", git_probe=clean_git
        )

    def test_live_route_check_accepts_exact_snapshot_and_rejects_drift(self):
        responses = []
        for route in self.snapshot["reviewers"]:
            responses.append(
                (
                    b"{}",
                    {
                        "data": {
                            "endpoints": [
                                {
                                    "tag": route["providerTag"],
                                    "provider_name": route["providerDisplayName"],
                                    "name": f"Provider | {route['upstreamModel']}",
                                    "status": 0,
                                    "pricing": {
                                        "prompt": route["promptPriceUsdPerToken"],
                                        "completion": route["completionPriceUsdPerToken"],
                                    },
                                    "supported_parameters": route["requiredParameters"],
                                }
                            ]
                        }
                    },
                )
            )
        with mock.patch.object(runner, "_request_json", side_effect=responses):
            runner._verify_live_routes(self.config, self.snapshot)

        drifted = copy.deepcopy(responses)
        drifted[0][1]["data"]["endpoints"][0]["pricing"]["prompt"] = "0.1"
        with mock.patch.object(runner, "_request_json", side_effect=drifted):
            with self.assertRaisesRegex(ModelReviewError, "differs from frozen snapshot"):
                runner._verify_live_routes(self.config, self.snapshot)

    def test_settlement_poll_is_bounded_and_never_retries_inference(self):
        unsettled = (b"{}", {"data": {"total_cost": None}})
        settled = (b"{}", {"data": {"total_cost": 0.01}})
        config = copy.deepcopy(self.config)
        config["execution"]["settlementAttempts"] = 2
        with (
            mock.patch.object(runner, "_request_json", side_effect=[unsettled, settled]) as request,
            mock.patch.object(runner.time, "sleep"),
        ):
            self.assertEqual(runner._settle(config, "secret", "gen-1"), settled)
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.args[0] == "GET" for call in request.call_args_list))

    def test_settlement_poll_tolerates_only_transient_not_found(self):
        missing = runner.OpenRouterHTTPError(404, "generation not found")
        settled = (b"{}", {"data": {"total_cost": 0.01}})
        config = copy.deepcopy(self.config)
        config["execution"]["settlementAttempts"] = 2
        with (
            mock.patch.object(runner, "_request_json", side_effect=[missing, settled]) as request,
            mock.patch.object(runner.time, "sleep"),
        ):
            self.assertEqual(runner._settle(config, "secret", "gen-1"), settled)
        self.assertEqual(request.call_count, 2)
        with mock.patch.object(
            runner, "_request_json", side_effect=runner.OpenRouterHTTPError(500, "server error")
        ):
            with self.assertRaisesRegex(runner.OpenRouterHTTPError, "HTTP 500"):
                runner._settle(config, "secret", "gen-1")

    def test_provider_error_envelope_stops_before_settlement(self):
        request = self.plan.requests[0]
        one_call_plan = replace(
            self.plan,
            requestCount=1,
            requests=(request,),
            outputDir=".artifacts/provider-error-test",
        )
        response = {
            "id": "gen-rate-limited",
            "error": {"code": 429, "message": "temporarily rate-limited upstream"},
        }
        response_bytes = json.dumps(response).encode()
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            with (
                mock.patch.object(runner, "ROOT", temp_root),
                mock.patch.object(
                    runner, "_request_json", return_value=(response_bytes, response)
                ) as transport,
                self.assertRaisesRegex(ModelReviewError, "provider error 429"),
            ):
                runner.run(self.config, one_call_plan, "secret")
            output = temp_root / one_call_plan.outputDir
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(
                (output / "calls/primary-00.response.json").read_bytes(), response_bytes
            )
            self.assertFalse((output / "calls/primary-00.settlement.json").exists())
            state = json.loads((output / "run-state.json").read_text())
            self.assertEqual((state["status"], state["completedCalls"]), ("failed", 0))
            self.assertEqual(state["currentCall"]["responseId"], "gen-rate-limited")
            self.assertEqual(
                state["currentCall"]["responseSha256"],
                hashlib.sha256(response_bytes).hexdigest(),
            )

    def test_invalid_completion_is_persisted_settled_and_quarantined_without_retry(self):
        request = self.plan.requests[0]
        one_call_plan = replace(self.plan, requestCount=1, requests=(request,))
        invalid_output = {
            "schemaVersion": 1,
            "reviews": {
                "planner-smoke-injected-99": {
                    "verdict": "approved",
                    "criteria": [
                        {
                            "criterion": criterion,
                            "passed": True,
                            "evidence": f"Grounded evidence for {criterion} in the trace.",
                        }
                        for criterion in CRITERIA
                    ],
                    "summary": "All six criteria pass against the complete trace.",
                }
            },
        }
        response = {
            "id": "gen-invalid",
            "model": request.model,
            "provider": request.providerDisplayName,
            "choices": [
                {
                    "finish_reason": "stop",
                    "native_finish_reason": "stop",
                    "message": {"content": json.dumps(invalid_output)},
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cost": 0.01,
            },
        }
        settlement = {
            "data": {
                "id": "gen-invalid",
                "provider_name": request.providerDisplayName,
                "model": request.model,
                "finish_reason": "stop",
                "native_finish_reason": "stop",
                "total_cost": 0.01,
            }
        }
        response_bytes = json.dumps(response).encode()
        settlement_bytes = json.dumps(settlement).encode()
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            with (
                mock.patch.object(runner, "ROOT", temp_root),
                mock.patch.object(
                    runner,
                    "_request_json",
                    side_effect=[(response_bytes, response), (settlement_bytes, settlement)],
                ) as transport,
            ):
                result = runner.run(self.config, one_call_plan, "secret")
            output = temp_root / one_call_plan.outputDir
            self.assertEqual(transport.call_count, 2)
            self.assertEqual((output / "calls/primary-00.response.json").read_bytes(), response_bytes)
            self.assertEqual(
                (output / "calls/primary-00.settlement.json").read_bytes(), settlement_bytes
            )
            state = json.loads((output / "run-state.json").read_text())
            self.assertEqual((state["status"], state["completedCalls"]), ("complete", 1))
            self.assertEqual(state["actualCostUsd"], "0.01")
            self.assertEqual(state["invalidReviewCount"], 1)
            self.assertNotIn("currentCall", state)
            invalid = json.loads((output / "invalid-reviews.jsonl").read_text())
            self.assertEqual(invalid["responseId"], "gen-invalid")
            self.assertEqual(invalid["responseSha256"], hashlib.sha256(response_bytes).hexdigest())
            self.assertEqual(invalid["error"], "review output does not cover the exact batch trace ids")
            self.assertEqual(result["attestationCount"], 0)
            self.assertEqual(result["invalidReviewCount"], 1)

    def test_promotion_requires_two_passes_and_escalates_disagreement(self):
        attestations = []
        for request in self.plan.requests:
            reviewed_at = (
                "2026-09-03T03:00:00.000001Z"
                if request.role == "primary"
                else "2026-09-03T03:01:00.000001Z"
            )
            for trace_id in request.traceIds:
                attestations.append(
                    {
                        "schemaVersion": 1,
                        "traceId": trace_id,
                        "role": request.role,
                        "reviewer": f"openrouter:{request.model}",
                        "reviewerFamily": request.family,
                        "providerTag": request.providerTag,
                        "requestSha256": request.requestSha256,
                        "responseId": f"gen-{request.role}-{request.batchIndex}",
                        "responseSha256": "a" * 64,
                        "verdict": "approved",
                        "criteria": [
                            {
                                "criterion": criterion,
                                "passed": True,
                                "evidence": f"Grounded evidence for {criterion} in the trace.",
                            }
                            for criterion in CRITERIA
                        ],
                        "summary": "All six criteria pass against the complete trace.",
                        "reviewedAt": reviewed_at,
                        "batchIndex": request.batchIndex,
                        "settledCostUsd": "0.01",
                        "settlementSha256": "b" * 64,
                    }
                )
        decisions, escalations = publisher._decisions(attestations, [], self.plan)
        self.assertEqual((len(decisions), len(escalations)), (50, 0))

        secondary = next(
            item
            for item in attestations
            if item["role"] == "secondary" and item["traceId"] == decisions[0]["traceId"]
        )
        secondary["verdict"] = "rejected"
        secondary["criteria"][0]["passed"] = False
        decisions, escalations = publisher._decisions(attestations, [], self.plan)
        self.assertEqual(len(escalations), 1)
        self.assertEqual(escalations[0]["derivedStatus"], "pending")

        invalid = attestations.pop(0)
        invalid_review = {
            key: invalid[key]
            for key in (
                "schemaVersion",
                "traceId",
                "role",
                "reviewer",
                "reviewerFamily",
                "providerTag",
                "requestSha256",
                "responseId",
                "responseSha256",
                "reviewedAt",
                "batchIndex",
                "settledCostUsd",
                "settlementSha256",
            )
        }
        invalid_review["error"] = "invalid review summary"
        decisions, escalations = publisher._decisions(attestations, [invalid_review], self.plan)
        self.assertEqual(escalations[0]["primary"]["verdict"], "invalid")
        self.assertEqual(decisions[0]["primary"]["verdict"], "pending")


if __name__ == "__main__":
    unittest.main()
