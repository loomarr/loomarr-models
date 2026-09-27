#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.flash_next_screen import AUTHORITY, DECODING, ENDPOINT, GATES, VARIANTS, bindings, experiment_id, scoring


def output(gate: str) -> Path:
    return Path(f"experiments/{experiment_id(gate)}.json")


def content(gate: str) -> bytes:
    value = {
        "schemaVersion": 1,
        "experimentId": experiment_id(gate),
        "gate": gate,
        "status": "planned-local-zero-spend",
        "purpose": (
            "Screen the served Flash-Next model, which Loomarr uses for every function, on the "
            "current-contract gate before choosing a training target."
        ),
        "bindings": {
            name: {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
            for name, path in sorted(bindings(gate).items())
        },
        "endpoint": ENDPOINT,
        "decoding": DECODING,
        "variants": VARIANTS,
        "scoring": scoring(gate),
        "authority": AUTHORITY,
    }
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Flash-Next screen plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for gate in GATES:
        expected, target = content(gate), ROOT / output(gate)
        if args.check:
            if not target.is_file() or target.read_bytes() != expected:
                raise SystemExit(f"generated artifact drift: {output(gate)}")
            continue
        target.write_bytes(expected)


if __name__ == "__main__":
    main()
