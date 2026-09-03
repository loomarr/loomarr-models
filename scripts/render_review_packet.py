#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.review import derive_review, load_review_decisions


INPUT = ROOT / "corpus/planner-smoke-v1/drafts.jsonl"
OUTPUT = ROOT / "reviews/planner-smoke-v1.md"
DECISIONS = ROOT / "reviews/planner-smoke-v1.jsonl"


def render() -> bytes:
    traces = [json.loads(line) for line in INPUT.read_text(encoding="utf-8").splitlines() if line]
    decisions = load_review_decisions(DECISIONS, [trace["traceId"] for trace in traces])
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

        decision = decisions[trace["traceId"]]
        review = derive_review(decision)
        primary = decision["primary"]
        secondary = decision["secondary"]
        secondary_text = (
            f"**{secondary['verdict']}** by `{secondary['reviewer'] or '—'}`"
            if secondary["required"]
            else "not required"
        )
        lines.extend(
            [
                f"## {trace['traceId']}",
                "",
                f"- Axis: `{trace['axes'][0]}`",
                f"- Intent: {user}",
                f"- Contract: `{trace['contract']['systemPromptSha256']}` / `{trace['contract']['toolSchemaSha256']}`",
                f"- Flow: {' → '.join(interactions)}",
                f"- Primary review: **{primary['verdict']}** by `{primary['reviewer'] or '—'}`; notes: {primary['notes'] or '—'}",
                f"- Secondary review: {secondary_text}; notes: {secondary['notes'] or '—'}",
                f"- Derived artifact status: **{review.status}**",
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
