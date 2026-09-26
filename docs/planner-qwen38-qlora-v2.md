# Targeted planner QLoRA v2 plan

Issue [#20](https://github.com/loomarr/loomarr-models/issues/20) owns one controlled test of whether
the reviewed planner-behavior-v2 corpus fixes the first adapter's 16 hard failures. This milestone
preregisters the experiment and costs `$0`; it does not authorize a Runpod pod, model download,
training, evaluation, packaging, serving, or release.

## Hypothesis and isolation

The first adapter established that Qwen3.8-27B and Unsloth QLoRA fit one A40 and can learn Loomarr
policy behavior. Its failure analysis found missing behavioral contrasts rather than evidence that a
different rank, learning rate, or optimizer was needed. V2 therefore changes the reviewed corpus and
the number of steps needed to preserve exposure, while keeping every other proven training setting
fixed. This is a corpus correction experiment, not a hyperparameter sweep.

The only training input is the frozen 120-trace `planner-behavior-v2` corpus: 20 traces each for exact
argument preservation, one tool operation per turn, complete proposal JSON, structured abstention,
tool-error recovery, and ambiguous-intent mapping. The earlier 50 traces, failed model generations,
review rationales, household data, and the untouched development cases are excluded.

## Exact training configuration

- Base: revision-pinned `Qwen/Qwen3.8-27B` through the pinned
  `unsloth/Qwen3.8-27B-unsloth-bnb-4bit` artifact.
- Hardware: one NVIDIA A40 with at least 48 GB marketed VRAM, Linux amd64, pinned CUDA/Unsloth lock.
- Adapter: rank 8, alpha 8, dropout 0; language, attention, and MLP modules enabled; vision disabled.
- SFT: response-only, deterministic seed 3407, 4,096-token ceiling, batch size 1, gradient
  accumulation 4, AdamW 8-bit, learning rate 0.0002, linear schedule, five warmup steps.
- Duration: exactly 45 optimizer steps. The effective 180 examples consumed equal 1.5 passes over
  120 traces, matching the first run's approximately 1.56-epoch exposure without adding a new tuning
  variable.
- Output: adapter and tokenizer only under `.artifacts`; no merged model or base-weight mutation.
- Artifact proof: the runner reloads the saved adapter into a fresh pinned base-model instance and
  performs a tiny deterministic generation before writing the run manifest. The separate artifact
  verifier then checks all 45 steps, identities, runtime, hashes, adapter-only inventory, and probe.

The 45-step runtime is expected to be roughly 30–35 minutes from the measured 20-step A40 run, but
the hard alarm remains 9,000 seconds. Runtime estimates are not promotion evidence.

## Evaluation contract

After a successful training publication, a generated evaluation config will bind the exact adapter
files and compare stock versus adapter, in that order, on all 60 untouched
`planner-behavior-development-v2` cases. Both candidates receive the same deterministic decoding,
tool-call ceiling, case order, contract, and A40 environment. The evaluation reservation is separate
from training.

This 60-case gate measures the six corrected curation behaviors. It does not by itself certify
personalization, controlled serendipity, recommendation acquisition, or filler curation. Those remain
separate #856 pillar contracts and require their own held-out cases; surprise never offsets a schema,
grounding, or authority failure.

## Budget and authorization

The reconciled live ledger currently commits `$28.6967677051754599875 / $40.00`. The plan reserves at most `$1.50`
for training and `$3.00` for evaluation, producing a maximum aggregate commitment of
`$33.1967677051754599875 / $40.00` and leaving `$6.8032322948245400125` uncommitted.

The checked-in plan has `paidTrainingAuthorized: false`. A later clean authorization commit must
refresh the ledger projection, change only the reviewed authorization state, pass CI, and be published
before any paid command runs. There is one configuration, no sweep, and no automatic paid retry.

The exact provision, detached execution, retrieval, cost supervision, and teardown sequence is in
[`planner-qwen38-qlora-v2-runbook.md`](planner-qwen38-qlora-v2-runbook.md). Runpod currently has no
working provider-side stop/terminate timer, so an uninterrupted supervisor must own the resource and
delete it by the recorded 9,000-second provider deadline.

## Promotion gate

The adapter advances only if the preregistered evaluation shows a meaningful aggregate improvement
over stock, improves the six targeted behavior families, and introduces zero unsupported IDs,
authority violations, or executable-envelope regressions. Otherwise the run is published as rejected
and work stops before packaging or integration.
