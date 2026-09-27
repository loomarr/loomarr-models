#!/usr/bin/env python3
"""Run the synthetic filler text gate against the served Flash-Next endpoint (issue #37)."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.experiment import _git_probe
from loomarr_models.filler_text_gate import CONTRACT, call, load_contract, request_payload, score
from loomarr_models.flash_next_screen import ENDPOINT, read_api_key


EXPERIMENT_ID = "filler-text-gate-v1"
CASES = Path("evaluation/filler-text-v1/cases.jsonl")
INPUTS = [CONTRACT, CASES, Path("evaluation/filler-text-v1/manifest.json"),
          Path("src/loomarr_models/filler_text_gate.py"), Path("scripts/run_filler_text_gate.py")]


def run(trial: int) -> dict:
    output = ROOT / ".artifacts" / EXPERIMENT_ID / "flash-next-served" / f"t{trial}"
    if output.exists():
        raise SystemExit(f"refusing to overwrite {output}")
    source_commit = _git_probe(ROOT, [ROOT / path for path in INPUTS])
    contract, taxonomy = load_contract(ROOT)
    cases = [json.loads(line) for line in (ROOT / CASES).read_text(encoding="utf-8").splitlines()]
    api_key = read_api_key(Path(ENDPOINT["apiKeyFile"]))
    results, generations = [], []
    started = time.monotonic()
    for case in cases:
        reply = call(ENDPOINT, api_key, request_payload(contract, case, ENDPOINT["modelAlias"]))
        results.append(score(contract, taxonomy, case, reply["content"]))
        generations.append({"caseId": case["caseId"], **reply})
        print(f"{case['caseId']}: {'pass' if results[-1]['passed'] else 'FAIL'}", flush=True)
    output.mkdir(parents=True)
    blobs = {name: b"".join(json.dumps(r, sort_keys=True, separators=(",", ":")).encode() + b"\n" for r in rows)
             for name, rows in (("results.jsonl", results), ("generations.jsonl", generations))}
    for name, blob in blobs.items():
        (output / name).write_bytes(blob)
    by_site: dict[str, list[bool]] = {}
    for result in results:
        by_site.setdefault(result["callSite"], []).append(result["passed"])
    manifest = {
        "schemaVersion": 1, "experimentId": EXPERIMENT_ID, "candidate": "flash-next-served", "trial": trial,
        "sourceCommit": source_commit, "endpoint": {k: ENDPOINT[k] for k in ("baseUrl", "modelAlias")},
        "elapsedSeconds": time.monotonic() - started, "externalSpendUsd": "0",
        "passed": sum(r["passed"] for r in results), "cases": len(results),
        "byCallSite": {site: {"passed": sum(v), "cases": len(v)} for site, v in sorted(by_site.items())},
        "artifacts": {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()},
    }
    (output / "run-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.publish:
        source, target = ROOT / ".artifacts" / EXPERIMENT_ID, ROOT / "runs" / EXPERIMENT_ID
        if target.exists():
            raise SystemExit(f"refusing to overwrite {target}")
        shutil.copytree(source, target)
        print(json.dumps({"published": str(target.relative_to(ROOT))}))
        return
    for trial in range(1, args.trials + 1):
        manifest = run(trial)
        print(json.dumps({k: manifest[k] for k in ("trial", "passed", "cases", "byCallSite")}), flush=True)


if __name__ == "__main__":
    main()
