#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_baseline import SCORING
from loomarr_models.current_baseline_v3 import COMPARISON
from loomarr_models.local_baseline import AUTHORITY, BINDINGS, EXECUTION, EXPERIMENT_ID, MODEL


OUTPUT = Path(f"experiments/{EXPERIMENT_ID}.json")


def content() -> bytes:
    value = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "planned-local-zero-spend",
        "purpose": (
            "Re-establish the current-contract stock baseline on the local Strix Halo host with bf16 "
            "weights before local LoRA training. Scores are compared with, not substituted for, the "
            "published A40 bnb-4bit v3 baseline."
        ),
        "bindings": {
            name: {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
            for name, path in sorted(BINDINGS.items())
        },
        "model": MODEL,
        "execution": EXECUTION,
        "comparison": COMPARISON,
        "scoring": SCORING,
        "authority": AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local zero-spend stock baseline plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = content()
    target = ROOT / OUTPUT
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            raise SystemExit(f"generated artifact drift: {OUTPUT}")
        return
    target.write_bytes(expected)


if __name__ == "__main__":
    main()
