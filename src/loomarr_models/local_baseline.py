"""Zero-spend current-contract stock baseline on the local Strix Halo host.

Reuses the v3 cases, contract, scorer, thresholds, and decoding settings unchanged. Only the host
(gfx1151, ROCm), weights (bf16 Qwen3.8-27B instead of Unsloth bnb-4bit), and runtime (plain
Transformers) differ. The pinned Unsloth tokenizer and chat template are kept because every
existing capacity report and training trace was rendered with them.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from .current_baseline import (
    FIXTURE_ID,
    SCORING,
    baseline_decision,
    evaluate_current_case,
    summarize_current_candidate,
)
from .current_baseline_v3 import COMPARISON
from .current_contract import (
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_current_development_case,
)
from .experiment import HEAVY_MODULE_PREFIXES, PreflightError, _git_probe, _input_path, _output_path, sha256_file


EXPERIMENT_ID = "planner-current-qwen-local-baseline-v1"
ENVIRONMENT_ID = "qwen38-strixhalo-v1"
MODEL = {
    "candidateId": "qwen38-27b-bf16",
    "repository": "Qwen/Qwen3.8-27B",
    "revision": "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0",
    "dtype": "bfloat16",
    "tokenizer": {
        "repository": "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
        "revision": "8aa5f05d26b7205477066e1449e0af13f762a299",
        "chatTemplateSha256": "12827f24b742ea4e80cdc12dbcf9622227056b9f797252a3149263d4f9aaadce",
        "tokenizerSha256": "06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523",
    },
}
EXECUTION = {
    "host": "fictional-ai-server",
    "platform": "linux-amd64",
    "gpuArch": "gfx1151",
    "minimumGpuMemoryGb": 100,
    # The flash SDPA backend fails with hipErrorInvalidValue on gfx1151 for Qwen3.5 attention;
    # the memory-efficient backend works.
    "flashSdpa": False,
    "maxWallClockSeconds": 21600,
    "outputDir": f".artifacts/{EXPERIMENT_ID}",
    "requireCleanGit": True,
    "automaticRetry": False,
    "externalSpendUsd": "0",
}
AUTHORITY = {
    "externalSpendAuthorized": False,
    "trainingAuthorized": False,
    "certificationAuthority": False,
    "deploymentAuthority": False,
    "releaseAuthority": False,
}
BINDINGS = {
    "budgetLedger": "budgets/external-spend-v1.json",
    "cases": "evaluation/planner-current-v1/cases.jsonl",
    "casesManifest": "evaluation/planner-current-v1/manifest.json",
    "contract": "contracts/planner-contract-v5.json",
    "environment": f"environments/{ENVIRONMENT_ID}.json",
    "generator": "scripts/build_planner_local_baseline.py",
    "holdoutDenylist": "contracts/planner-holdout-denylist-v2.json",
    "referenceBaseline": "runs/planner-current-qwen-stock-baseline-v3/publication.json",
    "runner": "scripts/run_planner_local_baseline.py",
    "runtime": "src/loomarr_models/local_baseline.py",
}

GitProbe = Callable[[Path, Iterable[Path]], str]


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("experimentId") != EXPERIMENT_ID:
        raise PreflightError("local baseline config identity drifted")
    return value


def preflight(root: Path, config_path: Path, *, git_probe: GitProbe | None = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_config(config_path)
    if (
        config.get("model") != MODEL
        or config.get("execution") != EXECUTION
        or config.get("comparison") != COMPARISON
        or config.get("scoring") != SCORING
        or config.get("authority") != AUTHORITY
        or set(config.get("bindings", {})) != set(BINDINGS)
    ):
        raise PreflightError("local baseline config differs from the pinned plan")
    bound: dict[str, Path] = {}
    for name, binding in config["bindings"].items():
        if binding.get("path") != BINDINGS[name]:
            raise PreflightError(f"local baseline {name} binding path drifted")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"local baseline {name} digest mismatch")

    contract = _object(bound["contract"])
    exact, normalized, minimum, protected = load_current_denylist(bound["holdoutDenylist"])
    cases = read_jsonl(bound["cases"])
    for case in cases:
        try:
            validate_current_development_case(case, contract, FIXTURE_ID)
            assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected)
        except ValueError as exc:
            raise PreflightError(str(exc)) from exc
    manifest = _object(bound["casesManifest"])
    if len(cases) != 24 or manifest.get("sha256") != sha256_file(bound["cases"]) or manifest.get("modelExposure") != "none":
        raise PreflightError("local baseline requires the exact unexposed 24-case development gate")
    environment = _object(bound["environment"])
    if environment.get("environmentId") != ENVIRONMENT_ID or environment.get("baseModel") != {
        k: MODEL[k] for k in ("repository", "revision", "dtype")
    }:
        raise PreflightError("local baseline environment or model drifted")
    ledger = _object(bound["budgetLedger"])
    if ledger.get("outstandingReservationsUsd") != "0":
        raise PreflightError("local baseline refuses to run while external reservations are outstanding")

    output = _output_path(root, Path(EXECUTION["outputDir"]))
    source_commit = (git_probe or _git_probe)(root, [config_path, *bound.values()])
    imported = sorted(name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES)
    if imported:
        raise PreflightError(f"heavyweight modules imported before local baseline preflight: {imported[0]}")
    return {
        "experimentId": EXPERIMENT_ID,
        "candidateId": MODEL["candidateId"],
        "configSha256": sha256_file(config_path),
        "casesSha256": sha256_file(bound["cases"]),
        "caseCount": len(cases),
        "contractId": contract["contractId"],
        "environmentSha256": sha256_file(bound["environment"]),
        "externalSpendUsd": "0",
        "sourceCommit": source_commit,
        "outputDir": str(output.relative_to(root)),
    }


def run_baseline(root: Path, config_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    config = load_config(config_path)
    os.environ["TORCH_COMPILE_DISABLE"] = "1"

    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForImageTextToText, AutoTokenizer

    from .eval_runtime import HuggingFaceTurnGenerator
    from .stock_runtime import redact_generation_records

    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise PreflightError("local baseline requires Linux amd64")
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise PreflightError("local baseline requires a ROCm GPU")
    props = torch.cuda.get_device_properties(0)
    if not props.gcnArchName.startswith(EXECUTION["gpuArch"]):
        raise PreflightError(f"local baseline requires {EXECUTION['gpuArch']}, found {props.gcnArchName}")
    if props.total_memory < EXECUTION["minimumGpuMemoryGb"] * 2**30:
        raise PreflightError("local baseline GPU memory is below the pinned minimum")
    torch.backends.cuda.enable_flash_sdp(EXECUTION["flashSdpa"])

    output = root / EXECUTION["outputDir"]
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing output: {output}")

    tokenizer_pin = MODEL["tokenizer"]
    tokenizer_dir = Path(
        snapshot_download(
            tokenizer_pin["repository"],
            revision=tokenizer_pin["revision"],
            allow_patterns=["*.json", "*.jinja"],
        )
    )
    if (
        sha256_file(tokenizer_dir / "chat_template.jinja") != tokenizer_pin["chatTemplateSha256"]
        or sha256_file(tokenizer_dir / "tokenizer.json") != tokenizer_pin["tokenizerSha256"]
    ):
        raise PreflightError("pinned Unsloth tokenizer or chat template drifted")
    output.mkdir(parents=True)

    contract = _object(root / BINDINGS["contract"])
    cases = read_jsonl(root / BINDINGS["cases"])
    comparison = config["comparison"]
    started = time.monotonic()
    torch.manual_seed(comparison["seed"])
    torch.cuda.manual_seed_all(comparison["seed"])
    torch.cuda.reset_peak_memory_stats()
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir)
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL["repository"],
        revision=MODEL["revision"],
        dtype=torch.bfloat16,
        device_map="cuda",
    )
    model.eval()
    loaded_revision = getattr(model.config, "_commit_hash", None)
    if loaded_revision and loaded_revision != MODEL["revision"]:
        raise PreflightError(f"loaded model revision {loaded_revision} differs from pinned weights")
    generator = HuggingFaceTurnGenerator(model, tokenizer, comparison, torch)
    results = []
    for index, case in enumerate(cases, start=1):
        results.append(
            evaluate_current_case(
                case,
                system_prompt=contract["systemPrompt"],
                tools=contract["tools"],
                generate=generator,
                max_model_calls=comparison["maxModelCallsPerCase"],
            )
        )
        print(f"local baseline progress: case={index}/{len(cases)} caseId={case['caseId']}", flush=True)

    results_bytes = _jsonl(result.as_dict() for result in results)
    generations_bytes = _jsonl(redact_generation_records(generator.records))
    (output / "results.jsonl").write_bytes(results_bytes)
    (output / "generations.jsonl").write_bytes(generations_bytes)
    peak = torch.cuda.max_memory_reserved(0)
    summary = summarize_current_candidate(MODEL["candidateId"], results, peak_vram_bytes=peak)
    manifest = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "complete",
        "preflight": plan,
        "elapsedSeconds": time.monotonic() - started,
        "packages": {
            name: importlib.metadata.version(name) for name in ("torch", "transformers", "accelerate")
        },
        "runtime": {
            "python": platform.python_version(),
            "hip": torch.version.hip,
            "gpu": {
                "name": props.name,
                "arch": props.gcnArchName,
                "totalMemoryBytes": props.total_memory,
                "peakReservedBytes": peak,
            },
        },
        "artifacts": {
            "results": {"path": "results.jsonl", "sha256": hashlib.sha256(results_bytes).hexdigest()},
            "generations": {"path": "generations.jsonl", "sha256": hashlib.sha256(generations_bytes).hexdigest()},
        },
        "summary": summary,
        "decision": baseline_decision(summary, config["scoring"]),
        "externalSpendUsd": "0",
        "authority": config["authority"],
    }
    (output / "run-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _jsonl(records: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n" for record in records
    )


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must be a JSON object")
    return value
