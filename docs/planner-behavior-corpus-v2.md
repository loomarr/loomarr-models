# Planner behavior corpus v2

The first QLoRA adapter improved planner quality but failed 16 of 50 development cases. The
first-divergence analysis found four output failure classes: exact tool-argument drift, omitted final
fields, prose in place of proposal JSON, and multiple tool calls in one assistant turn. Recovery also
regressed. A second training run on the original 50 traces is therefore not authorized.

This milestone creates the targeted evidence required before that decision can be reconsidered. It is
owned by [loomarr-models#9](https://github.com/loomarr/loomarr-models/issues/9) and contains:

- 120 new training drafts, exactly 20 for each of six corrective behaviors;
- 60 frozen development cases, exactly 10 for each behavior, with no review attestations or training
  messages;
- a deterministic pairwise leakage report covering the original training and development sets plus
  both new sets; and
- a fail-closed independent-review contract and a review plan that explicitly disables paid calls.

The six behaviors are canonical tool-argument preservation, one tool operation per assistant turn,
complete proposal JSON, structured JSON abstention, recovery from synthetic tool errors, and
ambiguous-intent mapping without clarification prose.

## Current state

`planner-behavior-v2` is a draft. All 120 traces have two empty review slots and none may enter a
training artifact. `planner-behavior-development-v2` is frozen development-only data. It contains
scripts and scoring expectations but no model-produced answers, review decisions, or training
messages.

The validator rejects unsupported selected IDs, malformed calls, multiple calls in a turn, missing
final fields, prose finals, wrong recovery order, synthetic-fixture refusal, household-like data,
secrets, certification leakage, and cross-split content reuse. Normalized-content comparison removes
external IDs before hashing, so relabelling a copied case does not evade the leakage gate.

Generate and verify the no-spend artifacts with:

```bash
make generate-targeted-corpus
make check
```

The publication index under `runs/planner-behavior-corpus-v2/` binds the generator, drafts,
development cases, manifests, disjointness report, review decisions, validators, and review plan.
A clean clone must reproduce the same bytes.

## Independent review gate

Every training draft requires blind approvals from `google/gemini-3.1-pro-preview` through the exact
`google-ai-studio` route and `anthropic/claude-sonnet-4.6` through the exact `anthropic` route. Each
reviewer checks the existing six criteria: intent, tool calls, grounding, recovery, constraints, and
final proposal. They do not see one another's output.

The live no-inference check found both exact routes healthy and advertising every required structured
output parameter. OpenRouter exposes no no-inference proof that an exact multi-trace schema compiles,
so multi-trace batching remains disabled. The plan uses one trace per call. Each request contains a
compact trace with the complete intent, tool/result turns, final answer, and contract identity; it omits
only the repeated full system prompt and tool declaration after deterministic validation binds them.

The resulting 240-call plan has a 3,000 output-token ceiling and a conservative byte-as-token input
bound. Its exact worst case is `$13.906540`, below the `$15.00` reservation. Provider fallback and data
collection are denied, inference retries are disabled, and every completed generation must settle to
an exact cost before its output can count. Any rejection, disagreement, invalid completion, route
drift, or unsettled charge leaves the affected trace pending.

The execution wrapper reconstructs all 240 request bodies from committed sources and refuses any
request-hash, corpus, route, price, budget, runner, or execution-envelope drift. It reads the existing
`OPENROUTER_API_KEY` from the process environment or the ignored repository `.env` without printing it.
Its read-only preflight is:

```bash
make preflight-targeted-review
```

`make run-targeted-review` is enabled by a separate reviewed authorization commit. It still refuses
before inference if the live route, price, budget, committed source, or exact execution envelope differs.

The completed review settled 240 valid observations for exactly `$4.080632`. It produced 118
unanimous approvals and two disagreements. The first disagreement treated the contract's `query`
title-search field as though a nonexistent `title` field were required; the second incorrectly required
a per-pick confidence value when the abstention contained no picks. Both traces remain pending. The
completed plan is now terminal and paid execution is disabled; a corrected full review packet must be
published as a separate experiment.

The complete evidence lifecycle is implemented before any paid call:

1. `make run-targeted-review` preserves every raw response and exact generation settlement, quarantines
   settled model-authored invalid output, and never retries inference.
2. `make publish-targeted-review` replays all 240 observations from raw evidence, verifies their hashes
   and settled costs, derives 120 two-review decisions, copies the immutable evidence publication, and
   reconciles the aggregate budget ledger.
3. `make promote-targeted-review` changes the canonical decision file only if all 120 traces have two
   valid approvals and zero escalations.
4. `make finalize-targeted-corpus` creates the frozen training artifact only from that unanimous
   publication. It keeps `trainingAuthorized: false`; freezing data is not permission to train.

The runnable plan binds the runner, publisher, and finalizer by SHA-256. A route failure, malformed
response, missing observation, invalid settlement, disagreement, budget change, or artifact drift
stops promotion or leaves the affected trace pending.

The completed review settled for `$4.080632`. Aggregate external commitment is now
`$23.3611685675672820 / $40.00`, leaving `$16.6388314324327180` uncommitted. A future corrected review
must use a separate experiment, refresh route availability and worst-case pricing, and fit within that
remaining authorization before a reviewed authorization commit may enable it. The completed plan has
`paidReviewAuthorized: false`; it cannot be used as permission to call OpenRouter.

## Corrected full review plan

`planner-behavior-review-v3` is a separate, no-spend experiment over the same immutable corpus. It
reviews all 120 traces with both independent reviewers again—240 new calls if later authorized—not
only the two disputed cases. This prevents selective retry or approval shopping.

The corrected packet still contains one trace per call, but it now embeds the exact production tool
declaration and a deterministic targeted-audit projection. That projection makes the formerly implicit
semantics executable and reviewable: known-title search uses `query` and has no separate `title`
argument; each assistant turn contains at most one tool operation; the final object has exactly
`channelName`, `rationale`, `picks`, and `policy`; `picks` may be empty; and `confidence` is required on
each existing pick rather than at the top level. Tests bind those statements to the production contract
and corpus validators.

The 240-call envelope retains the 3,000-token output ceiling and has a conservative `$15.617740`
worst case inside a `$16.50` reservation. Starting from `$23.3611685675672820` committed, the maximum
aggregate commitment is `$39.8611685675672820 / $40.00`. The plan is intentionally
`planned-no-paid-calls-authorized`; route health and pricing must be refreshed immediately before a
separate reviewed authorization commit.

```bash
make preflight-corrected-targeted-review
make run-corrected-targeted-review # refuses while authorization is false
```

The v2 evidence remains immutable. A future v3 publication must settle and bind all 240 new calls; only
a unanimous 120/120 result may be promoted into the canonical training decisions.

## Stop point

This milestone stops after all 120 traces are independently approved and frozen while the 60
development cases remain untouched. It does not authorize GPU provisioning, model downloads,
training, certification, packaging, serving, or release. A later tracked decision may authorize one
new Unsloth QLoRA configuration if the reviewed corpus and remaining budget justify it.
