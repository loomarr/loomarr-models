#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.eval_replay import replay_evaluation
from loomarr_models.experiment import PreflightError


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay captured planner generations through the corrected parser and scorer"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/planner-adapter-eval-replay-v1.json"),
    )
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        manifest = replay_evaluation(ROOT, config_path)
    except (PreflightError, ValueError) as exc:
        parser.error(str(exc))
    comparison = manifest["comparison"]
    print(
        json.dumps(
            {
                "runId": manifest["runId"],
                "decision": comparison["decision"],
                "qualityDelta": comparison["qualityDelta"],
                "stockQuality": comparison["stock"]["qualityScore"],
                "adapterQuality": comparison["adapter"]["qualityScore"],
                "failures": comparison["failures"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
