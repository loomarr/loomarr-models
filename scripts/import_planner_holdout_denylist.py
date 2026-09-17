#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


SOURCE_PREFIX = "internal/eval/testdata/"
SOURCE_PATTERNS = (
    re.compile(r"planner-catalog-v\d+\.json$"),
    re.compile(r"planner-certification-v\d+(?:-base)?\.json$"),
    re.compile(r"planner-release-(?:catalog|sources)-v\d+\.json$"),
    re.compile(r"planner-release-gate-v\d+\.json$"),
    re.compile(r"query-expansion-(?:catalog|sources)-v\d+\.json$"),
    re.compile(r"query-expansion-v\d+\.json$"),
    re.compile(r"query-pilot-(?:catalog|sources)-v\d+\.json$"),
    re.compile(r"query-pilot-v\d+\.json$"),
)
MIN_PROTECTED_TEXT_LENGTH = 1
PROTECTED_KEYS = {
    "acceptableKeys",
    "caseId",
    "description",
    "excerpt",
    "fixtureCase",
    "fixtureId",
    "forbidKeys",
    "forbiddenPrograms",
    "id",
    "key",
    "mustExclude",
    "mustInclude",
    "name",
    "overview",
    "proposalKeys",
    "referenceTitles",
    "requireKeys",
    "requiredPrograms",
    "title",
    "titleAnchors",
    "traceId",
}


def git(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def protected_values(value: Any, protected: bool = False) -> Iterable[str]:
    if isinstance(value, str):
        if protected and len(value.strip()) >= MIN_PROTECTED_TEXT_LENGTH:
            yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from protected_values(item, protected)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from protected_values(item, protected or key in PROTECTED_KEYS)


def selected_paths(repository: Path, revision: str) -> list[str]:
    paths = git(repository, "ls-tree", "-r", "--name-only", revision, SOURCE_PREFIX).decode().splitlines()
    selected = [
        path
        for path in paths
        if any(pattern.fullmatch(path.removeprefix(SOURCE_PREFIX)) for pattern in SOURCE_PATTERNS)
    ]
    if not selected:
        raise SystemExit("no application planner evaluation artifacts matched")
    return sorted(selected)


def build_denylist(repository: Path, revision_name: str) -> dict[str, Any]:
    revision = git(repository, "rev-parse", f"{revision_name}^{{commit}}").decode().strip()
    bindings: list[dict[str, str]] = []
    exact: set[str] = set()
    normalized: set[str] = set()
    for path in selected_paths(repository, revision):
        blob = git(repository, "show", f"{revision}:{path}")
        bindings.append({"path": path, "sha256": digest(blob)})
        try:
            document = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}: invalid JSON at imported revision") from exc
        for value in protected_values(document):
            exact.add(digest(value.encode()))
            normalized.add(digest(normalized_text(value).encode()))
        exact.add(digest(canonical(document)))
    return {
        "schemaVersion": 2,
        "contractId": "loomarr-planner-holdout-denylist-v2",
        "sourceRepository": "https://github.com/loomarr/loomarr",
        "sourceRevision": revision,
        "artifactBindings": bindings,
        "protection": {
            "minimumTextLength": MIN_PROTECTED_TEXT_LENGTH,
            "protectedKeys": sorted(PROTECTED_KEYS),
            "exactValueSha256": sorted(exact),
            "normalizedTextSha256": sorted(normalized),
            "rawApplicationContentStored": False,
        },
    }


def encoded(value: Any) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode() + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("loomarr", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = encoded(build_denylist(args.loomarr, args.revision))
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != expected:
            raise SystemExit(f"{args.output}: imported holdout denylist drifted")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(expected)


if __name__ == "__main__":
    main()
