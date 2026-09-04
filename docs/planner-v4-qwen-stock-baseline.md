# Qwen 3.8 planner-v4 stock baseline

This experiment answers one bounded question: does the exact stock Qwen 3.8 27B artifact already
meet Loomarr's planner-v4 development contract, or do its measured failures justify one targeted
QLoRA configuration? It is development evidence, not product certification.

The zero-cost local screen could not answer that question. Gemma 4 12B failed the 120-case gate,
while the Qwen MLX/NVFP4 artifact ran out of Metal memory on the 24 GB M5 Pro host before the first
case. This baseline therefore uses the revision-pinned Unsloth bitsandbytes artifact on the already
locked Linux/CUDA environment.

## Frozen experiment

- Model: `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` at revision
  `8aa5f05d26b7205477066e1449e0af13f762a299`.
- Data: all 120 synthetic, disjoint planner-v4 development cases already exposed by the local
  screen. No case, transcript, or result may enter training.
- Runtime: one secure Runpod `NVIDIA A40`, CUDA 12.8+, pinned PyTorch image digest, 48 GB VRAM,
  deterministic decoding, at most five model calls per case, and no automatic retry.
- Limit: 9,000 seconds from provider creation and a hard `$1.50` reservation. At the captured
  `$0.49/hour` GPU rate, the GPU maximum is `$1.225`; disk and short-lived volume charges must fit
  inside the same reservation.
- Outputs: redacted generation records, scored case results, peak VRAM, exact package/runtime
  identity, threshold failures, and a provider settlement. Raw model output remains local and is
  represented by SHA-256 so hidden reasoning is not published.

The live Runpod price, CUDA capacity, zero-pod account state, and the repository budget must be
rechecked immediately before launch. The catalog snapshot is evidence for this plan, not permission
to assume future availability or price.

## Decision boundary

If stock Qwen clears every preregistered threshold with zero hard failures, QLoRA is not justified
and training stays blocked. If it completes but misses one or more thresholds, QLoRA is justified
as an experiment; that still does not authorize training. An infrastructure failure, timeout,
identity drift, or unsettled provider cost yields no model decision and no automatic retry.

The result cannot authorize release, deployment, or any of the recommendation/filler pillars. A
trained adapter, if later authorized, must be compared to these same stock results without rerunning
or editing the baseline.

## Launch boundary

The checked-in plan deliberately reports `paidBaselineAuthorized: false`. Before any volume or pod
is created, the maintainer must separately authorize the exact plan commit and `$1.50` ceiling, and
a subsequent authorization commit must update the bound authorization ledger and make the runner
executable. The supervisor must record the pod and volume IDs, enforce the provider-creation
deadline, retrieve and hash the artifacts, delete the pod, settle the exact Runpod charge, and
delete the volume. `make publish-v4-stock-baseline` replays the scores, verifies redaction and
teardown evidence, settles the budget, and makes the experiment terminal. Any failure is published
as terminal evidence rather than retried.
