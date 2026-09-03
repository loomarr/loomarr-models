from __future__ import annotations

import json
import unittest
from dataclasses import replace

from loomarr_models.eval_replay import replay_candidate
from loomarr_models.eval_runner import CaseResult, evaluate_case
from loomarr_models.experiment import PreflightError


CASE = {
    "caseId": "replay-case-01",
    "axis": "title-search",
    "intent": "Center a channel on Synthetic One.",
    "script": [
        {
            "arguments": {"query": "Synthetic One"},
            "result": {
                "candidates": [
                    {
                        "mediaType": "movie",
                        "tmdbId": 910001,
                        "name": "Synthetic One",
                    }
                ]
            },
        }
    ],
    "expectation": {
        "selectedIds": [{"mediaType": "movie", "tmdbId": 910001}],
        "forbiddenIds": [],
        "expectedPolicy": {},
        "abstain": False,
    },
}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "catalog_search",
            "description": "Synthetic search.",
            "parameters": {"type": "object"},
        },
    }
]
RECORDS = [
    {
        "modelCall": 1,
        "raw": """choose query
</think>
<tool_call><function=catalog_search><parameter=query>Synthetic One</parameter></function></tool_call>""",
    },
    {
        "modelCall": 2,
        "raw": """use the grounded candidate
</think>
{"channelName":"Synthetic Signal","rationale":"Synthetic fixture.","picks":[{"mediaType":"movie","tmdbId":910001,"name":"Synthetic One","rationale":"Requested fixture.","confidence":1.0}],"policy":{}}""",
    },
]


class EvalReplayTests(unittest.TestCase):
    def test_replays_captured_reasoning_prefix_and_preserves_measured_latency(self):
        position = 0

        def old_parser(_messages, _tools):
            nonlocal position
            raw = RECORDS[position]["raw"]
            position += 1
            if "<tool_call>" in raw:
                return {
                    "role": "assistant",
                    "toolCalls": [
                        {
                            "id": "old",
                            "name": "catalog_search",
                            "arguments": {"query": "Synthetic One"},
                        }
                    ],
                }
            return {"role": "assistant", "content": raw}

        original = evaluate_case(
            CASE,
            system_prompt="Synthetic system.",
            tools=TOOLS,
            generate=old_parser,
        )
        original = replace(original, latencyNanos=987654321)
        self.assertFalse(original.schemaValidity)

        replayed = replay_candidate(
            [CASE],
            system_prompt="Synthetic system.",
            tools=TOOLS,
            records=RECORDS,
            originals=[original],
            max_model_calls=5,
        )[0]
        self.assertTrue(replayed.schemaValidity)
        self.assertTrue(replayed.groundedCompletion)
        self.assertTrue(replayed.proposalQuality)
        self.assertEqual(replayed.latencyNanos, 987654321)

    def test_refuses_unconsumed_captured_generation(self):
        original = CaseResult(
            caseId=CASE["caseId"],
            axis=CASE["axis"],
            groundedCompletion=False,
            correctToolOperation=True,
            argumentValidity=True,
            schemaValidity=False,
            policyAccuracy=False,
            proposalQuality=False,
            recoveryExpected=False,
            recoverySuccessful=True,
            unsupportedIdCount=0,
            authorityViolationCount=0,
            modelCalls=2,
            toolCalls=1,
            latencyNanos=1,
            hardFailures=["schema_invalid"],
            transcript=[],
        )
        extra = {"modelCall": 3, "raw": json.dumps({"unused": True})}
        with self.assertRaisesRegex(PreflightError, "consumed 2 of 3"):
            replay_candidate(
                [CASE],
                system_prompt="Synthetic system.",
                tools=TOOLS,
                records=[*RECORDS, extra],
                originals=[original],
                max_model_calls=5,
            )


if __name__ == "__main__":
    unittest.main()
