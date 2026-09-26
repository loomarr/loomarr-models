#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_review import build_promotion_artifacts, load_review_state
from loomarr_models.validator import ValidationError


PLAN_PATH = ROOT / "reviews/planner-current-v1/review-plan.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote completely approved current-contract training drafts"
    )
    args = parser.parse_args()
    try:
        state = load_review_state(ROOT, PLAN_PATH, require_complete=True)
        artifacts = build_promotion_artifacts(state)
        existing = [relative for relative in artifacts if (ROOT / relative).exists()]
        if existing:
            raise ValidationError(
                "refusing to overwrite immutable current review output: "
                + ", ".join(path.as_posix() for path in existing)
            )
        for relative, content in artifacts.items():
            target = ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    except (OSError, ValidationError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
