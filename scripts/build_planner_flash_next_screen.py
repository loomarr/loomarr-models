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
from loomarr_models.flash_next_screen import AUTHORITY, BINDINGS, DECODING, ENDPOINT, EXPERIMENT_ID, VARIANTS


OUTPUT = Path(f"experiments/{EXPERIMENT_ID}.json")


def content() -> bytes:
    value = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "planned-local-zero-spend",
        "purpose": (
            "Screen the served Flash-Next model, which Loomarr uses for every function, on the "
            "current-contract gate before choosing a training target."
        ),
        "bindings": {
            name: {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
            for name, path in sorted(BINDINGS.items())
        },
        "endpoint": ENDPOINT,
        "decoding": DECODING,
        "variants": VARIANTS,
        "scoring": SCORING,
        "authority": AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Flash-Next screen plan")
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
