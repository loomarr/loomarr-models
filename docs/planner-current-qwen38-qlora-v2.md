# Corrected current-contract Qwen3.8 QLoRA v2

This plan replaces the terminal v1 run after its model download exhausted the 40 GB
pod-persistent quota before optimizer step 1. The failure was infrastructure-only: no adapter was
produced, the evaluation did not run, and the reviewed training or development data did not
change.

The corrected envelope separates disposable dependencies from persistent model data. The pinned
environment is installed on the 40 GB container disk at `/opt/loomarr-venv`; the 80 GB
pod-persistent mount at `/workspace` holds only the Hugging Face cache, logs, and adapter output.
`HF_HUB_DISABLE_XET=1` is set before Unsloth or Hugging Face imports, preventing the Xet
reconstruction path that exhausted v1 storage. A pre-download check requires at least 70 GB free
on the persistent mount.

Everything that determines model behavior remains unchanged: the exact Qwen3.8 27B 4-bit
revision, 24 independently approved synthetic traces, disjoint 24-case development gate, 8,192
token context, response-only training, batch size 1, accumulation 4, nine optimizer steps, and
adapter-only output with a fresh-base reload probe. There is one configuration, no sweep, and no
automatic paid retry.

The proposed ceiling remains $1.50 for training plus $1.50 for adapter evaluation, $3.00
combined. The current committed ledger is $29.3563469369284740175, so the maximum combined
projection is $32.3563469369284740175 of $40.00. This plan grants no paid authority. A later
authorization must name the exact clean plan commit and the $3.00 combined ceiling.

Application safety, approval, scheduling, authorization, and playback authority remain
deterministic Go behavior outside this repository.
