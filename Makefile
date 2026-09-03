.PHONY: check compile test init-review generate-drafts check-generated generate-development-eval check-development-eval init-targeted-review generate-targeted-corpus check-targeted-corpus generate-corrected-targeted-review check-corrected-targeted-review preflight-targeted-review run-targeted-review publish-targeted-review promote-targeted-review preflight-corrected-targeted-review run-corrected-targeted-review publish-corrected-targeted-review promote-corrected-targeted-review finalize-targeted-corpus check-targeted-finalized generate-review check-review check-finalized finalize-corpus preflight-model-review run-model-review publish-model-review promote-model-review lock-qwen38-a40 check-environment sync-qwen38-a40 validate-drafts validate-corpus preflight-qwen38 preflight-planner-eval run-planner-eval replay-planner-eval

PYTHON ?= python3
UV ?= uv
UV_VERSION := 0.12.9

check: compile test check-generated check-development-eval check-targeted-corpus check-corrected-targeted-review check-targeted-finalized check-review check-finalized check-environment validate-drafts

compile:
	$(PYTHON) -m compileall -q scripts src tests

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

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

generate-corrected-targeted-review:
	$(PYTHON) scripts/build_planner_behavior_review_v3.py

check-corrected-targeted-review:
	$(PYTHON) scripts/build_planner_behavior_review_v3.py --check

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
