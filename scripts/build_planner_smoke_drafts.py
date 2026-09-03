#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import loomarr_models.review as review_contract
from loomarr_models.review import empty_decision, load_review_decisions, trace_review


CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
OUT_PATH = ROOT / "corpus/planner-smoke-v1/drafts.jsonl"
MANIFEST_PATH = ROOT / "corpus/planner-smoke-v1/draft-manifest.json"
REVIEW_PATH = ROOT / "reviews/planner-smoke-v1.jsonl"
FIXTURE_ID = "planner-synthetic-catalog-v1"
GENERATOR_ID = "planner-smoke-draft-generator-v1"

FAMILIES = (
    "title-search",
    "genre-discovery",
    "keyword-discovery",
    "must-include",
    "must-exclude",
    "ambiguous-intent",
    "conflicting-intent",
    "empty-results",
    "tool-error-recovery",
    "malformed-final-repair",
)

ADJECTIVES = ("Amber", "Cobalt", "Juniper", "Lunar", "Velvet")
NOUNS = ("Voyage", "Harbor", "Signal", "Archive", "Parade")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def candidate(number: int, *, media_type: str = "movie", genre: str = "Adventure", suffix: str = "") -> dict:
    adjective = ADJECTIVES[number % len(ADJECTIVES)]
    noun = NOUNS[(number // len(ADJECTIVES)) % len(NOUNS)]
    name = f"{adjective} {noun} {number:02d}{suffix}"
    return {
        "mediaType": media_type,
        "tmdbId": 900000 + number,
        "name": name,
        "year": 1980 + ((number - 1) % 40),
        "inLibrary": number % 3 != 0,
        "genres": [genre],
        "overview": f"A wholly synthetic {genre.lower()} story identified as fixture item {number}.",
    }


def tool_call(call_id: str, arguments: dict[str, Any]) -> dict:
    return {
        "role": "assistant",
        "toolCalls": [{"id": call_id, "name": "catalog_search", "arguments": arguments}],
    }


def tool_result(call_id: str, *, candidates: list[dict] | None = None, error: str | None = None) -> dict:
    content: dict[str, Any] = {"candidates": candidates or []}
    if error is not None:
        content["error"] = error
    return {
        "role": "tool",
        "toolCallId": call_id,
        "name": "catalog_search",
        "content": content,
    }


def final_message(title: str, picks: list[dict], policy: dict | None = None) -> dict:
    selected = [
        {
            "mediaType": item["mediaType"],
            "tmdbId": item["tmdbId"],
            "name": item["name"],
            "rationale": "This synthetic candidate satisfies every stated qualifier.",
            "confidence": 0.92 - index * 0.06,
        }
        for index, item in enumerate(picks)
    ]
    final = {
        "channelName": title,
        "rationale": "A grounded proposal using only synthetic catalog evidence.",
        "picks": selected,
        "policy": policy or {},
    }
    return {"role": "assistant", "content": json.dumps(final, separators=(",", ":"))}


def family_messages(family: str, variant: int, item_number: int) -> tuple[str, list[dict]]:
    item = candidate(item_number, media_type="series" if variant % 2 else "movie")
    allowed = candidate(item_number, media_type=item["mediaType"], genre="Adventure")
    excluded = candidate(item_number + 500, media_type=item["mediaType"], genre="Horror", suffix=" After Dark")
    call_1 = f"call-{item_number}-1"
    call_2 = f"call-{item_number}-2"

    if family == "title-search":
        intent = f"Build a channel around the synthetic title {item['name']}."
        messages = [tool_call(call_1, {"query": item["name"]}), tool_result(call_1, candidates=[item]), final_message(f"{ADJECTIVES[variant]} Spotlight", [item])]
    elif family == "genre-discovery":
        genre = ("Adventure", "Comedy", "Mystery", "Animation", "Documentary")[variant]
        era = ("1980s", "1990s", "2000s", "2010s", "2020s")[variant]
        article = "an" if genre[0].lower() in "aeiou" else "a"
        item = candidate(item_number, media_type=item["mediaType"], genre=genre)
        item["year"] = int(era[:4]) + variant
        intent = f"Build {article} {genre.lower()} channel from the synthetic {era} catalog."
        messages = [tool_call(call_1, {"genres": [genre], "era": era, "media_type": item["mediaType"]}), tool_result(call_1, candidates=[item]), final_message(f"{ADJECTIVES[variant]} {genre}", [item], {"genres": {"include": [genre]}, "era": {"from": int(era[:4]), "to": int(era[:4]) + 9}})]
    elif family == "keyword-discovery":
        keyword = ("clockwork", "paper moons", "hidden gardens", "midnight trains", "glass oceans")[variant]
        intent = f"Build a synthetic channel about {keyword}."
        messages = [tool_call(call_1, {"keywords": [keyword], "media_type": item["mediaType"]}), tool_result(call_1, candidates=[item]), final_message(f"{ADJECTIVES[variant]} Motifs", [item])]
    elif family == "must-include":
        intent = f"Build a varied channel that must include the synthetic title {item['name']}."
        messages = [tool_call(call_1, {"query": item["name"]}), tool_result(call_1, candidates=[item]), final_message(f"{ADJECTIVES[variant]} Essentials", [item])]
    elif family == "must-exclude":
        intent = f"Build synthetic adventure programming but exclude horror and {excluded['name']}."
        messages = [tool_call(call_1, {"genres": ["Adventure"]}), tool_result(call_1, candidates=[allowed, excluded]), final_message(f"{ADJECTIVES[variant]} Adventures", [allowed], {"genres": {"include": ["Adventure"], "exclude": ["Horror"]}})]
    elif family == "ambiguous-intent":
        mood = ("quiet", "bright", "restless", "curious", "windswept")[variant]
        intent = f"Build something synthetic that feels {mood}, without inventing titles."
        messages = [tool_call(call_1, {"keywords": [mood]}), tool_result(call_1, candidates=[item]), final_message(f"{ADJECTIVES[variant]} Moods", [item])]
    elif family == "conflicting-intent":
        intent = f"Build an all-horror synthetic channel that excludes every horror title in fixture group {variant}."
        messages = [tool_call(call_1, {"genres": ["Horror"]}), tool_result(call_1, candidates=[]), tool_call(call_2, {"query": f"synthetic horror group {variant}"}), tool_result(call_2, candidates=[]), final_message(f"{ADJECTIVES[variant]} Abstains", [])]
    elif family == "empty-results":
        token = f"absent-synthetic-motif-{variant}"
        intent = f"Build a channel about the nonexistent synthetic motif {token}."
        messages = [tool_call(call_1, {"keywords": [token]}), tool_result(call_1, candidates=[]), tool_call(call_2, {"query": token}), tool_result(call_2, candidates=[]), final_message(f"{ADJECTIVES[variant]} Empty", [])]
    elif family == "tool-error-recovery":
        intent = f"Build a synthetic {item['genres'][0].lower()} channel and recover from a fixture timeout {variant}."
        messages = [tool_call(call_1, {"genres": item["genres"]}), tool_result(call_1, error="synthetic fixture timeout"), tool_call(call_2, {"genres": item["genres"]}), tool_result(call_2, candidates=[item]), final_message(f"{ADJECTIVES[variant]} Recovery", [item])]
    elif family == "malformed-final-repair":
        intent = f"Build a channel around the synthetic title {item['name']} and repair malformed output."
        messages = [tool_call(call_1, {"query": item["name"]}), tool_result(call_1, candidates=[item]), {"role": "assistant", "content": "{not-json"}, {"role": "user", "content": "Return only valid proposal JSON using the already surfaced id."}, final_message(f"{ADJECTIVES[variant]} Repaired", [item])]
    else:
        raise ValueError(f"unknown family {family}")
    return intent, messages


def expected_trace_ids() -> list[str]:
    return [
        f"planner-smoke-{family}-{variant:02d}"
        for family in FAMILIES
        for variant in range(1, 6)
    ]


def default_review_bytes() -> bytes:
    return b"".join(
        canonical(empty_decision(trace_id)) + b"\n"
        for trace_id in expected_trace_ids()
    )


def load_reviews() -> dict[str, dict]:
    if not REVIEW_PATH.exists():
        raise SystemExit(f"{REVIEW_PATH.relative_to(ROOT)} is missing; run with --init-review once")
    return load_review_decisions(REVIEW_PATH, expected_trace_ids())


def build_traces(contract: dict, reviews: dict[str, dict]) -> list[dict]:
    identity = {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": FIXTURE_ID,
    }
    traces: list[dict] = []
    number = 1
    for family in FAMILIES:
        for variant in range(5):
            intent, body = family_messages(family, variant, number)
            trace_id = f"planner-smoke-{family}-{variant + 1:02d}"
            traces.append(
                {
                    "schemaVersion": 1,
                    "traceId": trace_id,
                    "split": "smoke",
                    "axes": [family],
                    "contract": copy.deepcopy(identity),
                    "tools": copy.deepcopy(contract["tools"]),
                    "messages": [
                        {"role": "system", "content": contract["systemPrompt"]},
                        {"role": "user", "content": intent},
                        *body,
                    ],
                    "review": trace_review(reviews[trace_id]),
                    "provenance": {"source": "synthetic", "generator": GENERATOR_ID, "author": "codex:draft"},
                }
            )
            number += 1
    return traces


def build_outputs() -> tuple[bytes, bytes]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    reviews = load_reviews()
    traces = build_traces(contract, reviews)
    trace_bytes = b"".join(canonical(trace) + b"\n" for trace in traces)
    generator_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-smoke-v1",
        "status": "draft-pending-independent-review",
        "traceCount": len(traces),
        "familyCounts": {family: 5 for family in FAMILIES},
        "tracesPath": str(OUT_PATH.relative_to(ROOT)),
        "tracesSha256": hashlib.sha256(trace_bytes).hexdigest(),
        "generator": GENERATOR_ID,
        "generatorSha256": generator_digest,
        "contractId": contract["contractId"],
        "contractSourceRevision": contract["sourceRevision"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "environmentId": "qwen38-a40-v1",
        "reviewDecisionsPath": str(REVIEW_PATH.relative_to(ROOT)),
        "reviewDecisionsSha256": hashlib.sha256(REVIEW_PATH.read_bytes()).hexdigest(),
        "reviewContract": "planner-smoke-review-decision-v1",
        "reviewValidatorPath": str(Path(review_contract.__file__).relative_to(ROOT)),
        "reviewValidatorSha256": hashlib.sha256(Path(review_contract.__file__).read_bytes()).hexdigest(),
        "review": {
            "approved": sum(trace["review"]["status"] == "approved" for trace in traces),
            "pending": sum(trace["review"]["status"] == "pending" for trace in traces),
            "rejected": sum(trace["review"]["status"] == "rejected" for trace in traces),
        },
    }
    return trace_bytes, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--init-review", action="store_true")
    actions.add_argument("--migrate-pending-review", action="store_true")
    args = parser.parse_args()
    if args.init_review:
        if REVIEW_PATH.exists():
            raise SystemExit(f"{REVIEW_PATH.relative_to(ROOT)} already exists")
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_PATH.write_bytes(default_review_bytes())
        return
    if args.migrate_pending_review:
        legacy = [json.loads(line) for line in REVIEW_PATH.read_text(encoding="utf-8").splitlines() if line]
        flat_pending = [
            {"traceId": trace_id, "status": "pending", "reviewer": "", "reviewedAt": None, "notes": ""}
            for trace_id in expected_trace_ids()
        ]
        structured_pending = len(legacy) == len(expected_trace_ids()) and all(
            isinstance(item, dict)
            and item.get("traceId") == trace_id
            and item.get("primary")
            == {"verdict": "pending", "reviewer": "", "reviewedAt": None, "notes": ""}
            and isinstance(item.get("secondary"), dict)
            and item["secondary"].get("verdict") in {"pending", "not-required"}
            and item["secondary"].get("reviewer") == ""
            and item["secondary"].get("reviewedAt") is None
            and item["secondary"].get("notes") == ""
            for item, trace_id in zip(legacy, expected_trace_ids(), strict=True)
        )
        if legacy != flat_pending and not structured_pending:
            raise SystemExit("refusing migration: review file is not the exact unevidenced legacy pending set")
        REVIEW_PATH.write_bytes(default_review_bytes())
        return
    traces, manifest = build_outputs()
    if args.check:
        if not OUT_PATH.exists() or OUT_PATH.read_bytes() != traces:
            raise SystemExit(f"{OUT_PATH.relative_to(ROOT)} is stale; regenerate it")
        if not MANIFEST_PATH.exists() or MANIFEST_PATH.read_bytes() != manifest:
            raise SystemExit(f"{MANIFEST_PATH.relative_to(ROOT)} is stale; regenerate it")
        return
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(traces)
    MANIFEST_PATH.write_bytes(manifest)


if __name__ == "__main__":
    main()
