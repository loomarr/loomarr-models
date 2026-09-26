from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .eval_experiment import load_eval_experiment
from .eval_runner import CaseResult, compare_candidates, evaluate_case, summarize_candidate
from .eval_runtime import parse_qwen_turn
from .evaluation import load_cases
from .experiment import PreflightError, _git_probe, _input_path, _output_path, sha256_file
from .validator import load_contract, load_jsonl


REPLAY_CONFIG_KEYS = {
    "schemaVersion",
    "replayId",
    "issue",
    "sourceExperiment",
    "sourceRun",
    "outputDir",
}
SOURCE_RUN_KEYS = {"directory", "runManifest", "artifacts"}
ARTIFACT_KEYS = {
    "stockResults",
    "stockGenerations",
    "adapterResults",
    "adapterGenerations",
    "runLog",
}


class CapturedTurnGenerator:
    def __init__(self, records: Iterable[dict[str, Any]]):
        self.records = list(records)
        self.position = 0

    def __call__(self, _messages: list[dict[str, Any]], _tools: list[dict[str, Any]]) -> dict[str, Any]:
        if self.position >= len(self.records):
            raise PreflightError("captured generation stream ended before replay completed")
        record = self.records[self.position]
        self.position += 1
        return parse_qwen_turn(record["raw"], record["modelCall"])

    def require_consumed(self) -> None:
        if self.position != len(self.records):
            raise PreflightError(
                f"replay consumed {self.position} of {len(self.records)} captured generations"
            )


def replay_evaluation(root: Path, config_path: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = _load_replay_config(config_path)
    source_experiment_path = _bound_path(root, config["sourceExperiment"], "source experiment")
    source_experiment = load_eval_experiment(source_experiment_path)
    source_dir = _input_path(root, Path(config["sourceRun"]["directory"]))
    source_manifest_path = _bound_child(
        source_dir, config["sourceRun"]["runManifest"], "source run manifest"
    )
    source_manifest = _load_object(source_manifest_path, "source run manifest")
    artifacts = {
        name: _bound_child(source_dir, binding, name)
        for name, binding in config["sourceRun"]["artifacts"].items()
    }
    output_dir = _output_path(root, Path(config["outputDir"]))
    if output_dir.exists():
        raise PreflightError(f"refusing to overwrite existing replay output: {output_dir}")

    _validate_source_manifest(source_manifest, source_experiment, config)
    tracked_inputs = [
        config_path,
        source_experiment_path,
        root / "scripts/replay_planner_adapter_eval.py",
        root / "src/loomarr_models/eval_replay.py",
        root / "src/loomarr_models/eval_runtime.py",
        root / "src/loomarr_models/eval_runner.py",
        root / source_experiment["bindings"]["cases"]["path"],
        root / source_experiment["bindings"]["casesManifest"]["path"],
        root / source_experiment["bindings"]["contract"]["path"],
    ]
    replay_commit = _git_probe(root, tracked_inputs)

    cases = load_cases(root / source_experiment["bindings"]["cases"]["path"])
    contract = load_contract(root / source_experiment["bindings"]["contract"]["path"])
    scoring = _load_object(
        root / source_experiment["bindings"]["casesManifest"]["path"], "cases manifest"
    )["scoring"]
    summaries: dict[str, dict[str, Any]] = {}
    replayed_hashes: dict[str, str] = {}
    output_dir.mkdir(parents=True)

    for candidate in source_experiment["comparison"]["candidateOrder"]:
        records = _load_generation_records(artifacts[f"{candidate}Generations"])
        originals = [CaseResult(**item) for item in load_jsonl(artifacts[f"{candidate}Results"])]
        results = replay_candidate(
            cases,
            system_prompt=contract["systemPrompt"],
            tools=contract["tools"],
            records=records,
            originals=originals,
            max_model_calls=source_experiment["comparison"]["maxModelCallsPerCase"],
        )
        result_bytes = b"".join(
            json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for result in results
        )
        result_path = output_dir / f"{candidate}-results.jsonl"
        result_path.write_bytes(result_bytes)
        replayed_hashes[candidate] = hashlib.sha256(result_bytes).hexdigest()
        summaries[candidate] = summarize_candidate(
            candidate,
            results,
            scoring,
            peak_vram_bytes=source_manifest["comparison"][candidate]["peakVramBytes"],
        )

    comparison = compare_candidates(summaries["stock"], summaries["adapter"], scoring)
    manifest = {
        "schemaVersion": 1,
        "runId": "planner-adapter-eval-a40-v1-parser-replay-v1",
        "kind": "deterministic-parser-replay-no-inference",
        "sourceRun": {
            "runId": source_manifest["runId"],
            "runManifestSha256": config["sourceRun"]["runManifest"]["sha256"],
            "rawArtifactSha256": source_manifest["rawArtifactSha256"],
            "runLogSha256": config["sourceRun"]["artifacts"]["runLog"]["sha256"],
            "sourceCommit": source_manifest["preflight"]["sourceCommit"],
            "configSha256": source_manifest["preflight"]["configSha256"],
            "elapsedSeconds": source_manifest["elapsedSeconds"],
        },
        "replay": {
            "sourceCommit": replay_commit,
            "configSha256": sha256_file(config_path),
            "parserSourceSha256": sha256_file(root / "src/loomarr_models/eval_runtime.py"),
            "resultSha256": replayed_hashes,
        },
        "preflight": source_manifest["preflight"],
        "runtime": source_manifest["runtime"],
        "packages": source_manifest["packages"],
        "comparison": comparison,
    }
    manifest_path = output_dir / "run-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def replay_candidate(
    cases: list[dict[str, Any]],
    *,
    system_prompt: str,
    tools: list[dict[str, Any]],
    records: list[dict[str, Any]],
    originals: list[CaseResult],
    max_model_calls: int,
) -> list[CaseResult]:
    if len(cases) != len(originals):
        raise PreflightError("source candidate result count differs from evaluation cases")
    generator = CapturedTurnGenerator(records)
    results: list[CaseResult] = []
    for case, original in zip(cases, originals, strict=True):
        if original.caseId != case["caseId"]:
            raise PreflightError("source candidate case identity or order differs")
        replayed = evaluate_case(
            case,
            system_prompt=system_prompt,
            tools=tools,
            generate=generator,
            max_model_calls=max_model_calls,
        )
        if replayed.modelCalls != original.modelCalls or replayed.toolCalls != original.toolCalls:
            raise PreflightError(f"replay call structure drifted for {original.caseId}")
        results.append(replace(replayed, latencyNanos=original.latencyNanos))
    generator.require_consumed()
    return results


def _load_replay_config(path: Path) -> dict[str, Any]:
    config = _load_object(path, "replay config")
    if set(config) != REPLAY_CONFIG_KEYS or config.get("schemaVersion") != 1:
        raise PreflightError("replay config fields differ from schema v1")
    if config.get("replayId") != "planner-adapter-eval-parser-replay-v1":
        raise PreflightError("unexpected replay id")
    source_run = config.get("sourceRun")
    if not isinstance(source_run, dict) or set(source_run) != SOURCE_RUN_KEYS:
        raise PreflightError("source run fields differ from schema v1")
    artifacts = source_run.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != ARTIFACT_KEYS:
        raise PreflightError("source artifact fields differ from schema v1")
    return config


def _bound_path(root: Path, binding: Any, label: str) -> Path:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise PreflightError(f"invalid {label} binding")
    path = _input_path(root, Path(binding["path"]))
    if sha256_file(path) != binding["sha256"]:
        raise PreflightError(f"{label} digest mismatch")
    return path


def _bound_child(parent: Path, binding: Any, label: str) -> Path:
    if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
        raise PreflightError(f"invalid {label} binding")
    relative = Path(binding["path"])
    if relative.is_absolute():
        raise PreflightError(f"{label} path must be relative")
    path = (parent / relative).resolve(strict=True)
    if not path.is_relative_to(parent):
        raise PreflightError(f"{label} path escapes source directory")
    if sha256_file(path) != binding["sha256"]:
        raise PreflightError(f"{label} digest mismatch")
    return path


def _validate_source_manifest(
    manifest: dict[str, Any], source_experiment: dict[str, Any], config: dict[str, Any]
) -> None:
    expected_raw = {
        "stock": config["sourceRun"]["artifacts"]["stockResults"]["sha256"],
        "stockGenerations": config["sourceRun"]["artifacts"]["stockGenerations"]["sha256"],
        "adapter": config["sourceRun"]["artifacts"]["adapterResults"]["sha256"],
        "adapterGenerations": config["sourceRun"]["artifacts"]["adapterGenerations"]["sha256"],
    }
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("runId") != "planner-adapter-eval-a40-v1"
        or manifest.get("candidateOrder") != ["stock", "adapter"]
        or manifest.get("rawArtifactSha256") != expected_raw
    ):
        raise PreflightError("source run manifest identity or artifact bindings differ")
    preflight = manifest.get("preflight", {})
    if (
        preflight.get("configSha256") != config["sourceExperiment"]["sha256"]
        or preflight.get("casesSha256") != source_experiment["bindings"]["cases"]["sha256"]
        or preflight.get("caseCount") != 50
        or manifest.get("comparison", {}).get("stock", {}).get("caseCount") != 50
        or manifest.get("comparison", {}).get("adapter", {}).get("caseCount") != 50
    ):
        raise PreflightError("source run manifest experiment bindings differ")


def _load_generation_records(path: Path) -> list[dict[str, Any]]:
    records = load_jsonl(path)
    expected_keys = {
        "schemaVersion",
        "modelCall",
        "inputTokens",
        "outputTokens",
        "elapsedSeconds",
        "raw",
        "parsed",
    }
    for index, record in enumerate(records, start=1):
        if (
            set(record) != expected_keys
            or record.get("schemaVersion") != 1
            or record.get("modelCall") != index
            or not isinstance(record.get("raw"), str)
        ):
            raise PreflightError("captured generation record fields or order differ")
    return records


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"{label} must be an object")
    return value
