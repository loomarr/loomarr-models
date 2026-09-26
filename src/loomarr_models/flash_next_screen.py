"""Zero-spend screen of the served Qwen3.8-Flash-Next model on the current-contract gate.

Loomarr uses Flash-Next through the OpenAI-compatible llama-server on fictional-ai-server for every
function, so this screen calls that same endpoint instead of rendering prompts locally. Cases,
contract, scorer, thresholds, call budget, and completion budget match the v3 stock baseline;
decoding is greedy. The `single-call` variant sets `parallel_tool_calls=false` to measure how much
of the gap is the one-operation-per-turn protocol rather than model judgment.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from .current_baseline import SCORING, baseline_decision, evaluate_current_case, summarize_current_candidate
from .current_baseline_v3 import COMPARISON
from .current_contract import read_jsonl
from .eval_runtime import _to_huggingface_messages
from .experiment import PreflightError, _git_probe, _input_path, sha256_file
from .stock_runtime import redact_generation_records
from .training_data import to_huggingface_tools


EXPERIMENT_ID = "planner-current-flash-next-screen-v1"
VARIANTS = {"default": {}, "single-call": {"parallel_tool_calls": False}}
ENDPOINT = {
    "host": "fictional-ai-server",
    "service": "fictional-ai-primary",
    "baseUrl": "http://127.0.0.1:8080/v1",
    "modelAlias": "flash-next",
    "apiKeyFile": "/etc/fictional-ai/api-keys",
}
DECODING = {
    "temperature": 0.0,
    "seed": COMPARISON["seed"],
    "maxTokens": COMPARISON["maxNewTokens"],
    "maxModelCallsPerCase": COMPARISON["maxModelCallsPerCase"],
    "requestTimeoutSeconds": 600,
}
AUTHORITY = {
    "externalSpendAuthorized": False,
    "trainingAuthorized": False,
    "certificationAuthority": False,
    "deploymentAuthority": False,
    "releaseAuthority": False,
}
BINDINGS = {
    "cases": "evaluation/planner-current-v1/cases.jsonl",
    "casesManifest": "evaluation/planner-current-v1/manifest.json",
    "contract": "contracts/planner-contract-v5.json",
    "holdoutDenylist": "contracts/planner-holdout-denylist-v2.json",
    "referenceBaseline": "runs/planner-current-qwen-stock-baseline-v3/publication.json",
    "generator": "scripts/build_planner_flash_next_screen.py",
    "runner": "scripts/run_planner_flash_next_screen.py",
    "runtime": "src/loomarr_models/flash_next_screen.py",
}


class OpenAIChatTurnGenerator:
    def __init__(self, api_key: str, extra: dict[str, Any]):
        self.api_key = api_key
        self.extra = extra
        self.records: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": ENDPOINT["modelAlias"],
            "messages": _to_openai_messages(messages),
            "tools": to_huggingface_tools(tools),
            "temperature": DECODING["temperature"],
            "seed": DECODING["seed"],
            "max_tokens": DECODING["maxTokens"],
            **self.extra,
        }
        request = urllib.request.Request(
            f"{ENDPOINT['baseUrl']}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=DECODING["requestTimeoutSeconds"]) as response:
            body = json.loads(response.read())
        choice = body["choices"][0]
        message = choice["message"]
        parsed = parse_openai_turn(message, len(self.records) + 1)
        self.records.append(
            {
                "schemaVersion": 1,
                "modelCall": len(self.records) + 1,
                "inputTokens": body.get("usage", {}).get("prompt_tokens"),
                "outputTokens": body.get("usage", {}).get("completion_tokens"),
                "finishReason": choice.get("finish_reason"),
                "elapsedSeconds": time.monotonic() - started,
                "raw": json.dumps(message, sort_keys=True),
                "parsed": parsed,
            }
        )
        return parsed


def parse_openai_turn(message: dict[str, Any], call_number: int) -> dict[str, Any]:
    calls = message.get("tool_calls") or []
    if calls:
        parsed_calls = []
        for index, call in enumerate(calls):
            function = call.get("function", {})
            try:
                arguments = json.loads(function.get("arguments") or "")
            except json.JSONDecodeError:
                arguments = function.get("arguments")
            parsed_calls.append(
                {"id": f"model-call-{call_number}-{index}", "name": function.get("name"), "arguments": arguments}
            )
        return {"role": "assistant", "toolCalls": parsed_calls}
    content = message.get("content") or ""
    content = re.sub(r"\A(?:<think>)?.*?</think>\s*", "", content, count=1, flags=re.DOTALL).strip()
    return {"role": "assistant", "content": content}


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = _to_huggingface_messages(messages)
    for message in converted:
        for call in message.get("tool_calls", []):
            if not isinstance(call["function"]["arguments"], str):
                call["function"]["arguments"] = json.dumps(call["function"]["arguments"], sort_keys=True)
    return converted


def read_api_key(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()
    raise PreflightError("no API key available")


def preflight(root: Path, config_path: Path, *, git_probe: Any = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        config.get("experimentId") != EXPERIMENT_ID
        or config.get("endpoint") != ENDPOINT
        or config.get("decoding") != DECODING
        or config.get("scoring") != SCORING
        or config.get("variants") != VARIANTS
        or config.get("authority") != AUTHORITY
        or set(config.get("bindings", {})) != set(BINDINGS)
    ):
        raise PreflightError("Flash-Next screen config differs from the pinned plan")
    bound = {}
    for name, binding in config["bindings"].items():
        bound[name] = _input_path(root, Path(binding["path"]))
        if binding["path"] != BINDINGS[name] or sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"Flash-Next screen {name} digest mismatch")
    return {
        "experimentId": EXPERIMENT_ID,
        "configSha256": sha256_file(config_path),
        "casesSha256": sha256_file(bound["cases"]),
        "sourceCommit": (git_probe or _git_probe)(root, [config_path, *bound.values()]),
        "externalSpendUsd": "0",
    }


def run_screen(root: Path, plan: dict[str, Any], variant: str, api_key: str) -> dict[str, Any]:
    output = root / ".artifacts" / EXPERIMENT_ID / variant
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing output: {output}")
    server = _server_identity(api_key)
    output.mkdir(parents=True)
    contract = json.loads((root / BINDINGS["contract"]).read_text(encoding="utf-8"))
    cases = read_jsonl(root / BINDINGS["cases"])
    generator = OpenAIChatTurnGenerator(api_key, VARIANTS[variant])
    started = time.monotonic()
    results = []
    for index, case in enumerate(cases, start=1):
        results.append(
            evaluate_current_case(
                case,
                system_prompt=contract["systemPrompt"],
                tools=contract["tools"],
                generate=generator,
                max_model_calls=DECODING["maxModelCallsPerCase"],
            )
        )
        print(f"flash-next screen {variant}: case={index}/{len(cases)} caseId={case['caseId']}", flush=True)
    results_bytes = _jsonl(result.as_dict() for result in results)
    generations_bytes = _jsonl(redact_generation_records(generator.records))
    (output / "results.jsonl").write_bytes(results_bytes)
    (output / "generations.jsonl").write_bytes(generations_bytes)
    summary = summarize_current_candidate(f"qwen38-flash-next-served-{variant}", results)
    manifest = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "variant": variant,
        "status": "complete",
        "preflight": plan,
        "server": server,
        "elapsedSeconds": time.monotonic() - started,
        "artifacts": {
            "results": {"path": "results.jsonl", "sha256": hashlib.sha256(results_bytes).hexdigest()},
            "generations": {"path": "generations.jsonl", "sha256": hashlib.sha256(generations_bytes).hexdigest()},
        },
        "summary": summary,
        "decision": baseline_decision(summary, SCORING),
        "externalSpendUsd": "0",
        "authority": AUTHORITY,
    }
    (output / "run-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _server_identity(api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{ENDPOINT['baseUrl']}/models", headers={"Authorization": f"Bearer {api_key}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        models = json.loads(response.read())
    return {"models": [{"id": m.get("id"), "meta": m.get("meta")} for m in models.get("data", [])]}


def _jsonl(records: Any) -> bytes:
    return b"".join(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n" for r in records)
