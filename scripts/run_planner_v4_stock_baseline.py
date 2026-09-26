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
from loomarr_models.stock_baseline import load_config, preflight


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed Qwen v4 stock baseline")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/planner-v4-qwen-stock-baseline-v1.json"),
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        report = preflight(
            ROOT,
            config_path,
            require_authorized=not args.preflight_only,
        )
        if args.preflight_only:
            print(json.dumps(report.as_dict(), sort_keys=True))
            return
        config = load_config(config_path)
        _arm_timeout(config["execution"]["maxWallClockSeconds"])
        from loomarr_models.stock_runtime import run_baseline

        manifest = run_baseline(ROOT, config_path, report)
    except (PreflightError, ValueError, TimeoutError) as exc:
        parser.error(str(exc))
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
    print(json.dumps(manifest, sort_keys=True))


def _arm_timeout(seconds: int) -> None:
    if not hasattr(signal, "SIGALRM"):
        raise PreflightError("live stock baseline requires SIGALRM wall-clock enforcement")

    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"stock baseline exceeded {seconds} seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)


if __name__ == "__main__":
    main()
