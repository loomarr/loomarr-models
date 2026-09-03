# Planner smoke trace review policy

Every synthetic trace receives two independent model-backed reviews. This replaces 72 manual decisions
after the maintainer chose to spend a bounded amount on review and reserve human attention for actual
disagreements. Deterministic validation remains the authority that admits evidence into the corpus.

## Frozen criteria

The reviewer checks the compact packet in `reviews/planner-smoke-v1.md` against the frozen contract bundle:

1. the intent contains no household fact and is meaningfully distinct from certification material;
2. tool mode and arguments follow the production search contract;
3. tool results are wholly synthetic and contain enough evidence for the target decision;
4. every selected identity and name appeared in a tool result;
5. exclusions, audience/era/format qualifiers, abstention, and recovery behavior are correct;
6. the final output uses the production schema and carries honest confidence values.

The review prompt treats every trace string as untrusted data and requires a separate boolean plus
trace-grounded evidence for each criterion. A trace-level approval is valid only when all six pass.

## Independent reviewers

The primary reviewer is `anthropic/claude-sonnet-5` through the exact `anthropic` route. The secondary
reviewer is `google/gemini-3.1-pro-preview` through the exact `google-ai-studio` route. They review all 50
traces in separate calls without seeing each other's output. Neither belongs to the Qwen candidate family.

The route snapshot, exact prices, supported parameters, request hashes, response bytes, provider and model
identity, finish reasons, native token counts, generation settlement, and costs are immutable evidence.
Every request requires strict structured output, a single provider, no fallback, parameter support,
and provider data-collection denial. Live route drift stops the run before inference.

Review v1 also required OpenRouter ZDR routing. Its pinned Anthropic route rejected that policy before
inference on 2026-09-03: zero calls completed and `$0` was charged. Because every trace is deliberately
public synthetic fixture data, later reviews remove only the request-level ZDR filter; provider collection
remains denied. The immutable zero-call failure evidence is
`reviews/planner-smoke-v1/model-review-v1-zdr-failure.json`.

Review v2 received one Anthropic response but rejected it because its trace IDs did not cover the exact
batch. The runner had not preserved the response ID before content validation, so the full `$0.067828`
current-key daily usage observed immediately afterward is conservatively charged to the program. Review
v3 writes the raw response before validation, settles and accounts for it before content acceptance, and
records the failing call hashes in run state. Its structured-output schema also requires the five literal
trace IDs as exact object keys, rather than permitting arbitrary strings. The v2 evidence is
`reviews/planner-smoke-v1/model-review-v2-coverage-failure.json`.

Review v3 preserved one exact-key response, then stopped when OpenRouter's first settlement lookup
temporarily returned 404. The generation became visible immediately afterward and settled at `$0.064384`.
Its preserved output also exposed that the provider did not enforce nested `minItems` or `minLength`: all
criteria collections and summaries were empty. Review v4 tolerates 404 only inside a bounded 60-attempt
GET-only settlement poll, binds the provider-native finish reason between response and settlement, and replaces
each criteria array with six required named properties plus explicit substantive-evidence instructions.
The v3 evidence is `reviews/planner-smoke-v1/model-review-v3-settlement-failure.json`.

The run is limited to twenty five-trace calls with no automatic inference retry, at most 6,000 output
tokens per call, and a conservative `$5.00` reservation. Its byte-count token upper bound prices the exact
v4 request bodies at no more than `$4.580936`, projecting aggregate commitments to
`$9.587107891125471 / $40` before any call. The maintainer raised the aggregate authorization from `$20`
to `$40` on 2026-09-03; both model-review and QLoRA preflights enforce that exact ledger value.

## Disagreement and escalation

Only two approvals with all twelve criterion decisions passing derive an approved trace. Two rejections
derive rejected; any disagreement derives pending. Malformed output, missing coverage, route/model drift,
provider failure, abnormal finish, or unsettled cost invalidates the run rather than shrinking the
denominator. Rejected, disputed, or invalid traces go into a small human escalation packet and never enter
training data. Corrected traces require a new hash-bound review generation.

After review, regenerate with `make generate-drafts generate-review`, inspect the decisions, and run
`make finalize-corpus`. Finalization creates `traces.jsonl`, `manifest.json`, and
`validation-report.json` only when strict validation reports 50 approved, 0 pending, and 0 rejected.
`make check` verifies the frozen set whenever it exists. The GPU smoke may consume only that frozen set.
