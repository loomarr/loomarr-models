#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.candidate_screen import BINDINGS, CANDIDATES, EXPERIMENT_ID, RUNTIME, SCREEN_GATES, TRIALS
from loomarr_models.flash_next_screen import AUTHORITY, DECODING


OUTPUT = Path(f"experiments/{EXPERIMENT_ID}.json")


def content() -> bytes:
    value = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "issue": "https://github.com/loomarr/loomarr-models/issues/35",
        "status": "planned-local-zero-spend",
        "purpose": (
            "Screen stock planner candidates against the served Flash-Next incumbent on the v2 gate "
            "and training-split screen, feeding loomarr/loomarr#831."
        ),
        "bindings": {
            name: {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
            for name, path in sorted(BINDINGS.items())
        },
        "candidates": CANDIDATES,
        "runtime": RUNTIME,
        "decoding": DECODING,
        "gates": list(SCREEN_GATES),
        "trials": TRIALS,
        "authority": AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the stock planner candidate screen plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected, target = content(), ROOT / OUTPUT
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            raise SystemExit(f"generated artifact drift: {OUTPUT}")
        return
    target.write_bytes(expected)


if __name__ == "__main__":
    main()
