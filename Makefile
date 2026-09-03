.PHONY: check compile test init-review generate-drafts check-generated generate-review check-review check-finalized finalize-corpus lock-qwen38-a40 check-environment sync-qwen38-a40 validate-drafts validate-corpus preflight-qwen38

PYTHON ?= python3
UV ?= uv
UV_VERSION := 0.12.9

check: compile test check-generated check-review check-finalized check-environment validate-drafts

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

generate-review:
	$(PYTHON) scripts/render_review_packet.py

check-review:
	$(PYTHON) scripts/render_review_packet.py --check

check-finalized:
	$(PYTHON) scripts/finalize_planner_smoke.py --check-if-present

finalize-corpus:
	$(PYTHON) scripts/finalize_planner_smoke.py

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
