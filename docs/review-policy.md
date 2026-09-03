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
data-collection denial, and ZDR routing. Live route drift stops the run before inference.

The run is limited to twenty five-trace calls with no automatic inference retry, at most 6,000 output
tokens per call, and a conservative `$4.50` reservation. Its byte-count token upper bound prices the exact
request bodies at no more than `$4.142856`, projecting aggregate commitments to
`$8.954895891125471 / $20` before any call.

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
