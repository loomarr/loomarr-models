#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import signal
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.experiment import PreflightError
from loomarr_models.local_baseline import EXECUTION, EXPERIMENT_ID, preflight


CONFIG = Path(f"experiments/{EXPERIMENT_ID}.json")
PUBLISHED = Path(f"runs/{EXPERIMENT_ID}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local zero-spend current-contract stock baseline")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--publish", action="store_true", help="copy a completed run into runs/ for commit")
    args = parser.parse_args()
    try:
        if args.publish:
            print(json.dumps(publish(), sort_keys=True))
            return
        plan = preflight(ROOT, ROOT / CONFIG)
        if args.preflight_only:
            print(json.dumps(plan, sort_keys=True))
            return
        _arm_timeout(EXECUTION["maxWallClockSeconds"])
        from loomarr_models.local_baseline import run_baseline

        manifest = run_baseline(ROOT, ROOT / CONFIG, plan)
    except (PreflightError, ValueError, TimeoutError) as exc:
        parser.error(str(exc))
    finally:
        signal.alarm(0)
    print(json.dumps({"summary": manifest["summary"], "decision": manifest["decision"]}, sort_keys=True))


def publish() -> dict[str, str]:
    source = ROOT / EXECUTION["outputDir"]
    target = ROOT / PUBLISHED
    manifest = json.loads((source / "run-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("experimentId") != EXPERIMENT_ID or manifest.get("status") != "complete":
        raise PreflightError("local baseline run is not complete")
    for artifact in manifest["artifacts"].values():
        if hashlib.sha256((source / artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
            raise PreflightError(f"local baseline {artifact['path']} digest mismatch")
    if target.exists():
        raise PreflightError(f"refusing to overwrite published run: {PUBLISHED}")
    target.mkdir(parents=True)
    for name in ("run-manifest.json", *(a["path"] for a in manifest["artifacts"].values())):
        shutil.copyfile(source / name, target / name)
    return {"published": str(PUBLISHED), "sourceCommit": manifest["preflight"]["sourceCommit"]}


def _arm_timeout(seconds: int) -> None:
    def expired(_signum: int, _frame: object) -> None:
        raise TimeoutError(f"local baseline exceeded {seconds} seconds")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(seconds)


if __name__ == "__main__":
    main()
