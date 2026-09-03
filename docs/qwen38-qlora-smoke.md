# Qwen 3.8 planner QLoRA smoke

Issue [loomarr/loomarr#938](https://github.com/loomarr/loomarr/issues/938) owns this bounded
compatibility, memory, and throughput experiment. It does not certify the adapter or authorize a
release.

## Hardware lanes

The reproducible training lane is one NVIDIA A40 with 48 GB VRAM in the pinned Runpod container.
The official Unsloth Qwen3.8-27B recipe measured roughly 24 GiB peak reserved memory for its short
text-only QLoRA setup; 48 GB leaves room for the pinned single-GPU run and avoids multi-GPU
placement differences.

A 64 GB Apple-silicon Mac is useful for corpus generation, validation, quantized 27B inference,
evaluation, and adapter sanity checks. It may also host a separately tracked MLX experiment. An MLX
result is not treated as equivalent to this CUDA/Unsloth experiment.

## Gates

The runner performs all checks before importing Torch or any training framework. It refuses to run
unless all 50 traces pass the independent dual-model review, every immutable digest matches, both Qwen revisions match
the environment, critical runner files are tracked and clean, one training configuration is present,
the output stays under `.artifacts`, and the budget projects below the aggregate `$40` authorization.

The current config points at the reviewed-frozen 50-trace corpus produced by the unanimous v11
certification. This no-spend preflight must pass from a clean commit before provisioning a GPU:

```bash
PYTHONPATH=src python3 scripts/train_planner_smoke.py --preflight-only
```

Run the same preflight inside the pinned container. Only after that succeeds may the paid command run:

```bash
PYTHONPATH=src python3 scripts/train_planner_smoke.py
```

The experiment has a `$1.50` reservation ceiling and a 9,000-second process alarm. It saves only the
LoRA adapter, tokenizer metadata, trainer checkpoints, and a hash-bound run manifest. Merging,
quantizing, packaging, certification, or deployment belongs to later tracked work.

The pinned tokenizer renders the certified traces at 3,179–3,287 tokens, with the final assistant
response beginning as late as token 3,204. The smoke therefore uses a 4,096-token ceiling; 1,024
truncated the response marker and was rejected before the first training step.

## First run result

The pinned secure Runpod A40 run completed all 20 steps on September 3, 2026. Training took
780.09 seconds; model preparation plus training took 850.25 seconds. Peak reserved GPU memory was
26.74 GB of 47.71 GB available, so one A40 has ample headroom for this recipe. The adapter-only
artifact is 233,605,480 bytes with SHA-256
`08a166aa73ec1aaf965cf5a53af61a728d4542c841859b477af72305e5cb35f7`.

The observed training loss was 0.38348. That is a compatibility signal, not a quality result: all
50 reviewed traces were training inputs and no holdout was evaluated. The adapter remains local and
unreleased. The decision is to continue with a deterministic held-out comparison of stock Qwen and
the adapter before considering packaging, serving, or a larger training run.

The compact run manifest and publication record are committed under
`runs/planner-qwen38-smoke-v1/`. Raw logs, checkpoints, caches, and adapter bytes remain under the
gitignored `.artifacts/runpod-qwen38-qlora-smoke-v1/` directory. Runpod has not yet posted the exact
pod charge, so the entire `$1.50` allowance remains reserved in the aggregate ledger until settlement.

The run exposed and fixed four pre-step integration defects: the resolver checksum had targeted
Apple silicon instead of Linux x86_64, Unsloth was imported after the training stack, the A40 guard
compared decimal marketed capacity with binary GiB, and the original context ceiling truncated the
response marker. Each failure stopped before a paid training step and now has regression coverage.

For another ephemeral pod, keep the virtual environment on the faster container disk while placing
the model cache and retained artifacts on persistent workspace storage. Network-backed environment
imports dominated setup time in this first run.

## Recipe provenance

The code follows Unsloth's official Qwen3.8-27B conversational recipe at repository revision
`24a61a6f128a835de6a8c1f68a01b9cb00d60b4d`: `FastModel`, a dynamic 4-bit artifact, frozen vision
layers for text-only training, response-only SFT, batch size one with gradient accumulation, and an
adapter-only save. Transformers `5.15.1` and TRL `0.22.2` are explicit uv overrides because that
official notebook installs them after Unsloth with dependency checks disabled.
