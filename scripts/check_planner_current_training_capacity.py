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

from loomarr_models.current_training import EXPERIMENT_ID, MODEL
from loomarr_models.training_data import to_training_rows


REPORT = ROOT / "reviews/planner-current-qwen38-qlora-v1/training-capacity-report.json"
CORPUS = ROOT / "corpus/planner-current-v1/traces.jsonl"
PACKAGES = {"jinja2": "3.1.6", "markupsafe": "3.0.3", "tokenizers": "0.22.2"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure the current QLoRA rendered-token capacity")
    parser.add_argument("--tokenizer-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check and args.tokenizer_dir is None:
        validate_committed_report()
        return
    if args.tokenizer_dir is None:
        parser.error("--tokenizer-dir is required when measuring")
    try:
        measured = measure(args.tokenizer_dir)
    except (ImportError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.check:
        expected = json.loads(REPORT.read_text(encoding="utf-8"))
        if measured != expected:
            parser.error("measured current QLoRA capacity differs from the committed report")
    else:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"maximumTokens": max(row["tokens"] for row in measured["measurements"]), "records": 24}, sort_keys=True))


def validate_committed_report() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    traces = _jsonl(CORPUS)
    if (
        report.get("schemaVersion") != 1
        or report.get("experimentId") != EXPERIMENT_ID
        or report.get("status") != "passed"
        or report.get("corpus") != {
            "path": str(CORPUS.relative_to(ROOT)),
            "records": len(traces),
            "sha256": _sha(CORPUS),
        }
        or report.get("model") != {"repository": MODEL["repository"], "revision": MODEL["revision"]}
        or report.get("environmentPackages") != PACKAGES
        or [row.get("traceId") for row in report.get("measurements", [])]
        != [trace["traceId"] for trace in traces]
        or max(row.get("tokens", 0) for row in report["measurements"]) != 5416
        or any(not 0 < row.get("tokens", 0) <= 8192 for row in report["measurements"])
    ):
        raise SystemExit("committed current QLoRA capacity report drifted")


def measure(tokenizer_dir: Path) -> dict[str, Any]:
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    from tokenizers import Tokenizer

    tokenizer_dir = tokenizer_dir.resolve(strict=True)
    files = {
        name: tokenizer_dir / name
        for name in ("chat_template.jinja", "tokenizer.json", "tokenizer_config.json")
    }
    if any(not path.is_file() for path in files.values()):
        raise ValueError("tokenizer directory lacks the exact three required files")
    traces = _jsonl(CORPUS)
    rows = to_training_rows(traces)
    environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    # Transformers preserves mapping insertion order in its chat-template
    # ``tojson`` filter. Jinja defaults to sorting keys, which changes the
    # rendered-byte identity even when token counts remain identical.
    environment.policies["json.dumps_kwargs"] = {"ensure_ascii": False}

    def raise_exception(message: str) -> None:
        raise ValueError(message)

    environment.globals["raise_exception"] = raise_exception
    template = environment.from_string(files["chat_template.jinja"].read_text(encoding="utf-8"))
    tokenizer = Tokenizer.from_file(str(files["tokenizer.json"]))
    measurements: list[dict[str, Any]] = []
    rendered: list[str] = []
    for row in rows:
        text = template.render(
            messages=row["conversations"],
            tools=row["tools"],
            add_generation_prompt=False,
            reasoning_effort="low",
            preserve_thinking=True,
            add_vision_id=False,
        )
        rendered.append(text)
        measurements.append(
            {
                "traceId": row["trace_id"],
                "renderedBytes": len(text.encode("utf-8")),
                "tokens": len(tokenizer.encode(text, add_special_tokens=False).ids),
            }
        )
    return {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "passed" if max(row["tokens"] for row in measurements) <= 8192 else "failed",
        "model": {"repository": MODEL["repository"], "revision": MODEL["revision"]},
        "tokenizerFiles": {name: _sha(path) for name, path in files.items()},
        "environmentPackages": PACKAGES,
        "rendering": {
            "addGenerationPrompt": False,
            "reasoningEffort": "low",
            "preserveThinking": True,
            "truncation": False,
        },
        "corpus": {
            "path": str(CORPUS.relative_to(ROOT)),
            "sha256": _sha(CORPUS),
            "records": len(traces),
        },
        "measurements": measurements,
        "renderedTrainingSha256": hashlib.sha256(
            b"".join(text.encode("utf-8") + b"\n" for text in rendered)
        ).hexdigest(),
    }


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
