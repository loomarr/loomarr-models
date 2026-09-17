# Current-contract stock baseline v3

Issue [#29](https://github.com/loomarr/loomarr-models/issues/29) owns the correction for the terminal v2 context-capacity failure. V2 produced no model-quality result and grants no training justification.

V3 preserves the exact model revision, 24-case current-contract development gate, scoring thresholds, secure A40, pinned environment, deterministic decoding, 9,000-second deadline, `$1.50` maximum reservation, and no-retry policy. Its context is 16,384 tokens with a 2,048-token completion budget.

The exact pinned Qwen processor rendered every scripted initial, tool-result, retry, and finalization turn in the committed, hash-bound capacity report. The maximum input was 5,260 tokens and the minimum remaining capacity was 11,124 tokens, so all 50 stages retain the full 2,048-token completion budget.

The plan remains deliberately non-executable until v2 billing is exactly settled and the aggregate-spend check is refreshed. No paid v3 authorization follows from the capacity result alone.

Training, certification, deployment, and release authority remain false.

```bash
python3 scripts/build_planner_current_stock_baseline_v3.py
PYTHONPATH=src python3 scripts/preflight_planner_current_stock_baseline_v3.py
```
