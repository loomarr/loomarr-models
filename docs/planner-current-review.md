# Current planner training review

Issue [#27](https://github.com/loomarr/loomarr-models/issues/27) owns the independent review gate for the 24 current-contract training drafts. The review plan binds the exact draft bytes, current production contract, development split, hash-only application denylist, source manifests, generator, and validator.

The editable artifact is `reviews/planner-current-v1/decisions.jsonl`. Each row binds one draft by its exact line hash and requires a reviewer distinct from the draft generator, an RFC 3339 UTC timestamp, a verdict, and explicit results for contract conformance, grounding, constraint behavior, recovery evidence, and synthetic/private-data safety. Approval requires every criterion. Rejection requires at least one failed criterion and explanatory notes. Pending rows cannot carry review evidence.

The generated packet at `reviews/planner-current-v1/review-packet.md` omits only the repeated system prompt and tool schema for readability while keeping their source bytes hash-bound. It shows every other turn exactly, including source coordinates, tool arguments, complete synthetic evidence, the finalization instruction, final Proposal JSON, capability, draft hash, and current decision for each trace.

While decisions remain pending or rejected, regenerate and check the packet with:

```bash
make generate-current-review
make check-current-review
```

Only 24 valid approvals permit finalization. At that point, regenerate the packet, finalize once, and run the repository gate:

```bash
make generate-current-review
make finalize-current-review
make check
```

Finalization never rewrites the synthetic dialogue: it adds review provenance, revalidates the source traces, denylist, and train/development disjointness, and creates hash-bound training, manifest, and publication artifacts. It refuses to overwrite an existing publication.

The pending plan and any future completed publication grant no provider, model-download, GPU, training, certification, deployment, or release authority and introduce no external spend.
