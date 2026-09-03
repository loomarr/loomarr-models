# Planner smoke trace review policy

The 50-trace smoke corpus is small enough that every trace receives a primary human review. Automated
validation is necessary but cannot judge whether a synthetic target actually honors every intent qualifier.

## Primary review

The reviewer checks the compact packet in `reviews/planner-smoke-v1.md` against the frozen contract bundle:

1. the intent contains no household fact and is meaningfully distinct from certification material;
2. tool mode and arguments follow the production search contract;
3. tool results are wholly synthetic and contain enough evidence for the target decision;
4. every selected identity and name appeared in a tool result;
5. exclusions, audience/era/format qualifiers, abstention, and recovery behavior are correct;
6. the final output uses the production schema and carries honest confidence values.

The reviewer updates only the `primary` object in `reviews/planner-smoke-v1.jsonl`, using
`github:<login>` as the reviewer, an RFC 3339 UTC timestamp, and a short note. `approved` requires all
checks; `rejected` requires a note and stays outside every artifact. A pending record must carry no
reviewer, timestamp, or note.

## Independent sample and disagreement

A second reviewer checks all empty-result, tool-error, and repair traces plus a deterministic 20% sample of
the other families (variant `01` in each family): exactly 22 traces. Those rows carry
`secondary.required: true`; the second reviewer updates the `secondary` object and must use a different
GitHub identity after the primary review. A secondary rejection derives a pending disagreement until the
target is corrected and both reviewers approve. The generator never converts pending, rejected, or
disputed work into an approved record.

After review, regenerate with `make generate-drafts generate-review`, inspect the decisions, and run
`make finalize-corpus`. Finalization creates `traces.jsonl`, `manifest.json`, and
`validation-report.json` only when strict validation reports 50 approved, 0 pending, and 0 rejected.
`make check` verifies the frozen set whenever it exists. The GPU smoke may consume only that frozen set.
