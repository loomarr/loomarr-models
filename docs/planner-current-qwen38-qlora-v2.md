# Corrected current-contract Qwen3.8 QLoRA v2

## Terminal outcome

The authorized run is complete-failed and settled. It stopped before optimizer step 1, produced no
adapter, and therefore did not enter paid evaluation. Runpod billed exactly
`$0.06595210370142013`; the pod and its persistent storage were deleted.

All 24 live token counts matched the preregistered measurements exactly, including the 5,416-token
maximum. The fail-closed gate rejected the rendered-byte hash because the offline capacity checker
used Jinja's default sorted-key JSON serialization while the pinned Transformers runtime preserved
mapping insertion order. Reproducing the offline render with JSON key sorting disabled matches the
runtime byte-for-byte across all 24 traces.

This result is a harness-parity failure, not evidence about adapter quality. V2 is terminal and cannot
be rerun. Any retry must use a new experiment identity, bind a newly generated exact-runtime capacity
artifact, and receive separate explicit authorization.

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

The proposed ceiling was $1.50 for training plus $1.50 for adapter evaluation, $3.00
combined. At authorization, the committed ledger was $29.3563469369284740175, so the maximum combined
projection was $32.3563469369284740175 of $40.00. This plan initially granted no paid authority. A later
authorization must name the exact clean plan commit and the $3.00 combined ceiling.

Application safety, approval, scheduling, authorization, and playback authority remain
deterministic Go behavior outside this repository.
