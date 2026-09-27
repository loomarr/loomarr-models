#!/usr/bin/env python3
"""Aggregate repeated Flash-Next screen trials per case set and prompt.

Served greedy decoding is not batch-invariant: two identical runs flipped 6 of 24 cases. So a
prompt is judged on per-capability pass rates across trials, never on a single run.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATES = {
    "dev": "runs/planner-current-flash-next-screen-v2",
    "train-split": "runs/planner-current-flash-next-screen-v2-trainsplit",
}
LABEL = re.compile(r"^default(?:--(?!t\d+$)(?P<prompt>[a-z0-9-]+?))?(?:--t(?P<trial>\d+))?$")


def collect() -> dict:
    report: dict = {"schemaVersion": 1, "sets": {}}
    for name, directory in GATES.items():
        prompts: dict[str, dict] = {}
        for run in sorted((ROOT / directory).iterdir()):
            match = LABEL.match(run.name)
            if not match:
                continue
            prompt = match["prompt"] or "production"
            results = [json.loads(line) for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            entry = prompts.setdefault(prompt, {"trials": 0, "passed": [], "capabilities": {}})
            entry["trials"] += 1
            entry["passed"].append(sum(not r["hardFailures"] for r in results))
            for r in results:
                entry["capabilities"].setdefault(r["axis"], 0)
                entry["capabilities"][r["axis"]] += not r["hardFailures"]
        for entry in prompts.values():
            entry["meanPassed"] = round(statistics.mean(entry["passed"]), 2)
            entry["rangePassed"] = [min(entry["passed"]), max(entry["passed"])]
            entry["capabilities"] = {k: round(v / entry["trials"], 2) for k, v in sorted(entry["capabilities"].items())}
        report["sets"][name] = prompts
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", type=Path, help="write the JSON report to this path")
    args = parser.parse_args()
    report = collect()
    if args.write:
        args.write.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, prompts in report["sets"].items():
        print(f"\n== {name}")
        for prompt, entry in prompts.items():
            print(f"  {prompt:12} trials={entry['trials']} mean passed={entry['meanPassed']:5} range={entry['rangePassed']}")
        names = list(prompts)
        if len(names) > 1:
            base, other = prompts["production"], prompts[[n for n in names if n != "production"][0]]
            print(f"  {'capability':32} {'production':>10} {names[-1]:>12}")
            for capability, rate in base["capabilities"].items():
                delta = other["capabilities"][capability] - rate
                flag = "  +" if delta >= 0.4 else ("  -" if delta <= -0.4 else "")
                print(f"  {capability:32} {rate:10.2f} {other['capabilities'][capability]:12.2f}{flag}")


if __name__ == "__main__":
    main()
