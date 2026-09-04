#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


PROMPT_VERSION = "suggester-prompt-v4"
PROMPT_SHA256 = "3666d0f134076eb0d294d1b962e1b52194edfaa073677d38c0e9590c1d28dd13"
TOOL_SCHEMA_VERSION = "catalog-search-v4"
TOOL_SCHEMA_SHA256 = "876af81bcb942b55c5a2f3df2bafa540edaa7124b9d6a01e90505fcd46d8548e"
MESSAGE_TEMPLATE_VERSION = "planner-tool-result-finalization-v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def go_tool_schema_bytes(tools: list[dict]) -> bytes:
    # encoding/json preserves Go struct field order while sorting map keys.
    tool = tools[0]
    return (
        "[{\"Name\":"
        + json.dumps(tool["Name"], ensure_ascii=False)
        + ",\"Description\":"
        + json.dumps(tool["Description"], ensure_ascii=False)
        + ",\"Parameters\":"
        + json.dumps(tool["Parameters"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "}]"
    ).encode()


def catalog_tool() -> dict:
    return {
        "Name": "catalog_search",
        "Description": (
            "Find real titles from the library + TMDB. Provide `query` to search by title, `genres` "
            "to discover genre/era matches, or `keywords` to discover holidays, motifs, franchises, and topics. "
            "Discovery may also use explicitly requested country, original-language, runtime, vote, movie cast/creator, and TV network filters. "
            "Returns real external ids, genres, a short overview, available language/country/runtime/vote/keyword/network/person evidence, "
            "and an inLibrary flag. Missing fields mean unknown. This is the ONLY way to find titles."
        ),
        "Parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "title keywords (for a known title)"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "TMDB thematic keywords, e.g. [\"Christmas\"] or [\"heist\"]"},
                "genres": {"type": "array", "items": {"type": "string"}, "description": "genre names to discover by, e.g. [\"Action\",\"Science Fiction\"]"},
                "era": {"type": "string", "description": "decade or year range for discovery, e.g. \"1990s\" or \"1985-1995\""},
                "media_type": {"type": "string", "enum": ["movie", "series"]},
                "original_language": {"type": "string", "description": "explicit ISO 639-1 original-language code, e.g. \"ja\""},
                "origin_country": {"type": "string", "description": "explicit ISO 3166-1 origin-country code, e.g. \"GB\""},
                "runtime_min": {"type": "integer", "minimum": 1, "maximum": 1440},
                "runtime_max": {"type": "integer", "minimum": 1, "maximum": 1440},
                "vote_average_min": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
                "vote_count_min": {"type": "integer", "minimum": 1, "maximum": 100000000},
                "network": {
                    "type": "string",
                    "maxLength": 100,
                    "description": "exact TV network name; requires media_type=series",
                },
                "cast": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {"type": "string", "maxLength": 100},
                    "description": "exact cast names; requires media_type=movie",
                },
                "creators": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {"type": "string", "maxLength": 100},
                    "description": "exact director/writer/crew names; requires media_type=movie",
                },
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("loomarr", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    prompt_path = args.loomarr / "internal/suggest/prompt.go"
    source = prompt_path.read_text(encoding="utf-8")
    match = re.search(r"const systemPrompt = `(?P<prompt>.*?)`\n", source, re.DOTALL)
    if match is None:
        raise SystemExit("production systemPrompt raw string was not found")
    prompt = match.group("prompt")
    prompt_digest = hashlib.sha256(prompt.encode()).hexdigest()
    if prompt_digest != PROMPT_SHA256:
        raise SystemExit(f"prompt drift: got {prompt_digest}, want {PROMPT_SHA256}")

    tool = catalog_tool()
    tool_digest = hashlib.sha256(go_tool_schema_bytes([tool])).hexdigest()
    if tool_digest != TOOL_SCHEMA_SHA256:
        raise SystemExit(f"tool schema drift: got {tool_digest}, want {TOOL_SCHEMA_SHA256}")

    revision = subprocess.run(
        ["git", "-C", str(args.loomarr), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    contract = {
        "schemaVersion": 1,
        "contractId": "loomarr-planner-contract-v4",
        "sourceRepository": "https://github.com/loomarr/loomarr",
        "sourceRevision": revision,
        "promptVersion": PROMPT_VERSION,
        "systemPromptSha256": PROMPT_SHA256,
        "systemPrompt": prompt,
        "toolSchemaVersion": TOOL_SCHEMA_VERSION,
        "toolSchemaSha256": TOOL_SCHEMA_SHA256,
        "tools": [tool],
        "messageTemplateVersion": MESSAGE_TEMPLATE_VERSION,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
