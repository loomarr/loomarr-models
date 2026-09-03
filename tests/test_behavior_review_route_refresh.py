from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import refresh_planner_behavior_routes as refresh
from loomarr_models.model_review import ModelReviewError


CONFIG_PATH = ROOT / "experiments/planner-behavior-review-v3.json"
SNAPSHOT_PATH = ROOT / "reviews/planner-behavior-v3/route-snapshot.json"


class CorrectedRouteRefreshTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    def endpoint_responses(self) -> dict[str, dict[str, Any]]:
        result = {}
        for route, source in zip(
            self.snapshot["reviewers"], self.snapshot["sources"], strict=True
        ):
            result[source] = {
                "data": {
                    "endpoints": [
                        {
                            "tag": route["providerTag"],
                            "status": 0,
                            "provider_name": route["providerDisplayName"],
                            "name": f"provider | {route['upstreamModel']}",
                            "pricing": {
                                "prompt": route["promptPriceUsdPerToken"],
                                "completion": route["completionPriceUsdPerToken"],
                            },
                            "supported_parameters": route["requiredParameters"],
                        }
                    ]
                }
            }
        return result

    def test_reconstructs_exact_snapshot_without_inference(self):
        responses = self.endpoint_responses()
        calls = []

        def fetch(method, url, api_key, payload, timeout):
            calls.append((method, url, api_key, payload, timeout))
            return b"{}", responses[url]

        actual = refresh.fetch_snapshot(
            self.config,
            "secret-not-printed",
            fetch=fetch,
            captured_at=self.snapshot["capturedAt"],
        )
        self.assertEqual(actual, self.snapshot)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[0] == "GET" and call[3] is None for call in calls))

    def test_refuses_unhealthy_or_parameter_incomplete_route(self):
        responses = self.endpoint_responses()
        first = self.snapshot["sources"][0]
        responses[first]["data"]["endpoints"][0]["status"] = -1

        def fetch_unhealthy(_method, url, _api_key, _payload, _timeout):
            return b"{}", responses[url]

        with self.assertRaisesRegex(ModelReviewError, "unavailable"):
            refresh.fetch_snapshot(self.config, "secret", fetch=fetch_unhealthy)

        responses = self.endpoint_responses()
        responses[first]["data"]["endpoints"][0]["supported_parameters"].remove(
            "structured_outputs"
        )

        def fetch_incomplete(_method, url, _api_key, _payload, _timeout):
            return b"{}", responses[url]

        with self.assertRaisesRegex(ModelReviewError, "lacks a required"):
            refresh.fetch_snapshot(self.config, "secret", fetch=fetch_incomplete)

    def test_only_disabled_v3_config_can_refresh(self):
        self.assertEqual(refresh.load_refresh_config(CONFIG_PATH), self.config)
        enabled = copy.deepcopy(self.config)
        enabled["status"] = "ready-for-review"
        enabled["execution"]["paidReviewAuthorized"] = True
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", dir=ROOT, delete=False, encoding="utf-8"
        ) as handle:
            json.dump(enabled, handle)
            path = Path(handle.name)
        try:
            with self.assertRaisesRegex(ValueError, "only the disabled corrected review"):
                refresh.load_refresh_config(path)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
