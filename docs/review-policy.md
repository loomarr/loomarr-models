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

The current primary reviewer is `google/gemini-3.1-pro-preview` through the exact `google-ai-studio`
route. The secondary reviewer is `openai/gpt-5.4` through the exact `openai` route. They review all 50
traces in separate calls without seeing each other's output. Neither belongs to the Qwen candidate family,
and neither reuses the unreliable Anthropic route from v7.

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

Review v4 stopped before inference when Anthropic rejected the five-trace strict schema as too large to
compile; current-key usage did not change. Review v5 therefore reviews one trace per request. This keeps
the same two independent decisions for every trace while reducing each provider grammar to one exact
trace key and six exact criterion keys. The zero-cost v4 evidence is
`reviews/planner-smoke-v1/model-review-v4-grammar-failure.json`.

Review v5 settled one valid response and then received a second response containing short placeholder
evidence and a verdict inconsistent with its own criteria. It stopped after the local validator rejected
that content, with both calls settling at `$0.038452` total. Review v6 retained the strict validator,
quarantined settled model-authored content failures as invalid observations, and proceeded to the next
planned trace without retrying inference. The v5 evidence is
`reviews/planner-smoke-v1/model-review-v5-content-failure.json`.

Review v6 then settled ten completed observations and an eleventh response that reached its exact output
limit. The response and settlement agreed on `length` / `max_tokens`, but v6 classified every non-stop
finish as an infrastructure failure and stopped after `$0.226310`. Review v7 classifies a settled,
identity-bound non-stop completion as invalid model content and continues; finish-reason disagreement
between response and settlement still stops globally. Provider identity, response envelope, usage,
settlement, route, or budget failures also still stop the whole run. The v6 evidence is
`reviews/planner-smoke-v1/model-review-v6-finish-failure.json`.

Review v7 completed all 100 settled observations for `$2.212744`. Gemini produced 50 valid reviews;
Sonnet produced 18 valid reviews and 32 quarantined invalid responses. The valid evidence yielded 13
unanimous approvals, four disagreements, and one unanimous rejection; 30 more traces have an invalid
Sonnet review paired with a Gemini approval, and two pair an invalid Sonnet review with a Gemini
rejection. The 37 non-approved traces are staged for targeted paid escalation. Partial decisions remain
inside `reviews/planner-smoke-v1/planner-model-review-v7/` and do not mutate the canonical pending corpus
until escalation is complete.

Before spending on adjudication, the v7 rejection patterns were applied at the generator-family level.
Twenty-five traces changed: genre and keyword discovery no longer invent a `media_type` restriction;
keyword candidates contain explicit thematic evidence; must-include no longer promises unsupported
variety; ambiguous moods map to grounded genre discovery; and error recovery switches to the required
alternate search mode. Review v8 therefore re-reviews the complete corrected corpus with Gemini and the
new OpenAI family rather than asking a third model to vote over known defects.

The run is limited to one hundred one-trace calls with no automatic inference retry, at most 2,000 output
tokens per call, and a conservative `$7.50` reservation. Its byte-count token upper bound prices the exact
v8 request bodies at no more than `$6.7973455`, projecting aggregate commitments to
`$14.564613891125471 / $40` before any call. The maintainer raised the aggregate authorization from `$20`
to `$40` on 2026-09-03; both model-review and QLoRA preflights enforce that exact ledger value.

Review v8 completed all 100 settled observations for exactly `$2.4979775`. Gemini returned 50 valid
approvals; GPT-5.4 returned 42 valid reviews and eight quarantined length completions. Thirty-six traces
received two approvals. Fourteen remain pending: all five ambiguous-mood traces and one conflicting-intent
trace were rejected by GPT-5.4, while two keyword-discovery, four other conflicting-intent, and two
tool-error-recovery traces lack a valid GPT-5.4 attestation. The rejection evidence shows that genre alone
does not ground a requested mood and that synthetic fixture-group language is not representable through
the production search contract. Those are generator defects to correct before replacement review; the
canonical corpus remains unchanged.

## Disagreement and escalation

Only two approvals with all twelve criterion decisions passing derive an approved trace. Two rejections
derive rejected; any disagreement derives pending. A settled model-authored malformed output becomes an
explicit invalid observation, keeps its trace pending, and remains part of the exact 100-observation
denominator. Missing request coverage, route/model drift, provider failure, response/settlement finish
disagreement, or unsettled cost invalidates the run. Rejected, disputed, or invalid traces go into a
targeted paid escalation packet and never enter training data. Corrected traces require a new hash-bound
review generation.

After review, regenerate with `make generate-drafts generate-review`, inspect the decisions, and run
`make finalize-corpus`. Finalization creates `traces.jsonl`, `manifest.json`, and
`validation-report.json` only when strict validation reports 50 approved, 0 pending, and 0 rejected.
`make check` verifies the frozen set whenever it exists. The GPU smoke may consume only that frozen set.
