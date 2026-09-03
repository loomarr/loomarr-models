from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path
from typing import Any

from .experiment import PreflightError, PreflightReport, load_experiment
from .training_data import to_training_rows
from .validator import load_jsonl


def run_training(root: Path, config_path: Path, preflight: PreflightReport) -> dict[str, Any]:
    from unsloth import FastModel
    from unsloth.chat_templates import train_on_responses_only

    import torch
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    config = load_experiment(config_path)
    execution = config["execution"]
    run = config["runs"][0]
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise PreflightError("live QLoRA execution requires Linux amd64")
    if not torch.cuda.is_available() or torch.cuda.device_count() < execution["gpuCount"]:
        raise PreflightError("required NVIDIA GPU is unavailable")
    props = torch.cuda.get_device_properties(0)
    vram_gb = props.total_memory / 1024**3
    if execution["gpuSku"] not in props.name or vram_gb < execution["minimumVramGb"] - 1:
        raise PreflightError(
            f"GPU identity {props.name!r} / {vram_gb:.1f} GiB is outside the experiment envelope"
        )

    output = root / execution["outputDir"]
    if output.exists():
        raise PreflightError(f"refusing to overwrite existing output: {output}")
    adapter_dir = output / "adapter"
    trainer_dir = output / "trainer"
    output.mkdir(parents=True)

    model_identity = config["models"]["trainingArtifact"]
    started = time.monotonic()
    model, tokenizer = FastModel.from_pretrained(
        model_name=model_identity["repository"],
        revision=model_identity["revision"],
        max_seq_length=run["maxSeqLength"],
        load_in_4bit=True,
        full_finetuning=False,
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

    traces = load_jsonl(root / config["bindings"]["corpus"]["path"])
    dataset = Dataset.from_list(to_training_rows(traces))

    def format_rows(batch: dict[str, list[Any]]) -> dict[str, list[str]]:
        texts = [
            tokenizer.apply_chat_template(
                conversation,
                tools=tools,
                tokenize=False,
                add_generation_prompt=False,
                reasoning_effort=run["reasoningEffort"],
            )
            for conversation, tools in zip(batch["conversations"], batch["tools"], strict=True)
        ]
        return {"text": texts}

    dataset = dataset.map(format_rows, batched=True)
    rendered_sha = hashlib.sha256(
        b"".join(text.encode("utf-8") + b"\n" for text in dataset["text"])
    ).hexdigest()
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        eval_dataset=None,
        args=SFTConfig(
            dataset_text_field="text",
            max_length=run["maxSeqLength"],
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
            output_dir=str(trainer_dir),
            report_to="none",
        ),
    )
    if run["trainOnResponsesOnly"]:
        trainer = train_on_responses_only(trainer)
    stats = trainer.train()
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)

    adapter_hashes = {
        str(path.relative_to(adapter_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(adapter_dir.rglob("*"))
        if path.is_file()
    }
    package_names = ("torch", "unsloth", "unsloth-zoo", "transformers", "trl", "peft", "datasets")
    packages = {name: importlib.metadata.version(name) for name in package_names}
    manifest = {
        "schemaVersion": 1,
        "preflight": preflight.as_dict(),
        "runId": run["runId"],
        "elapsedSeconds": time.monotonic() - started,
        "renderedTrainingSha256": rendered_sha,
        "packages": packages,
        "runtime": {
            "python": platform.python_version(),
            "cuda": torch.version.cuda,
            "gpu": [
                {
                    "name": torch.cuda.get_device_properties(index).name,
                    "totalMemoryBytes": torch.cuda.get_device_properties(index).total_memory,
                    "peakReservedBytes": torch.cuda.max_memory_reserved(index),
                }
                for index in range(torch.cuda.device_count())
            ],
        },
        "metrics": _json_values(stats.metrics),
        "adapterFiles": adapter_hashes,
    }
    (output / "run-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _json_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
        for key, value in values.items()
    }
