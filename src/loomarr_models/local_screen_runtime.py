from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .eval_runner import evaluate_case, summarize_candidate
from .evaluation import load_cases
from .experiment import PreflightError, sha256_file
from .local_screen import LocalScreenPlan, canonical
from .training_data import to_huggingface_tools
from .validator import load_contract


Transport = Callable[[str, dict[str, Any] | None, int], dict[str, Any]]
HostProbe = Callable[[], dict[str, Any]]
CandidateProbe = Callable[[Transport, dict[str, Any], str], dict[str, Any]]


class OllamaTurnGenerator:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        comparison: dict[str, Any],
        timeout_seconds: int,
        transport: Transport,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.comparison = comparison
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.records: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        call_number = len(self.records) + 1
        payload = {
            "model": self.model,
            "messages": to_ollama_messages(messages),
            "tools": to_huggingface_tools(tools),
            "stream": False,
            "think": self.comparison["think"],
            "keep_alive": self.comparison["keepAlive"],
            "options": {
                "seed": self.comparison["seed"],
                "num_ctx": self.comparison["numCtx"],
                "num_predict": self.comparison["numPredict"],
                "temperature": self.comparison["temperature"],
            },
        }
        started = time.monotonic_ns()
        response = self.transport("/api/chat", payload, self.timeout_seconds)
        elapsed_nanos = time.monotonic_ns() - started
        parsed = parse_ollama_turn(response, call_number)
        message = response.get("message", {})
        thinking = message.get("thinking", "") if isinstance(message, dict) else ""
        self.records.append(
            {
                "schemaVersion": 1,
                "modelCall": call_number,
                "requestSha256": hashlib.sha256(canonical(payload)).hexdigest(),
                "responseSha256": hashlib.sha256(canonical(response)).hexdigest(),
                "thinkingSha256": hashlib.sha256(str(thinking).encode()).hexdigest(),
                "promptEvalCount": _nonnegative_int(response.get("prompt_eval_count")),
                "evalCount": _nonnegative_int(response.get("eval_count")),
                "loadDurationNanos": _nonnegative_int(response.get("load_duration")),
                "promptEvalDurationNanos": _nonnegative_int(response.get("prompt_eval_duration")),
                "evalDurationNanos": _nonnegative_int(response.get("eval_duration")),
                "elapsedNanos": elapsed_nanos,
                "doneReason": str(response.get("done_reason", "")),
                "parsed": parsed,
            }
        )
        return parsed


def run_candidate(
    root: Path,
    config_path: Path,
    config: dict[str, Any],
    plan: LocalScreenPlan,
    snapshot: dict[str, Any],
    candidate_id: str,
    *,
    transport: Transport | None = None,
    host_probe: HostProbe | None = None,
    candidate_probe: CandidateProbe | None = None,
) -> dict[str, Any]:
    if candidate_id not in plan.candidateIds:
        raise PreflightError(f"unknown local screen candidate: {candidate_id}")
    client = transport or http_transport(config["execution"]["apiBaseUrl"])
    live_host = (host_probe or probe_host)()
    if live_host != snapshot["host"]:
        raise PreflightError("live host identity differs from the frozen Ollama snapshot")
    candidate = next(item for item in snapshot["candidates"] if item["candidateId"] == candidate_id)
    live_model = (candidate_probe or probe_ollama_candidate)(
        client, candidate, snapshot["serverVersion"]
    )

    output = root / plan.outputDir / candidate_id
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing local screen output: {output}")
    output.mkdir(parents=True)
    contract = load_contract(root / config["bindings"]["contract"]["path"])
    cases = load_cases(root / config["bindings"]["cases"]["path"])
    runtime_comparison = {**config["comparison"], "keepAlive": config["execution"]["keepAlive"]}
    generator = OllamaTurnGenerator(
        base_url=config["execution"]["apiBaseUrl"],
        model=candidate["model"],
        comparison=runtime_comparison,
        timeout_seconds=config["execution"]["requestTimeoutSeconds"],
        transport=client,
    )
    started = time.monotonic()
    results = []
    for index, case in enumerate(cases, start=1):
        results.append(
            evaluate_case(
                case,
                system_prompt=contract["systemPrompt"],
                tools=contract["tools"],
                generate=generator,
                max_model_calls=config["comparison"]["maxModelCallsPerCase"],
            )
        )
        print(
            f"local screen progress: candidate={candidate_id} case={index}/{len(cases)} "
            f"caseId={case['caseId']}",
            flush=True,
        )

    results_path = output / "results.jsonl"
    generations_path = output / "generations.jsonl"
    results_path.write_bytes(_jsonl([result.as_dict() for result in results]))
    generations_path.write_bytes(_jsonl(generator.records))
    summary = summarize_candidate(candidate_id, results, config["scoring"])
    manifest = {
        "schemaVersion": 1,
        "screenId": plan.screenId,
        "candidateId": candidate_id,
        "status": "complete",
        "sourceCommit": plan.sourceCommit,
        "configPath": str(config_path.relative_to(root)),
        "configSha256": plan.configSha256,
        "casesSha256": plan.casesSha256,
        "caseCount": plan.caseCount,
        "contractId": plan.contractId,
        "externalCostUsd": "0",
        "elapsedSeconds": time.monotonic() - started,
        "host": live_host,
        "ollama": live_model,
        "artifacts": {
            "results": {"path": "results.jsonl", "sha256": sha256_file(results_path)},
            "generations": {
                "path": "generations.jsonl",
                "sha256": sha256_file(generations_path),
            },
        },
        "summary": summary,
        "authority": config["authority"],
    }
    (output / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role in {"system", "user"}:
            converted.append({"role": role, "content": message["content"]})
        elif role == "assistant" and "toolCalls" in message:
            converted.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"],
                            },
                        }
                        for call in message["toolCalls"]
                    ],
                }
            )
        elif role == "tool":
            converted.append(
                {
                    "role": "tool",
                    "tool_name": message["name"],
                    "content": json.dumps(
                        message["content"], sort_keys=True, separators=(",", ":")
                    ),
                }
            )
        elif role == "assistant":
            converted.append({"role": "assistant", "content": message["content"]})
        else:
            raise PreflightError(f"unsupported local screen message role: {role!r}")
    return converted


def parse_ollama_turn(response: dict[str, Any], call_number: int) -> dict[str, Any]:
    message = response.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise PreflightError("Ollama response does not contain an assistant message")
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        parsed = []
        for index, call in enumerate(tool_calls, start=1):
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                raise PreflightError("Ollama tool call is malformed")
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise PreflightError("Ollama tool arguments are not JSON") from exc
            parsed.append(
                {
                    "id": f"ollama-call-{call_number}-{index}",
                    "name": function.get("name"),
                    "arguments": arguments,
                }
            )
        return {"role": "assistant", "toolCalls": parsed}
    content = message.get("content")
    if not isinstance(content, str):
        raise PreflightError("Ollama assistant content is not text")
    return {"role": "assistant", "content": content.strip()}


def probe_ollama_candidate(
    transport: Transport,
    candidate: dict[str, Any],
    expected_server_version: str,
) -> dict[str, Any]:
    version = transport("/api/version", None, 30).get("version")
    if version != expected_server_version:
        raise PreflightError("live Ollama server version differs from snapshot")
    tags = transport("/api/tags", None, 30).get("models")
    if not isinstance(tags, list):
        raise PreflightError("live Ollama tags response is malformed")
    tag = next((item for item in tags if item.get("name") == candidate["model"]), None)
    if not isinstance(tag, dict):
        raise PreflightError(f"Ollama model is not installed: {candidate['model']}")
    if tag.get("digest") != candidate["digest"] or tag.get("size") != candidate["sizeBytes"]:
        raise PreflightError("live Ollama tag digest or size differs from snapshot")
    shown = transport("/api/show", {"model": candidate["model"], "verbose": True}, 300)
    info = shown.get("model_info")
    details = shown.get("details")
    capabilities = shown.get("capabilities")
    if not isinstance(info, dict) or not isinstance(details, dict) or not isinstance(capabilities, list):
        raise PreflightError("live Ollama show response is malformed")
    architecture = info.get("general.architecture")
    if architecture != candidate["architecture"]:
        raise PreflightError("live Ollama model architecture differs from snapshot")
    observed = {
        "parameterCount": info.get("general.parameter_count"),
        "contextLength": info.get(f"{architecture}.context_length"),
        "format": details.get("format"),
        "quantization": details.get("quantization_level"),
        "capabilities": capabilities,
        "templateSha256": hashlib.sha256(str(shown.get("template", "")).encode()).hexdigest(),
        "modelfileSha256": hashlib.sha256(str(shown.get("modelfile", "")).encode()).hexdigest(),
    }
    expected = {key: candidate[key] for key in observed}
    if observed != expected:
        raise PreflightError("live Ollama model metadata differs from snapshot")
    return {
        "serverVersion": version,
        "model": candidate["model"],
        "digest": candidate["digest"],
        **observed,
    }


def http_transport(base_url: str) -> Transport:
    if base_url != "http://127.0.0.1:11434":
        raise PreflightError("local screen transport must remain on pinned loopback endpoint")

    def send(path: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
        if path not in {"/api/version", "/api/tags", "/api/show", "/api/chat"}:
            raise PreflightError(f"local screen attempted an unapproved Ollama route: {path}")
        body = canonical(payload) if payload is not None else None
        request = urllib.request.Request(
            base_url + path,
            data=body,
            headers={"Content-Type": "application/json"} if body is not None else {},
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            raise PreflightError(f"Ollama request failed at {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise PreflightError(f"Ollama response at {path} is not an object")
        return value

    return send


def probe_host() -> dict[str, Any]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise PreflightError("local screen requires Darwin arm64")
    try:
        memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        hardware = json.loads(
            subprocess.check_output(
                ["system_profiler", "SPHardwareDataType", "-json"], text=True
            )
        )["SPHardwareDataType"][0]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot identify local Apple host: {exc}") from exc
    return {
        "platform": "darwin-arm64",
        "chip": hardware.get("chip_type"),
        "memoryBytes": memory,
    }


def _jsonl(values: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical(value) + b"\n" for value in values)


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
