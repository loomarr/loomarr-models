"""Zero-spend stock planner candidate screen on the local Strix Halo appliance (issue #35).

Each candidate GGUF is served by a pinned llama.cpp build in its own llama-server on a separate
port, beside the production Flash-Next service, so no production service is stopped. Every
candidate is scored on the same v2 development gate and training-split screen, with the same
prompt, tools, decoding, and trial count as the served Flash-Next screen. That screen is the
incumbent.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from .experiment import PreflightError, _git_probe, _input_path, sha256_file
from .flash_next_screen import (
    AUTHORITY,
    DECODING,
    ENDPOINT,
    GATES,
    OpenAIChatTurnGenerator,
    _server_identity,
    evaluate_cases,
    read_api_key,
    write_run,
)


EXPERIMENT_ID = "planner-candidate-screen-v1"
SCREEN_GATES = ("v2", "v2-trainsplit")
TRIALS = 5
HF_HUB = "/srv/fictional-ai/models/huggingface/hub"
RUNTIME = {
    "build": "strix-llama-hip-gfx1151-8c1c282e",
    "binary": "/var/cache/fictional-ai/build/strix-llama-hip-gfx1151-8c1c282e/bin/llama-server",
    "host": "127.0.0.1",
    "port": 8090,
    "ctxSize": 16384,
    "parallel": 1,
    "gpuLayers": 999,
    "flags": ["--jinja", "--no-webui"],
    "readyTimeoutSeconds": 600,
}
CANDIDATES = {
    # The incumbent: Loomarr's production Flash-Next service, measured with the same wire profile,
    # gates, and trials as every challenger. No server is started for it.
    "flash-next-served": {"served": True, "endpoint": ENDPOINT},
    "qwen35-9b-q8_0": {
        "repository": "unsloth/Qwen3.5-9B-GGUF",
        "revision": "3885219b6810b007914f3a7950a8d1b469d598a5",
        "file": "Qwen3.5-9B-Q8_0.gguf",
        "sha256": "a5573e05ae69eb9a0c70b5b5a5460d15d72d8c8ea2057233352313b3138dc82a",
        "bytes": 9527502048,
    },
    # Reference, not a deployable candidate: it does not fit beside Flash-Next, so it runs
    # overnight inside with_gpu.sh with the primary service stopped.
    "qwen38-27b-q8_k_xl": {
        "repository": "unsloth/Qwen3.8-27B-GGUF",
        "revision": "4ca720788d1e01f1bff70c033e0d0028fd02e502",
        "file": "Qwen3.8-27B-UD-Q8_K_XL.gguf",
        "sha256": "701cf79e7f0d4c2177a3fe202ead1126275dc66ba51900d0d5332edfeb380fce",
        "bytes": 31457991680,
        "exclusiveGpu": True,
    },
    "qwen35-4b-q4_k_m": {
        "repository": "unsloth/Qwen3.5-4B-GGUF",
        "revision": "e87f176479d0855a907a41277aca2f8ee7a09523",
        "file": "Qwen3.5-4B-Q4_K_M.gguf",
        "sha256": "1d203c2196991da08bc5b191ab4727516f476f3167e3276f75a0c5257493aadb",
        "bytes": 2740937888,
    },
}
BINDINGS = {
    "contract": "contracts/planner-contract-v5.json",
    "gateModule": "src/loomarr_models/current_gate_v2.py",
    "screenModule": "src/loomarr_models/flash_next_screen.py",
    "runtime": "src/loomarr_models/candidate_screen.py",
    "generator": "scripts/build_planner_candidate_screen.py",
    "runner": "scripts/run_planner_candidate_screen.py",
    **{f"cases:{gate}": GATES[gate]["cases"] for gate in SCREEN_GATES},
}


def preflight(root: Path, config_path: Path, *, git_probe: Any = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (
        config.get("experimentId") != EXPERIMENT_ID
        or config.get("candidates") != CANDIDATES
        or config.get("runtime") != RUNTIME
        or config.get("decoding") != DECODING
        or config.get("gates") != list(SCREEN_GATES)
        or config.get("trials") != TRIALS
        or config.get("authority") != AUTHORITY
        or set(config.get("bindings", {})) != set(BINDINGS)
    ):
        raise PreflightError("candidate screen config differs from the pinned plan")
    bound = {}
    for name, binding in config["bindings"].items():
        bound[name] = _input_path(root, Path(binding["path"]))
        if binding["path"] != BINDINGS[name] or sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"candidate screen {name} digest mismatch")
    return {
        "experimentId": EXPERIMENT_ID,
        "configSha256": sha256_file(config_path),
        "sourceCommit": (git_probe or _git_probe)(root, [config_path, *bound.values()]),
        "externalSpendUsd": "0",
    }


def model_path(candidate: dict[str, Any]) -> Path:
    """Resolve the pinned GGUF in the local HF cache; the LFS blob name is its SHA-256."""
    repo_dir = "models--" + candidate["repository"].replace("/", "--")
    path = Path(HF_HUB) / repo_dir / "snapshots" / candidate["revision"] / candidate["file"]
    blob = path.resolve(strict=True)
    if blob.name != candidate["sha256"] or blob.stat().st_size != candidate["bytes"]:
        raise PreflightError(f"{candidate['file']} does not match its pinned SHA-256 or size")
    return path


def server_command(candidate_id: str, path: Path) -> list[str]:
    return [
        RUNTIME["binary"], "--model", str(path), "--alias", candidate_id,
        "--host", RUNTIME["host"], "--port", str(RUNTIME["port"]),
        "--ctx-size", str(RUNTIME["ctxSize"]), "--parallel", str(RUNTIME["parallel"]),
        "--n-gpu-layers", str(RUNTIME["gpuLayers"]), *RUNTIME["flags"],
    ]


def run_candidate(root: Path, plan: dict[str, Any], candidate_id: str, log: Path) -> list[dict[str, Any]]:
    candidate = CANDIDATES[candidate_id]
    base = root / ".artifacts" / EXPERIMENT_ID / candidate_id
    if base.exists():
        raise PreflightError(f"refusing to overwrite existing output: {base}")
    if candidate.get("served"):
        endpoint = candidate["endpoint"]
        api_key = read_api_key(Path(endpoint["apiKeyFile"]))
        identity = _server_identity(api_key, endpoint)
        return _run_trials(root, plan, candidate_id, base, endpoint, api_key, identity, {"sharedProductionService": True})
    if candidate.get("exclusiveGpu") and _primary_active():
        raise PreflightError(f"{candidate_id} needs the GPU to itself; run it inside with_gpu.sh")
    path = model_path(candidate)
    endpoint = {"baseUrl": f"http://{RUNTIME['host']}:{RUNTIME['port']}/v1", "modelAlias": candidate_id}
    env = {**os.environ, "LD_LIBRARY_PATH": str(Path(RUNTIME["binary"]).parent)}
    with log.open("w", encoding="utf-8") as handle:
        server = subprocess.Popen(server_command(candidate_id, path), stdout=handle, stderr=subprocess.STDOUT, env=env)
        try:
            gtt_before = _gtt_used()
            _wait_ready(endpoint, server)
            identity = _server_identity("unused", endpoint)
            memory = {"gttUsedBytesAfterLoad": _gtt_used(), "gttUsedBytesBeforeLoad": gtt_before}
            return _run_trials(root, plan, candidate_id, base, endpoint, "unused", identity, memory)
        finally:
            server.terminate()
            try:
                server.wait(timeout=60)
            except subprocess.TimeoutExpired:
                server.kill()


def _run_trials(
    root: Path,
    plan: dict[str, Any],
    candidate_id: str,
    base: Path,
    endpoint: dict[str, Any],
    api_key: str,
    identity: dict[str, Any],
    memory: dict[str, Any],
) -> list[dict[str, Any]]:
    contract = json.loads((root / BINDINGS["contract"]).read_text(encoding="utf-8"))
    manifests = []
    for trial in range(1, TRIALS + 1):
        for gate in SCREEN_GATES:
            generator = OpenAIChatTurnGenerator(api_key, {}, endpoint)
            started = time.monotonic()
            results = evaluate_cases(root, gate, generator, contract["systemPrompt"], f"{candidate_id} {gate} t{trial}")
            manifests.append(
                write_run(
                    base / gate / f"t{trial}",
                    results,
                    generator,
                    candidate_id=candidate_id,
                    gate=gate,
                    fields={
                        "experimentId": EXPERIMENT_ID,
                        "candidate": {"id": candidate_id, **CANDIDATES[candidate_id]},
                        "runtime": None if CANDIDATES[candidate_id].get("served") else RUNTIME,
                        "decoding": DECODING,
                        "gate": gate,
                        "trial": trial,
                        "preflight": plan,
                        "server": identity,
                        "memory": memory,
                        "elapsedSeconds": time.monotonic() - started,
                    },
                )
            )
    return manifests


def _wait_ready(endpoint: dict[str, Any], server: subprocess.Popen) -> None:
    health = endpoint["baseUrl"].removesuffix("/v1") + "/health"
    deadline = time.monotonic() + RUNTIME["readyTimeoutSeconds"]
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise PreflightError(f"candidate server exited with status {server.returncode}")
        try:
            with urllib.request.urlopen(health, timeout=5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(2)
    raise PreflightError("candidate server did not become ready")


def _primary_active() -> bool:
    status = subprocess.run(["systemctl", "is-active", "--quiet", "fictional-ai-primary"], check=False)
    return status.returncode == 0


def _gtt_used() -> int | None:
    try:
        return int(Path("/sys/class/drm/card0/device/mem_info_gtt_used").read_text())
    except OSError:
        return None
