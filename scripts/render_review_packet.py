#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "corpus/planner-smoke-v1/drafts.jsonl"
OUTPUT = ROOT / "reviews/planner-smoke-v1.md"


def render() -> bytes:
    traces = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines() if line]
    lines = [
        "# Planner smoke v1 review packet",
        "",
        "Generated from `corpus/planner-smoke-v1/drafts.jsonl`. The repeated frozen system prompt and tool schema",
        "are intentionally represented by their hashes here; their complete bytes remain in every source trace.",
        "Edit review decisions in `reviews/planner-smoke-v1.jsonl`, not this generated packet.",
        "",
    ]
    for trace in traces:
        messages = trace["messages"]
        user = messages[1]["content"]
        interactions: list[str] = []
        for message in messages[2:]:
            if message["role"] == "assistant" and "toolCalls" in message:
                call = message["toolCalls"][0]
                interactions.append(f"call `{call['name']}` `{json.dumps(call['arguments'], sort_keys=True)}`")
            elif message["role"] == "tool":
                content = message["content"]
                if content.get("error"):
                    interactions.append(f"result error: `{content['error']}`")
                else:
                    names = [candidate["name"] for candidate in content.get("candidates", [])]
                    interactions.append("result candidates: " + (", ".join(f"`{name}`" for name in names) or "none"))
            elif message["role"] == "assistant" and "content" in message:
                try:
                    final = json.loads(message["content"])
                except json.JSONDecodeError:
                    interactions.append(f"malformed assistant turn: `{message['content']}`")
                else:
                    picks = [pick["name"] for pick in final["picks"]]
                    interactions.append("final picks: " + (", ".join(f"`{name}`" for name in picks) or "none (abstain)"))
            elif message["role"] == "user":
                interactions.append(f"repair instruction: {message['content']}")

        review = trace["review"]
        lines.extend(
            [
                f"## {trace['traceId']}",
                "",
                f"- Axis: `{trace['axes'][0]}`",
                f"- Intent: {user}",
                f"- Contract: `{trace['contract']['systemPromptSha256']}` / `{trace['contract']['toolSchemaSha256']}`",
                f"- Flow: {' → '.join(interactions)}",
                f"- Decision: **{review['status']}**; reviewer `{review['reviewer'] or '—'}`; notes: {review['notes'] or '—'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip().encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != expected:
            raise SystemExit(f"{OUTPUT.relative_to(ROOT)} is stale; regenerate it")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(expected)


if __name__ == "__main__":
    main()
