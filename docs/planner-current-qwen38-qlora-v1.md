# Current-contract Qwen3.8 QLoRA v1

This plan trains one adapter against the current Loomarr planner contract after the settled v3 stock baseline established a model-quality miss.

The exact inputs are the 24 independently approved synthetic traces in `corpus/planner-current-v1/traces.jsonl`, contract v5, holdout denylist v2, the pinned Qwen3.8 27B 4-bit revision, and the locked A40 environment. The 24 development cases remain evaluation-only and are never included in training.

The tokenizer-capacity report measures every fully rendered training trace against the pinned tokenizer and chat template. The maximum is 5,416 tokens, so the run uses an 8,192-token context without truncation. The old 4,096-token recipe is not reused.

The recipe is one deterministic response-only adapter run: batch size 1, gradient accumulation 4, 9 optimizer steps, and 36 total example exposures (1.5 passes over 24 traces). There is no sweep and no automatic paid retry. Output is adapter-only, and success requires reloading the persisted adapter into a fresh pinned base model and completing a deterministic generation probe.

The proposed ceiling is $1.50 for training plus $1.50 for adapter evaluation, $3.00 combined. Published stock results are reused; evaluation does not rerun the stock model. The plan initially grants no model download, GPU, training, evaluation, deployment, certification, or release authority. Paid execution requires a maintainer authorization that names the exact clean plan commit and the $3.00 combined ceiling.

Application safety, approval, scheduling, authorization, and playback authority remain deterministic Go behavior outside this repository.
