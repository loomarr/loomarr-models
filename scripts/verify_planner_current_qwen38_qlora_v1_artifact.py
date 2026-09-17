#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loomarr_models.current_training import EXPERIMENT_ID, load_config, preflight
from loomarr_models.experiment import PreflightError


DEFAULT_CONFIG = Path("experiments/planner-current-qwen38-qlora-v1.json")
MANIFEST_KEYS = {
    "schemaVersion", "experimentId", "status", "preflight", "runId", "elapsedSeconds",
    "completedSteps", "renderedTrainingSha256", "renderedTokenCounts", "packages", "runtime",
    "metrics", "adapterFiles", "loadProbe", "providerCostUsd", "authority",
}


class ArtifactVerificationError(ValueError):
    pass


def verify_artifact(
    root: Path,
    config_path: Path,
    artifact_dir: Path,
    expected_source_commit: str,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    config_path = _inside(root, config_path, must_exist=True)
    artifact_dir = _inside(root, artifact_dir, must_exist=True)
    config = load_config(config_path)
    if config.get("experimentId") != EXPERIMENT_ID or config.get("status") != "ready-for-training":
        raise ArtifactVerificationError("current QLoRA experiment is not in the authorized training state")
    if artifact_dir != (root / config["execution"]["outputDir"]).resolve():
        raise ArtifactVerificationError("artifact directory differs from the current QLoRA output")
    if re.fullmatch(r"[0-9a-f]{40}", expected_source_commit) is None:
        raise ArtifactVerificationError("expected source commit must be lowercase 40-hex")
    manifest_path = artifact_dir / "run-manifest.json"
    manifest = _object(manifest_path)
    if set(manifest) != MANIFEST_KEYS or manifest.get("schemaVersion") != 1:
        raise ArtifactVerificationError("current QLoRA run manifest fields drifted")
    run = config["runs"][0]
    if (
        manifest["experimentId"] != EXPERIMENT_ID
        or manifest["status"] != "complete-unsettled"
        or manifest["runId"] != run["runId"]
        or manifest["completedSteps"] != run["maxSteps"]
        or manifest["providerCostUsd"] is not None
        or manifest["authority"] != config["authority"]
        or isinstance(manifest["elapsedSeconds"], bool)
        or not isinstance(manifest["elapsedSeconds"], (int, float))
        or not 0 < manifest["elapsedSeconds"] <= config["execution"]["maxWallClockSeconds"]
    ):
        raise ArtifactVerificationError("current QLoRA run identity or completion drifted")
    try:
        expected_plan = preflight(
            root,
            config_path,
            require_authorized=True,
            git_probe=lambda *_: expected_source_commit,
        )
    except PreflightError as exc:
        raise ArtifactVerificationError(str(exc)) from exc
    if manifest["preflight"] != expected_plan.as_dict():
        raise ArtifactVerificationError("current QLoRA run preflight differs from the bound experiment")
    capacity = _object(root / config["bindings"]["capacityReport"]["path"])
    expected_counts = [row["tokens"] for row in capacity["measurements"]]
    if (
        manifest["renderedTokenCounts"] != expected_counts
        or manifest["renderedTrainingSha256"] != capacity["renderedTrainingSha256"]
    ):
        raise ArtifactVerificationError("current QLoRA rendered training identity drifted")
    _verify_runtime(root, config, manifest)
    _verify_output_tree(artifact_dir)
    adapter_hashes = _verify_adapter(artifact_dir / "adapter", manifest["adapterFiles"])
    probe = manifest["loadProbe"]
    if (
        not isinstance(probe, dict)
        or set(probe) != {"activeAdapter", "generatedTokenCount", "outputSha256"}
        or not probe["activeAdapter"]
        or not isinstance(probe["generatedTokenCount"], int)
        or not 1 <= probe["generatedTokenCount"] <= 8
        or re.fullmatch(r"[0-9a-f]{64}", probe["outputSha256"]) is None
    ):
        raise ArtifactVerificationError("current QLoRA persisted-adapter load probe is invalid")
    return {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "runId": manifest["runId"],
        "sourceCommit": expected_source_commit,
        "completedSteps": manifest["completedSteps"],
        "manifestSha256": _sha(manifest_path),
        "adapterFileCount": len(adapter_hashes),
        "adapterModelSha256": adapter_hashes["adapter_model.safetensors"],
        "loadProbeOutputSha256": probe["outputSha256"],
        "status": "verified-adapter-only-artifact",
    }


def _verify_runtime(root: Path, config: dict[str, Any], manifest: dict[str, Any]) -> None:
    environment = _object(root / config["bindings"]["environment"]["path"])
    expected_packages = {
        "unsloth": environment["trainingPackages"]["unsloth"],
        "unsloth-zoo": environment["trainingPackages"]["unsloth_zoo"],
        "transformers": environment["trainingPackages"]["transformers"],
        "trl": environment["trainingPackages"]["trl"],
        "peft": environment["trainingPackages"]["peft"],
    }
    packages = manifest["packages"]
    if not isinstance(packages, dict) or any(packages.get(key) != value for key, value in expected_packages.items()):
        raise ArtifactVerificationError("current QLoRA packages differ from the locked environment")
    runtime = manifest["runtime"]
    gpu = runtime.get("gpu") if isinstance(runtime, dict) else None
    if (
        not isinstance(runtime, dict)
        or not str(runtime.get("python", "")).startswith(environment["python"] + ".")
        or not str(runtime.get("cuda", "")).startswith(config["execution"]["minimumCudaVersion"])
        or not isinstance(gpu, dict)
        or config["execution"]["gpuSku"] not in str(gpu.get("name", ""))
        or gpu.get("totalMemoryBytes", 0) < 47_000_000_000
        or not 0 < gpu.get("peakReservedBytes", 0) <= gpu.get("totalMemoryBytes", 0)
    ):
        raise ArtifactVerificationError("current QLoRA runtime differs from the A40 envelope")
    metrics = manifest["metrics"]
    if (
        not isinstance(metrics, dict)
        or isinstance(metrics.get("train_runtime"), bool)
        or not isinstance(metrics.get("train_runtime"), (int, float))
        or not 0 < metrics["train_runtime"] <= manifest["elapsedSeconds"]
    ):
        raise ArtifactVerificationError("current QLoRA training metrics are invalid")


def _verify_output_tree(artifact_dir: Path) -> None:
    if {path.name for path in artifact_dir.iterdir()} - {"adapter", "trainer", "run-manifest.json"}:
        raise ArtifactVerificationError("current QLoRA artifact contains unexpected top-level entries")
    for path in artifact_dir.rglob("*"):
        if path.is_symlink():
            raise ArtifactVerificationError("current QLoRA artifact contains a symlink")
        if path.is_file() and (
            path.name in {"model.safetensors", "model.safetensors.index.json", "pytorch_model.bin"}
            or path.suffix.lower() in {".gguf", ".pt", ".pth"}
        ):
            raise ArtifactVerificationError("merged or base-model weights are forbidden")


def _verify_adapter(adapter_dir: Path, recorded: Any) -> dict[str, str]:
    if not adapter_dir.is_dir() or adapter_dir.is_symlink():
        raise ArtifactVerificationError("current QLoRA adapter directory is missing")
    actual = {
        str(path.relative_to(adapter_dir)): _sha(path)
        for path in sorted(adapter_dir.rglob("*"))
        if path.is_file()
    }
    if not actual or any((adapter_dir / name).stat().st_size == 0 for name in actual) or recorded != actual:
        raise ArtifactVerificationError("current QLoRA adapter inventory or digest drifted")
    required = {"adapter_config.json", "adapter_model.safetensors", "tokenizer.json"}
    if not required.issubset(actual):
        raise ArtifactVerificationError("current QLoRA adapter or tokenizer files are missing")
    adapter_config = _object(adapter_dir / "adapter_config.json")
    if (
        adapter_config.get("peft_type") != "LORA"
        or adapter_config.get("r") != 8
        or adapter_config.get("lora_alpha") != 8
        or adapter_config.get("lora_dropout") != 0
    ):
        raise ArtifactVerificationError("current QLoRA adapter configuration drifted")
    return actual


def _inside(root: Path, path: Path, *, must_exist: bool) -> Path:
    candidate = path.resolve(strict=must_exist) if path.is_absolute() else (root / path).resolve(strict=must_exist)
    if not candidate.is_relative_to(root):
        raise ArtifactVerificationError(f"path escapes repository: {path}")
    return candidate


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactVerificationError(f"cannot load {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactVerificationError(f"{path.name} must contain one object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the current QLoRA adapter-only artifact")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = load_config(config_path)
    artifact_dir = args.artifact_dir or Path(config["execution"]["outputDir"])
    try:
        report = verify_artifact(
            ROOT,
            config_path,
            artifact_dir,
            args.expected_source_commit or _git_head(ROOT),
        )
    except ArtifactVerificationError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
