#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_training import load_config
from loomarr_models.current_training_v2 import preflight
from loomarr_models.experiment import PreflightError


DEFAULT_CONFIG = Path("experiments/planner-current-qwen38-qlora-v2.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one corrected current-contract QLoRA training")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--plan-check-only", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        if args.preflight_only and args.plan_check_only:
            raise PreflightError("choose either preflight-only or plan-check-only")
        plan = preflight(ROOT, config_path, require_authorized=not args.plan_check_only)
        if args.preflight_only or args.plan_check_only:
            print(json.dumps(plan.as_dict(), sort_keys=True))
            return
        config = load_config(config_path)
        _arm_timeout(config["execution"]["maxWallClockSeconds"])
        from loomarr_models.current_training_runtime import run_training

        manifest = run_training(ROOT, config_path, plan)
    except (PreflightError, TimeoutError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    print(json.dumps(manifest, sort_keys=True))


def _arm_timeout(seconds: int) -> None:
    if not hasattr(signal, "SIGALRM"):
        raise PreflightError("live corrected current QLoRA training requires SIGALRM enforcement")

    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"training exceeded hard wall-clock limit of {seconds} seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)


if __name__ == "__main__":
    main()
