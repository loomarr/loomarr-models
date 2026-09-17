from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from .current_contract import read_jsonl
from .current_training import CurrentTrainingPlan, load_config
from .experiment import PreflightError
from .training_data import to_training_rows


def run_training(
    root: Path,
    config_path: Path,
    preflight: CurrentTrainingPlan,
) -> dict[str, Any]:
    os.environ["TORCH_COMPILE_DISABLE"] = "1"
    os.environ["UNSLOTH_COMPILE_DISABLE"] = "1"

    from unsloth import FastModel
    from unsloth.chat_templates import train_on_responses_only

    import torch
    from datasets import Dataset
    from peft import PeftModel
    from trl import SFTConfig, SFTTrainer

    config = load_config(config_path)
    execution = config["execution"]
    run = config["runs"][0]
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise PreflightError("live current QLoRA training requires Linux amd64")
    if not torch.cuda.is_available() or torch.cuda.device_count() < execution["gpuCount"]:
        raise PreflightError("required NVIDIA GPU is unavailable")
    props = torch.cuda.get_device_properties(0)
    if execution["gpuSku"] not in props.name or props.total_memory < 47_000_000_000:
        raise PreflightError("GPU identity or memory is outside the current QLoRA envelope")

    output = root / execution["outputDir"]
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing output: {output}")
    adapter_dir = output / "adapter"
    trainer_dir = output / "trainer"
    output.mkdir(parents=True)

    model_identity = config["model"]
    started = time.monotonic()
    torch.manual_seed(run["seed"])
    torch.cuda.manual_seed_all(run["seed"])
    torch.cuda.reset_peak_memory_stats()
    model, tokenizer = FastModel.from_pretrained(
        model_name=model_identity["repository"],
        revision=model_identity["revision"],
        max_seq_length=run["maxSeqLength"],
        load_in_4bit=True,
        full_finetuning=False,
        offload_embedding=False,
    )
    loaded_revision = getattr(model.config, "_commit_hash", None)
    if loaded_revision and loaded_revision != model_identity["revision"]:
        raise PreflightError(
            f"loaded model revision {loaded_revision} differs from the pinned artifact"
        )
    model = FastModel.get_peft_model(
        model,
        finetune_vision_layers=run["finetuneVisionLayers"],
        finetune_language_layers=run["finetuneLanguageLayers"],
        finetune_attention_modules=run["finetuneAttentionModules"],
        finetune_mlp_modules=run["finetuneMlpModules"],
        r=run["loraR"],
        lora_alpha=run["loraAlpha"],
        lora_dropout=run["loraDropout"],
        bias="none",
        use_gradient_checkpointing=run["gradientCheckpointing"],
        random_state=run["seed"],
    )

    traces = read_jsonl(root / config["bindings"]["corpus"]["path"])
    rows = to_training_rows(traces)
    rendered = [
        tokenizer.apply_chat_template(
            row["conversations"],
            tools=row["tools"],
            tokenize=False,
            add_generation_prompt=False,
            reasoning_effort=run["reasoningEffort"],
            preserve_thinking=True,
        )
        for row in rows
    ]
    token_counts = [_token_count(tokenizer, text) for text in rendered]
    rendered_sha = hashlib.sha256(
        b"".join(text.encode("utf-8") + b"\n" for text in rendered)
    ).hexdigest()
    capacity = json.loads(
        (root / config["bindings"]["capacityReport"]["path"]).read_text(encoding="utf-8")
    )
    expected_counts = [item["tokens"] for item in capacity["measurements"]]
    if (
        token_counts != expected_counts
        or rendered_sha != capacity["renderedTrainingSha256"]
        or max(token_counts) > run["maxSeqLength"]
    ):
        raise PreflightError("live rendered training capacity differs from the preregistered report")

    dataset = Dataset.from_dict(
        {
            "trace_id": [row["trace_id"] for row in rows],
            "text": rendered,
        }
    )
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        eval_dataset=None,
        args=SFTConfig(
            dataset_text_field="text",
            max_length=run["maxSeqLength"],
            packing=False,
            dataset_num_proc=1,
            per_device_train_batch_size=run["perDeviceTrainBatchSize"],
            gradient_accumulation_steps=run["gradientAccumulationSteps"],
            warmup_steps=run["warmupSteps"],
            max_steps=run["maxSteps"],
            learning_rate=run["learningRate"],
            logging_steps=1,
            optim=run["optimizer"],
            weight_decay=run["weightDecay"],
            lr_scheduler_type=run["lrSchedulerType"],
            seed=run["seed"],
            data_seed=run["seed"],
            output_dir=str(trainer_dir),
            save_strategy="no",
            report_to="none",
        ),
    )
    trainer = train_on_responses_only(trainer)
    stats = trainer.train()
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)

    del trainer, model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()
    probe_model, probe_tokenizer = FastModel.from_pretrained(
        model_name=model_identity["repository"],
        revision=model_identity["revision"],
        max_seq_length=run["maxSeqLength"],
        load_in_4bit=True,
        full_finetuning=False,
        offload_embedding=False,
    )
    probe_model = PeftModel.from_pretrained(probe_model, adapter_dir, is_trainable=False)
    FastModel.for_inference(probe_model)
    probe_text = probe_tokenizer.apply_chat_template(
        [{"role": "user", "content": "Return a short acknowledgement."}],
        tokenize=False,
        add_generation_prompt=True,
        reasoning_effort=run["reasoningEffort"],
    )
    probe_inputs = probe_tokenizer(text=probe_text, return_tensors="pt").to(probe_model.device)
    probe_input_tokens = int(probe_inputs["input_ids"].shape[-1])
    with torch.inference_mode():
        probe_output = probe_model.generate(
            **probe_inputs,
            max_new_tokens=8,
            do_sample=False,
            pad_token_id=probe_tokenizer.eos_token_id,
            use_cache=True,
        )
    probe_generated = probe_output[0, probe_input_tokens:]
    if int(probe_generated.shape[-1]) < 1:
        raise PreflightError("persisted adapter load probe generated no tokens")
    probe_bytes = probe_tokenizer.decode(probe_generated, skip_special_tokens=True).encode("utf-8")

    adapter_hashes = {
        str(path.relative_to(adapter_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(adapter_dir.rglob("*"))
        if path.is_file()
    }
    packages = {
        name: importlib.metadata.version(name)
        for name in ("torch", "unsloth", "unsloth-zoo", "transformers", "trl", "peft", "datasets")
    }
    manifest = {
        "schemaVersion": 1,
        "experimentId": config["experimentId"],
        "status": "complete-unsettled",
        "preflight": preflight.as_dict(),
        "runId": run["runId"],
        "elapsedSeconds": time.monotonic() - started,
        "completedSteps": int(stats.global_step),
        "renderedTrainingSha256": rendered_sha,
        "renderedTokenCounts": token_counts,
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
        "metrics": _json_values(stats.metrics),
        "adapterFiles": adapter_hashes,
        "loadProbe": {
            "activeAdapter": str(probe_model.active_adapter),
            "generatedTokenCount": int(probe_generated.shape[-1]),
            "outputSha256": hashlib.sha256(probe_bytes).hexdigest(),
        },
        "providerCostUsd": None,
        "authority": config["authority"],
    }
    (output / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _token_count(tokenizer: Any, text: str) -> int:
    encoded = tokenizer(text=text, add_special_tokens=False)
    input_ids = encoded["input_ids"]
    if input_ids and isinstance(input_ids[0], list):
        input_ids = input_ids[0]
    return len(input_ids)


def _json_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
        for key, value in values.items()
    }
