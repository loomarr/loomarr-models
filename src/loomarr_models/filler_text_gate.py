"""Model-calling gates for Loomarr's live filler text call sites (issue #37).

Requests are rendered from the imported contract exactly as Loomarr renders them (system prompt,
user template, JSON mode, temperature, token bound, thinking off for a self-hosted server).
Scoring mirrors Loomarr's own post-validation, so a case measures what production would store:
- text enrichment normalizes kind/audience, drops an ungrounded brand, and resolves tags through
  slugs and synonyms on the requested axis;
- research clamps confidence and must cite only packet IDs, never a URL;
- split rescue parses mm:ss spans.

Inputs are wholly synthetic: invented brands, products, transcripts, and evidence.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any


CONTRACT = Path("contracts/filler-text-contract-v1.json")
BOUNDARY_TOLERANCE_MS = 3000
KINDS = {"commercial", "bumper", "station_id", "psa", "trailer", "interstitial"}
AUDIENCES = {"kids", "family", "general", "late_night"}
TAG_AXES = {"product": "product", "format": "format", "seasonal": "seasonal",
            "audienceCue": "audience-cue", "presentation": "presentation"}


class Taxonomy:
    def __init__(self, taxa: list[dict[str, Any]]):
        self.by_slug = {t["slug"]: t for t in taxa}
        self.resolver: dict[str, str] = {}
        for taxon in taxa:
            self.resolver[taxon["slug"].strip().lower()] = taxon["slug"]
            for synonym in taxon["synonyms"]:
                self.resolver[synonym.strip().lower()] = taxon["slug"]

    def resolve(self, axis: str, raw: Any) -> list[str]:
        values = raw if isinstance(raw, list) else []
        out: list[str] = []
        for value in values:
            slug = self.resolver.get(str(value).strip().lower())
            if slug and slug not in out and self.by_slug[slug]["axis"] == axis:
                out.append(slug)
        return sorted(out)

    def descendants_or_self(self, slug: str) -> set[str]:
        found = {slug}
        changed = True
        while changed:
            changed = False
            for taxon in self.by_slug.values():
                if taxon["parent"] in found and taxon["slug"] not in found:
                    found.add(taxon["slug"])
                    changed = True
        return found


def fold(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isascii() and ch.isalnum())


def signal_text(signals: dict[str, str]) -> str:
    parts = [signals.get(key, "") for key in ("title", "description", "originalName", "transcript", "visibleText")]
    return "\n".join(part.strip() for part in parts if part.strip())


def transcript_text(lines: list[list[Any]]) -> str:
    return "".join(f"[{ms // 1000 // 60:02d}:{ms // 1000 % 60:02d}] {' '.join(text.split())}\n" for ms, text in lines)


def render(contract: dict[str, Any], case: dict[str, Any]) -> tuple[str, str]:
    site = contract["callSites"][case["callSite"]]
    if case["callSite"] == "filler.text_single":
        user = site["user"].format(axes=", ".join(case["requestedAxes"]), vocab=contract["taxonomy"]["vocab"],
                                   text=signal_text(case["signals"]))
    elif case["callSite"] == "filler.research":
        requested = ", ".join(case["requested"])
        packet = json.dumps(case["packet"], separators=(",", ":"), ensure_ascii=False)
        user = site["user"].format(title=case["title"], description=case["description"], requested=requested, packet=packet)
    elif case["callSite"] == "filler.split_rescue":
        user = site["user"].format(transcript=transcript_text(case["transcript"]))
    else:
        raise ValueError(f"unsupported call site {case['callSite']}")
    return site["system"], user


def request_payload(contract: dict[str, Any], case: dict[str, Any], model: str) -> dict[str, Any]:
    system, user = render(contract, case)
    options = contract["callSites"][case["callSite"]]["options"]
    return {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": options["temperature"],
        "max_tokens": options["maxTokens"],
        "response_format": {"type": "json_object"},
        # Loomarr states thinking off for any JSON request to a self-hosted server.
        "chat_template_kwargs": {"enable_thinking": False},
    }


def call(endpoint: dict[str, Any], api_key: str, payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{endpoint['baseUrl']}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read())
    choice = body["choices"][0]
    return {
        "content": choice["message"].get("content") or "",
        "finishReason": choice.get("finish_reason"),
        "inputTokens": body.get("usage", {}).get("prompt_tokens"),
        "outputTokens": body.get("usage", {}).get("completion_tokens"),
        "elapsedSeconds": time.monotonic() - started,
    }


def extract_json_object(content: str) -> str:
    """Mirror llm.ExtractJSONObject: the first balanced {...}, respecting strings and escapes."""
    start = content.find("{")
    if start < 0:
        return content
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return content  # unbalanced: json.loads reports the real error, as json.Unmarshal does


def parse_output(call_site: str, content: str) -> Any:
    # Split rescue unmarshals the raw reply; the other call sites extract the first JSON object.
    text = content if call_site == "filler.split_rescue" else extract_json_object(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def score(contract: dict[str, Any], taxonomy: Taxonomy, case: dict[str, Any], content: str) -> dict[str, Any]:
    output = parse_output(case["callSite"], content)
    checks: dict[str, bool] = {"json": isinstance(output, dict)}
    if checks["json"]:
        scorer = {"filler.text_single": _score_text, "filler.research": _score_research,
                  "filler.split_rescue": _score_rescue}[case["callSite"]]
        checks.update(scorer(taxonomy, case, output))
    return {"caseId": case["caseId"], "callSite": case["callSite"], "passed": all(checks.values()),
            "checks": checks}


def _score_text(taxonomy: Taxonomy, case: dict[str, Any], output: dict[str, Any]) -> dict[str, bool]:
    expect, checks = case["expect"], {}
    raw_confidence = output.get("confidence")
    checks["confidenceBounded"] = isinstance(raw_confidence, int) and 0 <= raw_confidence <= 80
    for axis, allowed in (("kind", KINDS), ("audience", AUDIENCES)):
        if axis in expect:
            value = str(output.get(axis) or "").strip().lower()
            checks[axis] = (value if value in allowed else "") == expect[axis]
    if "brand" in expect:
        brand = str(output.get("brand") or "").strip()
        grounded = fold(brand) if brand and fold(brand) in fold(signal_text(case["signals"])) else ""
        wanted = fold(expect["brand"])
        # A fuller grounded name ("Fizzleberry Cola" for "Fizzleberry") names the same brand.
        checks["brand"] = grounded == wanted if not wanted or not grounded else (wanted in grounded or grounded in wanted)
    for key, axis in TAG_AXES.items():
        if key not in expect:
            continue
        resolved = set(taxonomy.resolve(axis, output.get(key)))
        wanted = expect[key]
        checks[key] = (not resolved) if not wanted else all(resolved & taxonomy.descendants_or_self(slug) for slug in wanted)
    return checks


def _score_research(_taxonomy: Taxonomy, case: dict[str, Any], output: dict[str, Any]) -> dict[str, bool]:
    expect, checks = case["expect"], {}
    ids = {citation["id"] for citation in case["packet"]}
    cited = output.get("citationIds")
    checks["citationsValid"] = isinstance(cited, list) and all(isinstance(i, int) and i in ids for i in cited)
    checks["noUrl"] = not re.search(r"https?://|www\.", json.dumps(output))
    confidence = output.get("confidence")
    checks["confidenceBounded"] = isinstance(confidence, (int, float)) and 0 <= confidence <= 80
    year, decade = output.get("year") or 0, output.get("decade") or 0
    country = str(output.get("countryCode") or "").strip().upper()
    if expect["abstain"]:
        checks["abstained"] = year == 0 and decade == 0 and country == ""
    else:
        if "decade" in expect:
            checks["decade"] = decade == expect["decade"] or (year and year // 10 * 10 == expect["decade"])
        if "year" in expect:
            checks["year"] = year == expect["year"]
        if "countryCode" in expect:
            checks["countryCode"] = country == expect["countryCode"]
    # Only the answer fields count; the explanation may legitimately mention what it ignored.
    answer = json.dumps({key: output.get(key) for key in ("year", "decade", "countryCode", "country")})
    for forbidden in expect.get("forbiddenValues", []):
        checks[f"ignored:{forbidden}"] = str(forbidden) not in answer
    return checks


def _mmss(value: Any) -> int | None:
    parts = str(value).strip().split(":")
    if not 1 <= len(parts) <= 3:
        return None
    seconds, multiplier = 0.0, 1.0
    for part in reversed(parts):
        try:
            seconds += float(part.strip()) * multiplier
        except ValueError:
            return None
        multiplier *= 60
    return int(seconds * 1000)


def _score_rescue(_taxonomy: Taxonomy, case: dict[str, Any], output: dict[str, Any]) -> dict[str, bool]:
    expect, spans = case["expect"], []
    for advert in output.get("adverts") or []:
        if not isinstance(advert, dict):
            continue
        start, end = _mmss(advert.get("start")), _mmss(advert.get("end"))
        if start is None or end is None or end <= start:
            continue
        spans.append((start, end, " ".join(str(advert.get("product") or "").split()) or "unknown"))
    spans.sort()
    checks = {"advertCount": len(spans) == len(expect["products"])}
    if checks["advertCount"]:
        boundaries = [start for start, _end, _product in spans[1:]]
        checks["boundaries"] = all(abs(got - want) <= BOUNDARY_TOLERANCE_MS for got, want in zip(boundaries, expect["boundariesMs"]))
        checks["products"] = all(
            (want == "unknown" and fold(got) in {"unknown", ""}) or (want != "unknown" and fold(want) in fold(got))
            for (_s, _e, got), want in zip(spans, expect["products"])
        )
    return checks


def load_contract(root: Path) -> tuple[dict[str, Any], Taxonomy]:
    contract = json.loads((root / CONTRACT).read_text(encoding="utf-8"))
    return contract, Taxonomy(contract["taxonomy"]["taxa"])
