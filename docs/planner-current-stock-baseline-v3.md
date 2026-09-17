# Current-contract stock baseline v3

Issue [#29](https://github.com/loomarr/loomarr-models/issues/29) owns the correction for the terminal v2 context-capacity failure. V2 produced no model-quality result and grants no training justification.

V3 preserves the exact model revision, 24-case current-contract development gate, scoring thresholds, secure A40, pinned environment, deterministic decoding, 9,000-second deadline, `$1.50` maximum reservation, and no-retry policy. Its candidate context is 16,384 tokens with a 2,048-token completion budget.

The plan is deliberately non-executable. Before paid authorization, the exact pinned Qwen processor must render every scripted initial, tool-result, retry, and finalization turn. Every stage must retain all 2,048 completion tokens, and the resulting report must be committed and hash-bound into the experiment. V2 billing must also be exactly settled before the aggregate-spend check is refreshed.

Training, certification, deployment, and release authority remain false.

```bash
python3 scripts/build_planner_current_stock_baseline_v3.py
PYTHONPATH=src python3 scripts/preflight_planner_current_stock_baseline_v3.py
```
