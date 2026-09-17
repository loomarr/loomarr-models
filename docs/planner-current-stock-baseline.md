# Current-contract stock baseline harness

Issue [#25](https://github.com/loomarr/loomarr-models/issues/25) turns the current-contract preregistration from #22 into a fail-closed, replayable baseline harness. It remains a no-spend plan: the authorization record carries a zero reservation, and every model-download, provider, GPU, training, certification, deployment, and release authority flag is false.

The harness evaluates the exact 24-case development artifact in committed order against `planner-contract-v5`. It renders the production user and finalization turns, requires exact scripted tool arguments, preserves tool results as production JSON strings, and accepts only complete final Proposal JSON with surfaced catalog keys and unchanged `dateMeaning`.

Scoring reports every capability plus grounded completion, exact tool operation, argument validity, schema validity, date-meaning accuracy, policy accuracy, proposal quality, observed-fault recovery, latency, tool calls, memory, unsupported keys, authority violations, and hard failures. Recovery is measured only by the dedicated case containing an injected and observed fault followed by a valid retry; empty-result fallback is not counted as fault recovery.

A passing stock result deterministically stops the training lane. Only a completed model-quality miss can justify considering one adapter, and that decision still grants no training authority. Runtime, infrastructure, fixture, accounting, application-contract, or teardown failures produce no training justification.

The publisher replays the summary and decision from hash-bound results, verifies the pinned runtime and packages, requires one redacted generation record per model call, and rejects raw model output. Provider evidence must prove bounded lifetime, exact cost arithmetic, zero active pods, and deleted storage before settlement can be accepted.

## Local checks

```bash
make generate-current-stock-baseline
make check-current-stock-baseline
make preflight-current-stock-baseline
make check
```

The preflight command reconstructs the plan locally and reports the zero-reservation state. The live run and publisher targets intentionally refuse while paid authorization remains false. No command in this issue downloads the pinned model or allocates infrastructure.
