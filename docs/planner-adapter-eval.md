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
first and the adapter second on the same A40. The 2.37 GB untied embedding table remains on the GPU:
the pinned 48 GB envelope has sufficient headroom, and Unsloth's automatic CPU offload made the
first inference attempt transfer-bound. Torch/Unsloth runtime compilation is disabled before the
Unsloth import because the pinned Qwen 3.8 delta-net inference path otherwise recompiles across
changing conversation shapes. Raw generations are captured before deterministic scoring.

The scorer reports grounded completion, correct tool operation, argument validity, schema validity,
policy accuracy, exact fixture proposal quality, recovery, latency, tool calls, hard failures, and
peak VRAM. The adapter must clear the frozen 0.02 weighted-quality margin, improve policy accuracy or
recovery, meet every absolute quality threshold, avoid a greater-than-0.02 regression on any other
quality metric, and produce zero unsupported-ID, grounding, schema, or authority hard failures.

## Result

The secure A40 comparison completed all 50 stock and 50 adapter cases in 6,260 seconds. The adapter
raised weighted quality from `0.3967` to `0.5043`, including a material policy-accuracy improvement
from `0.00` to `0.48`. It also reduced hard failures from 20 to 16 and produced no unsupported IDs
or authority violations. Those gains show that this QLoRA recipe can teach useful Loomarr-specific
behavior.

It is nevertheless rejected. The adapter missed all six absolute quality thresholds, retained 16
hard failures, reduced recovery from `0.4667` to `0.3333`, and used five tool calls at p95. It
therefore does not advance to certification and is not authorized for packaging, serving, or release.

| Metric | Stock | Adapter |
| --- | ---: | ---: |
| Weighted quality | 0.3967 | 0.5043 |
| Grounded completion | 52% | 58% |
| Correct tool operation | 28% | 40% |
| Argument validity | 98% | 72% |
| Schema validity | 60% | 68% |
| Policy accuracy | 0% | 48% |
| Exact proposal quality | 52% | 54% |
| Recovery | 46.7% | 33.3% |
| Hard failures | 20 | 16 |
| p50 latency | 43.0 s | 70.3 s |
| p95 latency | 77.2 s | 134.8 s |
| Peak VRAM | 21.97 GiB | 22.40 GiB |

The first generated comparison was invalid because Qwen decoding removed the opening `<think>` token
while retaining `</think>`, and the parser treated the remaining reasoning prefix as final output.
The committed result is a deterministic parser replay of the captured generations: it performs no
inference, preserves the measured latency and VRAM, requires the same per-case call structure, and
binds the source run, raw files, corrected results, parser, and source commits by SHA-256. The compact
manifest in `runs/planner-adapter-eval-v1/` contains per-case metrics but no prompts, completions, or
transcripts. Runpod settled the exact charge at `$0.7827729525743052`: `$0.7560368422418833` for GPU
and `$0.02673611033242196` for disk. The full program ledger is now
`$19.2805365675672820 / $40.00`, including the standing `$0.10` reservation.

## Reproduction boundary

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
`$21.4977636149929768 / $40.00` after the first Runpod charge settled, and has a four-hour alarm.
Copy results and logs off the pod, verify their hashes, and delete the pod and unused storage.

The only valid decisions are `adapter-advances-to-single-certification-run` and
`adapter-rejected-no-release`. This run produced the latter, so the separately tracked one-time
certification evaluation under [loomarr/loomarr#833](https://github.com/loomarr/loomarr/issues/833)
is not authorized. It also does not authorize adapter packaging, serving, broader training, or
transfer to another pillar.
