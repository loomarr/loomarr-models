.PHONY: check test init-review generate-drafts check-generated generate-review check-review validate-drafts validate-corpus

PYTHON ?= python3

check: test check-generated check-review validate-drafts

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

validate-drafts:
	PYTHONPATH=src $(PYTHON) -m loomarr_models.cli validate --allow-pending corpus/planner-smoke-v1/drafts.jsonl

validate-corpus:
	PYTHONPATH=src $(PYTHON) -m loomarr_models.cli validate corpus/planner-smoke-v1/traces.jsonl
