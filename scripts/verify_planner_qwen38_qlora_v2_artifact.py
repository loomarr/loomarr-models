#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path("experiments/planner-qwen38-qlora-v2.json")
EXPECTED_MANIFEST_KEYS = {
    "schemaVersion",
    "preflight",
    "runId",
    "elapsedSeconds",
    "completedSteps",
    "renderedTrainingSha256",
    "packages",
    "runtime",
    "metrics",
    "adapterFiles",
    "loadProbe",
}


class ArtifactVerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactVerificationError(f"{label} must be an object")
    return value


def verify_artifact(
    root: Path,
    config_path: Path,
    artifact_dir: Path,
    expected_source_commit: str,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = _inside(root, config_path, must_exist=True)
    artifact_dir = _inside(root, artifact_dir, must_exist=True)
    config = load_object(config_path, "experiment config")
    if config.get("experimentId") != "planner-qwen38-qlora-v2":
        raise ArtifactVerificationError("unexpected experiment identity")
    if config.get("status") != "ready-for-training":
        raise ArtifactVerificationError("experiment is not the authorized training state")
    expected_artifact_dir = (root / config["execution"]["outputDir"]).resolve()
    if artifact_dir != expected_artifact_dir:
        raise ArtifactVerificationError("artifact directory differs from the experiment output")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source_commit):
        raise ArtifactVerificationError("expected source commit must be a lowercase 40-hex SHA")

    manifest_path = artifact_dir / "run-manifest.json"
    manifest = load_object(manifest_path, "run manifest")
    if set(manifest) != EXPECTED_MANIFEST_KEYS or manifest.get("schemaVersion") != 1:
        raise ArtifactVerificationError("run manifest fields differ from schema v1")
    run = config["runs"][0]
    if manifest["runId"] != run["runId"]:
        raise ArtifactVerificationError("run identity differs from the experiment")
    if manifest["completedSteps"] != run["maxSteps"]:
        raise ArtifactVerificationError("training did not complete the exact step count")
    elapsed = manifest["elapsedSeconds"]
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not 0 < elapsed <= config["execution"]["maxWallClockSeconds"]
    ):
        raise ArtifactVerificationError("training elapsed time is outside the execution envelope")

    _verify_preflight(root, config_path, config, manifest["preflight"], expected_source_commit)
    _verify_runtime(root, config, manifest)
    _verify_output_tree(artifact_dir)
    adapter_hashes = _verify_adapter_files(artifact_dir / "adapter", manifest["adapterFiles"])
    probe = manifest["loadProbe"]
    if (
        not isinstance(probe, dict)
        or set(probe) != {"activeAdapter", "generatedTokenCount", "outputSha256"}
        or not probe["activeAdapter"]
        or isinstance(probe["generatedTokenCount"], bool)
        or not isinstance(probe["generatedTokenCount"], int)
        or not 1 <= probe["generatedTokenCount"] <= 8
        or not re.fullmatch(r"[0-9a-f]{64}", probe["outputSha256"])
    ):
        raise ArtifactVerificationError("persisted adapter load probe is invalid")

    return {
        "schemaVersion": 1,
        "experimentId": config["experimentId"],
        "runId": manifest["runId"],
        "sourceCommit": expected_source_commit,
        "completedSteps": manifest["completedSteps"],
        "manifestSha256": sha256_file(manifest_path),
        "adapterFileCount": len(adapter_hashes),
        "adapterModelSha256": adapter_hashes["adapter_model.safetensors"],
        "loadProbeOutputSha256": probe["outputSha256"],
        "status": "verified-adapter-only-artifact",
    }


def _verify_preflight(
    root: Path,
    config_path: Path,
    config: dict[str, Any],
    preflight: Any,
    expected_source_commit: str,
) -> None:
    if not isinstance(preflight, dict):
        raise ArtifactVerificationError("run preflight must be an object")
    environment_path = root / config["bindings"]["environment"]["path"]
    environment = load_object(environment_path, "environment")
    if sha256_file(environment_path) != config["bindings"]["environment"]["sha256"]:
        raise ArtifactVerificationError("environment digest differs from the experiment")
    budget = load_object(root / config["bindings"]["budget"]["path"], "budget ledger")
    committed = Decimal(budget["committedSpendUsd"])
    reservation = Decimal(config["execution"]["maxReservationUsd"])
    expected = {
        "schemaVersion": 1,
        "experimentId": config["experimentId"],
        "configSha256": sha256_file(config_path),
        "corpusSha256": config["bindings"]["corpus"]["sha256"],
        "traceCount": config["bindings"]["corpus"]["traceCount"],
        "approvedCount": config["bindings"]["corpus"]["traceCount"],
        "environmentSha256": config["bindings"]["environment"]["sha256"],
        "environmentId": environment["environmentId"],
        "upstreamRevision": config["models"]["upstream"]["revision"],
        "trainingArtifactRevision": config["models"]["trainingArtifact"]["revision"],
        "committedSpendUsd": str(committed),
        "reservationUsd": str(reservation),
        "projectedSpendUsd": str(committed + reservation),
        "authorizationUsd": str(Decimal(budget["authorizationUsd"])),
        "sourceCommit": expected_source_commit,
        "outputDir": config["execution"]["outputDir"],
    }
    if preflight != expected:
        raise ArtifactVerificationError("run preflight differs from the bound experiment")


def _verify_runtime(root: Path, config: dict[str, Any], manifest: dict[str, Any]) -> None:
    environment = load_object(
        root / config["bindings"]["environment"]["path"], "environment"
    )
    packages = manifest["packages"]
    expected_packages = {
        "unsloth": environment["trainingPackages"]["unsloth"],
        "unsloth-zoo": environment["trainingPackages"]["unsloth_zoo"],
        "transformers": environment["trainingPackages"]["transformers"],
        "trl": environment["trainingPackages"]["trl"],
        "peft": environment["trainingPackages"]["peft"],
    }
    if not isinstance(packages, dict) or any(
        packages.get(key) != value for key, value in expected_packages.items()
    ):
        raise ArtifactVerificationError(
            "training package versions differ from the environment lock"
        )
    runtime = manifest["runtime"]
    gpu = runtime.get("gpu") if isinstance(runtime, dict) else None
    metrics = manifest["metrics"]
    if (
        not isinstance(runtime, dict)
        or not str(runtime.get("python", "")).startswith(environment["python"] + ".")
        or runtime.get("cuda") != "12.8"
        or not isinstance(gpu, list)
        or len(gpu) != config["execution"]["gpuCount"]
        or not isinstance(gpu[0], dict)
        or gpu[0].get("name") != config["execution"]["gpuSku"]
        or gpu[0].get("totalMemoryBytes", 0) < 47_000_000_000
        or gpu[0].get("peakReservedBytes", 0) <= 0
    ):
        raise ArtifactVerificationError("runtime differs from the A40 execution envelope")
    if (
        not isinstance(metrics, dict)
        or isinstance(metrics.get("train_runtime"), bool)
        or not isinstance(metrics.get("train_runtime"), (int, float))
        or not 0 < metrics["train_runtime"] <= manifest["elapsedSeconds"]
    ):
        raise ArtifactVerificationError("training metrics are invalid")


def _verify_output_tree(artifact_dir: Path) -> None:
    allowed_top_level = {"adapter", "trainer", "run-manifest.json"}
    unexpected = {path.name for path in artifact_dir.iterdir()} - allowed_top_level
    if unexpected:
        raise ArtifactVerificationError("artifact output contains unexpected top-level entries")
    for path in artifact_dir.rglob("*"):
        if path.is_symlink():
            raise ArtifactVerificationError("artifact output contains a symlink")
        if not path.is_file():
            continue
        if (
            path.name
            in {"model.safetensors", "model.safetensors.index.json", "pytorch_model.bin"}
            or path.suffix.lower() in {".gguf", ".pt", ".pth"}
        ):
            raise ArtifactVerificationError("merged or base-model weights are forbidden")


def _verify_adapter_files(adapter_dir: Path, recorded: Any) -> dict[str, str]:
    if not adapter_dir.is_dir() or adapter_dir.is_symlink():
        raise ArtifactVerificationError("adapter output is missing or is a symlink")
    actual: dict[str, str] = {}
    for path in sorted(adapter_dir.rglob("*")):
        if path.is_symlink():
            raise ArtifactVerificationError("adapter output contains a symlink")
        if path.is_file():
            relative = str(path.relative_to(adapter_dir))
            if path.stat().st_size == 0:
                raise ArtifactVerificationError(f"adapter output is empty: {relative}")
            actual[relative] = sha256_file(path)
    if recorded != actual:
        raise ArtifactVerificationError("adapter file inventory or digest differs from the manifest")
    required = {"adapter_config.json", "adapter_model.safetensors", "tokenizer.json"}
    if not required.issubset(actual):
        raise ArtifactVerificationError("required adapter or tokenizer files are missing")
    adapter_config = load_object(adapter_dir / "adapter_config.json", "adapter config")
    if (
        adapter_config.get("peft_type") != "LORA"
        or adapter_config.get("r") != 8
        or adapter_config.get("lora_alpha") != 8
        or adapter_config.get("lora_dropout") != 0
    ):
        raise ArtifactVerificationError("adapter configuration differs from the QLoRA plan")
    return actual


def _inside(root: Path, path: Path, *, must_exist: bool) -> Path:
    candidate = (
        path.resolve(strict=must_exist)
        if path.is_absolute()
        else (root / path).resolve(strict=must_exist)
    )
    if not candidate.is_relative_to(root):
        raise ArtifactVerificationError(f"path escapes repository: {path}")
    return candidate


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the QLoRA v2 adapter-only artifact"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = load_object(config_path, "experiment config")
    artifact_dir = args.artifact_dir or Path(config["execution"]["outputDir"])
    expected_source_commit = args.expected_source_commit or _git_head(ROOT)
    try:
        report = verify_artifact(ROOT, config_path, artifact_dir, expected_source_commit)
    except ArtifactVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
