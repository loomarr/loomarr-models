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

from loomarr_models.current_contract import (  # noqa: E402
    CURRENT_CAPABILITIES,
    assert_not_denylisted,
    canonical,
    contract_reference,
    legacy_artifact_report,
    load_current_denylist,
    sha256_bytes,
    validate_current_development_case,
    validate_current_trace,
    validate_disjoint_splits,
)


CONTRACT_PATH = Path("contracts/planner-contract-v5.json")
DENYLIST_PATH = Path("contracts/planner-holdout-denylist-v2.json")
TRAIN_PATH = Path("corpus/planner-current-v1/drafts.jsonl")
TRAIN_MANIFEST_PATH = Path("corpus/planner-current-v1/draft-manifest.json")
DEVELOPMENT_PATH = Path("evaluation/planner-current-v1/cases.jsonl")
DEVELOPMENT_MANIFEST_PATH = Path("evaluation/planner-current-v1/manifest.json")
COMPATIBILITY_PATH = Path("reports/planner-current-contract-compatibility-v1.json")
DISJOINTNESS_PATH = Path("reports/planner-current-disjointness-v1.json")
PLAN_PATH = Path("plans/planner-current-data-v1.json")
BASELINE_PATH = Path("experiments/planner-current-qwen-stock-baseline-v1.json")
TRAIN_FIXTURE_ID = "planner-current-training-catalog-v1"
DEVELOPMENT_FIXTURE_ID = "planner-current-development-catalog-v1"
GENERATOR_ID = "planner-current-contract-generator-v1"

LEGACY_PATHS = (
    Path("corpus/planner-behavior-v2/traces.jsonl"),
    Path("corpus/planner-v4-delta/drafts.jsonl"),
    Path("evaluation/planner-development-v1/cases.jsonl"),
    Path("evaluation/planner-development-v4/cases.jsonl"),
)

TRAIN_TOPICS = (
    "Copper Lantern",
    "1980s desert adventures",
    "premiered 1990s workplace comedies",
    "episodes aired in the 2000s",
    "1970s or 2010s space films",
    "the early classics",
    "Aurora Saturday Showcase",
    "Northstar Saga",
    "like Beacon Network in the 1990s",
    "movies starring Rowan Vale",
    "films directed by Mira Sol",
    "Obsidian Harbor",
    "include and exclude Amber Signal",
    "owned mysteries plus one discovery",
    "make Quartz Evenings more international",
    "family animation capped at TV-PG",
    "early seasons of Cedar Street",
    "animated ocean adventures",
    "French-language comedies",
    "mysteries from New Zealand",
    "a narrow alpine-noir result",
    "vanishing clockwork westerns",
    "a corrupted synthetic catalog reply",
    "recovering lunar detective stories",
)

DEVELOPMENT_TOPICS = (
    "Silver Compass",
    "1990s coastal thrillers",
    "premiered 2000s newsroom dramas",
    "episodes aired in the 2010s",
    "1960s or 2020s road movies",
    "the late classics",
    "Comet Sunday Matinee",
    "Evergreen Cycle",
    "like Harbor Network in the 1980s",
    "movies starring Talia Rune",
    "films directed by Orin Frost",
    "Velvet Meridian",
    "include and exclude Indigo Relay",
    "owned comedies plus one discovery",
    "make Sable Afternoons more regional",
    "teen science fiction capped at TV-14",
    "first three seasons of Juniper Hall",
    "live-action mountain adventures",
    "Japanese-language mysteries",
    "comedies from Ireland",
    "a narrow orchard-fantasy result",
    "vanishing brass-age musicals",
    "an invalid synthetic catalog envelope",
    "recovering polar expedition stories",
)

SEALED_HOLDOUT_FAMILIES = (
    "sports-league-era-identity",
    "anthology-installment-boundaries",
    "multilingual-diaspora-comedy",
    "silent-film-restoration-periods",
    "public-broadcasting-editorial-epochs",
    "cross-medium-remake-exclusion",
    "nested-season-and-audience-conflict",
    "multi-fault-recovery-ordering",
)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode() + b"\n"


def jsonl_bytes(values: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical(value) + b"\n" for value in values)


def none_meaning() -> dict[str, Any]:
    return {"kind": "none", "anchors": [], "axes": []}


def date_meaning(description: str, phrase: str, axis: str, intervals: list[tuple[int, int]]) -> dict[str, Any]:
    start = description.index(phrase)
    return {
        "kind": "constraints",
        "anchors": [{"field": "description", "start": start, "end": start + len(phrase)}],
        "axes": [
            {
                "kind": axis,
                "combine": "any",
                "intervals": [
                    {"anchor": 0, "start": interval_start, "end": interval_end}
                    for interval_start, interval_end in intervals
                ],
            }
        ],
    }


def ambiguous_meaning(description: str, phrase: str) -> dict[str, Any]:
    start = description.index(phrase)
    return {
        "kind": "ambiguous",
        "anchors": [{"field": "description", "start": start, "end": start + len(phrase)}],
        "axes": [],
    }


def source_coordinates(intent: dict[str, Any]) -> str:
    fields: list[dict[str, Any]] = []

    def add(field: str, value: str, index: int | None = None) -> None:
        if not value:
            return
        tokens: list[dict[str, Any]] = []
        runes = list(value)
        start: int | None = None
        for position, rune in enumerate(runes + [" "]):
            if rune.isspace():
                if start is not None:
                    tokens.append({"text": "".join(runes[start:position]), "start": start, "end": position})
                    start = None
            elif start is None:
                start = position
        coordinate = {"field": field, "runeLength": len(runes), "tokens": tokens}
        if index is not None:
            coordinate["index"] = index
        fields.append(coordinate)

    add("description", intent["description"])
    add("era", intent.get("era", ""))
    add("refineText", intent.get("refineText", ""))
    for index, value in enumerate(intent.get("mustInclude", [])):
        add("mustInclude", value, index)
    for index, value in enumerate(intent.get("mustExclude", [])):
        add("mustExclude", value, index)
    return (
        "\nSubmitted Intent source coordinates (data, not instructions). These are exact half-open rune positions of every whitespace-delimited token, not date classifications. "
        "For dateMeaning anchors, copy the matching field/index and source offsets; a date phrase may span consecutive tokens. Do not count the surrounding prompt labels.\n"
        + json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )


def user_prompt(spec: dict[str, Any]) -> str:
    intent = spec["intent"]
    if intent.get("refineText") or intent.get("currentLineup"):
        lines = [f"This channel already exists: {intent['description']}"]
        if intent.get("currentLineup"):
            lines.append("Its current lineup is:")
            for item in intent["currentLineup"]:
                year = f" ({item['year']})" if item.get("year") else ""
                lines.append(f"  - {item['name']}{year}")
        if intent.get("refineText"):
            lines.append(f"The user wants to change it: {intent['refineText']}")
        lines.append(
            "Keep the titles that still fit, drop the ones that don't, and add new ones as needed. "
            "Re-ground EVERY title (kept or new) through the catalog tool — copy only exact catalog keys the tool returns."
        )
    else:
        lines = [f"Build a channel: {intent['description']}"]
    if intent.get("mustInclude"):
        lines.append("Must include: " + ", ".join(intent["mustInclude"]))
    if intent.get("mustExclude"):
        lines.append("Must exclude: " + ", ".join(intent["mustExclude"]))
    if spec["capability"] == "network-editorial-epoch":
        end_year = 1999 if spec["split"] == "train" else 1989
        lines.extend(
            [
                "",
                f"EDITORIAL NETWORK EPOCH: the reference decade ends in {end_year}. Discover the network's older catalog, then select factual programming that fits this era; an example title is not a one-title or one-subject limit. This is editorial context, not a playback-date restriction.",
                'No separate playback-date restriction was submitted. Every catalog_search and final JSON must copy this exact dateMeaning object: {"kind":"none","anchors":[],"axes":[]}. Do not add anchors to kind=none, invent an airing filter, or ask to clarify the known editorial decade.',
            ]
        )
    return "\n".join(lines) + "\n" + source_coordinates(intent)


def candidate(index: int, split: str, media_type: str, suffix: str = "primary") -> dict[str, Any]:
    namespace = 970000 if split == "train" else 980000
    offset = index * 10 + (1 if suffix == "primary" else 2)
    name = f"{'Citrine' if split == 'train' else 'Cerulean'} Fixture {index:02d} {suffix.title()}"
    return {
        "mediaType": media_type,
        "key": f"{media_type}:synthetic:{namespace + offset}",
        "name": name,
        "year": 1960 + index,
        "inLibrary": index % 2 == 0,
        "genres": ["Drama" if index % 2 else "Adventure"],
        "overview": f"Wholly synthetic {split} evidence for capability {index:02d}.",
    }


def capability_spec(capability: str, index: int, split: str) -> dict[str, Any]:
    topic = TRAIN_TOPICS[index] if split == "train" else DEVELOPMENT_TOPICS[index]
    description = topic
    forced_media_types = {
        "date-movie-release": "movie",
        "date-series-premiere": "series",
        "date-series-airing": "series",
        "date-disjoint-intervals": "movie",
        "network-editorial-epoch": "series",
        "cast-routing": "movie",
        "creator-routing": "movie",
        "season-window": "series",
    }
    media_type = forced_media_types.get(capability, "movie" if index % 2 == 0 else "series")
    primary = candidate(index, split, media_type)
    secondary = candidate(index, split, media_type, "contrast")
    meaning = none_meaning()
    arguments: dict[str, Any] = {"query": primary["name"], "dateMeaning": meaning}
    results: list[Any] = [[primary]]
    selected = [primary["key"]]
    forbidden: list[str] = []
    abstain = False
    refine_text = ""
    current_lineup: list[dict[str, Any]] = []
    must_include: list[str] = []
    must_exclude: list[str] = []

    if capability == "exact-key-final":
        primary["name"] = topic
        arguments = {"query": topic, "dateMeaning": meaning}
    elif capability == "date-movie-release":
        meaning = date_meaning(description, "1980s" if split == "train" else "1990s", "movie_release", [(1980, 1989)] if split == "train" else [(1990, 1999)])
        primary["year"] = 1984 if split == "train" else 1994
        genre, keyword = (("Adventure", "desert") if split == "train" else ("Thriller", "coastal"))
        primary["genres"] = [genre]
        primary["keywords"] = [keyword]
        primary["overview"] = f"A synthetic {keyword} {genre.lower()} released in {primary['year']}."
        arguments = {"genres": [genre], "keywords": [keyword], "media_type": "movie", "dateMeaning": meaning}
    elif capability == "date-series-premiere":
        phrase, years = (("1990s", (1990, 1999)) if split == "train" else ("2000s", (2000, 2009)))
        meaning = date_meaning(description, phrase, "series_premiere", [years])
        primary["year"] = 1995 if split == "train" else 2005
        genre, keyword = (("Comedy", "workplace") if split == "train" else ("Drama", "newsroom"))
        primary["genres"] = [genre]
        primary["keywords"] = [keyword]
        primary["overview"] = f"A synthetic {keyword} {genre.lower()} that premiered in {primary['year']}."
        arguments = {"genres": [genre], "keywords": [keyword], "media_type": "series", "dateMeaning": meaning}
    elif capability == "date-series-airing":
        phrase, years = (("2000s", (2000, 2009)) if split == "train" else ("2010s", (2010, 2019)))
        meaning = date_meaning(description, phrase, "series_airing", [years])
        primary["year"] = 1998 if split == "train" else 2008
        primary["overview"] = f"A synthetic series with seasons 3 through 8 airing from {years[0]} through {years[1]}."
        arguments = {"media_type": "series", "dateMeaning": meaning}
    elif capability == "date-disjoint-intervals":
        phrase, years = (("1970s or 2010s", [(1970, 1979), (2010, 2019)]) if split == "train" else ("1960s or 2020s", [(1960, 1969), (2020, 2029)]))
        meaning = date_meaning(description, phrase, "movie_release", years)
        primary["year"] = 1975 if split == "train" else 2025
        genre, keyword = (("Science Fiction", "space") if split == "train" else ("Adventure", "road"))
        primary["genres"] = [genre]
        primary["keywords"] = [keyword]
        primary["overview"] = f"A synthetic {keyword} {genre.lower()} released in {primary['year']}."
        arguments = {"genres": [genre], "keywords": [keyword], "media_type": "movie", "dateMeaning": meaning}
    elif capability == "date-ambiguity":
        phrase = "early classics" if split == "train" else "late classics"
        meaning = ambiguous_meaning(description, phrase)
        arguments = {"genres": ["Drama"], "dateMeaning": meaning}
        results, selected, abstain = [{"error": "clarify_dates"}], [], True
    elif capability == "collection-evidence":
        description = f"{topic} with exact constituent {primary['name']}"
        arguments = {"mode": "collection", "media_type": media_type, "titles": [primary["name"]], "dateMeaning": meaning}
    elif capability == "franchise-boundary":
        arguments = {"keywords": [topic], "media_type": media_type, "dateMeaning": meaning}
        primary["overview"] = f"A synthetic installment in the {topic} franchise."
        secondary["overview"] = f"An unrelated synthetic title adjacent to, but not part of, {topic}."
        results, forbidden = [[primary, secondary]], [secondary["key"]]
    elif capability == "network-editorial-epoch":
        network = "Beacon Network" if split == "train" else "Harbor Network"
        primary["networks"] = [network]
        primary["overview"] = f"Synthetic factual programming from the older {network} editorial era."
        arguments = {"network": network, "media_type": "series", "dateMeaning": meaning}
    elif capability == "cast-routing":
        performer = "Rowan Vale" if split == "train" else "Talia Rune"
        primary["cast"] = [performer]
        arguments = {"cast": [performer], "media_type": "movie", "dateMeaning": meaning}
    elif capability == "creator-routing":
        creator = "Mira Sol" if split == "train" else "Orin Frost"
        primary["creators"] = [creator]
        arguments = {"creators": [creator], "media_type": "movie", "dateMeaning": meaning}
    elif capability == "exact-title-unfamiliar":
        primary["name"] = topic
        arguments = {"query": topic, "media_type": media_type, "dateMeaning": meaning}
    elif capability == "constraint-conflict-abstention":
        conflicted_title = "Amber Signal" if split == "train" else "Indigo Relay"
        primary["name"] = conflicted_title
        must_include = [conflicted_title]
        must_exclude = [conflicted_title]
        arguments = {"query": conflicted_title, "media_type": media_type, "dateMeaning": meaning}
        results, selected, abstain = [[primary]], [], True
    elif capability == "ownership-acquisition-balance":
        primary["inLibrary"] = True
        secondary["inLibrary"] = False
        primary["genres"] = secondary["genres"] = ["Mystery" if split == "train" else "Comedy"]
        results, selected = [[primary, secondary]], [primary["key"], secondary["key"]]
        arguments = {"genres": ["Mystery" if split == "train" else "Comedy"], "dateMeaning": meaning}
    elif capability == "refinement-preservation":
        description = "Quartz Evenings" if split == "train" else "Sable Afternoons"
        refine_text = "make it more international" if split == "train" else "make it more regional"
        current_lineup = [{"name": primary["name"], "year": primary["year"]}]
        primary["overview"] = "Synthetic evidence that preserves the existing channel while satisfying the requested refinement."
        arguments = {"query": primary["name"], "media_type": media_type, "dateMeaning": meaning}
    elif capability == "audience-ceiling":
        primary["genres"] = ["Animation" if split == "train" else "Science Fiction"]
        primary["officialRating"] = "TV-PG" if split == "train" else "TV-14"
        arguments = {"genres": ["Animation" if split == "train" else "Science Fiction"], "dateMeaning": meaning}
    elif capability == "season-window":
        title = "Cedar Street" if split == "train" else "Juniper Hall"
        primary["name"] = title
        arguments = {"query": title, "media_type": "series", "dateMeaning": meaning}
    elif capability == "medium-constraint":
        primary["genres"] = ["Animation"] if split == "train" else ["Adventure"]
        primary["overview"] = "A synthetic animated ocean adventure." if split == "train" else "A synthetic live-action mountain adventure."
        opposite = "series" if media_type == "movie" else "movie"
        secondary = candidate(index, split, opposite, "contrast")
        secondary["genres"] = ["Drama"] if split == "train" else ["Animation"]
        secondary["overview"] = "A synthetic live-action drama." if split == "train" else "A synthetic animated adventure."
        arguments = {"genres": ["Animation" if split == "train" else "Adventure"], "media_type": media_type, "dateMeaning": meaning}
        results, forbidden = [[primary, secondary]], [secondary["key"]]
    elif capability == "language-constraint":
        primary["originalLanguage"] = "fr" if split == "train" else "ja"
        primary["genres"] = ["Comedy" if split == "train" else "Mystery"]
        arguments = {"genres": ["Comedy" if split == "train" else "Mystery"], "original_language": "fr" if split == "train" else "ja", "dateMeaning": meaning}
    elif capability == "region-constraint":
        primary["originCountries"] = ["NZ" if split == "train" else "IE"]
        primary["genres"] = ["Mystery" if split == "train" else "Comedy"]
        arguments = {"genres": ["Mystery" if split == "train" else "Comedy"], "origin_country": "NZ" if split == "train" else "IE", "dateMeaning": meaning}
    elif capability == "thin-results":
        primary["overview"] = f"Synthetic evidence for the narrow {'alpine-noir' if split == 'train' else 'orchard-fantasy'} request."
        arguments = {"keywords": ["alpine-noir" if split == "train" else "orchard-fantasy"], "dateMeaning": meaning}
    elif capability == "empty-results":
        arguments = {"keywords": ["clockwork-western" if split == "train" else "brass-age-musical"], "dateMeaning": meaning}
        results, selected, abstain = [[], []], [], True
    elif capability == "malformed-tool-result":
        results, selected, abstain = [{"error": "malformed_catalog_response"}], [], True
    elif capability == "observed-fault-recovery":
        genre = "Mystery" if split == "train" else "Adventure"
        keywords = ["lunar", "detective"] if split == "train" else ["polar", "expedition"]
        primary["genres"] = [genre]
        primary["keywords"] = keywords
        primary["overview"] = f"A synthetic {genre.lower()} about a {' '.join(keywords)}."
        arguments = {"genres": [genre], "keywords": keywords, "dateMeaning": meaning}
        results = [
            {"error": "transient_catalog_failure", "fault": {"injected": True, "observed": True}},
            [primary],
        ]

    arguments_by_step = [arguments for _ in results]
    if capability == "empty-results":
        arguments_by_step[1] = {
            "query": "clockwork-western" if split == "train" else "brass-age-musical",
            "dateMeaning": meaning,
        }

    intent: dict[str, Any] = {"description": description}
    if refine_text:
        intent["refineText"] = refine_text
        intent["currentLineup"] = current_lineup
    if must_include:
        intent["mustInclude"] = must_include
    if must_exclude:
        intent["mustExclude"] = must_exclude

    return {
        "capability": capability,
        "split": split,
        "description": description,
        "intent": intent,
        "meaning": meaning,
        "arguments": arguments,
        "argumentsByStep": arguments_by_step,
        "results": results,
        "selected": selected,
        "forbidden": forbidden,
        "abstain": abstain,
    }


def final_payload(spec: dict[str, Any]) -> str:
    picks = []
    candidates = [candidate for result in spec["results"] if isinstance(result, list) for candidate in result]
    by_key = {candidate["key"]: candidate for candidate in candidates}
    for key in spec["selected"]:
        item = by_key[key]
        pick: dict[str, Any] = {
            "mediaType": item["mediaType"],
            "key": key,
            "name": item["name"],
            "rationale": "The exact synthetic catalog evidence satisfies the submitted constraints.",
            "confidence": 0.91,
        }
        if spec["capability"] in {"date-series-airing", "season-window"}:
            pick["seasonMin"], pick["seasonMax"] = 1, 3
        if spec["capability"] == "date-series-airing":
            pick["seasonMin"], pick["seasonMax"] = 3, 8
        picks.append(pick)
    policy: dict[str, Any] = {}
    if spec["capability"] == "audience-ceiling":
        policy = {"audience": {"ceiling": "TV-PG" if "family" in spec["description"] else "TV-14"}}
    return json.dumps(
        {
            "channelName": f"Synthetic {spec['capability'].split('-')[0].title()}",
            "rationale": "A bounded proposal grounded only in synthetic catalog evidence." if picks else "No grounded candidate can satisfy the submitted constraints.",
            "dateMeaning": spec["meaning"],
            "picks": picks,
            "policy": policy,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def tool_result_text(result: Any) -> str:
    return json.dumps(result, separators=(",", ":"), ensure_ascii=False)


def training_trace(contract: dict[str, Any], capability: str, index: int) -> dict[str, Any]:
    spec = capability_spec(capability, index, "train")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": contract["systemPrompt"]},
        {"role": "user", "content": user_prompt(spec)},
    ]
    for step_index, (arguments, result) in enumerate(zip(spec["argumentsByStep"], spec["results"], strict=True), 1):
        call_id = f"current-train-{index + 1:02d}-{step_index}"
        messages.extend(
            [
                {"role": "assistant", "toolCalls": [{"id": call_id, "name": "catalog_search", "arguments": arguments}]},
                {"role": "tool", "toolCallId": call_id, "content": tool_result_text(result)},
            ]
        )
    messages.extend(
        [
            {
                "role": "user",
                "content": "Retrieval is complete and no further tools are available. Produce the final JSON now using only the catalog candidates already provided; an incomplete catalog result does not authorize another search. Copy this accepted dateMeaning object unchanged into your final JSON: "
                + json.dumps(spec["meaning"], separators=(",", ":")),
            },
            {"role": "assistant", "content": final_payload(spec)},
        ]
    )
    return {
        "schemaVersion": 1,
        "traceId": f"planner-current-train-{capability}-01",
        "split": "train",
        "axes": [capability],
        "contract": contract_reference(contract, TRAIN_FIXTURE_ID),
        "tools": contract["tools"],
        "messages": messages,
        "review": {"status": "pending", "reviewer": "", "reviewedAt": None, "notes": ""},
        "provenance": {"source": "synthetic", "generator": GENERATOR_ID, "author": "codex:draft", "intent": spec["intent"]},
    }


def development_case(contract: dict[str, Any], capability: str, index: int) -> dict[str, Any]:
    spec = capability_spec(capability, index, "development")
    expectation: dict[str, Any] = {
        "selectedKeys": spec["selected"],
        "forbiddenKeys": spec["forbidden"],
        "dateMeaning": spec["meaning"],
        "abstain": spec["abstain"],
        "maxToolCalls": len(spec["results"]),
    }
    if capability == "observed-fault-recovery":
        expectation["faultInjected"] = True
        expectation["faultObserved"] = True
    return {
        "schemaVersion": 1,
        "caseId": f"planner-current-development-{capability}-01",
        "split": "development-eval",
        "axis": capability,
        "contract": contract_reference(contract, DEVELOPMENT_FIXTURE_ID),
        "intent": spec["intent"],
        "script": [
            {"arguments": arguments, "result": tool_result_text(result)}
            for arguments, result in zip(spec["argumentsByStep"], spec["results"], strict=True)
        ],
        "expectation": expectation,
        "provenance": {"source": "synthetic", "generator": GENERATOR_ID, "author": "codex:fixture", "intent": spec["intent"]},
    }


def build_outputs() -> dict[Path, bytes]:
    contract = json.loads((ROOT / CONTRACT_PATH).read_text(encoding="utf-8"))
    budget_ledger = json.loads((ROOT / "budgets/external-spend-v1.json").read_text(encoding="utf-8"))
    denylist_exact, denylist_normalized, minimum_text_length, protected_keys = load_current_denylist(ROOT / DENYLIST_PATH)
    traces = [training_trace(contract, capability, index) for index, capability in enumerate(CURRENT_CAPABILITIES)]
    development = [development_case(contract, capability, index) for index, capability in enumerate(CURRENT_CAPABILITIES)]
    for trace in traces:
        validate_current_trace(trace, contract, TRAIN_FIXTURE_ID)
        assert_not_denylisted(trace["traceId"], trace, denylist_exact, denylist_normalized, minimum_text_length, protected_keys)
    for case in development:
        validate_current_development_case(case, contract, DEVELOPMENT_FIXTURE_ID)
        assert_not_denylisted(case["caseId"], case, denylist_exact, denylist_normalized, minimum_text_length, protected_keys)
    disjointness = validate_disjoint_splits({"current-training": traces, "current-development": development})

    train_blob, development_blob = jsonl_bytes(traces), jsonl_bytes(development)
    contract_blob = (ROOT / CONTRACT_PATH).read_bytes()
    generator_blob = Path(__file__).read_bytes()
    compatibility = {
        "schemaVersion": 1,
        "reportId": "planner-current-contract-compatibility-v1",
        "contract": {"path": CONTRACT_PATH.as_posix(), "sha256": sha256_bytes(contract_blob)},
        "historicalArtifacts": [legacy_artifact_report(ROOT / path, display_path=path) for path in LEGACY_PATHS],
        "decision": "exclude-all-historical-v3-v4-training-and-development-records",
        "activeMixture": [],
        "candidateMixtureAfterIndependentReview": [TRAIN_PATH.as_posix()],
    }
    if any(item["currentContractCompatibleRecords"] for item in compatibility["historicalArtifacts"]):
        raise SystemExit("historical compatibility report unexpectedly admitted records")
    disjointness_report = {
        "schemaVersion": 1,
        "reportId": "planner-current-disjointness-v1",
        **disjointness,
        "identityOverlap": 0,
        "catalogKeyOverlap": 0,
        "normalizedSemanticOverlap": 0,
        "sealedHoldoutFamilies": list(SEALED_HOLDOUT_FAMILIES),
        "holdoutMaterialized": False,
    }
    plan = {
        "schemaVersion": 1,
        "planId": "planner-current-data-v1",
        "issue": "https://github.com/loomarr/loomarr-models/issues/22",
        "contract": {"path": CONTRACT_PATH.as_posix(), "sha256": sha256_bytes(contract_blob)},
        "holdoutDenylist": {"path": DENYLIST_PATH.as_posix(), "sha256": sha256_bytes((ROOT / DENYLIST_PATH).read_bytes())},
        "capabilityMatrix": list(CURRENT_CAPABILITIES),
        "training": {"path": TRAIN_PATH.as_posix(), "records": len(traces), "sha256": sha256_bytes(train_blob), "reviewStatus": "pending"},
        "development": {"path": DEVELOPMENT_PATH.as_posix(), "records": len(development), "sha256": sha256_bytes(development_blob), "modelExposure": "none"},
        "historicalCompatibility": {"path": COMPATIBILITY_PATH.as_posix()},
        "sealedHoldout": {"families": list(SEALED_HOLDOUT_FAMILIES), "materialized": False, "modelExposure": "none"},
        "recoveryEvidence": {"requiresInjectedFault": True, "requiresObservedFault": True, "applicationBlocker": "https://github.com/loomarr/loomarr/issues/1195"},
        "authority": {
            "externalSpendUsd": "0",
            "providerInferenceAuthorized": False,
            "modelDownloadAuthorized": False,
            "gpuAuthorized": False,
            "trainingAuthorized": False,
            "certificationAuthorized": False,
        },
    }
    baseline = {
        "schemaVersion": 1,
        "experimentId": "planner-current-qwen-stock-baseline-v1",
        "issue": "https://github.com/loomarr/loomarr-models/issues/22",
        "status": "preregistered-no-paid-execution-authorized",
        "model": {
            "candidateId": "qwen38-27b-unsloth-bnb-4bit",
            "repository": "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
            "revision": "8aa5f05d26b7205477066e1449e0af13f762a299",
            "quantization": "unsloth-bnb-4bit",
        },
        "bindings": {
            "contract": {"path": CONTRACT_PATH.as_posix(), "sha256": sha256_bytes(contract_blob)},
            "holdoutDenylist": {"path": DENYLIST_PATH.as_posix(), "sha256": sha256_bytes((ROOT / DENYLIST_PATH).read_bytes())},
            "development": {"path": DEVELOPMENT_PATH.as_posix(), "sha256": sha256_bytes(development_blob), "records": len(development)},
            "dataPlan": {"path": PLAN_PATH.as_posix()},
            "environment": {"path": "environments/qwen38-a40-v1.json", "sha256": sha256_bytes((ROOT / "environments/qwen38-a40-v1.json").read_bytes())},
            "budgetLedger": {"path": "budgets/external-spend-v1.json", "sha256": sha256_bytes((ROOT / "budgets/external-spend-v1.json").read_bytes())},
        },
        "comparison": {
            "seed": 3407,
            "temperature": None,
            "doSample": False,
            "maxNewTokens": 2048,
            "maxModelCallsPerCase": 3,
            "sameCasesAndOrderRequiredForAdapter": True,
        },
        "scoring": {
            "scorerVersion": "planner-current-development-scorer-v1",
            "thresholds": {
                "maxP95ToolCalls": 2,
                "minCorrectToolOperationRate": 0.90,
                "minGroundedCompletionRate": 0.95,
                "minPolicyAccuracyRate": 0.95,
                "minProposalQualityRate": 0.90,
                "minRecoveryRate": 1.0,
                "minSchemaValidityRate": 0.98,
            },
            "passingStockStopsTraining": True,
        },
        "hostedProductionComparison": {
            "status": "preregistered-no-provider-inference-authorized",
            "exactCurrentContractRequired": True,
            "sameCasesAndOrderRequired": True,
            "historicalScoresComparable": False,
            "certificationAuthority": False,
        },
        "decision": {
            "passingStockStopsTraining": True,
            "runtimeOrInfrastructureFailureJustifiesTraining": False,
            "requiresObservedRecoveryFault": True,
            "applicationRecoveryBlocker": "https://github.com/loomarr/loomarr/issues/1195",
        },
        "budget": {
            "aggregateAuthorizationUsd": budget_ledger["authorizationUsd"],
            "currentCommittedUsd": budget_ledger["committedSpendUsd"],
            "outstandingReservationsUsd": budget_ledger["outstandingReservationsUsd"],
            "proposedReservationUsd": "0",
        },
        "authority": {
            "paidBaselineAuthorized": False,
            "modelDownloadAuthorized": False,
            "gpuAuthorized": False,
            "trainingAuthorized": False,
            "certificationAuthority": False,
            "deploymentAuthority": False,
        },
    }
    train_manifest = {
        "schemaVersion": 1,
        "corpusId": "planner-current-training-v1",
        "records": len(traces),
        "sha256": sha256_bytes(train_blob),
        "generator": {"id": GENERATOR_ID, "path": Path(__file__).relative_to(ROOT).as_posix(), "sha256": sha256_bytes(generator_blob)},
        "contract": {"path": CONTRACT_PATH.as_posix(), "sha256": sha256_bytes(contract_blob)},
        "holdoutDenylist": {"path": DENYLIST_PATH.as_posix(), "sha256": sha256_bytes((ROOT / DENYLIST_PATH).read_bytes())},
        "reviewStatus": "pending",
        "trainingAuthorized": False,
    }
    development_manifest = {
        "schemaVersion": 1,
        "evaluationId": "planner-current-development-v1",
        "records": len(development),
        "sha256": sha256_bytes(development_blob),
        "generator": {"id": GENERATOR_ID, "path": Path(__file__).relative_to(ROOT).as_posix(), "sha256": sha256_bytes(generator_blob)},
        "contract": {"path": CONTRACT_PATH.as_posix(), "sha256": sha256_bytes(contract_blob)},
        "holdoutDenylist": {"path": DENYLIST_PATH.as_posix(), "sha256": sha256_bytes((ROOT / DENYLIST_PATH).read_bytes())},
        "modelExposure": "none",
        "certificationAuthority": False,
    }
    return {
        TRAIN_PATH: train_blob,
        TRAIN_MANIFEST_PATH: json_bytes(train_manifest),
        DEVELOPMENT_PATH: development_blob,
        DEVELOPMENT_MANIFEST_PATH: json_bytes(development_manifest),
        COMPATIBILITY_PATH: json_bytes(compatibility),
        DISJOINTNESS_PATH: json_bytes(disjointness_report),
        PLAN_PATH: json_bytes(plan),
        BASELINE_PATH: json_bytes(baseline),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    if args.check:
        drift = [path.as_posix() for path, expected in outputs.items() if not (ROOT / path).is_file() or (ROOT / path).read_bytes() != expected]
        if drift:
            raise SystemExit("generated current-contract artifacts drifted: " + ", ".join(drift))
        return
    for path, content in outputs.items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


if __name__ == "__main__":
    main()
