#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


PROMPT_VERSION = "suggester-prompt-v15"
PROMPT_SHA256 = "e9ff95ae37efd0fc1085def7e6a3a2a653640fae6a78ebffbaa02b3da6a55e52"
TOOL_SCHEMA_VERSION = "catalog-search-v9"
TOOL_SCHEMA_SHA256 = "595a6ec8416fc9b0cf438cc86897006d69f5f2fcf6de238c0e310e8de8273f86"
MESSAGE_TEMPLATE_VERSION = "planner-tool-result-finalization-v3"
SOURCE_VERSION = "reference-source-v6"
SOURCE_PATHS = (
    "internal/suggest/diagnostic.go",
    "internal/suggest/intent_coordinates.go",
    "internal/suggest/parse.go",
    "internal/suggest/prompt.go",
    "internal/suggest/tools.go",
)


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
            "to discover genre matches, or `keywords` to discover holidays, motifs, franchises, and topics. "
            "For a named collection, set mode=collection with media_type and 1-8 exact constituent titles; no discovery filters are allowed. "
            "Discovery may also use explicitly requested country, original-language, runtime, vote, movie cast/creator, and TV network filters. "
            "Returns real external ids, genres, a short overview, available language/country/runtime/vote/keyword/network/person evidence, "
            "and an inLibrary flag. Missing fields mean unknown. This is the ONLY way to find titles."
        ),
        "Parameters": {
            "type": "object",
            "required": ["dateMeaning"],
            "properties": {
                "dateMeaning": date_meaning_schema(),
                "mode": {
                    "type": "string",
                    "enum": ["collection"],
                    "description": "collection requires media_type and titles; omit for ordinary title or discovery search",
                },
                "titles": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {
                        "oneOf": [
                            {"type": "string", "minLength": 1, "maxLength": 120},
                            {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                                    "year": {"type": "integer", "minimum": 1870, "maximum": 2200},
                                },
                                "required": ["name"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                    "description": "exact collection members as title strings or {name,year} anchors",
                },
                "query": {"type": "string", "description": "title keywords (for a known title)"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "TMDB thematic keywords, e.g. [\"Christmas\"] or [\"heist\"]"},
                "genres": {"type": "array", "items": {"type": "string"}, "description": "genre names to discover by, e.g. [\"Action\",\"Science Fiction\"]"},
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
            "allOf": [
                {
                    "if": {"properties": {"mode": {"const": "collection"}}, "required": ["mode"]},
                    "then": {"required": ["media_type", "titles"]},
                }
            ],
        },
    }


def date_meaning_schema() -> dict:
    return {
        "type": "object",
        "required": ["kind", "anchors", "axes"],
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["none", "constraints", "ambiguous"]},
            "anchors": {"type": "array", "items": date_anchor_schema()},
            "axes": {"type": "array", "items": date_axis_schema()},
        },
    }


def date_anchor_schema() -> dict:
    return {
        "type": "object",
        "required": ["field", "start", "end"],
        "properties": {
            "field": {
                "type": "string",
                "enum": ["description", "era", "refineText", "mustInclude", "mustExclude"],
            },
            "index": {"type": "integer", "minimum": 0},
            "start": {"type": "integer", "minimum": 0},
            "end": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
    }


def date_axis_schema() -> dict:
    return {
        "type": "object",
        "required": ["kind", "combine", "intervals"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["movie_release", "series_premiere", "series_airing"],
            },
            "combine": {"type": "string", "enum": ["any", "all"]},
            "intervals": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": date_interval_schema(),
            },
        },
        "additionalProperties": False,
    }


def date_interval_schema() -> dict:
    return {
        "type": "object",
        "required": ["anchor", "start", "end"],
        "properties": {
            "anchor": {"type": "integer", "minimum": 0},
            "start": {"type": "integer", "minimum": 1900, "maximum": 2099},
            "end": {"type": "integer", "minimum": 1900, "maximum": 2099},
        },
        "additionalProperties": False,
    }


def git_bytes(repository: Path, revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), "show", f"{revision}:{path}"],
        check=True,
        capture_output=True,
    ).stdout


def source_bindings(repository: Path, revision: str) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": hashlib.sha256(git_bytes(repository, revision, path)).hexdigest()}
        for path in SOURCE_PATHS
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("loomarr", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()

    revision = subprocess.run(
        ["git", "-C", str(args.loomarr), "rev-parse", f"{args.revision}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = git_bytes(args.loomarr, revision, "internal/suggest/prompt.go").decode()
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

    contract = {
        "schemaVersion": 2,
        "contractId": "loomarr-planner-contract-v5",
        "sourceRepository": "https://github.com/loomarr/loomarr",
        "sourceRevision": revision,
        "sourceVersion": SOURCE_VERSION,
        "sourceBindings": source_bindings(args.loomarr, revision),
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
