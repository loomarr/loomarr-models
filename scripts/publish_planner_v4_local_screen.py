#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_v4_delta
import build_planner_v4_local_screen
from loomarr_models.eval_runner import CaseResult, QUALITY_FIELDS, summarize_candidate
from loomarr_models.experiment import PreflightError, _git_probe, sha256_file
from loomarr_models.local_screen import (
    CANDIDATE_IDS,
    SCREEN_ID,
    LocalScreenPlan,
    validate_config,
)


RUNS = ROOT / "runs/planner-v4-local-screen-v1"
EXPOSURE = ROOT / "reviews/planner-v4-local-screen/development-exposure.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the planner v4 local screen evidence")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("experiments/planner-v4-local-screen-v1.json"),
    )
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    try:
        publication = publish(config_path)
    except (PreflightError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(publication, sort_keys=True))


def publish(config_path: Path, *, completed_at: str | None = None) -> dict[str, Any]:
    if RUNS.exists():
        raise PreflightError(f"refusing to overwrite publication: {RUNS.relative_to(ROOT)}")
    config, plan, snapshot, source_config_bytes = _load_source_plan(config_path)
    publication_commit = _git_probe(ROOT, [Path(__file__), config_path])
    frozen_candidates = {item["candidateId"]: item for item in snapshot["candidates"]}
    candidate_evidence = [
        _validate_candidate_manifest(
            ROOT / plan.outputDir / candidate_id,
            candidate_id,
            plan,
            frozen_candidates[candidate_id],
            snapshot["serverVersion"],
            config["scoring"],
        )
        for candidate_id in CANDIDATE_IDS
    ]
    by_candidate = {item["candidateId"]: item for item in candidate_evidence}
    summaries = {
        candidate_id: item["summary"]
        for candidate_id, item in by_candidate.items()
        if item["status"] == "complete"
    }
    if len(summaries) == 2 and summaries[CANDIDATE_IDS[0]]["caseIds"] != summaries[CANDIDATE_IDS[1]]["caseIds"]:
        raise PreflightError("local screen candidate case identities or order differ")
    decision = _decision(by_candidate)
    completed = completed_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    RUNS.mkdir(parents=True)
    source_config = RUNS / "source-experiment.json"
    source_config.write_bytes(source_config_bytes)
    copied: dict[str, dict[str, Any]] = {}
    for evidence in candidate_evidence:
        candidate_id = evidence["candidateId"]
        source = ROOT / plan.outputDir / candidate_id
        destination = RUNS / candidate_id
        shutil.copytree(source, destination)
        copied[candidate_id] = {
            "status": evidence["status"],
            "manifestPath": f"{candidate_id}/run-manifest.json",
            "manifestSha256": sha256_file(destination / "run-manifest.json"),
        }
        if evidence["status"] == "complete":
            copied[candidate_id].update(
                {
                    "resultsSha256": evidence["artifacts"]["results"]["sha256"],
                    "generationsSha256": evidence["artifacts"]["generations"]["sha256"],
                }
            )
        else:
            copied[candidate_id]["failure"] = evidence["failure"]
    publication = {
        "schemaVersion": 1,
        "screenId": SCREEN_ID,
        "status": "complete",
        "completedAt": completed,
        "sourceCommit": plan.sourceCommit,
        "publicationCommit": publication_commit,
        "sourceExperiment": {
            "path": "source-experiment.json",
            "sha256": sha256_file(source_config),
        },
        "externalCostUsd": "0",
        "candidateOrder": list(CANDIDATE_IDS),
        "candidateEvidence": copied,
        "summaries": summaries,
        "decision": decision,
        "authority": config["authority"],
    }
    publication_path = RUNS / "publication.json"
    publication_path.write_text(
        json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    exposure = {
        "schemaVersion": 1,
        "corpusId": "planner-development-v4",
        "status": "local-screen-complete",
        "reservation": {
            "screenId": SCREEN_ID,
            "candidateIds": list(CANDIDATE_IDS),
            "caseCount": plan.caseCount,
            "externalCostUsd": "0",
            "modelRunsPerCandidate": 1,
        },
        "exposures": [
            {
                "screenId": SCREEN_ID,
                "sourceCommit": plan.sourceCommit,
                "completedAt": completed,
                "publicationPath": str(publication_path.relative_to(ROOT)),
                "publicationSha256": sha256_file(publication_path),
                "candidateIds": list(CANDIDATE_IDS),
                "caseCount": plan.caseCount,
            }
        ],
    }
    EXPOSURE.write_text(json.dumps(exposure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_outputs(build_planner_v4_delta.build_outputs())
    build_planner_v4_local_screen.OUTPUT.write_bytes(build_planner_v4_local_screen.content())
    return publication


def _load_source_plan(
    config_path: Path,
) -> tuple[dict[str, Any], LocalScreenPlan, dict[str, Any], bytes]:
    artifact_root = ROOT / ".artifacts/planner-v4-local-screen-v1"
    manifests = [
        json.loads((artifact_root / candidate_id / "run-manifest.json").read_text(encoding="utf-8"))
        for candidate_id in CANDIDATE_IDS
    ]
    source_commits = {manifest.get("sourceCommit") for manifest in manifests}
    config_hashes = {manifest.get("configSha256") for manifest in manifests}
    config_paths = {manifest.get("configPath") for manifest in manifests if manifest.get("configPath")}
    if len(source_commits) != 1 or len(config_hashes) != 1:
        raise PreflightError("local screen candidates do not share one source commit and config")
    source_commit = next(iter(source_commits))
    config_sha = next(iter(config_hashes))
    if not isinstance(source_commit, str) or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise PreflightError("local screen source commit is invalid")
    relative_config = str(config_path.resolve(strict=True).relative_to(ROOT))
    if config_paths and config_paths != {relative_config}:
        raise PreflightError("local screen source config path drifted")
    source_config_bytes = _git_blob(source_commit, relative_config)
    if hashlib.sha256(source_config_bytes).hexdigest() != config_sha:
        raise PreflightError("local screen source config digest differs from committed blob")
    config = json.loads(source_config_bytes)
    if not isinstance(config, dict):
        raise PreflightError("local screen source config is not an object")
    validate_config(config)
    for name, binding in config["bindings"].items():
        blob = _git_blob(source_commit, binding["path"])
        if hashlib.sha256(blob).hexdigest() != binding["sha256"]:
            raise PreflightError(f"local screen source {name} binding differs from commit")
    snapshot = json.loads(
        _git_blob(source_commit, config["bindings"]["ollamaSnapshot"]["path"])
    )
    if snapshot.get("candidates") != config["candidates"]:
        raise PreflightError("local screen source candidates differ from snapshot")
    if config["bindings"]["cases"].get("count") != 120:
        raise PreflightError("local screen source case count drifted")
    expected = {
        "screenId": SCREEN_ID,
        "configSha256": config_sha,
        "casesSha256": config["bindings"]["cases"]["sha256"],
        "contractId": "loomarr-planner-contract-v4",
        "externalCostUsd": "0",
    }
    for manifest in manifests:
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise PreflightError(f"local screen source identity drifted at {key}")
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise PreflightError("local screen source commit is not an ancestor of publication HEAD")
    plan = LocalScreenPlan(
        schemaVersion=1,
        screenId=SCREEN_ID,
        configSha256=config_sha,
        casesSha256=expected["casesSha256"],
        caseCount=120,
        contractId=expected["contractId"],
        sourceCommit=source_commit,
        outputDir=config["execution"]["outputDir"],
        candidateIds=tuple(CANDIDATE_IDS),
        externalCostUsd="0",
    )
    return config, plan, snapshot, source_config_bytes


def _git_blob(commit: str, relative_path: str) -> bytes:
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
        raise PreflightError("local screen source binding escapes repository")
    try:
        return subprocess.check_output(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=ROOT,
        )
    except subprocess.CalledProcessError as exc:
        raise PreflightError(f"cannot read source blob {relative_path} at {commit}") from exc


def _validate_candidate_manifest(
    directory: Path,
    candidate_id: str,
    plan: Any,
    frozen_candidate: dict[str, Any],
    server_version: str,
    scoring: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = directory / "run-manifest.json"
    if not manifest_path.exists():
        raise PreflightError(f"missing local screen manifest for {candidate_id}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schemaVersion") != 1
        or manifest.get("screenId") != SCREEN_ID
        or manifest.get("candidateId") != candidate_id
        or manifest.get("sourceCommit") != plan.sourceCommit
        or manifest.get("configSha256") != plan.configSha256
        or manifest.get("casesSha256") != plan.casesSha256
        or manifest.get("contractId") != plan.contractId
        or manifest.get("externalCostUsd") != "0"
    ):
        raise PreflightError(f"local screen manifest identity drifted for {candidate_id}")
    if manifest.get("status") == "failed":
        _validate_failed_candidate(manifest, candidate_id, plan, frozen_candidate, server_version)
        return manifest
    if manifest.get("status") != "complete" or manifest.get("caseCount") != plan.caseCount:
        raise PreflightError(f"local screen completion status drifted for {candidate_id}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"results", "generations"}:
        raise PreflightError(f"local screen artifact bindings drifted for {candidate_id}")
    for name, binding in artifacts.items():
        path = (directory / binding.get("path", "")).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or sha256_file(path) != binding.get("sha256"):
            raise PreflightError(f"local screen {name} digest mismatch for {candidate_id}")
    results = _jsonl(directory / artifacts["results"]["path"])
    summary = manifest.get("summary")
    if not isinstance(summary, dict) or summary.get("candidateId") != candidate_id:
        raise PreflightError(f"local screen summary drifted for {candidate_id}")
    if summary.get("caseCount") != plan.caseCount or len(results) != plan.caseCount:
        raise PreflightError(f"local screen result count drifted for {candidate_id}")
    result_ids = [item.get("caseId") for item in results]
    if result_ids != summary.get("caseIds"):
        raise PreflightError(f"local screen result identities drifted for {candidate_id}")
    expected_ids_sha = hashlib.sha256(
        json.dumps(result_ids, separators=(",", ":")).encode()
    ).hexdigest()
    if summary.get("caseIdsSha256") != expected_ids_sha:
        raise PreflightError(f"local screen case identity digest drifted for {candidate_id}")
    try:
        recomputed = summarize_candidate(
            candidate_id,
            [CaseResult(**item) for item in results],
            scoring,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise PreflightError(f"local screen results are invalid for {candidate_id}: {exc}") from exc
    if recomputed != summary:
        raise PreflightError(f"local screen summary does not replay for {candidate_id}")
    expected_ollama = {
        "serverVersion": server_version,
        "model": frozen_candidate["model"],
        "digest": frozen_candidate["digest"],
        **{
            key: frozen_candidate[key]
            for key in (
                "parameterCount",
                "contextLength",
                "format",
                "quantization",
                "capabilities",
                "templateSha256",
                "modelfileSha256",
            )
        },
    }
    if manifest.get("ollama") != expected_ollama:
        raise PreflightError(f"local screen model identity drifted for {candidate_id}")
    return manifest


def _validate_failed_candidate(
    manifest: dict[str, Any],
    candidate_id: str,
    plan: Any,
    frozen_candidate: dict[str, Any],
    server_version: str,
) -> None:
    if candidate_id != "qwen38-27b-mlx-nvfp4":
        raise PreflightError("only the observed Qwen local-host failure is accepted")
    if (
        manifest.get("plannedCaseCount") != plan.caseCount
        or manifest.get("completedCaseCount") != 0
        or manifest.get("host")
        != {"platform": "darwin-arm64", "chip": "Apple M5 Pro", "memoryBytes": 25769803776}
        or manifest.get("ollama")
        != {
            "serverVersion": server_version,
            "model": frozen_candidate["model"],
            "digest": frozen_candidate["digest"],
        }
        or manifest.get("failure")
        != {
            "kind": "metal-out-of-memory",
            "httpStatus": 500,
            "phase": "first-case-prefill",
            "promptTokenCount": 3235,
            "peakModelMemoryBytesApprox": 21184926188,
            "message": (
                "MLX Metal command buffer failed with "
                "kIOGPUCommandBufferCallbackErrorOutOfMemory"
            ),
        }
        or manifest.get("disposition") != "ineligible-on-24gb-host-no-automatic-retry"
    ):
        raise PreflightError("Qwen local-host failure evidence drifted")


def _decision(evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    qwen_evidence = evidence[CANDIDATE_IDS[0]]
    gemma_evidence = evidence[CANDIDATE_IDS[1]]
    qwen = qwen_evidence.get("summary")
    gemma = gemma_evidence.get("summary")
    if not isinstance(gemma, dict):
        raise PreflightError("Gemma local screen did not produce a complete summary")
    qwen_failures = (
        _threshold_failures(qwen)
        if isinstance(qwen, dict)
        else ["ineligible-on-24gb-host"]
    )
    gemma_failures = _threshold_failures(gemma)
    if isinstance(qwen, dict) and not qwen_failures:
        outcome = "qlora-not-justified-by-local-screen"
    elif not gemma_failures:
        outcome = "gemma-local-candidate-viable-qwen-authoritative-baseline-required"
    else:
        outcome = "local-screen-rejects-gemma-qwen-authoritative-baseline-required"
    deltas = (
        {field: gemma[field] - qwen[field] for field in QUALITY_FIELDS}
        if isinstance(qwen, dict)
        else None
    )
    return {
        "outcome": outcome,
        "qwenThresholdFailures": qwen_failures,
        "gemmaThresholdFailures": gemma_failures,
        "gemmaMinusQwen": deltas,
        "artifactCaveat": (
            "The local Qwen MLX/NVFP4 artifact is not the pinned Unsloth bitsandbytes "
            "artifact. Qwen could not be scored on the 24 GB host, and neither local result "
            "can certify or release a model."
        ),
        "certificationAuthority": False,
        "trainingAuthorized": False,
        "releaseAuthorized": False,
    }


def _threshold_failures(summary: dict[str, Any]) -> list[str]:
    thresholds = build_planner_v4_local_screen.SCORING["thresholds"]
    failures: list[str] = []
    if summary["hardFailureCount"]:
        failures.append("hardFailureCount")
    mapping = {
        "groundedCompletionRate": "minGroundedCompletionRate",
        "correctToolOperationRate": "minCorrectToolOperationRate",
        "schemaValidityRate": "minSchemaValidityRate",
        "policyAccuracyRate": "minPolicyAccuracyRate",
        "proposalQualityRate": "minProposalQualityRate",
        "recoveryRate": "minRecoveryRate",
    }
    for metric, threshold in mapping.items():
        if summary[metric] < thresholds[threshold]:
            failures.append(metric)
    if summary["p95ToolCalls"] > thresholds["maxP95ToolCalls"]:
        failures.append("p95ToolCalls")
    return failures


def _jsonl(path: Path) -> list[dict[str, Any]]:
    values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not all(isinstance(value, dict) for value in values):
        raise PreflightError(f"{path.name} contains a non-object row")
    return values


def _write_outputs(outputs: dict[Path, bytes]) -> None:
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


if __name__ == "__main__":
    main()
