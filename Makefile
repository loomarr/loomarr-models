.PHONY: check compile test check-budget-reconciliation generate-current-contract check-current-contract init-current-review generate-current-review check-current-review finalize-current-review generate-current-stock-baseline check-current-stock-baseline preflight-current-stock-baseline generate-current-stock-baseline-v3 check-current-stock-baseline-v3 preflight-current-stock-baseline-v3 run-current-stock-baseline-v3 publish-current-stock-baseline-v3 check-current-prompt-capacity run-current-stock-baseline publish-current-stock-baseline publish-current-stock-failure init-review generate-drafts check-generated generate-development-eval check-development-eval init-targeted-review generate-targeted-corpus check-targeted-corpus init-v4-review generate-v4-corpus check-v4-corpus generate-v4-review-plan check-v4-review-plan preflight-v4-review run-v4-review publish-v4-review promote-v4-review generate-v4-local-screen check-v4-local-screen preflight-v4-local-screen run-v4-local-screen-qwen run-v4-local-screen-gemma publish-v4-local-screen generate-v4-stock-baseline check-v4-stock-baseline preflight-v4-stock-baseline run-v4-stock-baseline publish-v4-stock-baseline generate-corrected-targeted-review check-corrected-targeted-review refresh-corrected-targeted-review-routes check-live-corrected-targeted-review-routes preflight-targeted-review run-targeted-review publish-targeted-review promote-targeted-review preflight-corrected-targeted-review run-corrected-targeted-review publish-corrected-targeted-review promote-corrected-targeted-review finalize-targeted-corpus check-targeted-finalized generate-qlora-v2-plan check-qlora-v2-plan preflight-qlora-v2-plan preflight-qlora-v2 verify-qlora-v2-artifact generate-review check-review check-finalized finalize-corpus preflight-model-review run-model-review publish-model-review promote-model-review lock-qwen38-a40 check-environment sync-qwen38-a40 validate-drafts validate-corpus preflight-qwen38 preflight-planner-eval run-planner-eval replay-planner-eval

PYTHON ?= python3
UV ?= uv
UV_VERSION := 0.12.9

check: compile test check-budget-reconciliation check-current-contract check-current-review check-current-stock-baseline check-current-stock-baseline-v3 check-generated check-development-eval check-targeted-corpus check-v4-corpus check-v4-review-plan check-v4-local-screen check-v4-stock-baseline check-corrected-targeted-review check-targeted-finalized check-qlora-v2-plan check-review check-finalized check-environment validate-drafts

compile:
	$(PYTHON) -m compileall -q scripts src tests

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

check-budget-reconciliation:
	PYTHONPATH=src $(PYTHON) -m loomarr_models.budget_reconciliation \
		budgets/runpod-pod-billing-current-stock-baseline-v3-v1.json budgets/external-spend-v1.json
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p 'test_budget_reconciliation.py' -v

generate-current-contract:
	$(PYTHON) scripts/build_planner_current_contract.py

check-current-contract:
	$(PYTHON) scripts/build_planner_current_contract.py --check

init-current-review:
	$(PYTHON) scripts/build_planner_current_review.py --init-review

generate-current-review:
	$(PYTHON) scripts/build_planner_current_review.py

check-current-review:
	$(PYTHON) scripts/build_planner_current_review.py --check

finalize-current-review:
	$(PYTHON) scripts/finalize_planner_current_review.py

generate-current-stock-baseline:
	$(PYTHON) scripts/build_planner_current_stock_baseline.py

check-current-stock-baseline:
	$(PYTHON) scripts/build_planner_current_stock_baseline.py --check

preflight-current-stock-baseline:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_current_stock_baseline.py --preflight-only

generate-current-stock-baseline-v3:
	$(PYTHON) scripts/build_planner_current_stock_baseline_v3.py

check-current-stock-baseline-v3:
	$(PYTHON) scripts/build_planner_current_stock_baseline_v3.py --check

preflight-current-stock-baseline-v3:
	PYTHONPATH=src $(PYTHON) scripts/preflight_planner_current_stock_baseline_v3.py

run-current-stock-baseline-v3:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_current_stock_baseline_v3.py

publish-current-stock-baseline-v3:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_current_stock_baseline_v3.py

check-current-prompt-capacity:
	PYTHONPATH=src $(PYTHON) scripts/check_planner_current_prompt_capacity.py --config experiments/planner-current-qwen-stock-baseline-v2.json

run-current-stock-baseline:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_current_stock_baseline.py

publish-current-stock-baseline:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_current_stock_baseline.py

publish-current-stock-failure:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_current_stock_failure.py

init-review:
	$(PYTHON) scripts/build_planner_smoke_drafts.py --init-review

generate-drafts:
	$(PYTHON) scripts/build_planner_smoke_drafts.py

check-generated:
	$(PYTHON) scripts/build_planner_smoke_drafts.py --check

generate-development-eval:
	$(PYTHON) scripts/build_planner_development_eval.py

check-development-eval:
	$(PYTHON) scripts/build_planner_development_eval.py --check

init-targeted-review:
	$(PYTHON) scripts/build_planner_behavior_corpus.py --init-review

generate-targeted-corpus:
	$(PYTHON) scripts/build_planner_behavior_corpus.py

check-targeted-corpus:
	$(PYTHON) scripts/build_planner_behavior_corpus.py --check

init-v4-review:
	$(PYTHON) scripts/build_planner_v4_delta.py --init-review

generate-v4-corpus:
	$(PYTHON) scripts/build_planner_v4_delta.py

check-v4-corpus:
	$(PYTHON) scripts/build_planner_v4_delta.py --check

generate-v4-review-plan:
	$(PYTHON) scripts/build_planner_v4_review.py

check-v4-review-plan:
	$(PYTHON) scripts/build_planner_v4_review.py --check

preflight-v4-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_review.py --preflight-only

run-v4-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_review.py

publish-v4-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_v4_review.py

promote-v4-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_v4_review.py --promote-approved

generate-v4-local-screen:
	$(PYTHON) scripts/build_planner_v4_local_screen.py

check-v4-local-screen:
	$(PYTHON) scripts/build_planner_v4_local_screen.py --check

preflight-v4-local-screen:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_local_screen.py --preflight-only

run-v4-local-screen-qwen:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_local_screen.py --candidate qwen38-27b-mlx-nvfp4

run-v4-local-screen-gemma:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_local_screen.py --candidate gemma4-12b-q4-k-m

publish-v4-local-screen:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_v4_local_screen.py

generate-v4-stock-baseline:
	$(PYTHON) scripts/build_planner_v4_stock_baseline.py

check-v4-stock-baseline:
	$(PYTHON) scripts/build_planner_v4_stock_baseline.py --check

preflight-v4-stock-baseline:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_stock_baseline.py --preflight-only

run-v4-stock-baseline:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_v4_stock_baseline.py

publish-v4-stock-baseline:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_v4_stock_baseline.py

generate-corrected-targeted-review:
	$(PYTHON) scripts/build_planner_behavior_review_v3.py

check-corrected-targeted-review:
	$(PYTHON) scripts/build_planner_behavior_review_v3.py --check

refresh-corrected-targeted-review-routes:
	PYTHONPATH=src $(PYTHON) scripts/refresh_planner_behavior_routes.py --write
	$(MAKE) generate-corrected-targeted-review

check-live-corrected-targeted-review-routes:
	PYTHONPATH=src $(PYTHON) scripts/refresh_planner_behavior_routes.py

preflight-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_behavior_review.py --preflight-only

run-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_behavior_review.py

publish-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_behavior_review.py

promote-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_behavior_review.py --promote-approved

preflight-corrected-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_behavior_review.py --config experiments/planner-behavior-review-v3.json --preflight-only

run-corrected-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_behavior_review.py --config experiments/planner-behavior-review-v3.json

publish-corrected-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_behavior_review.py --config experiments/planner-behavior-review-v3.json

promote-corrected-targeted-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_behavior_review.py --config experiments/planner-behavior-review-v3.json --promote-approved

finalize-targeted-corpus:
	PYTHONPATH=src $(PYTHON) scripts/finalize_planner_behavior_corpus.py

check-targeted-finalized:
	PYTHONPATH=src $(PYTHON) scripts/finalize_planner_behavior_corpus.py --check-if-present

generate-qlora-v2-plan:
	$(PYTHON) scripts/build_planner_qwen38_qlora_v2.py

check-qlora-v2-plan:
	$(PYTHON) scripts/build_planner_qwen38_qlora_v2.py --check

preflight-qlora-v2-plan:
	PYTHONPATH=src $(PYTHON) scripts/train_planner_smoke.py --config experiments/planner-qwen38-qlora-v2.json --plan-check-only

preflight-qlora-v2:
	PYTHONPATH=src $(PYTHON) scripts/train_planner_smoke.py --config experiments/planner-qwen38-qlora-v2.json --preflight-only

verify-qlora-v2-artifact:
	$(PYTHON) scripts/verify_planner_qwen38_qlora_v2_artifact.py

generate-review:
	$(PYTHON) scripts/render_review_packet.py

check-review:
	$(PYTHON) scripts/render_review_packet.py --check

check-finalized:
	$(PYTHON) scripts/finalize_planner_smoke.py --check-if-present

finalize-corpus:
	$(PYTHON) scripts/finalize_planner_smoke.py

preflight-model-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_model_review.py --preflight-only

run-model-review:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_model_review.py

publish-model-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_model_review.py

promote-model-review:
	PYTHONPATH=src $(PYTHON) scripts/publish_planner_model_review.py --promote-approved

lock-qwen38-a40:
	@test "$$($(UV) --version | awk '{print $$2}')" = "$(UV_VERSION)" || { echo "uv $(UV_VERSION) is required" >&2; exit 1; }
	$(UV) pip compile environments/qwen38-a40-v1.requirements.in \
		--overrides environments/qwen38-a40-v1.overrides.txt \
		--python-platform x86_64-manylinux_2_28 --python-version 3.12 \
		--torch-backend cu128 --generate-hashes --only-binary=:all: --emit-index-url \
		--custom-compile-command 'make lock-qwen38-a40' \
		--output-file environments/qwen38-a40-v1.requirements.lock

check-environment:
	$(PYTHON) scripts/verify_environment.py

sync-qwen38-a40:
	@test "$$($(UV) --version | awk '{print $$2}')" = "$(UV_VERSION)" || { echo "uv $(UV_VERSION) is required" >&2; exit 1; }
	$(UV) pip sync --torch-backend cu128 --require-hashes environments/qwen38-a40-v1.requirements.lock

validate-drafts:
	PYTHONPATH=src $(PYTHON) -m loomarr_models.cli validate --allow-pending corpus/planner-smoke-v1/drafts.jsonl

validate-corpus:
	PYTHONPATH=src $(PYTHON) -m loomarr_models.cli validate corpus/planner-smoke-v1/traces.jsonl

preflight-qwen38:
	PYTHONPATH=src $(PYTHON) scripts/train_planner_smoke.py --preflight-only

preflight-planner-eval:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_adapter_eval.py --preflight-only

run-planner-eval:
	PYTHONPATH=src $(PYTHON) scripts/run_planner_adapter_eval.py

replay-planner-eval:
	PYTHONPATH=src $(PYTHON) scripts/replay_planner_adapter_eval.py
