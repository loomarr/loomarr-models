from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import time
from pathlib import Path
from typing import Any

from .eval_experiment import EvalPreflightReport, load_eval_experiment
from .eval_runner import CaseResult, compare_candidates, evaluate_case, summarize_candidate
from .evaluation import load_cases
from .experiment import PreflightError
from .training_data import to_huggingface_tools
from .validator import load_contract


def run_evaluation(
    root: Path,
    config_path: Path,
    preflight: EvalPreflightReport,
) -> dict[str, Any]:
    config = load_eval_experiment(config_path)
    comparison_config = config["comparison"]
    if comparison_config["disableCompile"]:
        os.environ["TORCH_COMPILE_DISABLE"] = "1"
        os.environ["UNSLOTH_COMPILE_DISABLE"] = "1"

    from unsloth import FastModel

    import torch
    from peft import PeftModel

    execution = config["execution"]
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise PreflightError("live planner evaluation requires Linux amd64")
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
    scoring = json.loads(
        (root / config["bindings"]["casesManifest"]["path"]).read_text(encoding="utf-8")
    )["scoring"]
    artifact = config["models"]["inferenceArtifact"]
    adapter_dir = (root / execution["adapterPath"]).parent
    started = time.monotonic()
    summaries: dict[str, dict[str, Any]] = {}
    raw_hashes: dict[str, str] = {}

    for candidate_id in comparison_config["candidateOrder"]:
        torch.manual_seed(comparison_config["seed"])
        torch.cuda.manual_seed_all(comparison_config["seed"])
        torch.cuda.reset_peak_memory_stats()
        model, tokenizer = FastModel.from_pretrained(
            model_name=artifact["repository"],
            revision=artifact["revision"],
            max_seq_length=comparison_config["maxSeqLength"],
            load_in_4bit=True,
            full_finetuning=False,
            offload_embedding=comparison_config["offloadEmbedding"],
        )
        loaded_revision = getattr(model.config, "_commit_hash", None)
        if loaded_revision and loaded_revision != artifact["revision"]:
            raise PreflightError(
                f"loaded model revision {loaded_revision} differs from pinned inference artifact"
            )
        if candidate_id == "adapter":
            model = PeftModel.from_pretrained(model, adapter_dir, is_trainable=False)
        FastModel.for_inference(model)
        generator = HuggingFaceTurnGenerator(model, tokenizer, comparison_config, torch)
        results = []
        for index, case in enumerate(cases, start=1):
            results.append(
                evaluate_case(
                    case,
                    system_prompt=contract["systemPrompt"],
                    tools=contract["tools"],
                    generate=generator,
                    max_model_calls=comparison_config["maxModelCallsPerCase"],
                )
            )
            print(
                f"evaluation progress: candidate={candidate_id} case={index}/{len(cases)} "
                f"caseId={case['caseId']}",
                flush=True,
            )
        raw_path = output / f"{candidate_id}-results.jsonl"
        raw_bytes = b"".join(
            json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")).encode()
            + b"\n"
            for result in results
        )
        raw_path.write_bytes(raw_bytes)
        raw_hashes[candidate_id] = hashlib.sha256(raw_bytes).hexdigest()
        summaries[candidate_id] = summarize_candidate(
            candidate_id,
            results,
            scoring,
            peak_vram_bytes=torch.cuda.max_memory_reserved(0),
        )
        generator_log = output / f"{candidate_id}-generations.jsonl"
        generation_bytes = b"".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for record in generator.records
        )
        generator_log.write_bytes(generation_bytes)
        raw_hashes[f"{candidate_id}Generations"] = hashlib.sha256(generation_bytes).hexdigest()
        del generator, model, tokenizer
        gc.collect()
        torch.cuda.empty_cache()

    comparison = compare_candidates(summaries["stock"], summaries["adapter"], scoring)
    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "unsloth", "unsloth-zoo", "transformers", "peft")
    }
    manifest = {
        "schemaVersion": 1,
        "runId": "planner-adapter-eval-a40-v1",
        "preflight": preflight.as_dict(),
        "elapsedSeconds": time.monotonic() - started,
        "packages": packages,
        "runtime": {
            "python": platform.python_version(),
            "cuda": torch.version.cuda,
            "gpu": {
                "name": props.name,
                "totalMemoryBytes": props.total_memory,
            },
        },
        "candidateOrder": comparison_config["candidateOrder"],
        "rawArtifactSha256": raw_hashes,
        "comparison": comparison,
    }
    (output / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


class HuggingFaceTurnGenerator:
    def __init__(self, model: Any, tokenizer: Any, config: dict[str, Any], torch: Any):
        self.model = model
        self.tokenizer = tokenizer
        self.config = config
        self.torch = torch
        self.records: list[dict[str, Any]] = []

    def __call__(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        conversation = _to_huggingface_messages(messages)
        rendered = self.tokenizer.apply_chat_template(
            conversation,
            tools=to_huggingface_tools(tools),
            tokenize=False,
            add_generation_prompt=True,
            reasoning_effort=self.config["reasoningEffort"],
        )
        inputs = self.tokenizer(text=rendered, return_tensors="pt").to(self.model.device)
        input_tokens = int(inputs["input_ids"].shape[-1])
        available = self.config["maxSeqLength"] - input_tokens
        if available < 32:
            raise PreflightError(
                f"evaluation prompt leaves only {available} generation tokens within context"
            )
        max_new_tokens = min(self.config["maxNewTokens"], available)
        started = time.monotonic()
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=self.config["doSample"],
                pad_token_id=self.tokenizer.eos_token_id,
                use_cache=True,
            )
        generated = output[0, input_tokens:]
        raw = self.tokenizer.decode(generated, skip_special_tokens=True)
        parsed = parse_qwen_turn(raw, len(self.records) + 1)
        self.records.append(
            {
                "schemaVersion": 1,
                "modelCall": len(self.records) + 1,
                "inputTokens": input_tokens,
                "outputTokens": int(generated.shape[-1]),
                "elapsedSeconds": time.monotonic() - started,
                "raw": raw,
                "parsed": parsed,
            }
        )
        return parsed


def parse_qwen_turn(raw: str, call_number: int) -> dict[str, Any]:
    text = raw.replace("<|im_end|>", "").strip()
    text = re.sub(r"\A(?:<think>)?.*?</think>\s*", "", text, count=1, flags=re.DOTALL)
    match = re.fullmatch(
        r".*?<tool_call>\s*<function=([^>\n]+)>\s*(.*?)</function>\s*</tool_call>\s*",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return {"role": "assistant", "content": text}
    name, body = match.groups()
    arguments: dict[str, Any] = {}
    position = 0
    for parameter in re.finditer(
        r"<parameter=([^>\n]+)>\s*(.*?)\s*</parameter>", body, flags=re.DOTALL
    ):
        if body[position : parameter.start()].strip():
            return {"role": "assistant", "content": text}
        key, raw_value = parameter.groups()
        if key in arguments:
            return {"role": "assistant", "content": text}
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value.strip()
        arguments[key] = value
        position = parameter.end()
    if body[position:].strip() or not arguments:
        return {"role": "assistant", "content": text}
    return {
        "role": "assistant",
        "toolCalls": [
            {
                "id": f"model-call-{call_number}",
                "name": name.strip(),
                "arguments": arguments,
            }
        ],
    }


def _to_huggingface_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role in {"system", "user"}:
            converted.append({"role": role, "content": message["content"]})
        elif role == "assistant" and "toolCalls" in message:
            converted.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call["id"],
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
                    "tool_call_id": message["toolCallId"],
                    "name": message["name"],
                    "content": json.dumps(
                        message["content"], sort_keys=True, separators=(",", ":")
                    ),
                }
            )
        elif role == "assistant":
            converted.append({"role": "assistant", "content": message["content"]})
        else:
            raise PreflightError(f"unsupported evaluation message role: {role!r}")
    return converted


def _validate_gpu(name: str, total_memory_bytes: int, execution: dict[str, Any]) -> None:
    vram_gb = total_memory_bytes / 1_000_000_000
    if execution["gpuSku"] not in name or vram_gb < execution["minimumVramGb"] - 1:
        raise PreflightError(
            f"GPU identity {name!r} / {vram_gb:.1f} GB is outside evaluation envelope"
        )
