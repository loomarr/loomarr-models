#!/usr/bin/env python3
"""Import the live filler text contracts from one exact Loomarr commit (issue #37).

Extracts, verbatim, the system prompts for filler text enrichment (single and batch), filler
research, and split rescue, plus the default taxonomy vocabulary those prompts embed. Go raw
string literals have no escapes, so the extracted bytes are exact. The vocabulary is rendered the
way `taxonomy.Forest.Vocab` renders `taxonomy.SeedForest()`, and must match the digest of Go's
own output at the pinned commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("contracts/filler-text-contract-v1.json")
REVISION = "c2fef697729579ba856ab8c7e4b45fe39fd0faec"
# sha256 of `taxonomy.New(taxonomy.SeedForest()).Vocab()` printed by Go at REVISION.
VOCAB_SHA256 = "d8c4d20b071f277c29a30428a76d2f5d1d4a629aeeca0272fa22a123912a4503"
SOURCES = {
    "textEnrichment": "internal/fillerenrichment/text.go",
    "research": "internal/fillerresearch/research.go",
    "splitRescue": "internal/filler/splitrescue.go",
    "splitTranscript": "internal/filler/split.go",
    "taxonomy": "internal/taxonomy/taxonomy.go",
    "taxonomySeed": "internal/taxonomy/seed.go",
    "chatOptions": "internal/llm/llm.go",
}


def git_text(repository: Path, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), "show", f"{REVISION}:{path}"], check=True, capture_output=True
    ).stdout.decode("utf-8")


def raw_literal_in_function(source: str, function: str, variable: str) -> str:
    start = re.search(rf"^func (?:\([^)]*\) )?{function}\(", source, re.MULTILINE)
    if not start:
        raise SystemExit(f"func {function} not found")
    body = source[start.start() :]
    match = re.search(rf"\b{variable} := `(?P<text>[^`]*)`", body)
    if not match:
        raise SystemExit(f"{function}: {variable} raw literal not found")
    return match["text"]


def raw_const(source: str, name: str) -> str:
    match = re.search(rf"const {name} = `(?P<text>[^`]*)`", source)
    if not match:
        raise SystemExit(f"const {name} not found")
    return match["text"]


def string_const(source: str, name: str) -> str:
    match = re.search(rf'const {name} = "(?P<text>[^"]*)"', source)
    if not match:
        raise SystemExit(f"const {name} not found")
    return match["text"]


def int_const(source: str, name: str) -> int:
    match = re.search(rf"\b{name}\s*=\s*(?P<value>\d+)", source)
    if not match:
        raise SystemExit(f"{name} not found")
    return int(match["value"])


def seed_taxa(taxonomy: str, seed: str) -> list[dict]:
    """Parse `SeedForest()` literals; later duplicates of a slug win, as in `taxonomy.New`."""
    axes = dict(re.findall(r'(Axis\w+) Axis = "([^"]+)"', taxonomy))
    by_slug: dict[str, dict] = {}
    for literal in re.findall(r"\{Slug: [^\n]*\}", seed):
        parent = re.search(r'Parent: "([^"]+)"', literal)
        synonyms = re.search(r"Synonyms: \[\]string\{([^}]*)\}", literal)
        slug = re.search(r'Slug: "([^"]+)"', literal)[1]
        by_slug[slug] = {
            "slug": slug,
            "parent": parent[1] if parent else "",
            "axis": axes[re.search(r"Axis: (Axis\w+)", literal)[1]],
            "synonyms": re.findall(r'"([^"]+)"', synonyms[1]) if synonyms else [],
        }
    return sorted(by_slug.values(), key=lambda taxon: (taxon["axis"], taxon["slug"]))


def render_vocab(taxa: list[dict]) -> str:
    lines: dict[str, list[str]] = {}
    for taxon in taxa:
        token = f"{taxon['slug']} (under {taxon['parent']})" if taxon["parent"] else taxon["slug"]
        lines.setdefault(taxon["axis"], []).append(token)
    return "\n".join(f"{axis}: {', '.join(tokens)}" for axis, tokens in lines.items())


def contract(repository: Path) -> dict:
    text = {name: git_text(repository, path) for name, path in SOURCES.items()}
    taxa = seed_taxa(text["taxonomy"], text["taxonomySeed"])
    vocab = render_vocab(taxa)
    if hashlib.sha256(vocab.encode()).hexdigest() != VOCAB_SHA256:
        raise SystemExit("rendered taxonomy vocabulary differs from Go's Vocab() at the pinned revision")
    structured_temperature = float(re.search(r"const StructuredTemperature = ([0-9.]+)", text["chatOptions"])[1])
    return {
        "schemaVersion": 1,
        "contractId": "loomarr-filler-text-contract-v1",
        "source": {
            "repository": "https://github.com/loomarr/loomarr",
            "revision": REVISION,
            "files": [
                {"path": path, "sha256": hashlib.sha256(text[name].encode()).hexdigest()}
                for name, path in sorted(SOURCES.items(), key=lambda item: item[1])
            ],
        },
        "taxonomy": {"vocab": vocab, "sha256": VOCAB_SHA256, "source": "taxonomy.New(taxonomy.SeedForest()).Vocab()", "taxa": taxa},
        "callSites": {
            "filler.text_single": {
                "system": raw_literal_in_function(text["textEnrichment"], "classifyText", "system"),
                "user": "Requested axes: {axes}\nTaxonomy:\n{vocab}\n\nClip text:\n{text}",
                "options": {"jsonMode": True, "temperature": structured_temperature, "reasoningEffort": "none",
                            "maxTokens": int_const(text["textEnrichment"], "textSingleMaxTokens")},
            },
            "filler.text_batch": {
                "system": raw_literal_in_function(text["textEnrichment"], "classifyTextBatch", "system"),
                "user": "Taxonomy:\n{vocab}\n\nClips:\n{items}",
                "options": {"jsonMode": True, "temperature": structured_temperature, "reasoningEffort": "none",
                            "maxTokens": int_const(text["textEnrichment"], "textBatchMaxTokens")},
            },
            "filler.research": {
                "promptVersion": string_const(text["research"], "PromptVersion"),
                "system": raw_literal_in_function(text["research"], "interpret", "system"),
                "user": "Public source title: {title}\nPublic source description: {description}\nRequested context: {requested}\nEvidence packet:\n{packet}",
                "options": {"jsonMode": True, "temperature": structured_temperature,
                            "maxTokens": int_const(text["research"], "researchMaxTokens")},
            },
            "filler.split_rescue": {
                "system": raw_const(text["splitRescue"], "rescueSystemPrompt"),
                "user": "Transcript:\n{transcript}\nFind the advert boundaries.",
                "options": {"jsonMode": True, "temperature": structured_temperature,
                            "maxTokens": int_const(text["splitRescue"], "rescueMaxTokens")},
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loomarr", type=Path, required=True, help="a Loomarr checkout containing the pinned revision")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(contract(args.loomarr), indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"
    target = ROOT / OUTPUT
    if args.check:
        if not target.is_file() or target.read_bytes() != expected:
            raise SystemExit(f"imported artifact drift: {OUTPUT}")
        return
    target.write_bytes(expected)


if __name__ == "__main__":
    main()
