from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

from .evaluation import load_cases, validate_development_corpus
from .experiment import (
    HEAVY_MODULE_PREFIXES,
    PreflightError,
    _git_probe,
    _input_path,
    _load_object,
    _output_path,
    sha256_file,
)
from .validator import load_contract, load_denylist, load_jsonl


CONFIG_KEYS = {
    "schemaVersion",
    "experimentId",
    "issue",
    "status",
    "bindings",
    "models",
    "execution",
    "comparison",
}
BINDING_KEYS = {
    "cases",
    "casesManifest",
    "trainingCorpus",
    "contract",
    "denylist",
    "environment",
    "adapterSourceManifest",
    "budget",
}
EXECUTION_KEYS = {
    "platform",
    "gpuSku",
    "gpuCount",
    "minimumVramGb",
    "maxWallClockSeconds",
    "maxReservationUsd",
    "outputDir",
    "adapterPath",
    "adapterSha256",
    "requireCleanGit",
}
COMPARISON_KEYS = {
    "candidateOrder",
    "seed",
    "maxSeqLength",
    "maxNewTokens",
    "maxModelCallsPerCase",
    "disableCompile",
    "offloadEmbedding",
    "reasoningEffort",
    "doSample",
    "temperature",
    "topP",
    "trials",
}


@dataclass(frozen=True)
class EvalPreflightReport:
    schemaVersion: int
    experimentId: str
    configSha256: str
    casesSha256: str
    caseCount: int
    trainingCorpusSha256: str
    environmentSha256: str
    adapterSha256: str
    committedSpendUsd: str
    reservationUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    sourceCommit: str
    outputDir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


GitProbe = Callable[[Path, Iterable[Path]], str]
AdapterProbe = Callable[[Path], str]


def load_eval_experiment(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load evaluation experiment {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS or value.get("schemaVersion") != 1:
        raise PreflightError("evaluation experiment fields differ from schema v1")
    return value


def preflight_eval(
    root: Path,
    config_path: Path,
    *,
    git_probe: GitProbe | None = None,
    adapter_probe: AdapterProbe | None = None,
) -> EvalPreflightReport:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_eval_experiment(config_path)
    _validate_shape(config)

    bound: dict[str, Path] = {}
    for name in (
        "cases",
        "casesManifest",
        "trainingCorpus",
        "contract",
        "denylist",
        "environment",
        "adapterSourceManifest",
    ):
        binding = config["bindings"][name]
        allowed = {"path", "sha256", "caseCount"} if name == "cases" else {"path", "sha256"}
        if not isinstance(binding, dict) or set(binding) != allowed:
            raise PreflightError(f"invalid {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"{name} digest mismatch")

    contract = load_contract(bound["contract"])
    identities, digests = load_denylist(bound["denylist"])
    development = validate_development_corpus(
        load_cases(bound["cases"]),
        contract=contract,
        training_traces=load_jsonl(bound["trainingCorpus"]),
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    if development.cases != config["bindings"]["cases"]["caseCount"]:
        raise PreflightError("development corpus count differs from binding")
    manifest = _load_object(bound["casesManifest"], "development manifest")
    _validate_manifest(manifest, config, development.sha256)
    generator_path = root / "scripts/build_planner_development_eval.py"
    if manifest.get("generatorSha256") != sha256_file(generator_path):
        raise PreflightError("development generator digest differs from manifest")
    _validate_environment(_load_object(bound["environment"], "environment"), config)
    adapter_source = _load_object(bound["adapterSourceManifest"], "adapter source")
    _validate_adapter_source(adapter_source, config)

    try:
        adapter_path = _input_path(root, Path(config["execution"]["adapterPath"]))
    except OSError as exc:
        raise PreflightError("local adapter is missing") from exc
    probe_adapter = adapter_probe or sha256_file
    for relative, expected_sha in adapter_source["adapterFiles"].items():
        try:
            local_file = _input_path(root, adapter_path.parent / relative)
        except OSError as exc:
            raise PreflightError(f"local adapter file is missing: {relative}") from exc
        if probe_adapter(local_file) != expected_sha:
            raise PreflightError(f"local adapter file digest mismatch: {relative}")
    observed_adapter = probe_adapter(adapter_path)
    if observed_adapter != config["execution"]["adapterSha256"]:
        raise PreflightError("local adapter digest mismatch")

    budget_path = _input_path(root, Path(config["bindings"]["budget"]["path"]))
    budget = _load_object(budget_path, "budget ledger")
    committed, reservation, projected, authorization = _validate_budget(config, budget)
    output = _output_path(root, Path(config["execution"]["outputDir"]))

    critical_paths = [
        config_path,
        *bound.values(),
        budget_path,
        root / "src/loomarr_models/evaluation.py",
        root / "src/loomarr_models/eval_experiment.py",
        root / "src/loomarr_models/eval_runner.py",
        root / "src/loomarr_models/eval_runtime.py",
        root / "scripts/build_planner_development_eval.py",
        root / "scripts/run_planner_adapter_eval.py",
    ]
    source_commit = (git_probe or _git_probe)(root, critical_paths)
    imported = sorted(
        name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES
    )
    if imported:
        raise PreflightError(f"heavyweight modules imported before evaluation preflight: {imported[0]}")

    return EvalPreflightReport(
        schemaVersion=1,
        experimentId=config["experimentId"],
        configSha256=sha256_file(config_path),
        casesSha256=development.sha256,
        caseCount=development.cases,
        trainingCorpusSha256=sha256_file(bound["trainingCorpus"]),
        environmentSha256=sha256_file(bound["environment"]),
        adapterSha256=observed_adapter,
        committedSpendUsd=str(committed),
        reservationUsd=str(reservation),
        projectedSpendUsd=str(projected),
        authorizationUsd=str(authorization),
        sourceCommit=source_commit,
        outputDir=str(output.relative_to(root)),
    )


def _validate_shape(config: dict[str, Any]) -> None:
    if config["experimentId"] != "planner-adapter-eval-v1":
        raise PreflightError("unexpected evaluation identity")
    if config["issue"] != "https://github.com/loomarr/loomarr-models/issues/5":
        raise PreflightError("unexpected evaluation tracking issue")
    if config["status"] != "ready-for-development-eval":
        raise PreflightError("evaluation is not ready-for-development-eval")
    if set(config["bindings"]) != BINDING_KEYS:
        raise PreflightError("evaluation bindings differ from schema v1")
    if config["bindings"]["budget"] != {"path": "budgets/external-spend-v1.json"}:
        raise PreflightError("invalid evaluation budget binding")
    if set(config["models"]) != {"upstream", "inferenceArtifact"}:
        raise PreflightError("evaluation model bindings differ from schema v1")
    if set(config["execution"]) != EXECUTION_KEYS:
        raise PreflightError("evaluation execution fields differ from schema v1")
    if config["execution"] != {
        "platform": "linux-amd64",
        "gpuSku": "NVIDIA A40",
        "gpuCount": 1,
        "minimumVramGb": 48,
        "maxWallClockSeconds": 14400,
        "maxReservationUsd": "3.00",
        "outputDir": ".artifacts/planner-adapter-eval-v1",
        "adapterPath": ".artifacts/runpod-qwen38-qlora-smoke-v1/planner-qwen38-smoke-v1/adapter/adapter_model.safetensors",
        "adapterSha256": "08a166aa73ec1aaf965cf5a53af61a728d4542c841859b477af72305e5cb35f7",
        "requireCleanGit": True,
    }:
        raise PreflightError("evaluation safety envelope drifted")
    if set(config["comparison"]) != COMPARISON_KEYS or config["comparison"] != {
        "candidateOrder": ["stock", "adapter"],
        "seed": 3407,
        "maxSeqLength": 4096,
        "maxNewTokens": 768,
        "maxModelCallsPerCase": 5,
        "disableCompile": True,
        "offloadEmbedding": False,
        "reasoningEffort": "low",
        "doSample": False,
        "temperature": None,
        "topP": None,
        "trials": 1,
    }:
        raise PreflightError("evaluation comparison protocol drifted")


def _validate_manifest(manifest: dict[str, Any], config: dict[str, Any], cases_sha: str) -> None:
    if (
        manifest.get("corpusId") != "planner-development-v1"
        or manifest.get("status") != "frozen-development-only"
        or manifest.get("caseCount") != 50
        or manifest.get("casesSha256") != cases_sha
    ):
        raise PreflightError("development manifest identity differs")
    if manifest.get("trainingCorpusSha256") != config["bindings"]["trainingCorpus"]["sha256"]:
        raise PreflightError("development manifest training binding differs")
    if manifest.get("holdoutDenylistSha256") != config["bindings"]["denylist"]["sha256"]:
        raise PreflightError("development manifest denylist binding differs")


def _validate_environment(environment: dict[str, Any], config: dict[str, Any]) -> None:
    if environment.get("environmentId") != "qwen38-a40-v1":
        raise PreflightError("unexpected evaluation environment")
    for config_name, environment_name in (
        ("upstream", "baseModel"),
        ("inferenceArtifact", "trainingArtifact"),
    ):
        expected = config["models"][config_name]
        actual = environment.get(environment_name, {})
        if (expected.get("repository"), expected.get("revision")) != (
            actual.get("repository"),
            actual.get("revision"),
        ):
            raise PreflightError(f"{config_name} revision differs from evaluation environment")


def _validate_adapter_source(manifest: dict[str, Any], config: dict[str, Any]) -> None:
    if manifest.get("runId") != "qwen38-qlora-a40-smoke-v1":
        raise PreflightError("adapter source run identity differs")
    observed = manifest.get("adapterFiles", {}).get("adapter_model.safetensors")
    if observed != config["execution"]["adapterSha256"]:
        raise PreflightError("adapter source manifest digest differs")
    preflight = manifest.get("preflight", {})
    if preflight.get("trainingArtifactRevision") != config["models"]["inferenceArtifact"]["revision"]:
        raise PreflightError("adapter base revision differs from evaluation candidate")


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
        raise PreflightError("spend ledger authority differs from evaluation contract")
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
    if authorization != Decimal("40.00"):
        raise PreflightError("aggregate authorization differs from $40")
    if reservation != Decimal("3.00"):
        raise PreflightError("evaluation reservation differs from $3")
    projected = committed + reservation
    if projected > authorization:
        raise PreflightError("evaluation would exceed aggregate authorization")
    return committed, reservation, projected, authorization
