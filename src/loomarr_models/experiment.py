from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

from .validator import load_contract, load_denylist, load_jsonl, validate_corpus


HEAVY_MODULE_PREFIXES = ("torch", "unsloth", "transformers", "trl", "peft", "datasets")
EXPERIMENT_KEYS = {
    "schemaVersion",
    "experimentId",
    "issue",
    "status",
    "bindings",
    "models",
    "execution",
    "runs",
}
BINDING_KEYS = {"corpus", "corpusManifest", "contract", "denylist", "environment", "budget"}
EXECUTION_KEYS = {
    "platform",
    "gpuSku",
    "gpuCount",
    "minimumVramGb",
    "maxWallClockSeconds",
    "maxReservationUsd",
    "outputDir",
    "requireCleanGit",
}
RUN_KEYS = {
    "runId",
    "seed",
    "maxSeqLength",
    "maxSteps",
    "perDeviceTrainBatchSize",
    "gradientAccumulationSteps",
    "warmupSteps",
    "learningRate",
    "optimizer",
    "weightDecay",
    "lrSchedulerType",
    "loraR",
    "loraAlpha",
    "loraDropout",
    "finetuneVisionLayers",
    "finetuneLanguageLayers",
    "finetuneAttentionModules",
    "finetuneMlpModules",
    "gradientCheckpointing",
    "reasoningEffort",
    "trainOnResponsesOnly",
    "saveMode",
}


class PreflightError(ValueError):
    pass


@dataclass(frozen=True)
class PreflightReport:
    schemaVersion: int
    experimentId: str
    configSha256: str
    corpusSha256: str
    traceCount: int
    approvedCount: int
    environmentSha256: str
    environmentId: str
    upstreamRevision: str
    trainingArtifactRevision: str
    committedSpendUsd: str
    reservationUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    sourceCommit: str
    outputDir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


GitProbe = Callable[[Path, Iterable[Path]], str]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_experiment(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load experiment config {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != EXPERIMENT_KEYS:
        raise PreflightError("experiment top-level fields differ from schema v1")
    if value["schemaVersion"] != 1:
        raise PreflightError("unsupported experiment schemaVersion")
    return value


def preflight(
    root: Path,
    config_path: Path,
    *,
    git_probe: GitProbe | None = None,
) -> PreflightReport:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_experiment(config_path)
    _validate_shape(config)

    bindings = config["bindings"]
    bound: dict[str, Path] = {}
    for name in ("corpus", "corpusManifest", "contract", "denylist", "environment"):
        binding = bindings[name]
        if set(binding) not in ({"path", "sha256"}, {"path", "sha256", "traceCount", "requireApproved"}):
            raise PreflightError(f"invalid {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        actual = sha256_file(bound[name])
        if actual != binding["sha256"]:
            raise PreflightError(f"{name} digest mismatch: {actual}")

    corpus_binding = bindings["corpus"]
    if corpus_binding["requireApproved"] is not True:
        raise PreflightError("training corpus must require approved reviews")
    contract = load_contract(bound["contract"])
    identities, digests = load_denylist(bound["denylist"])
    report = validate_corpus(
        load_jsonl(bound["corpus"]),
        denylisted_identities=identities,
        denylisted_sha256=digests,
        contract_bundle=contract,
        allow_pending=False,
    )
    if report.traces != corpus_binding["traceCount"] or report.approved != report.traces:
        raise PreflightError("corpus is not the exact fully approved trace set")
    if config["status"] != "ready-for-smoke":
        raise PreflightError("experiment status is not ready-for-smoke")

    environment = _load_object(bound["environment"], "environment")
    _validate_environment(root, environment, config["models"])
    budget_path = _input_path(root, Path(bindings["budget"]["path"]))
    budget = _load_object(budget_path, "budget ledger")
    committed, reservation, projected, authorization = _validate_budget(config, budget)
    output = _output_path(root, Path(config["execution"]["outputDir"]))

    critical_paths = [
        config_path,
        *bound.values(),
        budget_path,
        root / "src/loomarr_models/experiment.py",
        root / "src/loomarr_models/training.py",
        root / "src/loomarr_models/training_data.py",
        root / "scripts/train_planner_smoke.py",
    ]
    probe = git_probe or _git_probe
    source_commit = probe(root, critical_paths)

    imported = sorted(
        name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES
    )
    if imported:
        raise PreflightError(f"heavyweight modules imported before preflight: {imported[0]}")

    return PreflightReport(
        schemaVersion=1,
        experimentId=config["experimentId"],
        configSha256=sha256_file(config_path),
        corpusSha256=report.sha256,
        traceCount=report.traces,
        approvedCount=report.approved,
        environmentSha256=sha256_file(bound["environment"]),
        environmentId=environment["environmentId"],
        upstreamRevision=config["models"]["upstream"]["revision"],
        trainingArtifactRevision=config["models"]["trainingArtifact"]["revision"],
        committedSpendUsd=str(committed),
        reservationUsd=str(reservation),
        projectedSpendUsd=str(projected),
        authorizationUsd=str(authorization),
        sourceCommit=source_commit,
        outputDir=str(output.relative_to(root)),
    )


def _validate_shape(config: dict[str, Any]) -> None:
    if config["experimentId"] != "planner-qwen38-smoke-v1":
        raise PreflightError("unexpected experiment identity")
    if config["issue"] != "https://github.com/loomarr/loomarr/issues/938":
        raise PreflightError("unexpected experiment tracking issue")
    if set(config["bindings"]) != BINDING_KEYS:
        raise PreflightError("experiment bindings differ from schema v1")
    if set(config["bindings"]["budget"]) != {"path"}:
        raise PreflightError("invalid budget binding")
    if set(config["models"]) != {"upstream", "trainingArtifact"}:
        raise PreflightError("model bindings differ from schema v1")
    if set(config["execution"]) != EXECUTION_KEYS:
        raise PreflightError("execution fields differ from schema v1")
    runs = config["runs"]
    if not isinstance(runs, list) or len(runs) != 1:
        raise PreflightError("exactly one training configuration is required")
    run = runs[0]
    if not isinstance(run, dict) or set(run) != RUN_KEYS:
        raise PreflightError("training configuration fields differ from schema v1")
    execution = config["execution"]
    if execution != {
        "platform": "linux-amd64",
        "gpuSku": "NVIDIA A40",
        "gpuCount": 1,
        "minimumVramGb": 48,
        "maxWallClockSeconds": 9000,
        "maxReservationUsd": "1.50",
        "outputDir": ".artifacts/planner-qwen38-smoke-v1",
        "requireCleanGit": True,
    }:
        raise PreflightError("execution safety envelope drifted")
    required_run = {
        "runId": "qwen38-qlora-a40-smoke-v1",
        "seed": 3407,
        "maxSeqLength": 1024,
        "maxSteps": 20,
        "perDeviceTrainBatchSize": 1,
        "gradientAccumulationSteps": 4,
        "warmupSteps": 5,
        "learningRate": 0.0002,
        "optimizer": "adamw_8bit",
        "weightDecay": 0.001,
        "lrSchedulerType": "linear",
        "loraR": 8,
        "loraAlpha": 8,
        "loraDropout": 0,
        "finetuneVisionLayers": False,
        "finetuneLanguageLayers": True,
        "finetuneAttentionModules": True,
        "finetuneMlpModules": True,
        "gradientCheckpointing": "unsloth",
        "reasoningEffort": "low",
        "trainOnResponsesOnly": True,
        "saveMode": "adapter-only",
    }
    if run != required_run:
        raise PreflightError("immutable training configuration drifted")


def _validate_environment(root: Path, environment: dict[str, Any], models: dict[str, Any]) -> None:
    if environment.get("environmentId") != "qwen38-a40-v1":
        raise PreflightError("unexpected environment identity")
    requirements = environment.get("requirements", {})
    for stem in ("input", "overrides", "lock"):
        path = _input_path(root, Path(requirements[f"{stem}Path"]))
        if sha256_file(path) != requirements[f"{stem}Sha256"]:
            raise PreflightError(f"environment {stem} digest mismatch")
    for name, env_name in (("upstream", "baseModel"), ("trainingArtifact", "trainingArtifact")):
        expected = models.get(name)
        actual = environment.get(env_name)
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            raise PreflightError(f"missing {name} model identity")
        if (expected.get("repository"), expected.get("revision")) != (
            actual.get("repository"),
            actual.get("revision"),
        ):
            raise PreflightError(f"{name} model revision differs from the environment")


def _validate_budget(
    config: dict[str, Any], budget: dict[str, Any]
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    expected_keys = {
        "schemaVersion",
        "ledgerId",
        "asOf",
        "currency",
        "authorizationUsd",
        "postedSpendUsd",
        "outstandingReservationsUsd",
        "committedSpendUsd",
        "authorizedBy",
    }
    if set(budget) != expected_keys or budget.get("schemaVersion") != 1:
        raise PreflightError("spend ledger fields differ from schema v1")
    if budget.get("currency") != "USD" or budget.get("authorizedBy") != "loomarr-maintainer":
        raise PreflightError("spend ledger authority differs from the experiment contract")
    try:
        authorization = Decimal(budget["authorizationUsd"])
        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        reservation = Decimal(config["execution"]["maxReservationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("invalid spend ledger") from exc
    if posted + outstanding != committed:
        raise PreflightError("spend ledger does not reconcile")
    if authorization != Decimal("20.00"):
        raise PreflightError("aggregate authorization differs from $20")
    if reservation > Decimal("1.50") or reservation <= 0:
        raise PreflightError("experiment reservation exceeds $1.50")
    projected = committed + reservation
    if projected > authorization:
        raise PreflightError("experiment would exceed aggregate authorization")
    return committed, reservation, projected, authorization


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreflightError(f"{label} must be an object")
    return value


def _input_path(root: Path, path: Path) -> Path:
    if path.is_absolute():
        candidate = path.resolve(strict=True)
    else:
        candidate = (root / path).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise PreflightError(f"input path escapes repository: {path}")
    return candidate


def _output_path(root: Path, path: Path) -> Path:
    if path.is_absolute():
        raise PreflightError("output path must be repository-relative")
    artifact_root = (root / ".artifacts").resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(artifact_root) or candidate == artifact_root:
        raise PreflightError("output path must stay under .artifacts")
    return candidate


def _git_probe(root: Path, paths: Iterable[Path]) -> str:
    root = root.resolve()
    relative = [str(path.resolve().relative_to(root)) for path in paths]
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", *relative],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if tracked.returncode:
        raise PreflightError("runner inputs are untracked or uncommitted")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *relative],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    if dirty.stdout.strip():
        raise PreflightError("runner inputs have uncommitted changes")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
    ).stdout.strip()
    if len(commit) != 40:
        raise PreflightError("cannot resolve source commit")
    return commit
