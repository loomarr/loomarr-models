#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_baseline_v3 import preflight
from loomarr_models.experiment import PreflightError


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight the unauthorized current stock v3 plan")
    parser.add_argument("--require-authorized", action="store_true")
    args = parser.parse_args()
    try:
        report = preflight(
            ROOT,
            ROOT / "experiments/planner-current-qwen-stock-baseline-v3.json",
            require_authorized=args.require_authorized,
        )
    except PreflightError as exc:
        parser.error(str(exc))
    print(json.dumps(report.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()
