from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

from .current_baseline import FIXTURE_ID, MODEL, SCORING
from .current_contract import (
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_current_development_case,
)
from .experiment import HEAVY_MODULE_PREFIXES, PreflightError, _git_probe, _input_path, _output_path, sha256_file


EXPERIMENT_ID = "planner-current-qwen-stock-baseline-v3"
ISSUE = "https://github.com/loomarr/loomarr-models/issues/29"
AUTHORITY = {
    "paidBaselineAuthorized": False,
    "modelDownloadAuthorized": False,
    "gpuAuthorized": False,
    "trainingAuthorized": False,
    "certificationAuthority": False,
    "deploymentAuthority": False,
    "releaseAuthority": False,
}
EXECUTION = {
    "platform": "linux-amd64",
    "cloud": "SECURE",
    "gpuSku": "NVIDIA A40",
    "gpuCount": 1,
    "minimumVramGb": 48,
    "minimumCudaVersion": "12.8",
    "containerImage": "runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851",
    "containerDiskGb": 40,
    "persistentVolumeGb": 40,
    "storageMode": "pod-persistent",
    "maxWallClockSeconds": 9000,
    "outputDir": ".artifacts/planner-current-qwen-stock-baseline-v3",
    "requireCleanGit": True,
    "automaticRetry": False,
}
COMPARISON = {
    "seed": 3407,
    "maxSeqLength": 16384,
    "maxNewTokens": 2048,
    "maxModelCallsPerCase": 3,
    "disableCompile": True,
    "offloadEmbedding": False,
    "reasoningEffort": "low",
    "doSample": False,
    "temperature": None,
    "topP": None,
    "trials": 1,
    "sameCasesAndOrderRequiredForAdapter": True,
}
HOSTED_COMPARISON = {
    "status": "preregistered-no-provider-inference-authorized",
    "exactCurrentContractRequired": True,
    "sameCasesAndOrderRequired": True,
    "historicalScoresComparable": False,
    "certificationAuthority": False,
}
BINDING_KEYS = {
    "authorization",
    "budgetLedger",
    "cases",
    "casesManifest",
    "contract",
    "environment",
    "generator",
    "holdoutDenylist",
    "preflight",
    "promptCapacityChecker",
    "promptCapacityModule",
}
GitProbe = Callable[[Path, Iterable[Path]], str]


@dataclass(frozen=True)
class CurrentBaselineV3Plan:
    schemaVersion: int
    experimentId: str
    candidateId: str
    configSha256: str
    casesSha256: str
    caseCount: int
    contractId: str
    modelRevision: str
    environmentSha256: str
    committedSpendUsd: str
    proposedReservationUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    paidBaselineAuthorized: bool
    promptCapacityStatus: str
    sourceCommit: str
    outputDir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load current stock v3 config {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise PreflightError("current stock v3 config differs from schema v1")
    return value


def preflight(
    root: Path,
    config_path: Path,
    *,
    require_authorized: bool = False,
    git_probe: GitProbe | None = None,
) -> CurrentBaselineV3Plan:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_config(config_path)
    _validate_shape(config, require_authorized=require_authorized)
    bound: dict[str, Path] = {}
    for name, binding in config["bindings"].items():
        allowed = {"path", "sha256", "records"} if name == "cases" else {"path", "sha256"}
        if not isinstance(binding, dict) or set(binding) != allowed:
            raise PreflightError(f"invalid current stock v3 {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"current stock v3 {name} digest mismatch")

    contract = _object(bound["contract"])
    if contract.get("schemaVersion") != 2 or contract.get("contractId") != "loomarr-planner-contract-v5":
        raise PreflightError("current stock v3 contract drifted")
    exact, normalized, minimum, protected = load_current_denylist(bound["holdoutDenylist"])
    cases = read_jsonl(bound["cases"])
    for case in cases:
        try:
            validate_current_development_case(case, contract, FIXTURE_ID)
            assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected)
        except ValueError as exc:
            raise PreflightError(str(exc)) from exc
    if len(cases) != 24 or config["bindings"]["cases"]["records"] != 24:
        raise PreflightError("current stock v3 requires the exact 24-case development gate")
    case_sha = sha256_file(bound["cases"])
    manifest = _object(bound["casesManifest"])
    if (
        manifest.get("evaluationId") != "planner-current-development-v1"
        or manifest.get("records") != 24
        or manifest.get("sha256") != case_sha
        or manifest.get("modelExposure") != "none"
        or manifest.get("certificationAuthority") is not False
        or manifest.get("contract") != config["bindings"]["contract"]
        or manifest.get("holdoutDenylist") != config["bindings"]["holdoutDenylist"]
    ):
        raise PreflightError("current stock v3 development manifest drifted")
    environment = _object(bound["environment"])
    artifact = environment.get("trainingArtifact", {})
    if (
        environment.get("environmentId") != "qwen38-a40-v1"
        or environment.get("platform", {}).get("validatedSku") != EXECUTION["gpuSku"]
        or artifact.get("repository") != MODEL["repository"]
        or artifact.get("revision") != MODEL["revision"]
        or artifact.get("quantization") != MODEL["quantization"]
    ):
        raise PreflightError("current stock v3 environment or model drifted")
    authorization = _object(bound["authorization"])
    if authorization != {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "not-authorized",
        "maxReservationUsd": "1.50",
        "authorizedBy": None,
        "authorizedAt": None,
        "authorizedPlanCommit": None,
    }:
        raise PreflightError("current stock v3 authorization evidence drifted")
    committed, reservation, projected, aggregate = _validate_budget(config, _object(bound["budgetLedger"]))
    output = _output_path(root, Path(config["execution"]["outputDir"]))
    source_commit = (git_probe or _git_probe)(root, [config_path, *bound.values()])
    imported = sorted(name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES)
    if imported:
        raise PreflightError(f"heavyweight modules imported before current stock v3 preflight: {imported[0]}")
    return CurrentBaselineV3Plan(
        schemaVersion=1,
        experimentId=EXPERIMENT_ID,
        candidateId=MODEL["candidateId"],
        configSha256=sha256_file(config_path),
        casesSha256=case_sha,
        caseCount=len(cases),
        contractId=contract["contractId"],
        modelRevision=MODEL["revision"],
        environmentSha256=sha256_file(bound["environment"]),
        committedSpendUsd=str(committed),
        proposedReservationUsd=str(reservation),
        projectedSpendUsd=str(projected),
        authorizationUsd=str(aggregate),
        paidBaselineAuthorized=False,
        promptCapacityStatus=config["promptCapacity"]["status"],
        sourceCommit=source_commit,
        outputDir=str(output.relative_to(root)),
    )


def _validate_shape(config: dict[str, Any], *, require_authorized: bool) -> None:
    required = {
        "schemaVersion", "experimentId", "issue", "status", "bindings", "model", "execution",
        "comparison", "scoring", "decision", "hostedProductionComparison", "promptCapacity",
        "budget", "authority",
    }
    if set(config) != required or config["experimentId"] != EXPERIMENT_ID or config["issue"] != ISSUE:
        raise PreflightError("current stock v3 identity or fields drifted")
    if require_authorized:
        raise PreflightError("paid current stock v3 execution is not authorized")
    if (
        config["status"] != "planned-token-preflight-required"
        or set(config["bindings"]) != BINDING_KEYS
        or config["model"] != MODEL
        or config["execution"] != EXECUTION
        or config["comparison"] != COMPARISON
        or config["scoring"] != SCORING
        or config["hostedProductionComparison"] != HOSTED_COMPARISON
        or config["authority"] != AUTHORITY
        or config["promptCapacity"] != {
            "status": "required-not-run",
            "exactPinnedProcessorRequired": True,
            "fullGenerationBudgetRequiredAtEveryStage": True,
            "report": None,
        }
    ):
        raise PreflightError("current stock v3 protocol or authority drifted")
    if config["decision"] != {
        "passingStockStopsTraining": True,
        "runtimeOrInfrastructureFailureJustifiesTraining": False,
        "requiresObservedRecoveryFault": True,
        "applicationRecoveryBlocker": "https://github.com/loomarr/loomarr/issues/1195",
    }:
        raise PreflightError("current stock v3 decision contract drifted")


def _validate_budget(config: dict[str, Any], ledger: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    try:
        aggregate = Decimal(ledger["authorizationUsd"])
        posted = Decimal(ledger["postedSpendUsd"])
        outstanding = Decimal(ledger["outstandingReservationsUsd"])
        committed = Decimal(ledger["committedSpendUsd"])
        reservation = Decimal(config["budget"]["proposedReservationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("invalid current stock v3 budget") from exc
    projected = committed + reservation
    if posted + outstanding != committed or reservation != Decimal("1.50") or projected > aggregate:
        raise PreflightError("current stock v3 budget does not reconcile")
    if config["budget"] != {
        "aggregateAuthorizationUsd": str(aggregate),
        "currentCommittedUsd": str(committed),
        "outstandingReservationsUsd": str(outstanding),
        "proposedReservationUsd": "1.50",
        "projectedCommitmentUsd": str(projected),
        "remainingAuthorizationUsd": str(aggregate - projected),
    }:
        raise PreflightError("current stock v3 budget projection drifted")
    return committed, reservation, projected, aggregate


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must contain one JSON object")
    return value
