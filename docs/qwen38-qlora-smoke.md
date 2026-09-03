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
unless all 50 traces are human-approved, every immutable digest matches, both Qwen revisions match
the environment, critical runner files are tracked and clean, one training configuration is present,
the output stays under `.artifacts`, and the budget projects below the aggregate `$20` authorization.

The current config intentionally points at the pending review corpus, so this command must fail
closed until issue #937 produces the approved artifact:

```bash
PYTHONPATH=src python3 scripts/train_planner_smoke.py --preflight-only
```

After review, update the corpus path and immutable hashes in one commit, run `make check`, then run
the same preflight inside the pinned container. Only after that succeeds may the paid command run:

```bash
PYTHONPATH=src python3 scripts/train_planner_smoke.py
```

The experiment has a `$1.50` reservation ceiling and a 9,000-second process alarm. It saves only the
LoRA adapter, tokenizer metadata, trainer checkpoints, and a hash-bound run manifest. Merging,
quantizing, packaging, certification, or deployment belongs to later tracked work.

## Recipe provenance

The code follows Unsloth's official Qwen3.8-27B conversational recipe at repository revision
`24a61a6f128a835de6a8c1f68a01b9cb00d60b4d`: `FastModel`, a dynamic 4-bit artifact, frozen vision
layers for text-only training, response-only SFT, batch size one with gradient accumulation, and an
adapter-only save. Transformers `5.15.1` and TRL `0.22.2` are explicit uv overrides because that
official notebook installs them after Unsloth with dependency checks disabled.
