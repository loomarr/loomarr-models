from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from loomarr_models.experiment import PreflightError
from loomarr_models.local_screen import LocalScreenPlan
from loomarr_models.local_screen_runtime import (
    OllamaTurnGenerator,
    parse_ollama_turn,
    probe_ollama_candidate,
    run_candidate,
    to_ollama_messages,
)


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads(
    (ROOT / "reviews/planner-v4-local-screen/ollama-snapshot.json").read_text(encoding="utf-8")
)


class LocalScreenRuntimeTests(unittest.TestCase):
    def test_converts_tool_round_trip_for_ollama(self):
        converted = to_ollama_messages(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "intent"},
                {
                    "role": "assistant",
                    "toolCalls": [
                        {"id": "ignored", "name": "catalog_search", "arguments": {"query": "X"}}
                    ],
                },
                {
                    "role": "tool",
                    "toolCallId": "ignored",
                    "name": "catalog_search",
                    "content": {"candidates": []},
                },
            ]
        )
        self.assertEqual(converted[2]["tool_calls"][0]["function"]["arguments"], {"query": "X"})
        self.assertEqual(converted[3]["tool_name"], "catalog_search")
        self.assertEqual(converted[3]["content"], '{"candidates":[]}')

    def test_parses_native_tool_call_and_final(self):
        self.assertEqual(
            parse_ollama_turn(
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "catalog_search",
                                    "arguments": {"keywords": ["signal"]},
                                }
                            }
                        ],
                    }
                },
                3,
            ),
            {
                "role": "assistant",
                "toolCalls": [
                    {
                        "id": "ollama-call-3-1",
                        "name": "catalog_search",
                        "arguments": {"keywords": ["signal"]},
                    }
                ],
            },
        )
        self.assertEqual(
            parse_ollama_turn(
                {"message": {"role": "assistant", "content": "  {\"picks\":[]}  "}}, 4
            ),
            {"role": "assistant", "content": '{"picks":[]}'},
        )

    def test_generator_pins_deterministic_request_and_redacts_thinking(self):
        seen = []

        def transport(path, payload, timeout):
            seen.append((path, payload, timeout))
            return {
                "message": {
                    "role": "assistant",
                    "content": "{}",
                    "thinking": "private chain",
                },
                "prompt_eval_count": 5,
                "eval_count": 2,
                "done_reason": "stop",
            }

        generator = OllamaTurnGenerator(
            base_url="http://127.0.0.1:11434",
            model="fixture:model",
            comparison={
                "seed": 3407,
                "numCtx": 4096,
                "numPredict": 768,
                "temperature": 0,
                "think": "low",
                "keepAlive": "5m",
            },
            timeout_seconds=600,
            transport=transport,
        )
        self.assertEqual(
            generator([{"role": "user", "content": "synthetic"}], []),
            {"role": "assistant", "content": "{}"},
        )
        payload = seen[0][1]
        self.assertEqual(payload["options"]["seed"], 3407)
        self.assertFalse(payload["stream"])
        self.assertEqual(generator.records[0]["thinkingSha256"], hashlib.sha256(b"private chain").hexdigest())
        self.assertNotIn("private chain", json.dumps(generator.records[0]))

    def test_live_probe_requires_exact_frozen_identity(self):
        template = "frozen template"
        modelfile = "frozen modelfile"
        candidate = {
            **SNAPSHOT["candidates"][0],
            "templateSha256": hashlib.sha256(template.encode()).hexdigest(),
            "modelfileSha256": hashlib.sha256(modelfile.encode()).hexdigest(),
        }
        responses = self._responses(candidate)

        def transport(path, payload, _timeout):
            if path == "/api/show":
                self.assertEqual(payload, {"model": candidate["model"], "verbose": True})
            return responses[path]

        report = probe_ollama_candidate(transport, candidate, SNAPSHOT["serverVersion"])
        self.assertEqual(report["digest"], candidate["digest"])
        responses["/api/tags"]["models"][0]["digest"] = "0" * 64
        with self.assertRaisesRegex(PreflightError, "digest or size differs"):
            probe_ollama_candidate(transport, candidate, SNAPSHOT["serverVersion"])

    def test_candidate_run_writes_replayable_hash_bound_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_source = ROOT / "experiments/planner-v4-local-screen-v1.json"
            config = json.loads(config_source.read_text(encoding="utf-8"))
            config_path = root / config_source.relative_to(ROOT)
            config_path.parent.mkdir(parents=True)
            config_path.write_bytes(config_source.read_bytes())
            for name in ("contract", "cases"):
                source = ROOT / config["bindings"][name]["path"]
                destination = root / config["bindings"][name]["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            plan = LocalScreenPlan(
                schemaVersion=1,
                screenId=config["screenId"],
                configSha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                casesSha256=config["bindings"]["cases"]["sha256"],
                caseCount=120,
                contractId="loomarr-planner-contract-v4",
                sourceCommit="a" * 40,
                outputDir=config["execution"]["outputDir"],
                candidateIds=tuple(config["comparison"]["candidateOrder"]),
                externalCostUsd="0",
            )

            def transport(path, _payload, _timeout):
                self.assertEqual(path, "/api/chat")
                return {
                    "message": {"role": "assistant", "content": "{}", "thinking": ""},
                    "done_reason": "stop",
                }

            frozen = SNAPSHOT["candidates"][0]
            live_model = {
                "serverVersion": SNAPSHOT["serverVersion"],
                "model": frozen["model"],
                "digest": frozen["digest"],
                **{
                    key: frozen[key]
                    for key in (
                        "parameterCount",
                        "contextLength",
                        "format",
                        "quantization",
                        "capabilities",
                        "templateSha256",
                        "modelfileSha256",
                    )
                },
            }
            with contextlib.redirect_stdout(io.StringIO()):
                manifest = run_candidate(
                    root,
                    config_path,
                    config,
                    plan,
                    SNAPSHOT,
                    frozen["candidateId"],
                    transport=transport,
                    host_probe=lambda: SNAPSHOT["host"],
                    candidate_probe=lambda _client, _candidate, _version: live_model,
                )
            output = root / plan.outputDir / frozen["candidateId"]
            self.assertEqual(manifest["caseCount"], 120)
            self.assertEqual(manifest["summary"]["caseCount"], 120)
            self.assertEqual(manifest["externalCostUsd"], "0")
            self.assertEqual(len((output / "results.jsonl").read_text().splitlines()), 120)
            self.assertEqual(len((output / "generations.jsonl").read_text().splitlines()), 120)

    @staticmethod
    def _responses(candidate):
        architecture = candidate["architecture"]
        template = "frozen template"
        modelfile = "frozen modelfile"
        return {
            "/api/version": {"version": SNAPSHOT["serverVersion"]},
            "/api/tags": {
                "models": [
                    {
                        "name": candidate["model"],
                        "digest": candidate["digest"],
                        "size": candidate["sizeBytes"],
                    }
                ]
            },
            "/api/show": {
                "model_info": {
                    "general.architecture": architecture,
                    "general.parameter_count": candidate["parameterCount"],
                    f"{architecture}.context_length": candidate["contextLength"],
                },
                "details": {
                    "format": candidate["format"],
                    "quantization_level": candidate["quantization"],
                },
                "capabilities": candidate["capabilities"],
                "template": template,
                "modelfile": modelfile,
            },
        }


if __name__ == "__main__":
    unittest.main()
