#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.evaluation import FAMILIES, canonical, validate_development_corpus
from loomarr_models.validator import load_contract, load_denylist, load_jsonl


CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
TRAINING_PATH = ROOT / "corpus/planner-smoke-v1/traces.jsonl"
OUT_PATH = ROOT / "evaluation/planner-development-v1/cases.jsonl"
MANIFEST_PATH = ROOT / "evaluation/planner-development-v1/manifest.json"
GENERATOR_ID = "planner-development-eval-generator-v1"
FIXTURE_ID = "planner-development-catalog-v1"

ADJECTIVES = ("Aurora", "Birch", "Copper", "Meadow", "Quartz")
NOUNS = ("Crossing", "Lantern", "Meridian", "Orchard", "Relay")


def candidate(
    number: int,
    *,
    media_type: str = "movie",
    genre: str = "Adventure",
    suffix: str = "",
) -> dict[str, Any]:
    adjective = ADJECTIVES[number % len(ADJECTIVES)]
    noun = NOUNS[(number // len(ADJECTIVES)) % len(NOUNS)]
    return {
        "mediaType": media_type,
        "tmdbId": 910000 + number,
        "name": f"{adjective} {noun} {number:02d}{suffix}",
        "year": 1970 + ((number - 1) % 50),
        "inLibrary": number % 3 != 1,
        "genres": [genre],
        "overview": f"A wholly synthetic {genre.lower()} fixture story numbered {number}.",
    }


def identity(item: dict[str, Any]) -> dict[str, Any]:
    return {"mediaType": item["mediaType"], "tmdbId": item["tmdbId"]}


def build_case(family: str, variant: int, number: int, contract: dict[str, Any]) -> dict[str, Any]:
    item = candidate(number, media_type="series" if variant % 2 else "movie")
    selected = [identity(item)]
    forbidden: list[dict[str, Any]] = []
    policy: dict[str, Any] = {}
    repair: str | None = None

    if family == "title-search":
        intent = f"Center a synthetic channel on the catalog title {item['name']}."
        script = [{"arguments": {"query": item["name"]}, "result": {"candidates": [item]}}]
    elif family == "genre-discovery":
        genre = ("Science Fiction", "Romance", "Western", "Music", "Crime")[variant]
        era = ("1970s", "1980s", "1990s", "2000s", "2010s")[variant]
        item = candidate(number, media_type=item["mediaType"], genre=genre)
        item["year"] = int(era[:4]) + (4 - variant)
        selected = [identity(item)]
        intent = f"Design a synthetic {era} {genre.lower()} channel from catalog discoveries."
        script = [
            {
                "arguments": {"genres": [genre], "era": era},
                "result": {"candidates": [item]},
            }
        ]
        policy = {
            "genres": {"include": [genre]},
            "era": {"from": int(era[:4]), "to": int(era[:4]) + 9},
        }
    elif family == "keyword-discovery":
        keyword = (
            "lighthouse keepers",
            "desert radios",
            "forgotten maps",
            "winter carnivals",
            "underground rivers",
        )[variant]
        item["overview"] = f"A wholly synthetic fixture story about {keyword}."
        intent = f"Make a synthetic channel about {keyword}, a motif rather than a genre."
        script = [
            {"arguments": {"keywords": [keyword]}, "result": {"candidates": [item]}}
        ]
    elif family == "must-include":
        intent = f"Create a synthetic lineup that must include {item['name']}."
        script = [{"arguments": {"query": item["name"]}, "result": {"candidates": [item]}}]
    elif family == "must-exclude":
        excluded = candidate(
            number + 500,
            media_type=item["mediaType"],
            genre="Horror",
            suffix=" Midnight",
        )
        forbidden = [identity(excluded)]
        intent = f"Make synthetic adventure programming, excluding horror and {excluded['name']}."
        script = [
            {
                "arguments": {"genres": ["Adventure"]},
                "result": {"candidates": [item, excluded]},
            }
        ]
        policy = {"genres": {"include": ["Adventure"], "exclude": ["Horror"]}}
    elif family == "ambiguous-intent":
        mood, genre = (
            ("patient and reflective", "Drama"),
            ("buoyant and playful", "Comedy"),
            ("tense and conspiratorial", "Thriller"),
            ("observant and factual", "Documentary"),
            ("vast and exploratory", "Adventure"),
        )[variant]
        item = candidate(number, media_type=item["mediaType"], genre=genre)
        item["overview"] = f"A wholly synthetic {genre.lower()} fixture with a {mood} tone."
        selected = [identity(item)]
        intent = f"Create something synthetic that feels {mood}; use catalog evidence only."
        script = [{"arguments": {"genres": [genre]}, "result": {"candidates": [item]}}]
        policy = {"genres": {"include": [genre]}}
    elif family == "conflicting-intent":
        item = candidate(number, media_type=item["mediaType"], genre="Horror")
        selected = []
        policy = {"genres": {"include": ["Horror"]}}
        intent = f"Build synthetic horror that both must include and must exclude {item['name']}."
        script = [{"arguments": {"query": item["name"]}, "result": {"candidates": [item]}}]
    elif family == "empty-results":
        token = f"missing-development-emblem-{variant + 1}"
        selected = []
        intent = f"Build a synthetic channel around the absent motif {token}."
        script = [
            {"arguments": {"keywords": [token]}, "result": {"candidates": []}},
            {"arguments": {"query": token}, "result": {"candidates": []}},
        ]
    elif family == "tool-error-recovery":
        intent = f"Build synthetic adventure around {item['name']} despite a catalog timeout."
        script = [
            {
                "arguments": {"query": item["name"]},
                "result": {"candidates": [], "error": "synthetic development timeout"},
            },
            {
                "arguments": {"genres": ["Adventure"]},
                "result": {"candidates": [item]},
            },
        ]
        policy = {"genres": {"include": ["Adventure"]}}
    elif family == "malformed-final-repair":
        intent = f"Build a synthetic channel around {item['name']} and obey JSON repair feedback."
        script = [{"arguments": {"query": item["name"]}, "result": {"candidates": [item]}}]
        repair = "Return only valid proposal JSON using the already surfaced id."
    else:
        raise ValueError(f"unknown family {family}")

    return {
        "schemaVersion": 1,
        "caseId": f"planner-development-{family}-{variant + 1:02d}",
        "split": "development-eval",
        "axis": family,
        "contract": {
            "promptVersion": contract["promptVersion"],
            "systemPromptSha256": contract["systemPromptSha256"],
            "toolSchemaVersion": contract["toolSchemaVersion"],
            "toolSchemaSha256": contract["toolSchemaSha256"],
            "messageTemplateVersion": contract["messageTemplateVersion"],
            "fixtureId": FIXTURE_ID,
        },
        "intent": intent,
        "script": script,
        "repairPrompt": repair,
        "expectation": {
            "selectedIds": selected,
            "forbiddenIds": forbidden,
            "expectedPolicy": policy,
            "abstain": len(selected) == 0,
            "maxToolCalls": len(script),
        },
        "provenance": {
            "source": "synthetic",
            "generator": GENERATOR_ID,
            "author": "codex:fixture",
        },
    }


def build_outputs() -> tuple[bytes, bytes]:
    contract = load_contract(CONTRACT_PATH)
    identities, digests = load_denylist(DENYLIST_PATH)
    training = load_jsonl(TRAINING_PATH)
    cases = [
        build_case(family, variant, family_index * 5 + variant + 1, contract)
        for family_index, family in enumerate(FAMILIES)
        for variant in range(5)
    ]
    case_bytes = b"".join(canonical(case) + b"\n" for case in cases)
    report = validate_development_corpus(
        cases,
        contract=contract,
        training_traces=training,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-development-v1",
        "status": "frozen-development-only",
        "caseCount": report.cases,
        "familyCounts": report.familyCounts,
        "casesPath": str(OUT_PATH.relative_to(ROOT)),
        "casesSha256": report.sha256,
        "generator": GENERATOR_ID,
        "generatorSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "contractId": contract["contractId"],
        "contractSourceRevision": contract["sourceRevision"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "fixtureId": FIXTURE_ID,
        "trainingCorpusPath": str(TRAINING_PATH.relative_to(ROOT)),
        "trainingCorpusSha256": hashlib.sha256(TRAINING_PATH.read_bytes()).hexdigest(),
        "holdoutDenylistPath": str(DENYLIST_PATH.relative_to(ROOT)),
        "holdoutDenylistSha256": hashlib.sha256(DENYLIST_PATH.read_bytes()).hexdigest(),
        "scoring": {
            "scorerVersion": "planner-development-scorer-v1",
            "qualityMargin": 0.02,
            "weights": {
                "groundedCompletion": 0.20,
                "correctToolOperation": 0.20,
                "schemaValidity": 0.10,
                "policyAccuracy": 0.15,
                "proposalQuality": 0.25,
                "recovery": 0.10,
            },
            "thresholds": {
                "minGroundedCompletionRate": 0.95,
                "minCorrectToolOperationRate": 0.90,
                "minSchemaValidityRate": 0.98,
                "minPolicyAccuracyRate": 0.95,
                "minProposalQualityRate": 0.90,
                "minRecoveryRate": 0.80,
                "maxP95ToolCalls": 3,
            },
        },
    }
    if hashlib.sha256(case_bytes).hexdigest() != report.sha256:
        raise AssertionError("development corpus digest calculation diverged")
    return case_bytes, json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"


def main() -> None:
    check = sys.argv[1:] == ["--check"]
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("usage: build_planner_development_eval.py [--check]")
    cases, manifest = build_outputs()
    if check:
        if not OUT_PATH.exists() or OUT_PATH.read_bytes() != cases:
            raise SystemExit(f"{OUT_PATH.relative_to(ROOT)} is stale; regenerate it")
        if not MANIFEST_PATH.exists() or MANIFEST_PATH.read_bytes() != manifest:
            raise SystemExit(f"{MANIFEST_PATH.relative_to(ROOT)} is stale; regenerate it")
        return
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_bytes(cases)
    MANIFEST_PATH.write_bytes(manifest)


if __name__ == "__main__":
    main()
