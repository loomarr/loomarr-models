#!/usr/bin/env python3
"""Build the v2 current-contract development gate and training drafts.

The development cases, scripts, and fixture results are the v1 ones, with two additions:
- `script[].accept`: an explicit rule for which model tool calls count as equivalent to the step.
- `expectation.policy`: the objective policy obligations stated by the production prompt.

The training drafts are the v1 traces with final policies rewritten to follow the prompt (genres
implied by the intent, a ceiling only when requested, everything else omitted). They are pending
review and cannot enter training until independently approved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_current_contract as v1
from loomarr_models.current_contract import (
    CURRENT_CAPABILITIES,
    assert_not_denylisted,
    load_current_denylist,
    validate_current_development_case,
    validate_current_trace,
    validate_disjoint_splits,
)
from loomarr_models.current_gate_v2 import SCORER_VERSION, step_accepts


GENERATOR_ID = "planner-current-contract-generator-v2"
DEVELOPMENT_PATH = Path("evaluation/planner-current-v2/cases.jsonl")
DEVELOPMENT_MANIFEST_PATH = Path("evaluation/planner-current-v2/manifest.json")
TRAINSPLIT_PATH = Path("evaluation/planner-current-v2/trainsplit-cases.jsonl")
TRAINSPLIT_MANIFEST_PATH = Path("evaluation/planner-current-v2/trainsplit-manifest.json")
TRAIN_PATH = Path("corpus/planner-current-v2/drafts.jsonl")
TRAIN_MANIFEST_PATH = Path("corpus/planner-current-v2/draft-manifest.json")

# Genres the training intent names or directly implies. Everything not listed is omitted, per the
# prompt's "only include a field you can justify from the intent".
TRAIN_POLICY: dict[str, dict[str, Any]] = {
    "date-movie-release": {"genres": {"include": ["Adventure"]}},
    "date-series-premiere": {"genres": {"include": ["Comedy"]}},
    "date-disjoint-intervals": {"genres": {"include": ["Science Fiction"]}},
    "ownership-acquisition-balance": {"genres": {"include": ["Mystery"]}},
    "audience-ceiling": {"audience": {"ceiling": "TV-PG"}, "genres": {"include": ["Animation"]}},
    "medium-constraint": {"genres": {"include": ["Animation", "Adventure"]}},
    "language-constraint": {"genres": {"include": ["Comedy"]}},
    "region-constraint": {"genres": {"include": ["Mystery"]}},
    "empty-results": {"genres": {"include": ["Western"]}},
    "observed-fault-recovery": {"genres": {"include": ["Mystery"]}},
}

# Discovery terms the development intent states in words, used when the v1 script routed by genre
# alone.
EXTRA_TERMS = {"medium-constraint": ["mountain"]}


def _f(match: str, value: Any, required: bool = True) -> dict[str, Any]:
    return {"match": match, "value": value, "required": required}


def accept_rule(capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
    media = arguments.get("media_type")
    optional_media = {"media_type": _f("exact", media, required=False)} if media else {}

    def rule(
        fields: dict[str, Any],
        allowed: list[str] | str = (),
        require_any: list[str] = (),
        terms_across: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {"fields": fields, "allowed": allowed if allowed == "*" else sorted(allowed)}
        if require_any:
            value["requireAny"] = list(require_any)
        if terms_across:
            value["termsAcross"] = terms_across
        return value

    if capability in {"exact-key-final", "exact-title-unfamiliar", "constraint-conflict-abstention", "refinement-preservation", "season-window"}:
        return rule({"query": _f("ci", arguments["query"]), **optional_media})
    if capability in {"date-movie-release", "date-series-premiere", "date-disjoint-intervals"}:
        return rule({
            "keywords": _f("tokens", arguments["keywords"]),
            "genres": _f("containsAll", arguments["genres"], required=False),
            **optional_media,
        })
    if capability == "date-series-airing":
        return rule({"media_type": _f("exact", "series")})
    if capability == "date-ambiguity":
        return rule({}, allowed=["genres", "keywords", "media_type"], require_any=["genres", "keywords"])
    if capability == "collection-evidence":
        return rule({"mode": _f("exact", "collection"), "titles": _f("containsAll", arguments["titles"]), **optional_media})
    if capability == "franchise-boundary":
        franchise = arguments["keywords"][0]
        return rule(
            {"keywords": _f("tokens", [franchise], required=False), "query": _f("ci", franchise, required=False), **optional_media},
            require_any=["keywords", "query"],
        )
    if capability == "network-editorial-epoch":
        return rule({"network": _f("ci", arguments["network"]), **optional_media})
    if capability in {"cast-routing", "creator-routing"}:
        field = "cast" if capability == "cast-routing" else "creators"
        return rule({field: _f("containsAll", arguments[field]), **optional_media})
    if capability in {"ownership-acquisition-balance", "audience-ceiling"}:
        return rule({"genres": _f("containsAll", arguments["genres"])}, allowed=["media_type"])
    if capability == "medium-constraint":
        return rule(
            {"genres": _f("containsAll", arguments["genres"], required=False), "keywords": _f("tokens", EXTRA_TERMS[capability], required=False)},
            allowed=["media_type"],
            require_any=["genres", "keywords"],
        )
    if capability == "language-constraint":
        return rule({"original_language": _f("exact", arguments["original_language"]), "genres": _f("containsAll", arguments["genres"])}, allowed=["media_type"])
    if capability == "region-constraint":
        return rule({"origin_country": _f("exact", arguments["origin_country"]), "genres": _f("containsAll", arguments["genres"])}, allowed=["media_type"])
    if capability in {"thin-results", "empty-results"}:
        # The distinctive term may be split across a keyword and a genre ("orchard" + Fantasy).
        term = (arguments.get("keywords") or [arguments.get("query")])[0]
        return rule(
            {},
            allowed=["genres", "keywords", "media_type", "query"],
            require_any=["keywords", "query"],
            terms_across={"fields": ["genres", "keywords", "query"], "value": [term]},
        )
    if capability == "malformed-tool-result":
        # The intent never names the fixture title, so any valid search reaches the malformed reply
        # this case exists to test.
        return rule({}, allowed="*")
    if capability == "observed-fault-recovery":
        return rule({"keywords": _f("tokens", arguments["keywords"]), "genres": _f("containsAll", arguments["genres"], required=False)}, allowed=["media_type"])
    raise SystemExit(f"no accept rule for {capability}")


def development_case(contract: dict[str, Any], capability: str, index: int) -> dict[str, Any]:
    case = v1.development_case(contract, capability, index)
    for step in case["script"]:
        step["accept"] = accept_rule(capability, step["arguments"])
    case["expectation"]["policy"] = {
        "audienceCeiling": "TV-14" if capability == "audience-ceiling" else None,
        "rulesAllowed": False,
    }
    case["provenance"]["generator"] = GENERATOR_ID
    return case


def trainsplit_case(contract: dict[str, Any], capability: str, index: int) -> dict[str, Any]:
    """A development-shaped case over the training-split intent and catalog, for prompt screening.

    It shares intents with the training drafts, so it can detect prompt overfitting to the
    development cases but must never stand in for the development gate in a training decision.
    """
    spec = v1.capability_spec(capability, index, "train")
    expectation: dict[str, Any] = {
        "selectedKeys": spec["selected"],
        "forbiddenKeys": spec["forbidden"],
        "dateMeaning": spec["meaning"],
        "abstain": spec["abstain"],
        "maxToolCalls": len(spec["results"]),
        "policy": {"audienceCeiling": "TV-PG" if capability == "audience-ceiling" else None, "rulesAllowed": False},
    }
    if capability == "observed-fault-recovery":
        expectation["faultInjected"] = True
        expectation["faultObserved"] = True
    arguments_by_step = spec["argumentsByStep"]
    if capability == "medium-constraint":
        extra_terms = ["ocean"]
    else:
        extra_terms = None
    script = []
    for arguments, result in zip(arguments_by_step, spec["results"], strict=True):
        accept = accept_rule(capability, arguments)
        if extra_terms:
            accept["fields"]["keywords"]["value"] = extra_terms
        script.append({"arguments": arguments, "result": v1.tool_result_text(result), "accept": accept})
    return {
        "schemaVersion": 1,
        "caseId": f"planner-current-trainsplit-{capability}-01",
        "split": "development-eval",
        "axis": capability,
        "contract": v1.contract_reference(contract, v1.TRAIN_FIXTURE_ID),
        "intent": spec["intent"],
        "script": script,
        "expectation": expectation,
        "provenance": {"source": "synthetic", "generator": GENERATOR_ID, "author": "codex:fixture", "intent": spec["intent"]},
    }


def training_trace(contract: dict[str, Any], capability: str, index: int) -> dict[str, Any]:
    trace = v1.training_trace(contract, capability, index)
    final = json.loads(trace["messages"][-1]["content"])
    final["policy"] = TRAIN_POLICY.get(capability, {})
    trace["messages"][-1]["content"] = json.dumps(final, separators=(",", ":"), ensure_ascii=False)
    trace["traceId"] = f"planner-current-train-{capability}-02"
    trace["provenance"]["generator"] = GENERATOR_ID
    return trace


def build_outputs() -> dict[Path, bytes]:
    contract = json.loads((ROOT / v1.CONTRACT_PATH).read_text(encoding="utf-8"))
    exact, normalized, minimum, protected = load_current_denylist(ROOT / v1.DENYLIST_PATH)
    traces = [training_trace(contract, c, i) for i, c in enumerate(CURRENT_CAPABILITIES)]
    development = [development_case(contract, c, i) for i, c in enumerate(CURRENT_CAPABILITIES)]
    for trace in traces:
        validate_current_trace(trace, contract, v1.TRAIN_FIXTURE_ID)
        assert_not_denylisted(trace["traceId"], trace, exact, normalized, minimum, protected)
    for case in development:
        validate_current_development_case(case, contract, v1.DEVELOPMENT_FIXTURE_ID)
        assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected)
    validate_disjoint_splits({"current-training": traces, "current-development": development})
    trainsplit = [trainsplit_case(contract, c, i) for i, c in enumerate(CURRENT_CAPABILITIES)]
    for case in trainsplit:
        validate_current_development_case(case, contract, v1.TRAIN_FIXTURE_ID)
        assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected)
        for step in case["script"]:
            if not step_accepts(step, step["arguments"]):
                raise SystemExit(f"{case['caseId']}: canonical step rejected by its accept rule")
    trainsplit_blob = v1.jsonl_bytes(trainsplit)

    train_blob, development_blob = v1.jsonl_bytes(traces), v1.jsonl_bytes(development)
    generator = {
        "id": GENERATOR_ID,
        "path": Path(__file__).relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    common = {
        "contract": {"path": v1.CONTRACT_PATH.as_posix(), "sha256": hashlib.sha256((ROOT / v1.CONTRACT_PATH).read_bytes()).hexdigest()},
        "holdoutDenylist": {"path": v1.DENYLIST_PATH.as_posix(), "sha256": hashlib.sha256((ROOT / v1.DENYLIST_PATH).read_bytes()).hexdigest()},
        "generator": generator,
    }
    return {
        DEVELOPMENT_PATH: development_blob,
        DEVELOPMENT_MANIFEST_PATH: v1.json_bytes({
            "schemaVersion": 1,
            "evaluationId": "planner-current-development-v2",
            "supersedes": "planner-current-development-v1",
            "scorerVersion": SCORER_VERSION,
            "records": len(development),
            "sha256": hashlib.sha256(development_blob).hexdigest(),
            **common,
            "modelExposure": "none",
            "certificationAuthority": False,
        }),
        TRAINSPLIT_PATH: trainsplit_blob,
        TRAINSPLIT_MANIFEST_PATH: v1.json_bytes({
            "schemaVersion": 1,
            "evaluationId": "planner-current-trainsplit-screen-v2",
            "purpose": "prompt-overfitting screen only; shares intents with the training drafts",
            "trainingDecisionAuthority": False,
            "scorerVersion": SCORER_VERSION,
            "records": len(trainsplit),
            "sha256": hashlib.sha256(trainsplit_blob).hexdigest(),
            **common,
            "certificationAuthority": False,
        }),
        TRAIN_PATH: train_blob,
        TRAIN_MANIFEST_PATH: v1.json_bytes({
            "schemaVersion": 1,
            "corpusId": "planner-current-training-v2",
            "supersedes": "planner-current-training-v1",
            "records": len(traces),
            "sha256": hashlib.sha256(train_blob).hexdigest(),
            **common,
            "reviewStatus": "pending",
            "trainingAuthorized": False,
        }),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    if args.check:
        drift = [p.as_posix() for p, blob in outputs.items() if not (ROOT / p).is_file() or (ROOT / p).read_bytes() != blob]
        if drift:
            raise SystemExit("generated current-contract v2 artifacts drifted: " + ", ".join(drift))
        return
    for path, blob in outputs.items():
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / path).write_bytes(blob)


if __name__ == "__main__":
    main()
