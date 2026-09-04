#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.local_screen import AUTHORITY, COMPARISON, EXECUTION, SCREEN_ID, SCORING


OUTPUT = ROOT / "experiments/planner-v4-local-screen-v1.json"
SNAPSHOT = ROOT / "reviews/planner-v4-local-screen/ollama-snapshot.json"
EXPOSURE = ROOT / "reviews/planner-v4-local-screen/development-exposure.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path: Path, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
    }
    if count is not None:
        value["count"] = count
    return value


def build_config() -> dict[str, Any]:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    exposure = json.loads(EXPOSURE.read_text(encoding="utf-8"))
    status = (
        "ready-for-local-screen"
        if exposure == {
            "schemaVersion": 1,
            "corpusId": "planner-development-v4",
            "status": "local-screen-reserved",
            "reservation": {
                "screenId": SCREEN_ID,
                "candidateIds": ["qwen38-27b-mlx-nvfp4", "gemma4-12b-q4-k-m"],
                "caseCount": 120,
                "externalCostUsd": "0",
                "modelRunsPerCandidate": 1,
            },
            "exposures": [],
        }
        else "complete-local-screen"
    )
    return {
        "schemaVersion": 1,
        "screenId": SCREEN_ID,
        "issue": "https://github.com/loomarr/loomarr-models/issues/22",
        "status": status,
        "externalCostUsd": "0",
        "bindings": {
            "cases": binding(ROOT / "evaluation/planner-development-v4/cases.jsonl", count=120),
            "casesManifest": binding(ROOT / "evaluation/planner-development-v4/manifest.json"),
            "contract": binding(ROOT / "contracts/planner-contract-v4.json"),
            "holdoutDenylist": binding(ROOT / "contracts/holdout-denylist-v1.json"),
            "developmentExposure": binding(EXPOSURE),
            "ollamaSnapshot": binding(SNAPSHOT),
            "v4Generator": binding(ROOT / "scripts/build_planner_v4_delta.py"),
            "v4Validator": binding(ROOT / "src/loomarr_models/planner_v4.py"),
            "scorer": binding(ROOT / "src/loomarr_models/eval_runner.py"),
            "preflight": binding(ROOT / "src/loomarr_models/local_screen.py"),
            "runtime": binding(ROOT / "src/loomarr_models/local_screen_runtime.py"),
            "planGenerator": binding(Path(__file__)),
            "runner": binding(ROOT / "scripts/run_planner_v4_local_screen.py"),
            "publisher": binding(ROOT / "scripts/publish_planner_v4_local_screen.py"),
        },
        "candidates": snapshot["candidates"],
        "execution": EXECUTION,
        "comparison": COMPARISON,
        "scoring": SCORING,
        "authority": AUTHORITY,
    }


def content() -> bytes:
    return json.dumps(build_config(), indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the planner v4 local screen plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = content()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != expected:
            raise SystemExit(f"stale local screen plan: {OUTPUT.relative_to(ROOT)}")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(expected)


if __name__ == "__main__":
    main()
