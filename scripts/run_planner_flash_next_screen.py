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

from loomarr_models.experiment import PreflightError
from loomarr_models.flash_next_screen import ENDPOINT, EXPERIMENT_ID, VARIANTS, preflight, read_api_key, run_screen


CONFIG = Path(f"experiments/{EXPERIMENT_ID}.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen served Flash-Next on the current-contract gate")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="default")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--publish", action="store_true", help="copy a completed variant into runs/ for commit")
    args = parser.parse_args()
    try:
        if args.publish:
            print(json.dumps(publish(args.variant), sort_keys=True))
            return
        plan = preflight(ROOT, ROOT / CONFIG)
        if args.preflight_only:
            print(json.dumps(plan, sort_keys=True))
            return
        manifest = run_screen(ROOT, plan, args.variant, read_api_key(Path(ENDPOINT["apiKeyFile"])))
    except (PreflightError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"summary": manifest["summary"], "decision": manifest["decision"]}, sort_keys=True))


def publish(variant: str) -> dict[str, str]:
    source = ROOT / ".artifacts" / EXPERIMENT_ID / variant
    target = ROOT / "runs" / EXPERIMENT_ID / variant
    manifest = json.loads((source / "run-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("variant") != variant:
        raise PreflightError("Flash-Next screen variant is not complete")
    for artifact in manifest["artifacts"].values():
        if hashlib.sha256((source / artifact["path"]).read_bytes()).hexdigest() != artifact["sha256"]:
            raise PreflightError(f"Flash-Next screen {artifact['path']} digest mismatch")
    if target.exists():
        raise PreflightError(f"refusing to overwrite published run: {target.relative_to(ROOT)}")
    target.mkdir(parents=True)
    for name in ("run-manifest.json", *(a["path"] for a in manifest["artifacts"].values())):
        shutil.copyfile(source / name, target / name)
    return {"published": str(target.relative_to(ROOT))}


if __name__ == "__main__":
    main()
