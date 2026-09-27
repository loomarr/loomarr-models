#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.candidate_screen import CANDIDATES, EXPERIMENT_ID, preflight, run_candidate
from loomarr_models.experiment import PreflightError


CONFIG = Path(f"experiments/{EXPERIMENT_ID}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen one stock planner candidate on the local appliance")
    parser.add_argument("--candidate", choices=sorted(CANDIDATES), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--publish", action="store_true", help="copy a completed candidate into runs/ for commit")
    args = parser.parse_args()
    try:
        if args.publish:
            print(json.dumps(publish(args.candidate), sort_keys=True))
            return
        plan = preflight(ROOT, ROOT / CONFIG)
        if args.preflight_only:
            print(json.dumps(plan, sort_keys=True))
            return
        log = ROOT / ".artifacts" / f"{EXPERIMENT_ID}-{args.candidate}-server.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        manifests = run_candidate(ROOT, plan, args.candidate, log)
    except (PreflightError, ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"candidate": args.candidate, "runs": len(manifests), "hardFailures": [m["summary"]["hardFailureCount"] for m in manifests]}))


def publish(candidate: str) -> dict[str, str]:
    source = ROOT / ".artifacts" / EXPERIMENT_ID / candidate
    target = ROOT / "runs" / EXPERIMENT_ID / candidate
    if target.exists():
        raise PreflightError(f"refusing to overwrite published run: {target.relative_to(ROOT)}")
    for manifest_path in sorted(source.glob("*/t*/run-manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            raise PreflightError(f"{manifest_path.parent} is not complete")
        for artifact in manifest["artifacts"].values():
            if hashlib.sha256((manifest_path.parent / artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
                raise PreflightError(f"{manifest_path.parent / artifact['path']} digest mismatch")
    shutil.copytree(source, target)
    return {"published": str(target.relative_to(ROOT))}


if __name__ == "__main__":
    main()
