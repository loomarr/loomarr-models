# Current-contract stock baseline harness

Issue [#25](https://github.com/loomarr/loomarr-models/issues/25) turns the current-contract preregistration from #22 into a fail-closed, replayable baseline harness. The maintainer authorized the exact launch plan at commit `5c826f83940de4d9e50b7a0f3777b97a5137998c` with a hard `$1.50` reservation. At the launch-time secure A40 rate of `$0.49/hour`, the 9,000-second GPU maximum is `$1.225`; container-disk and short-lived pod-persistent storage charges must fit inside the same reservation. Training, certification, deployment, and release authority remain false.

The harness evaluates the exact 24-case development artifact in committed order against `planner-contract-v5`. It renders the production user and finalization turns, requires exact scripted tool arguments, preserves tool results as production JSON strings, and accepts only complete final Proposal JSON with surfaced catalog keys and unchanged `dateMeaning`.

Runpod's live A40 sites did not overlap any network-volume site at launch. The execution therefore uses the provider's 40 GB pod-persistent mount at `/workspace`, which is deleted with the pod after verified local retrieval. This changes only evidence transport: the exact GPU, model, image, deadline, cost cap, scoring, and no-retry rule remain fixed.

Scoring reports every capability plus grounded completion, exact tool operation, argument validity, schema validity, date-meaning accuracy, policy accuracy, proposal quality, observed-fault recovery, latency, tool calls, memory, unsupported keys, authority violations, and hard failures. Recovery is measured only by the dedicated case containing an injected and observed fault followed by a valid retry; empty-result fallback is not counted as fault recovery.

A passing stock result deterministically stops the training lane. Only a completed model-quality miss can justify considering one adapter, and that decision still grants no training authority. Runtime, infrastructure, fixture, accounting, application-contract, or teardown failures produce no training justification.

The publisher replays the summary and decision from hash-bound results, verifies the pinned runtime and packages, requires one redacted generation record per model call, and rejects raw model output. Provider evidence must prove bounded lifetime, exact cost arithmetic, zero active pods, and deletion of the pod-persistent storage before settlement can be accepted.

## Local checks

```bash
make generate-current-stock-baseline
make check-current-stock-baseline
make preflight-current-stock-baseline
make check
```

The preflight command reconstructs the authorized plan locally and proves that the `$1.50` reservation keeps aggregate commitment below `$40.00`. The authorization permits exactly one stock-baseline model download and secure A40 execution with no automatic retry; it grants no training or product authority.
