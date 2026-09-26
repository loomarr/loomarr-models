#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.eval_experiment import load_eval_experiment, preflight_eval
from loomarr_models.experiment import PreflightError


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed Loomarr planner adapter evaluation")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/planner-adapter-eval-v1.json"),
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        report = preflight_eval(ROOT, config_path)
        if args.preflight_only:
            print(json.dumps(report.as_dict(), sort_keys=True))
            return
        config = load_eval_experiment(config_path)
        _arm_timeout(config["execution"]["maxWallClockSeconds"])
        from loomarr_models.eval_runtime import run_evaluation

        manifest = run_evaluation(ROOT, config_path, report)
    except (PreflightError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    print(json.dumps(manifest, sort_keys=True))


def _arm_timeout(seconds: int) -> None:
    if not hasattr(signal, "SIGALRM"):
        raise PreflightError("live evaluation requires SIGALRM wall-clock enforcement")

    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"evaluation exceeded hard wall-clock limit of {seconds} seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)


if __name__ == "__main__":
    main()
