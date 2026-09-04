#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.experiment import PreflightError
from loomarr_models.local_screen import CANDIDATE_IDS, build_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a zero-cost planner v4 Ollama screen")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/planner-v4-local-screen-v1.json"),
    )
    parser.add_argument("--candidate", choices=CANDIDATE_IDS)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        config, plan, snapshot = build_plan(ROOT, config_path)
        if args.preflight_only:
            print(json.dumps(plan.as_dict(), sort_keys=True))
            return
        if args.candidate is None:
            parser.error("--candidate is required unless --preflight-only is used")
        _arm_timeout(config["execution"]["maxWallClockSecondsPerCandidate"])
        from loomarr_models.local_screen_runtime import run_candidate

        manifest = run_candidate(
            ROOT,
            config_path,
            config,
            plan,
            snapshot,
            args.candidate,
        )
    except (PreflightError, ValueError, TimeoutError) as exc:
        parser.error(str(exc))
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    print(json.dumps(manifest, sort_keys=True))


def _arm_timeout(seconds: int) -> None:
    if not hasattr(signal, "SIGALRM"):
        raise PreflightError("live local screen requires SIGALRM wall-clock enforcement")

    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"candidate exceeded hard wall-clock limit of {seconds} seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)


if __name__ == "__main__":
    main()
