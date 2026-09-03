# loomarr-models

[![CI](https://github.com/loomarr/loomarr-models/actions/workflows/ci.yml/badge.svg)](https://github.com/loomarr/loomarr-models/actions/workflows/ci.yml)

Offline research assets for Loomarr-specific model experiments. This repository is deliberately
separate from the Go application: Loomarr consumes released model bytes through its existing provider
boundary and never imports this toolchain.

The first milestone is [loomarr/loomarr#937](https://github.com/loomarr/loomarr/issues/937): a
validated 50-trace planner smoke corpus. Current files establish the fail-closed trace contract,
the pinned Qwen 3.8 / Unsloth candidate environment, and the reproducible evidence from the first
bounded GPU smoke. Model weights, adapters, caches, and raw logs remain local ignored artifacts;
only compact hash-bound evidence is committed.

## Checks

```bash
make check
```

`validate-corpus` accepts reviewed artifacts only. Draft validation is available explicitly for the
independent-review workflow and never promotes a draft into training data.

Every corrected trace requires separate Gemini 3.1 Pro and GPT-5.4 attestations through pinned OpenRouter
provider routes. The two model families remain blind to each other's output and outside the Qwen
candidate family. Once both pass all six criteria for all 50 traces, `make finalize-corpus` creates the
immutable artifact, manifest, and validation report. Any disagreement, rejection, invalid response,
route drift, partial run, or unsettled charge remains non-approved and produces a targeted escalation.

The completed v7 review established a 50/50 valid rate for Gemini and an 18/50 valid rate for Sonnet,
with 13 unanimous approvals and 37 targeted escalations. Its exact `$2.212744` cost and all replayable
evidence are staged under `reviews/planner-smoke-v1/planner-model-review-v7/`; partial results do not alter
the canonical pending corpus.

Review v8 re-ran the complete corrected corpus with Gemini 3.1 Pro and GPT-5.4. All 100 calls settled
for exactly `$2.4979775`: Gemini produced 50 valid approvals, while GPT-5.4 produced 42 valid reviews
and eight quarantined length completions. The paired evidence independently approves 36 traces and
leaves 14 pending. Five ambiguous-mood traces and one conflicting-intent trace exposed two remaining
generator defects; the other eight pending traces require replacement attestations for invalid GPT
completions. Replayable evidence is staged under
`reviews/planner-smoke-v1/planner-model-review-v8/`, and the canonical corpus remains unchanged.

Review v9 corrects the two remaining generator families and re-reviews the complete hash-bound corpus.
Ambiguous-mood candidates now contain explicit tone evidence; conflicting-intent traces use a named
title that the same request both requires and excludes, avoiding fixture-only search language. The
GPT-5.4 completion ceiling is raised to 4,000 tokens to reduce invalid reasoning-only completions while
preserving one call per trace and no automatic inference retry. Its first launch stopped before inference
when the pinned OpenAI route became unavailable; v9 now pins the same model and upstream revision through
the single healthy `openai/flex` route. That route then rate-limited its first GPT call after all 50
Gemini reviews had settled, so the partial v9 run stopped and charged only the exact `$0.967292` Gemini
cost. V10 uses the healthy `openai/fast` route and adds explicit provider-error-envelope validation.

V10 completed 100/100 valid reviews for exactly `$3.999040`, independently approving 46 traces and
leaving four disagreements. Two rejections misread the deliberately synthetic fixture provenance as
assistant-invented content. Two recovery traces exposed real contract gaps: one reused a bare genre as
a title query, and one omitted the requested genre from final policy. The canonical corpus remains
pending while those reviewer and generator defects are corrected.

V11 applies the recovery correction across all five variants and makes the auditor's fixture semantics
explicit. A tool-returned reserved-ID fixture stands in for real catalog content and is not an invented
title. The complete corpus will be reviewed again through the same healthy Gemini and GPT-5.4 fast
routes before any trace is promoted.

V11 completed with 100 valid attestations, 50 unanimous approvals, zero escalations, and an exact
`$3.785636` cost. Its replayable publication is the sole input to the fail-closed canonical promotion
step; no earlier partial decisions are combined with it.

The candidate NVIDIA environment is resolved with uv 0.12.9 for Linux x86_64, Python 3.12, CUDA
12.8, and PyTorch 2.8. `make lock-qwen38-a40` reproduces the hash-bound lock; inside the pinned
container, `make sync-qwen38-a40` installs it using uv's `cu128` package backend. Neither command
downloads model weights or starts training.

Issue [loomarr/loomarr#938](https://github.com/loomarr/loomarr/issues/938) owns the bounded QLoRA smoke
runner. The first pinned A40 run completed all 20 steps against the reviewed-frozen 50-trace corpus;
its compact publication is under `runs/planner-qwen38-smoke-v1/`. The result proves the environment,
memory envelope, and adapter-only save path, but does not certify or authorize the adapter for release.
See [docs/qwen38-qlora-smoke.md](docs/qwen38-qlora-smoke.md) for the result, the NVIDIA training lane,
and the 64 GB Mac development/evaluation lane.

The leakage-free development comparison in
[loomarr-models#5](https://github.com/loomarr/loomarr-models/issues/5) is complete. Across 50 frozen
synthetic cases, the adapter improved weighted quality and policy accuracy, but retained 16 hard
failures, missed the absolute quality gates, and regressed recovery. Its hash-bound publication is
under `runs/planner-adapter-eval-v1/`; the decision is `adapter-rejected-no-release`, so no
certification run, packaging, serving, or release is authorized. See
[docs/planner-adapter-eval.md](docs/planner-adapter-eval.md). The exact Runpod charge was
`$0.7827729525743052`.

The exhaustive no-spend follow-up in
[loomarr-models#7](https://github.com/loomarr/loomarr-models/issues/7) classifies all 16 hard failures
by first divergence. The current 50-trace corpus does not authorize another QLoRA configuration;
targeted reviewed traces and a newly frozen disjoint development set must exist first. See
[docs/planner-adapter-failure-analysis.md](docs/planner-adapter-failure-analysis.md).

The no-spend first stage of
[loomarr-models#9](https://github.com/loomarr/loomarr-models/issues/9) generates 120 targeted pending
training drafts and a separate 60-case development gate across the six observed corrective behaviors.
All four planner splits pass pairwise identity and normalized-content leakage checks. The review plan
is hash-bound but keeps paid calls disabled; it does not authorize retraining. See
[docs/planner-behavior-corpus-v2.md](docs/planner-behavior-corpus-v2.md).

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Report security issues privately as
described in [SECURITY.md](SECURITY.md). Product bugs and feature requests belong in the main
[Loomarr repository](https://github.com/loomarr/loomarr/issues).
