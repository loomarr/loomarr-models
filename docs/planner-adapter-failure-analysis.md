# Planner adapter failure analysis

Issue [loomarr-models#7](https://github.com/loomarr/loomarr-models/issues/7) classifies every hard
failure from the rejected Qwen3.8-27B adapter evaluation before any second training decision. The
analysis uses the corrected parser replay, not the invalid original scorer output, and adds no model
call, reviewer call, GPU allocation, or external spend.

## Exhaustive result

All 16 hard-failing cases ended in `schema_invalid`; there were no unsupported IDs or authority
violations. A first-divergence review of the hash-bound local generation stream assigns each case to
exactly one category:

| First divergence | Cases | What happened |
| --- | ---: | --- |
| Exact tool-argument drift | 7 | The model changed an era or keyword, added an unjustified filter, or mapped an ambiguous cue to the wrong genre. The frozen tool script rejected the call. |
| Required final-field omission | 1 | A grounded proposal omitted the required `policy` object. |
| Prose instead of proposal JSON | 5 | One ambiguous request produced clarification prose; four recovery requests treated synthetic fixtures as attempted fabrication and refused without calling the tool. |
| Multiple tool calls in one turn | 3 | Conflicting intents produced two catalog calls in one assistant message, outside the single-operation turn contract, so neither call executed. |

The 16 classified case IDs are committed in
`runs/planner-adapter-eval-v1/failure-analysis.json`. Its source bindings point to the compact run
manifest, corrected adapter-result stream, and ignored raw generation stream by SHA-256. Raw
generations and transcripts remain local and uncommitted.

## Training decision

Do not run a second training configuration on the current 50 traces. The first adapter proves that
Unsloth QLoRA fits the pinned A40 environment and can teach policy behavior, but changing learning
rate, rank, or step count would not supply the missing behavioral contrasts exposed here. That would
be a hyperparameter search against a known corpus gap.

The next legitimate training gate is a separately reviewed corpus revision covering canonical
tool-argument preservation, one operation per turn, complete final JSON including empty policy,
structured abstention, synthetic-fixture recovery, and ambiguous-intent mapping. A new development
set must be generated independently and frozen before training so these 16 cases do not become the
next evaluation target by memorization.

Until both artifacts exist, no further training, certification, packaging, serving, or deployment is
authorized. Unsloth remains a validated experimental framework, not a selected product dependency or
released model route.
