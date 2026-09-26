# Current planner contract rebaseline

Issue [#22](https://github.com/loomarr/loomarr-models/issues/22) replaces the obsolete v3/v4 execution plan with a no-spend, current-contract prerequisite. The imported bundle is pinned to one Loomarr commit and binds the production prompt, tool schema, message-template identity, source-contract identity, and the source files that define prompt rendering, source coordinates, tool results, and final response parsing.

## What changed

The historical model artifacts remain immutable evidence, but none are active training or evaluation inputs. Their assistant outputs use external-ID fields, omit mandatory `dateMeaning`, and predate exact catalog-key selection and the post-tool finalization turn. The compatibility report validates both tool calls and final outputs and machine-excludes every historical record.

The replacement data lane contains 24 pending synthetic training drafts and 24 separate development cases. Each split covers the same current capability matrix with different identities, normalized intents, catalog keys, and evidence. The disjointness check rejects identity, catalog-key, or normalized-semantic overlap. Pending drafts are not authorized for training until they receive independent review.

Application evaluation material remains application-owned. `planner-holdout-denylist-v2.json` stores only source-file hashes and hashes of protected case identities, intent text, catalog identities, names, and expected-answer values. It stores no raw application case content. Generation fails if a protected exact or normalized value appears in the new train/development artifacts.

Recovery receives credit only when a fixture records both an injected and observed fault followed by a retry. The application-side recovery case remains blocked by [loomarr/loomarr#1195](https://github.com/loomarr/loomarr/issues/1195), so this repository does not claim a current hosted-production comparison or release evidence.

## Decision sequence

1. Freeze the exact current Loomarr revision after its active merge queue settles, then regenerate the contract and hash-only denylist from that revision.
2. Independently review the 24 pending training drafts; rejected or unreviewed rows remain unusable.
3. Run the preregistered stock Qwen baseline only under a separately reviewed paid authorization. A passing stock result stops the training lane.
4. Consider the bounded adapter experiment in #20 only after a completed stock quality miss, repaired recovery evidence, and a fresh aggregate-spend decision.
5. Keep the reserved semantic families sealed and unmaterialized until a later certification plan is separately authorized.

This issue authorizes no provider calls, model downloads, GPU resources, training, packaging, serving, deployment, release, or merge.

## Reproduction

The repository-owned artifacts are deterministic:

```bash
make generate-current-contract
make check-current-contract
make check
```

The two imports require a local Loomarr checkout and an explicit reviewed commit:

```bash
python3 scripts/import_planner_contract.py /path/to/loomarr contracts/planner-contract-v5.json --revision <commit>
python3 scripts/import_planner_holdout_denylist.py /path/to/loomarr contracts/planner-holdout-denylist-v2.json --revision <commit>
```
