#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_behavior_corpus as foundational
import loomarr_models.planner_v4 as v4_contract
import loomarr_models.v4_review as review_contract
import loomarr_models.validator as corpus_validator
from loomarr_models.evaluation import load_cases
from loomarr_models.planner_v4 import (
    DEVELOPMENT_BEHAVIORS,
    DEVELOPMENT_FIXTURE_ID,
    DEVELOPMENT_GENERATOR_ID,
    DEVELOPMENT_PER_BEHAVIOR,
    ENTITY_BEHAVIORS,
    FOUNDATIONAL_BEHAVIORS,
    TRAINING_FIXTURE_ID,
    TRAINING_GENERATOR_ID,
    TRAINING_PER_BEHAVIOR,
    canonical,
    validate_delta_training,
    validate_development,
    validate_disjoint_splits,
)
from loomarr_models.validator import load_contract, load_denylist, load_jsonl
from loomarr_models.v4_review import empty_decision, load_review_decisions, trace_review


CONTRACT_PATH = ROOT / "contracts/planner-contract-v4.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
REVIEW_PATH = ROOT / "reviews/planner-v4-delta.jsonl"
TRAINING_PATH = ROOT / "corpus/planner-v4-delta/drafts.jsonl"
TRAINING_MANIFEST_PATH = ROOT / "corpus/planner-v4-delta/draft-manifest.json"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-development-v4/cases.jsonl"
DEVELOPMENT_MANIFEST_PATH = ROOT / "evaluation/planner-development-v4/manifest.json"
DISJOINTNESS_PATH = ROOT / "reports/planner-v4-disjointness.json"

PRIOR_SPLITS = {
    "planner-smoke-v1": ROOT / "corpus/planner-smoke-v1/traces.jsonl",
    "planner-development-v1": ROOT / "evaluation/planner-development-v1/cases.jsonl",
    "planner-behavior-v2": ROOT / "corpus/planner-behavior-v2/traces.jsonl",
    "planner-behavior-development-v2": ROOT / "evaluation/planner-behavior-development-v2/cases.jsonl",
}

COUNTRIES = ("US", "CA", "GB", "AU", "NZ", "IE", "FR", "DE", "JP", "MX")


@dataclass(frozen=True)
class Scenario:
    intent: str
    arguments: dict[str, Any]
    candidates: list[dict[str, Any]]
    selected: list[dict[str, Any]]
    forbidden: list[dict[str, Any]]
    channel_name: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return {"mediaType": candidate["mediaType"], "tmdbId": candidate["tmdbId"]}


def contract_identity(contract: dict[str, Any], fixture_id: str) -> dict[str, str]:
    return {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": fixture_id,
    }


def entity_candidate(
    number: int,
    *,
    development: bool,
    media_type: str,
    network: str = "",
    cast: tuple[str, ...] = (),
    creators: tuple[str, ...] = (),
    country: str = "US",
) -> dict[str, Any]:
    base = 950_000 if development else 940_000
    prefix = "Verdant" if development else "Saffron"
    candidate = {
        "mediaType": media_type,
        "tmdbId": base + number,
        "name": f"{prefix} Entity Fixture {number:03d}",
        "year": 1980 + number % 40,
        "inLibrary": number % 3 != 0,
        "genres": ["Drama" if media_type == "series" else "Comedy"],
        "overview": f"A wholly synthetic entity-routing fixture numbered {number}.",
        "originalLanguage": "en",
        "originCountries": [country],
    }
    if network:
        candidate["networks"] = [network]
    if cast:
        candidate["cast"] = list(cast)
    if creators:
        candidate["creators"] = list(creators)
    return candidate


def build_entity_scenario(
    behavior: str,
    variant: int,
    number: int,
    *,
    development: bool,
) -> Scenario:
    slate = "Verdant" if development else "Saffron"
    network = f"{slate} Network {variant + 1}"
    performer = f"{slate} Performer {variant + 1}"
    creator = f"{slate} Creator {variant + 1}"
    country = COUNTRIES[variant]
    forbidden: list[dict[str, Any]] = []

    if behavior == "network-routing":
        item = entity_candidate(number, development=development, media_type="series", network=network)
        intent = f"Build a synthetic TV channel from the exact network {network}."
        arguments = {"media_type": "series", "network": network}
        candidates = [item]
    elif behavior == "cast-routing":
        item = entity_candidate(number, development=development, media_type="movie", cast=(performer,))
        intent = f"Build a synthetic movie channel starring {performer}."
        arguments = {"media_type": "movie", "cast": [performer]}
        candidates = [item]
    elif behavior == "creator-routing":
        item = entity_candidate(number, development=development, media_type="movie", creators=(creator,))
        intent = f"Build a synthetic movie channel directed or written by {creator}."
        arguments = {"media_type": "movie", "creators": [creator]}
        candidates = [item]
    elif behavior == "combined-person-routing":
        item = entity_candidate(
            number,
            development=development,
            media_type="movie",
            cast=(performer,),
            creators=(creator,),
        )
        intent = f"Build synthetic movies starring {performer} and created by {creator}."
        arguments = {"media_type": "movie", "cast": [performer], "creators": [creator]}
        candidates = [item]
    elif behavior == "network-country-routing":
        ambiguous_network = "Union Broadcast"
        item = entity_candidate(
            number,
            development=development,
            media_type="series",
            network=ambiguous_network,
            country=country,
        )
        intent = f"Build synthetic series from the {country} network named {ambiguous_network}."
        arguments = {
            "media_type": "series",
            "network": ambiguous_network,
            "origin_country": country,
        }
        candidates = [item]
    elif behavior == "series-person-evidence-routing":
        item = entity_candidate(
            number,
            development=development,
            media_type="series",
            network=network,
            cast=(performer,),
        )
        distractor = entity_candidate(
            number + 1,
            development=development,
            media_type="series",
            network=network,
            cast=(f"{slate} Other Performer {variant + 1}",),
        )
        intent = f"Build a synthetic series channel from {network} featuring {performer}."
        arguments = {"media_type": "series", "network": network}
        candidates = [item, distractor]
        forbidden = [identity(distractor)]
    else:
        raise ValueError(f"unknown entity behavior {behavior}")
    return Scenario(
        intent=intent,
        arguments=arguments,
        candidates=candidates,
        selected=[identity(item)],
        forbidden=forbidden,
        channel_name=f"{slate} Route {variant + 1}",
    )


def trace_ids() -> list[str]:
    return [
        f"planner-v4-delta-{behavior}-{variant + 1:02d}"
        for behavior in ENTITY_BEHAVIORS
        for variant in range(TRAINING_PER_BEHAVIOR)
    ]


def build_training(
    contract: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for behavior_index, behavior in enumerate(ENTITY_BEHAVIORS):
        for variant in range(TRAINING_PER_BEHAVIOR):
            number = behavior_index * 20 + variant * 2 + 1
            scenario = build_entity_scenario(behavior, variant, number, development=False)
            trace_id = f"planner-v4-delta-{behavior}-{variant + 1:02d}"
            call_id = f"v4-delta-{behavior_index + 1}-{variant + 1}"
            selected = {(item["mediaType"], item["tmdbId"]) for item in scenario.selected}
            picked = [
                candidate
                for candidate in scenario.candidates
                if (candidate["mediaType"], candidate["tmdbId"]) in selected
            ]
            final = {
                "channelName": scenario.channel_name,
                "rationale": "A grounded proposal using exact synthetic entity evidence.",
                "picks": [
                    {
                        "mediaType": item["mediaType"],
                        "tmdbId": item["tmdbId"],
                        "name": item["name"],
                        "rationale": "The synthetic candidate matches the requested entity evidence.",
                        "confidence": 0.91,
                    }
                    for item in picked
                ],
                "policy": {},
            }
            traces.append(
                {
                    "schemaVersion": 1,
                    "traceId": trace_id,
                    "split": "train",
                    "axes": [behavior],
                    "contract": contract_identity(contract, TRAINING_FIXTURE_ID),
                    "tools": copy.deepcopy(contract["tools"]),
                    "messages": [
                        {"role": "system", "content": contract["systemPrompt"]},
                        {"role": "user", "content": scenario.intent},
                        {
                            "role": "assistant",
                            "toolCalls": [
                                {
                                    "id": call_id,
                                    "name": "catalog_search",
                                    "arguments": scenario.arguments,
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "toolCallId": call_id,
                            "name": "catalog_search",
                            "content": {"candidates": scenario.candidates},
                        },
                        {"role": "assistant", "content": json.dumps(final, separators=(",", ":"))},
                    ],
                    "review": trace_review(decisions[trace_id]),
                    "provenance": {
                        "source": "synthetic",
                        "generator": TRAINING_GENERATOR_ID,
                        "author": "codex:draft",
                    },
                }
            )
    return traces


def build_development(contract: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    identity_bundle = contract_identity(contract, DEVELOPMENT_FIXTURE_ID)
    number = 1001
    for behavior in FOUNDATIONAL_BEHAVIORS:
        for variant in range(DEVELOPMENT_PER_BEHAVIOR):
            scenario = foundational.build_scenario(behavior, variant + 60, number, development=True)
            scenario = foundational.Scenario(
                intent=f"{scenario.intent} Use fresh v4 development slate {number}.",
                steps=scenario.steps,
                selected=scenario.selected,
                forbidden=scenario.forbidden,
                policy=scenario.policy,
                title=scenario.title,
                rationale=scenario.rationale,
            )
            cases.append(_development_case(behavior, variant, scenario, identity_bundle))
            number += 1
    for behavior_index, behavior in enumerate(ENTITY_BEHAVIORS):
        for variant in range(DEVELOPMENT_PER_BEHAVIOR):
            entity_number = behavior_index * 20 + variant * 2 + 1
            scenario = build_entity_scenario(behavior, variant, entity_number, development=True)
            adapted = foundational.Scenario(
                intent=scenario.intent,
                steps=[{"arguments": scenario.arguments, "result": {"candidates": scenario.candidates}}],
                selected=scenario.selected,
                forbidden=scenario.forbidden,
                policy={},
                title=scenario.channel_name,
                rationale="A grounded v4 entity-route development fixture.",
            )
            cases.append(_development_case(behavior, variant, adapted, identity_bundle))
    return cases


def _development_case(
    behavior: str,
    variant: int,
    scenario: foundational.Scenario,
    identity_bundle: dict[str, str],
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "caseId": f"planner-v4-development-{behavior}-{variant + 1:02d}",
        "split": "development-eval",
        "axis": behavior,
        "contract": copy.deepcopy(identity_bundle),
        "intent": scenario.intent,
        "script": scenario.steps,
        "repairPrompt": None,
        "expectation": {
            "selectedIds": scenario.selected,
            "forbiddenIds": scenario.forbidden,
            "expectedPolicy": scenario.policy,
            "abstain": not scenario.selected,
            "maxToolCalls": len(scenario.steps),
        },
        "provenance": {
            "source": "synthetic",
            "generator": DEVELOPMENT_GENERATOR_ID,
            "author": "codex:fixture",
        },
    }


def binding(path: Path, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
    if count is not None:
        value["count"] = count
    return value


def build_outputs() -> dict[Path, bytes]:
    contract = load_contract(CONTRACT_PATH)
    identities, digests = load_denylist(DENYLIST_PATH)
    decisions = load_review_decisions(REVIEW_PATH, trace_ids())
    training = build_training(contract, decisions)
    development = build_development(contract)
    training_report = validate_delta_training(
        training,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    development_report = validate_development(
        development,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    prior = {
        name: load_jsonl(path) if "development" not in name else load_cases(path)
        for name, path in PRIOR_SPLITS.items()
    }
    disjoint = validate_disjoint_splits(
        {**prior, "planner-v4-delta": training, "planner-development-v4": development}
    )
    training_bytes = b"".join(canonical(trace) + b"\n" for trace in training)
    development_bytes = b"".join(canonical(case) + b"\n" for case in development)
    generator_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source_bindings = {
        "contract": binding(CONTRACT_PATH),
        "holdoutDenylist": binding(DENYLIST_PATH),
        "reviewDecisions": binding(REVIEW_PATH, count=len(decisions)),
        "foundationalGenerator": binding(Path(foundational.__file__)),
        "v4Validator": binding(Path(v4_contract.__file__)),
        "corpusValidator": binding(Path(corpus_validator.__file__)),
        "reviewValidator": binding(Path(review_contract.__file__)),
        **{name: binding(path) for name, path in PRIOR_SPLITS.items()},
    }
    disjointness = {
        "schemaVersion": 1,
        "reportId": "planner-v4-disjointness",
        "status": "passed",
        "pairwiseComparisons": disjoint.pair_count,
        "splits": disjoint.splits,
        "denylistIdentityCount": len(identities),
        "denylistDigestCount": len(digests),
        "bindings": {
            **source_bindings,
            "planner-v4-delta": {
                "path": str(TRAINING_PATH.relative_to(ROOT)),
                "sha256": training_report.sha256,
                "count": training_report.records,
            },
            "planner-development-v4": {
                "path": str(DEVELOPMENT_PATH.relative_to(ROOT)),
                "sha256": development_report.sha256,
                "count": development_report.records,
            },
        },
    }
    disjointness_bytes = pretty(disjointness)
    review_counts = {
        status: sum(trace["review"]["status"] == status for trace in training)
        for status in ("approved", "pending", "rejected")
    }
    training_manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-v4-delta",
        "status": (
            "reviewed-approved-training-delta"
            if review_counts == {"approved": 60, "pending": 0, "rejected": 0}
            else "draft-pending-independent-review"
        ),
        "traceCount": training_report.records,
        "behaviorCounts": training_report.behavior_counts,
        "tracesPath": str(TRAINING_PATH.relative_to(ROOT)),
        "tracesSha256": training_report.sha256,
        "generator": TRAINING_GENERATOR_ID,
        "generatorSha256": generator_sha,
        "contractId": contract["contractId"],
        "contractSourceRevision": contract["sourceRevision"],
        "fixtureId": TRAINING_FIXTURE_ID,
        "developmentCasesPath": str(DEVELOPMENT_PATH.relative_to(ROOT)),
        "developmentCasesSha256": development_report.sha256,
        "disjointnessReportPath": str(DISJOINTNESS_PATH.relative_to(ROOT)),
        "disjointnessReportSha256": hashlib.sha256(disjointness_bytes).hexdigest(),
        "review": review_counts,
        "bindings": source_bindings,
    }
    development_manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-development-v4",
        "status": "frozen-development-only-no-model-exposure",
        "caseCount": development_report.records,
        "behaviorCounts": development_report.behavior_counts,
        "casesPath": str(DEVELOPMENT_PATH.relative_to(ROOT)),
        "casesSha256": development_report.sha256,
        "generator": DEVELOPMENT_GENERATOR_ID,
        "generatorSha256": generator_sha,
        "contractId": contract["contractId"],
        "contractSourceRevision": contract["sourceRevision"],
        "fixtureId": DEVELOPMENT_FIXTURE_ID,
        "trainingDraftsPath": str(TRAINING_PATH.relative_to(ROOT)),
        "trainingDraftsSha256": training_report.sha256,
        "disjointnessReportPath": str(DISJOINTNESS_PATH.relative_to(ROOT)),
        "disjointnessReportSha256": hashlib.sha256(disjointness_bytes).hexdigest(),
        "bindings": source_bindings,
    }
    return {
        TRAINING_PATH: training_bytes,
        TRAINING_MANIFEST_PATH: pretty(training_manifest),
        DEVELOPMENT_PATH: development_bytes,
        DEVELOPMENT_MANIFEST_PATH: pretty(development_manifest),
        DISJOINTNESS_PATH: disjointness_bytes,
    }


def review_bytes() -> bytes:
    return b"".join(canonical(empty_decision(trace_id)) + b"\n" for trace_id in trace_ids())


def main() -> None:
    parser = argparse.ArgumentParser(description="Build planner v4 delta and fresh development gate")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--init-review", action="store_true")
    args = parser.parse_args()
    if args.init_review:
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        if REVIEW_PATH.exists():
            raise SystemExit(f"{REVIEW_PATH.relative_to(ROOT)} already exists")
        REVIEW_PATH.write_bytes(review_bytes())
    if not REVIEW_PATH.exists():
        raise SystemExit("initialize the v4 review ledger with --init-review")
    outputs = build_outputs()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, content in outputs.items()
            if not path.exists() or path.read_bytes() != content
        ]
        if stale:
            raise SystemExit("stale planner v4 artifacts: " + ", ".join(stale))
        return
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


if __name__ == "__main__":
    main()
