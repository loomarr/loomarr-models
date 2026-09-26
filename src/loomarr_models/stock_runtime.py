from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from .eval_runner import evaluate_case, summarize_candidate
from .evaluation import load_cases
from .experiment import PreflightError
from .stock_baseline import CANDIDATE_ID, StockBaselinePlan, load_config
from .validator import load_contract


def run_baseline(
    root: Path,
    config_path: Path,
    preflight: StockBaselinePlan,
) -> dict[str, Any]:
    config = load_config(config_path)
    comparison = config["comparison"]
    if comparison["disableCompile"]:
        os.environ["TORCH_COMPILE_DISABLE"] = "1"
        os.environ["UNSLOTH_COMPILE_DISABLE"] = "1"

    from unsloth import FastModel

    import torch

    from .eval_runtime import HuggingFaceTurnGenerator, _validate_gpu

    execution = config["execution"]
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise PreflightError("live stock baseline requires Linux amd64")
    if not torch.cuda.is_available() or torch.cuda.device_count() < execution["gpuCount"]:
        raise PreflightError("required NVIDIA GPU is unavailable")
    props = torch.cuda.get_device_properties(0)
    _validate_gpu(props.name, props.total_memory, execution)

    output = root / execution["outputDir"]
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    contract = load_contract(root / config["bindings"]["contract"]["path"])
    cases = load_cases(root / config["bindings"]["cases"]["path"])
    model_binding = config["model"]
    started = time.monotonic()
    torch.manual_seed(comparison["seed"])
    torch.cuda.manual_seed_all(comparison["seed"])
    torch.cuda.reset_peak_memory_stats()
    model, tokenizer = FastModel.from_pretrained(
        model_name=model_binding["repository"],
        revision=model_binding["revision"],
        max_seq_length=comparison["maxSeqLength"],
        load_in_4bit=True,
        full_finetuning=False,
        offload_embedding=comparison["offloadEmbedding"],
    )
    loaded_revision = getattr(model.config, "_commit_hash", None)
    if loaded_revision and loaded_revision != model_binding["revision"]:
        raise PreflightError(
            f"loaded model revision {loaded_revision} differs from pinned stock artifact"
        )
    FastModel.for_inference(model)
    generator = HuggingFaceTurnGenerator(model, tokenizer, comparison, torch)
    results = []
    for index, case in enumerate(cases, start=1):
        results.append(
            evaluate_case(
                case,
                system_prompt=contract["systemPrompt"],
                tools=contract["tools"],
                generate=generator,
                max_model_calls=comparison["maxModelCallsPerCase"],
            )
        )
        print(
            f"stock baseline progress: case={index}/{len(cases)} caseId={case['caseId']}",
            flush=True,
        )

    results_path = output / "results.jsonl"
    results_bytes = b"".join(
        json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for result in results
    )
    results_path.write_bytes(results_bytes)
    generations_path = output / "generations.jsonl"
    generations = redact_generation_records(generator.records)
    generations_bytes = b"".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for record in generations
    )
    generations_path.write_bytes(generations_bytes)
    summary = summarize_candidate(
        CANDIDATE_ID,
        results,
        config["scoring"],
        peak_vram_bytes=torch.cuda.max_memory_reserved(0),
    )
    decision = baseline_decision(summary, config["scoring"])
    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "unsloth", "unsloth-zoo", "transformers")
    }
    manifest = {
        "schemaVersion": 1,
        "experimentId": config["experimentId"],
        "status": "complete-unsettled",
        "preflight": preflight.as_dict(),
        "elapsedSeconds": time.monotonic() - started,
        "packages": packages,
        "runtime": {
            "python": platform.python_version(),
            "cuda": torch.version.cuda,
            "gpu": {
                "name": props.name,
                "totalMemoryBytes": props.total_memory,
                "peakReservedBytes": torch.cuda.max_memory_reserved(0),
            },
        },
        "artifacts": {
            "results": {
                "path": results_path.name,
                "sha256": hashlib.sha256(results_bytes).hexdigest(),
            },
            "generations": {
                "path": generations_path.name,
                "sha256": hashlib.sha256(generations_bytes).hexdigest(),
            },
        },
        "summary": summary,
        "decision": decision,
        "providerCostUsd": None,
        "authority": config["authority"],
    }
    (output / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def redact_generation_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    redacted = []
    for record in records:
        item = dict(record)
        raw = item.pop("raw", None)
        if not isinstance(raw, str):
            raise PreflightError("stock generation record lacks raw model output")
        item["rawSha256"] = hashlib.sha256(raw.encode()).hexdigest()
        redacted.append(item)
    return redacted


def baseline_decision(summary: dict[str, Any], scoring: dict[str, Any]) -> dict[str, Any]:
    thresholds = scoring["thresholds"]
    failures = []
    checks = (
        ("groundedCompletionRate", "minGroundedCompletionRate", lambda actual, limit: actual >= limit),
        (
            "correctToolOperationRate",
            "minCorrectToolOperationRate",
            lambda actual, limit: actual >= limit,
        ),
        ("schemaValidityRate", "minSchemaValidityRate", lambda actual, limit: actual >= limit),
        ("policyAccuracyRate", "minPolicyAccuracyRate", lambda actual, limit: actual >= limit),
        ("proposalQualityRate", "minProposalQualityRate", lambda actual, limit: actual >= limit),
        ("recoveryRate", "minRecoveryRate", lambda actual, limit: actual >= limit),
        ("p95ToolCalls", "maxP95ToolCalls", lambda actual, limit: actual <= limit),
    )
    for metric, threshold, accepted in checks:
        if not accepted(summary[metric], thresholds[threshold]):
            failures.append(metric)
    if summary["hardFailureCount"]:
        failures.append("hardFailureCount")
    justified = bool(failures)
    return {
        "outcome": (
            "qlora-justified-by-stock-development-failures"
            if justified
            else "qlora-not-justified-stock-clears-development-gate"
        ),
        "thresholdFailures": failures,
        "qloraJustified": justified,
        "trainingAuthorized": False,
        "releaseAuthorized": False,
        "certificationAuthority": False,
    }
