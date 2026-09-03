#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import loomarr_models.behavior_review as review_contract
import loomarr_models.behavior_model_review as review_preflight_contract
import loomarr_models.targeted as targeted_contract
from loomarr_models.behavior_review import empty_decision, load_review_decisions, trace_review
from loomarr_models.behavior_model_review import preflight as preflight_review
from loomarr_models.behavior_model_review import request_plan_bytes
from loomarr_models.evaluation import load_cases
from loomarr_models.targeted import (
    BEHAVIORS,
    DEVELOPMENT_FIXTURE_ID,
    DEVELOPMENT_GENERATOR_ID,
    DEVELOPMENT_PER_BEHAVIOR,
    TRAINING_FIXTURE_ID,
    TRAINING_GENERATOR_ID,
    TRAINING_PER_BEHAVIOR,
    canonical,
    validate_disjoint_splits,
    validate_targeted_development,
    validate_targeted_training,
)
from loomarr_models.validator import load_contract, load_denylist, load_jsonl


CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
BUDGET_PATH = ROOT / "budgets/external-spend-v1.json"
PRIOR_TRAINING_PATH = ROOT / "corpus/planner-smoke-v1/traces.jsonl"
PRIOR_DEVELOPMENT_PATH = ROOT / "evaluation/planner-development-v1/cases.jsonl"
REVIEW_POLICY_PATH = ROOT / "docs/planner-behavior-corpus-v2.md"
REVIEW_DECISIONS_PATH = ROOT / "reviews/planner-behavior-v2.jsonl"
ROUTE_SNAPSHOT_PATH = ROOT / "reviews/planner-behavior-v2/route-snapshot.json"
REQUEST_PLAN_PATH = ROOT / "reviews/planner-behavior-v2/request-plan.jsonl"
PREFLIGHT_REPORT_PATH = ROOT / "reviews/planner-behavior-v2/preflight-report.json"
TRAINING_PATH = ROOT / "corpus/planner-behavior-v2/drafts.jsonl"
TRAINING_MANIFEST_PATH = ROOT / "corpus/planner-behavior-v2/draft-manifest.json"
DEVELOPMENT_PATH = ROOT / "evaluation/planner-behavior-development-v2/cases.jsonl"
DEVELOPMENT_MANIFEST_PATH = ROOT / "evaluation/planner-behavior-development-v2/manifest.json"
DISJOINTNESS_PATH = ROOT / "reports/planner-behavior-v2-disjointness.json"
REVIEW_PLAN_PATH = ROOT / "experiments/planner-behavior-review-v2.json"
INDEX_PATH = ROOT / "runs/planner-behavior-corpus-v2/index.json"
REVIEW_RUNNER_PATH = ROOT / "scripts/run_planner_behavior_review.py"
REVIEW_PUBLISHER_PATH = ROOT / "scripts/publish_planner_behavior_review.py"
CORPUS_FINALIZER_PATH = ROOT / "scripts/finalize_planner_behavior_corpus.py"

TRAINING_BASE_ID = 920000
DEVELOPMENT_BASE_ID = 930000
TRAINING_ADJECTIVES = ("Aster", "Beryl", "Cinder", "Dune", "Ember")
DEVELOPMENT_ADJECTIVES = ("Fable", "Grove", "Hollow", "Iris", "Kestrel")
NOUNS = ("Beacon", "Circuit", "Delta", "Gallery", "Horizon", "Junction")
GENRES = ("Adventure", "Comedy", "Documentary", "Drama", "Mystery")
MOODS = (
    ("airy and optimistic", "Comedy"),
    ("patient and observant", "Documentary"),
    ("shadowy and investigative", "Mystery"),
    ("sweeping and exploratory", "Adventure"),
    ("intimate and reflective", "Drama"),
)


@dataclass(frozen=True)
class Scenario:
    intent: str
    steps: list[dict[str, Any]]
    selected: list[dict[str, Any]]
    forbidden: list[dict[str, Any]]
    policy: dict[str, Any]
    title: str
    rationale: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(item: dict[str, Any]) -> dict[str, Any]:
    return {"mediaType": item["mediaType"], "tmdbId": item["tmdbId"]}


def candidate(number: int, *, development: bool, genre: str = "Adventure") -> dict[str, Any]:
    adjectives = DEVELOPMENT_ADJECTIVES if development else TRAINING_ADJECTIVES
    base = DEVELOPMENT_BASE_ID if development else TRAINING_BASE_ID
    adjective = adjectives[(number - 1) % len(adjectives)]
    noun = NOUNS[((number - 1) // len(adjectives)) % len(NOUNS)]
    media_type = "series" if number % 2 == 0 else "movie"
    return {
        "mediaType": media_type,
        "tmdbId": base + number,
        "name": f"{adjective} {noun} Fixture {number:03d}",
        "year": 1980 + ((number - 1) % 40),
        "inLibrary": number % 3 != 0,
        "genres": [genre],
        "overview": f"A wholly synthetic {genre.lower()} catalog fixture numbered {number}.",
    }


def build_scenario(behavior: str, variant: int, number: int, *, development: bool) -> Scenario:
    item = candidate(number, development=development)
    selected = [identity(item)]
    forbidden: list[dict[str, Any]] = []
    policy: dict[str, Any] = {}
    rationale = "A grounded proposal using only the synthetic catalog fixture."

    if behavior == "canonical-argument-preservation":
        genre = GENRES[variant % len(GENRES)]
        era_start = 1980 + 10 * (variant % 4)
        era = f"{era_start}s"
        media_type = "series" if variant % 2 else "movie"
        language, country = (("en", "US"), ("fr", "FR"), ("ja", "JP"), ("es", "MX"), ("de", "DE"))[variant % 5]
        runtime_min = 20 + (variant % 4) * 10
        runtime_max = runtime_min + 30
        rating = 6.0 + (variant % 4) * 0.5
        votes = 100 + variant * 25
        item = candidate(number, development=development, genre=genre)
        item.update(
            {
                "mediaType": media_type,
                "year": era_start + variant % 10,
                "originalLanguage": language,
                "originCountry": country,
                "runtime": runtime_min + 10,
                "voteAverage": rating + 0.5,
                "voteCount": votes + 50,
                "overview": f"A wholly synthetic {genre.lower()} fixture satisfying every explicit catalog qualifier.",
            }
        )
        selected = [identity(item)]
        intent = (
            f"Build a synthetic {genre} channel from {era}, media type {media_type}, "
            f"original language {language}, origin country {country}, runtime {runtime_min}-{runtime_max} "
            f"minutes, minimum rating {rating:.1f}, and minimum {votes} votes; do not add other qualifiers."
        )
        arguments = {
            "genres": [genre],
            "era": era,
            "media_type": media_type,
            "original_language": language,
            "origin_country": country,
            "runtime_min": runtime_min,
            "runtime_max": runtime_max,
            "vote_average_min": rating,
            "vote_count_min": votes,
        }
        steps = [{"arguments": arguments, "result": {"candidates": [item]}}]
        policy = {"genres": {"include": [genre]}, "era": {"from": era_start, "to": era_start + 9}}
        title = f"{TRAINING_ADJECTIVES[variant % 5]} Exact Mix"
    elif behavior == "one-tool-operation-per-turn":
        motif = f"synthetic signal motif {variant + 1}"
        item["overview"] = f"A wholly synthetic catalog story about signal motif {variant + 1}."
        intent = f"Build a synthetic channel about {motif}; if keyword discovery is empty, retry that exact motif as a title."
        steps = [
            {"arguments": {"keywords": [motif]}, "result": {"candidates": []}},
            {"arguments": {"query": motif}, "result": {"candidates": [item]}},
        ]
        title = f"{TRAINING_ADJECTIVES[variant % 5]} Signal"
    elif behavior == "complete-proposal-json":
        intent = f"Build a synthetic channel around the exact catalog title {item['name']}; no policy was requested."
        steps = [{"arguments": {"query": item["name"]}, "result": {"candidates": [item]}}]
        title = f"{TRAINING_ADJECTIVES[variant % 5]} Complete"
    elif behavior == "structured-json-abstention":
        intent = f"Build a synthetic channel that must both include and exclude {item['name']}."
        steps = [{"arguments": {"query": item["name"]}, "result": {"candidates": [item]}}]
        selected = []
        forbidden = [identity(item)]
        title = f"{TRAINING_ADJECTIVES[variant % 5]} Abstains"
        rationale = "The synthetic request is contradictory, so the structured proposal contains no picks."
    elif behavior == "synthetic-tool-error-recovery":
        genre = GENRES[variant % len(GENRES)]
        item = candidate(number, development=development, genre=genre)
        selected = [identity(item)]
        intent = f"Build a synthetic {genre.lower()} channel around {item['name']} and recover from the fixture timeout."
        steps = [
            {
                "arguments": {"query": item["name"]},
                "result": {"candidates": [], "error": "synthetic fixture timeout"},
            },
            {"arguments": {"genres": [genre]}, "result": {"candidates": [item]}},
        ]
        policy = {"genres": {"include": [genre]}}
        title = f"{TRAINING_ADJECTIVES[variant % 5]} Recovery"
        rationale = "The alternate search recovered a grounded synthetic fixture result."
    elif behavior == "ambiguous-intent-mapping":
        mood, genre = MOODS[variant % len(MOODS)]
        item = candidate(number, development=development, genre=genre)
        item["overview"] = f"A wholly synthetic {genre.lower()} fixture with an {mood} tone."
        selected = [identity(item)]
        intent = f"Build something synthetic that feels {mood}; map the mood to the best catalog genre without asking a question."
        steps = [{"arguments": {"genres": [genre]}, "result": {"candidates": [item]}}]
        policy = {"genres": {"include": [genre]}}
        title = f"{TRAINING_ADJECTIVES[variant % 5]} Mood"
    else:
        raise ValueError(f"unknown behavior {behavior}")

    return Scenario(intent, steps, selected, forbidden, policy, title, rationale)


def final_message(scenario: Scenario) -> dict[str, Any]:
    selected = {(item["mediaType"], item["tmdbId"]) for item in scenario.selected}
    candidates = [
        candidate
        for step in scenario.steps
        for candidate in step["result"].get("candidates", [])
        if (candidate["mediaType"], candidate["tmdbId"]) in selected
    ]
    final = {
        "channelName": scenario.title,
        "rationale": scenario.rationale,
        "picks": [
            {
                "mediaType": item["mediaType"],
                "tmdbId": item["tmdbId"],
                "name": item["name"],
                "rationale": "This synthetic candidate satisfies the requested behavior.",
                "confidence": 0.91,
            }
            for item in candidates
        ],
        "policy": scenario.policy,
    }
    return {"role": "assistant", "content": json.dumps(final, separators=(",", ":"))}


def trace_ids() -> list[str]:
    return [
        f"planner-behavior-v2-{behavior}-{variant + 1:02d}"
        for behavior in BEHAVIORS
        for variant in range(TRAINING_PER_BEHAVIOR)
    ]


def review_bytes() -> bytes:
    return b"".join(canonical(empty_decision(trace_id)) + b"\n" for trace_id in trace_ids())


def build_training(contract: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    number = 1
    contract_identity = {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": TRAINING_FIXTURE_ID,
    }
    for behavior in BEHAVIORS:
        for variant in range(TRAINING_PER_BEHAVIOR):
            scenario = build_scenario(behavior, variant, number, development=False)
            trace_id = f"planner-behavior-v2-{behavior}-{variant + 1:02d}"
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": contract["systemPrompt"]},
                {"role": "user", "content": scenario.intent},
            ]
            for step_index, step in enumerate(scenario.steps, 1):
                call_id = f"behavior-{number}-{step_index}"
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "toolCalls": [
                                {"id": call_id, "name": "catalog_search", "arguments": step["arguments"]}
                            ],
                        },
                        {
                            "role": "tool",
                            "toolCallId": call_id,
                            "name": "catalog_search",
                            "content": step["result"],
                        },
                    ]
                )
            messages.append(final_message(scenario))
            traces.append(
                {
                    "schemaVersion": 1,
                    "traceId": trace_id,
                    "split": "train",
                    "axes": [behavior],
                    "contract": copy.deepcopy(contract_identity),
                    "tools": copy.deepcopy(contract["tools"]),
                    "messages": messages,
                    "review": trace_review(decisions[trace_id]),
                    "provenance": {
                        "source": "synthetic",
                        "generator": TRAINING_GENERATOR_ID,
                        "author": "codex:draft",
                    },
                }
            )
            number += 1
    return traces


def build_development(contract: dict[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    number = 1
    contract_identity = {
        "promptVersion": contract["promptVersion"],
        "systemPromptSha256": contract["systemPromptSha256"],
        "toolSchemaVersion": contract["toolSchemaVersion"],
        "toolSchemaSha256": contract["toolSchemaSha256"],
        "messageTemplateVersion": contract["messageTemplateVersion"],
        "fixtureId": DEVELOPMENT_FIXTURE_ID,
    }
    for behavior in BEHAVIORS:
        for variant in range(DEVELOPMENT_PER_BEHAVIOR):
            scenario = build_scenario(behavior, variant + 20, number, development=True)
            cases.append(
                {
                    "schemaVersion": 1,
                    "caseId": f"planner-behavior-development-v2-{behavior}-{variant + 1:02d}",
                    "split": "development-eval",
                    "axis": behavior,
                    "contract": copy.deepcopy(contract_identity),
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
            )
            number += 1
    return cases


def pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def binding(path: Path, *, count: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
    if count is not None:
        value["count"] = count
    return value


def build_outputs() -> dict[Path, bytes]:
    contract = load_contract(CONTRACT_PATH)
    denylisted_identities, denylisted_sha256 = load_denylist(DENYLIST_PATH)
    decisions = load_review_decisions(REVIEW_DECISIONS_PATH, trace_ids())
    prior_training = load_jsonl(PRIOR_TRAINING_PATH)
    prior_development = load_cases(PRIOR_DEVELOPMENT_PATH)
    training = build_training(contract, decisions)
    development = build_development(contract)
    training_bytes = b"".join(canonical(trace) + b"\n" for trace in training)
    development_bytes = b"".join(canonical(case) + b"\n" for case in development)
    training_report = validate_targeted_training(
        training,
        contract=contract,
        denylisted_identities=denylisted_identities,
        denylisted_sha256=denylisted_sha256,
    )
    development_report = validate_targeted_development(
        development,
        contract=contract,
        denylisted_identities=denylisted_identities,
        denylisted_sha256=denylisted_sha256,
    )
    disjoint = validate_disjoint_splits(
        prior_training=prior_training,
        prior_development=prior_development,
        targeted_training=training,
        targeted_development=development,
        denylisted_identities=denylisted_identities,
        denylisted_sha256=denylisted_sha256,
    )
    source_bindings = {
        "contract": binding(CONTRACT_PATH),
        "holdoutDenylist": binding(DENYLIST_PATH),
        "priorTraining": binding(PRIOR_TRAINING_PATH, count=len(prior_training)),
        "priorDevelopment": binding(PRIOR_DEVELOPMENT_PATH, count=len(prior_development)),
        "reviewDecisions": binding(REVIEW_DECISIONS_PATH, count=len(decisions)),
        "reviewPolicy": binding(REVIEW_POLICY_PATH),
        "reviewValidator": binding(Path(review_contract.__file__)),
        "targetedValidator": binding(Path(targeted_contract.__file__)),
    }
    generator_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    disjointness = {
        "schemaVersion": 1,
        "reportId": "planner-behavior-v2-disjointness",
        "status": "passed",
        "pairwiseComparisons": disjoint.pairCount,
        "splits": disjoint.splits,
        "denylistIdentityCount": len(denylisted_identities),
        "denylistDigestCount": len(denylisted_sha256),
        "bindings": {
            **source_bindings,
            "targetedTraining": {
                "path": str(TRAINING_PATH.relative_to(ROOT)),
                "sha256": training_report.sha256,
                "count": training_report.records,
            },
            "targetedDevelopment": {
                "path": str(DEVELOPMENT_PATH.relative_to(ROOT)),
                "sha256": development_report.sha256,
                "count": development_report.records,
            },
        },
    }
    disjointness_bytes = pretty(disjointness)
    training_manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-behavior-v2",
        "status": "draft-pending-independent-review",
        "traceCount": training_report.records,
        "behaviorCounts": training_report.behaviorCounts,
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
        "review": {
            "approved": sum(trace["review"]["status"] == "approved" for trace in training),
            "pending": sum(trace["review"]["status"] == "pending" for trace in training),
            "rejected": sum(trace["review"]["status"] == "rejected" for trace in training),
        },
        "bindings": source_bindings,
    }
    training_manifest_bytes = pretty(training_manifest)
    development_manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-behavior-development-v2",
        "status": "frozen-development-only",
        "caseCount": development_report.records,
        "behaviorCounts": development_report.behaviorCounts,
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
    development_manifest_bytes = pretty(development_manifest)
    route_snapshot = json.loads(ROUTE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    budget = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    review_preflight = preflight_review(
        training,
        route_snapshot=route_snapshot,
        budget=budget,
    )
    request_plan = request_plan_bytes(review_preflight)
    if hashlib.sha256(request_plan).hexdigest() != review_preflight.requestPlanSha256:
        raise AssertionError("review request-plan digest calculation diverged")
    review_bindings = {
        **source_bindings,
        "budget": binding(BUDGET_PATH),
        "routeSnapshot": binding(ROUTE_SNAPSHOT_PATH),
        "reviewPreflightValidator": binding(Path(review_preflight_contract.__file__)),
        "reviewRunner": binding(REVIEW_RUNNER_PATH),
        "reviewPublisher": binding(REVIEW_PUBLISHER_PATH),
        "corpusFinalizer": binding(CORPUS_FINALIZER_PATH),
    }
    review_plan = {
        "schemaVersion": 1,
        "reviewId": "planner-behavior-review-v2",
        "issue": "https://github.com/loomarr/loomarr-models/issues/9",
        "status": "planned-no-paid-calls-authorized",
        "candidateFamily": "qwen",
        "criteria": ["intent", "tool_calls", "grounding", "recovery", "constraints", "final_proposal"],
        "reviewers": list(review_preflight_contract.REVIEWERS),
        "execution": {
            "apiBaseUrl": "https://openrouter.ai/api/v1",
            "batchSize": review_preflight.batchSize,
            "maxCalls": review_preflight.requestCount,
            "maxOutputTokensPerCall": 3000,
            "reasoningEffort": "medium",
            "compactTracePacket": True,
            "multiTraceBatchAuthorized": False,
            "outputDir": ".artifacts/planner-behavior-review-v2",
            "requestTimeoutSeconds": 180,
            "settlementAttempts": 60,
            "settlementDelaySeconds": 1,
            "requireCleanGit": True,
            "strictStructuredOutput": True,
            "providerFallback": False,
            "providerDataCollection": "deny",
            "automaticInferenceRetry": False,
            "paidReviewAuthorized": False,
        },
        "budget": {
            "aggregateAuthorizationUsd": review_preflight.authorizationUsd,
            "currentCommittedUsd": review_preflight.committedSpendUsd,
            "reviewReservationUsd": review_preflight.reservationUsd,
            "projectedMaximumUsd": review_preflight.projectedSpendUsd,
            "remainingAfterMaximumUsd": str(
                Decimal(review_preflight.authorizationUsd)
                - Decimal(review_preflight.projectedSpendUsd)
            ),
            "worstCaseReviewUsd": review_preflight.worstCaseCostUsd,
        },
        "preflight": review_preflight.summary(),
        "bindings": {
            **review_bindings,
            "trainingDrafts": {
                "path": str(TRAINING_PATH.relative_to(ROOT)),
                "sha256": training_report.sha256,
                "count": training_report.records,
            },
            "trainingManifest": {
                "path": str(TRAINING_MANIFEST_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(training_manifest_bytes).hexdigest(),
            },
            "developmentCases": {
                "path": str(DEVELOPMENT_PATH.relative_to(ROOT)),
                "sha256": development_report.sha256,
                "count": development_report.records,
            },
            "developmentManifest": {
                "path": str(DEVELOPMENT_MANIFEST_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(development_manifest_bytes).hexdigest(),
            },
            "disjointnessReport": {
                "path": str(DISJOINTNESS_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(disjointness_bytes).hexdigest(),
            },
            "requestPlan": {
                "path": str(REQUEST_PLAN_PATH.relative_to(ROOT)),
                "sha256": review_preflight.requestPlanSha256,
                "count": review_preflight.requestCount,
            },
        },
    }
    review_plan_bytes = pretty(review_plan)
    preflight_report = {
        "schemaVersion": 1,
        "reportId": "planner-behavior-review-v2-preflight",
        "status": "passed-no-inference",
        "paidReviewAuthorized": False,
        "inferenceCalls": 0,
        "externalCostUsd": "0",
        "routeMetadataCapturedAt": route_snapshot["capturedAt"],
        "schemaCompilationProof": route_snapshot["schemaCompilationProof"],
        "decision": "compact-single-trace-plan-fits-reservation",
        "preflight": review_preflight.summary(),
        "bindings": {
            "reviewPlan": {
                "path": str(REVIEW_PLAN_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(review_plan_bytes).hexdigest(),
            },
            "requestPlan": {
                "path": str(REQUEST_PLAN_PATH.relative_to(ROOT)),
                "sha256": review_preflight.requestPlanSha256,
            },
            "routeSnapshot": binding(ROUTE_SNAPSHOT_PATH),
            "budget": binding(BUDGET_PATH),
            "trainingDrafts": {
                "path": str(TRAINING_PATH.relative_to(ROOT)),
                "sha256": training_report.sha256,
            },
        },
    }
    preflight_report_bytes = pretty(preflight_report)
    outputs = {
        TRAINING_PATH: training_bytes,
        TRAINING_MANIFEST_PATH: training_manifest_bytes,
        DEVELOPMENT_PATH: development_bytes,
        DEVELOPMENT_MANIFEST_PATH: development_manifest_bytes,
        DISJOINTNESS_PATH: disjointness_bytes,
        REVIEW_PLAN_PATH: review_plan_bytes,
        REQUEST_PLAN_PATH: request_plan,
        PREFLIGHT_REPORT_PATH: preflight_report_bytes,
    }
    index = {
        "schemaVersion": 1,
        "publicationId": "planner-behavior-corpus-v2",
        "status": "draft-no-spend",
        "artifacts": [
            {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(
                {**outputs, ROUTE_SNAPSHOT_PATH: ROUTE_SNAPSHOT_PATH.read_bytes()}.items(),
                key=lambda item: str(item[0]),
            )
        ],
        "generator": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": generator_sha},
        "nextGate": "maintainer authorization to enable the paid review runner",
        "trainingAuthorized": False,
    }
    outputs[INDEX_PATH] = pretty(index)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the targeted planner behavior corpus")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--init-review", action="store_true")
    actions.add_argument("--migrate-pending-review", action="store_true")
    args = parser.parse_args()
    if args.init_review:
        if REVIEW_DECISIONS_PATH.exists():
            raise SystemExit(f"{REVIEW_DECISIONS_PATH.relative_to(ROOT)} already exists")
        REVIEW_DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_DECISIONS_PATH.write_bytes(review_bytes())
        return
    if args.migrate_pending_review:
        existing = [
            json.loads(line)
            for line in REVIEW_DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if [item.get("traceId") for item in existing] != trace_ids() or any(
            item.get("primary", {}).get("verdict") != "pending"
            or item.get("secondary", {}).get("verdict") != "pending"
            or item.get("primary", {}).get("reviewer")
            or item.get("secondary", {}).get("reviewer")
            or item.get("primary", {}).get("reviewedAt") is not None
            or item.get("secondary", {}).get("reviewedAt") is not None
            or item.get("primary", {}).get("notes")
            or item.get("secondary", {}).get("notes")
            for item in existing
        ):
            raise SystemExit("refusing migration: review decisions are not the exact unevidenced pending set")
        REVIEW_DECISIONS_PATH.write_bytes(review_bytes())
        return
    outputs = build_outputs()
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, data in outputs.items() if not path.exists() or path.read_bytes() != data]
        if stale:
            raise SystemExit("stale targeted corpus artifacts: " + ", ".join(stale))
        return
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


if __name__ == "__main__":
    main()
