#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_planner_v4_delta
import build_planner_v4_local_screen
from loomarr_models.eval_runner import CaseResult, QUALITY_FIELDS, summarize_candidate
from loomarr_models.experiment import PreflightError, sha256_file
from loomarr_models.local_screen import CANDIDATE_IDS, SCREEN_ID, build_plan


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
    config, plan, snapshot = build_plan(ROOT, config_path)
    if RUNS.exists():
        raise PreflightError(f"refusing to overwrite publication: {RUNS.relative_to(ROOT)}")
    frozen_candidates = {item["candidateId"]: item for item in snapshot["candidates"]}
    candidate_evidence = [
        _validate_candidate_manifest(
            ROOT / plan.outputDir / candidate_id,
            candidate_id,
            plan,
            frozen_candidates[candidate_id],
            config["scoring"],
        )
        for candidate_id in CANDIDATE_IDS
    ]
    summaries = {item["candidateId"]: item["summary"] for item in candidate_evidence}
    if summaries[CANDIDATE_IDS[0]]["caseIds"] != summaries[CANDIDATE_IDS[1]]["caseIds"]:
        raise PreflightError("local screen candidate case identities or order differ")
    decision = _decision(summaries)
    completed = completed_at or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    RUNS.mkdir(parents=True)
    source_config = RUNS / "source-experiment.json"
    source_config.write_bytes(config_path.read_bytes())
    copied: dict[str, dict[str, Any]] = {}
    for evidence in candidate_evidence:
        candidate_id = evidence["candidateId"]
        source = ROOT / plan.outputDir / candidate_id
        destination = RUNS / candidate_id
        shutil.copytree(source, destination)
        copied[candidate_id] = {
            "manifestPath": f"{candidate_id}/run-manifest.json",
            "manifestSha256": sha256_file(destination / "run-manifest.json"),
            "resultsSha256": evidence["artifacts"]["results"]["sha256"],
            "generationsSha256": evidence["artifacts"]["generations"]["sha256"],
        }
    publication = {
        "schemaVersion": 1,
        "screenId": SCREEN_ID,
        "status": "complete",
        "completedAt": completed,
        "sourceCommit": plan.sourceCommit,
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


def _validate_candidate_manifest(
    directory: Path,
    candidate_id: str,
    plan: Any,
    frozen_candidate: dict[str, Any],
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
        or manifest.get("status") != "complete"
        or manifest.get("sourceCommit") != plan.sourceCommit
        or manifest.get("configSha256") != plan.configSha256
        or manifest.get("casesSha256") != plan.casesSha256
        or manifest.get("caseCount") != plan.caseCount
        or manifest.get("contractId") != plan.contractId
        or manifest.get("externalCostUsd") != "0"
    ):
        raise PreflightError(f"local screen manifest identity drifted for {candidate_id}")
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
        "serverVersion": json.loads(
            (ROOT / "reviews/planner-v4-local-screen/ollama-snapshot.json").read_text(
                encoding="utf-8"
            )
        )["serverVersion"],
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


def _decision(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    qwen = summaries[CANDIDATE_IDS[0]]
    gemma = summaries[CANDIDATE_IDS[1]]
    qwen_failures = _threshold_failures(qwen)
    gemma_failures = _threshold_failures(gemma)
    if not qwen_failures:
        outcome = "qlora-not-justified-by-local-screen"
    elif not gemma_failures:
        outcome = "change-base-candidate-before-training"
    else:
        outcome = "authoritative-a40-baseline-required-before-training"
    deltas = {field: gemma[field] - qwen[field] for field in QUALITY_FIELDS}
    return {
        "outcome": outcome,
        "qwenThresholdFailures": qwen_failures,
        "gemmaThresholdFailures": gemma_failures,
        "gemmaMinusQwen": deltas,
        "artifactCaveat": (
            "The local Qwen MLX/NVFP4 artifact is not the pinned Unsloth bitsandbytes "
            "artifact and cannot certify or release a model."
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
