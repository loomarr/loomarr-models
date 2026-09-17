#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_baseline import load_config
from loomarr_models.current_contract import read_jsonl
from loomarr_models.prompt_capacity import measure_prompt_capacity


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure every current-baseline prompt stage")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = load_config(config_path)
    contract = json.loads(
        (ROOT / config["bindings"]["contract"]["path"]).read_text(encoding="utf-8")
    )
    cases = read_jsonl(ROOT / config["bindings"]["cases"]["path"])

    from transformers import AutoProcessor

    tokenizer = AutoProcessor.from_pretrained(
        config["model"]["repository"], revision=config["model"]["revision"]
    )
    report = measure_prompt_capacity(tokenizer, contract, cases, config["comparison"])
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.write_text(encoded, encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
