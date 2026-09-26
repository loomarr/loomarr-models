#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from loomarr_models.current_training import load_config
from loomarr_models.current_training_v2 import EXPERIMENT_ID, preflight
from verify_planner_current_qwen38_qlora_v1_artifact import (
    ArtifactVerificationError,
    verify_artifact,
)


DEFAULT_CONFIG = Path("experiments/planner-current-qwen38-qlora-v2.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the corrected current QLoRA adapter")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = load_config(config_path)
    artifact_dir = args.artifact_dir or Path(config["execution"]["outputDir"])
    source_commit = args.expected_source_commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    try:
        report = verify_artifact(
            ROOT,
            config_path,
            artifact_dir,
            source_commit,
            expected_experiment_id=EXPERIMENT_ID,
            preflight_fn=preflight,
        )
    except ArtifactVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
