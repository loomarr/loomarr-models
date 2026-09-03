# Planner stock-versus-adapter development evaluation

Issue [loomarr-models#5](https://github.com/loomarr/loomarr-models/issues/5) owns the first quality
comparison of the stock Qwen3.8-27B artifact and the adapter produced by the A40 smoke. This is a
development gate for channel curation only. It does not certify a release or provide evidence for
channel recommendation or filler curation.

## Frozen comparison

The `planner-development-v1` corpus contains 50 new synthetic cases: five cases for each of the ten
planner axes used by the smoke corpus. Every case has a frozen intent, ordered tool script, synthetic
tool results, selected and forbidden IDs, expected policy, abstention state, and tool-call budget.
Validation rejects overlap with the training intents or content IDs and rejects every identity and
digest in the certification denylist. No household or certification payload is present.

Both candidates receive the same ordered cases, system prompt, tool schema, scripted tool results,
greedy decoding, 4,096-token context, 768-token per-turn ceiling, seed, and single trial. Stock runs
first and the adapter second on the same A40. Raw generations are captured before deterministic
scoring.

The scorer reports grounded completion, correct tool operation, argument validity, schema validity,
policy accuracy, exact fixture proposal quality, recovery, latency, tool calls, hard failures, and
peak VRAM. The adapter must clear the frozen 0.02 weighted-quality margin, improve policy accuracy or
recovery, meet every absolute quality threshold, avoid a greater-than-0.02 regression on any other
quality metric, and produce zero unsupported-ID, grounding, schema, or authority hard failures.

## No-spend preflight

The smoke adapter directory is a local ignored artifact. Copy the verified directory so that the
configured file exists at:

```text
.artifacts/runpod-qwen38-qlora-smoke-v1/planner-qwen38-smoke-v1/adapter/adapter_model.safetensors
```

Its required SHA-256 is
`08a166aa73ec1aaf965cf5a53af61a728d4542c841859b477af72305e5cb35f7`. Then run from a clean commit:

```bash
make preflight-planner-eval
```

Preflight completes before importing Torch, Unsloth, Transformers, PEFT, or datasets. It binds the
cases and manifest, training corpus, holdout denylist, prompt/tool contract, environment, model
revisions, adapter source manifest, local adapter bytes, clean source commit, output containment, and
aggregate budget. Any mismatch stops before model loading or spend.

## Paid run boundary

The paid command is:

```bash
make run-planner-eval
```

It is authorized only after the clean-commit preflight passes on the pinned secure A40 environment.
The experiment reserves at most `$3.00`, projects aggregate commitment to
`$22.814559391125471 / $40.00` while the first Runpod charge remains unsettled, and has a four-hour
alarm. Copy results and logs off the pod, verify their hashes, and delete the pod and unused storage.

The only valid decisions are `adapter-advances-to-single-certification-run` and
`adapter-rejected-no-release`. Even a development pass authorizes only the separately tracked one-time
certification evaluation under [loomarr/loomarr#833](https://github.com/loomarr/loomarr/issues/833).
It does not authorize adapter packaging, serving, broader training, or transfer to another pillar.
