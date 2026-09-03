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
`google-ai-studio` route and `openai/gpt-5.4` through the exact `openai/fast` route. Each reviewer checks
the existing six criteria: intent, tool calls, grounding, recovery, constraints, and final proposal.
They do not see one another's output.

The planned three-trace batch size is conditional. Before inference, a live no-inference check must
prove that each exact route supports the compiled strict-output schema. Otherwise the review must use
one trace per call or stop. Provider fallback and data collection are denied, inference retries are
disabled, and every completed generation must settle to an exact cost before its output can count.
Any rejection, disagreement, invalid completion, route drift, or unsettled charge leaves the affected
trace pending.

The review reservation ceiling is `$15.00`. Aggregate external commitment is currently
`$19.2805365675672820 / $40.00`, so the planned maximum would be
`$34.2805365675672820 / $40.00`. Route availability and worst-case pricing must be refreshed
immediately before authorization. The checked-in plan has `paidReviewAuthorized: false`; it cannot be
used as permission to call OpenRouter.

## Stop point

This milestone stops after all 120 traces are independently approved and frozen while the 60
development cases remain untouched. It does not authorize GPU provisioning, model downloads,
training, certification, packaging, serving, or release. A later tracked decision may authorize one
new Unsloth QLoRA configuration if the reviewed corpus and remaining budget justify it.
