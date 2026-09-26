from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from .current_baseline import evaluate_current_case, baseline_decision, summarize_current_candidate
from .current_baseline_v3 import CurrentBaselineV3Plan, load_config
from .current_contract import read_jsonl
from .experiment import PreflightError
from .stock_runtime import redact_generation_records


def run_baseline(
    root: Path,
    config_path: Path,
    preflight: CurrentBaselineV3Plan,
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
        raise PreflightError("live current stock baseline v3 requires Linux amd64")
    if not torch.cuda.is_available() or torch.cuda.device_count() < execution["gpuCount"]:
        raise PreflightError("required NVIDIA GPU is unavailable")
    props = torch.cuda.get_device_properties(0)
    _validate_gpu(props.name, props.total_memory, execution)

    output = root / execution["outputDir"]
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    contract = json.loads((root / config["bindings"]["contract"]["path"]).read_text(encoding="utf-8"))
    cases = read_jsonl(root / config["bindings"]["cases"]["path"])
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
        raise PreflightError(f"loaded model revision {loaded_revision} differs from pinned stock artifact")
    FastModel.for_inference(model)
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
        print(
            f"current stock baseline v3 progress: case={index}/{len(cases)} caseId={case['caseId']}",
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
    peak = torch.cuda.max_memory_reserved(0)
    summary = summarize_current_candidate(preflight.candidateId, results, peak_vram_bytes=peak)
    decision = baseline_decision(summary, config["scoring"])
    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "unsloth", "unsloth-zoo", "transformers")
    }
    manifest = {
        "schemaVersion": 3,
        "experimentId": config["experimentId"],
        "status": "complete-unsettled",
        "completionClass": "complete-model-quality",
        "preflight": preflight.as_dict(),
        "elapsedSeconds": time.monotonic() - started,
        "packages": packages,
        "runtime": {
            "python": platform.python_version(),
            "cuda": torch.version.cuda,
            "gpu": {
                "name": props.name,
                "totalMemoryBytes": props.total_memory,
                "peakReservedBytes": peak,
            },
        },
        "artifacts": {
            "results": {"path": results_path.name, "sha256": hashlib.sha256(results_bytes).hexdigest()},
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
