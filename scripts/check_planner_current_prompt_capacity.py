#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_contract import read_jsonl
from loomarr_models.prompt_capacity import measure_prompt_capacity


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure every current-baseline prompt stage")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or "bindings" not in config or "comparison" not in config:
        parser.error("prompt-capacity config is not a planner baseline object")
    contract = json.loads(
        (ROOT / config["bindings"]["contract"]["path"]).read_text(encoding="utf-8")
    )
    cases = read_jsonl(ROOT / config["bindings"]["cases"]["path"])

    from transformers import AutoProcessor

    tokenizer = AutoProcessor.from_pretrained(
        config["model"]["repository"], revision=config["model"]["revision"]
    )
    report = measure_prompt_capacity(tokenizer, contract, cases, config["comparison"])
    nested_tokenizer = getattr(tokenizer, "tokenizer", None)
    report["experimentId"] = config["experimentId"]
    report["inputs"] = {
        "config": {
            "path": str(config_path.relative_to(ROOT)),
            "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        },
        "contract": config["bindings"]["contract"],
        "cases": config["bindings"]["cases"],
        "environment": config["bindings"]["environment"],
        "model": config["model"],
    }
    report["processor"] = {
        "class": f"{type(tokenizer).__module__}.{type(tokenizer).__qualname__}",
        "tokenizerClass": (
            f"{type(nested_tokenizer).__module__}.{type(nested_tokenizer).__qualname__}"
            if nested_tokenizer is not None
            else None
        ),
        "loadedCommit": _loaded_commit(tokenizer, nested_tokenizer),
    }
    report["runtime"] = {
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "transformers": importlib.metadata.version("transformers"),
        "tokenizers": importlib.metadata.version("tokenizers"),
    }
    report["sourceCommit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.write_text(encoded, encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


def _loaded_commit(*objects: object) -> str | None:
    for value in objects:
        if value is None:
            continue
        direct = getattr(value, "_commit_hash", None)
        if isinstance(direct, str):
            return direct
        init = getattr(value, "init_kwargs", None)
        if isinstance(init, dict) and isinstance(init.get("_commit_hash"), str):
            return init["_commit_hash"]
    return None


if __name__ == "__main__":
    main()
