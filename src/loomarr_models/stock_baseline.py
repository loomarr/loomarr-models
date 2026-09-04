from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

from .experiment import HEAVY_MODULE_PREFIXES, PreflightError, _git_probe, _input_path, _output_path, sha256_file
from .local_screen import SCORING
from .planner_v4 import validate_development
from .validator import load_contract, load_denylist, load_jsonl


EXPERIMENT_ID = "planner-v4-qwen-stock-baseline-v1"
ISSUE = "https://github.com/loomarr/loomarr-models/issues/22"
CANDIDATE_ID = "qwen38-27b-unsloth-bnb-4bit"
CONFIG_KEYS = {
    "schemaVersion",
    "experimentId",
    "issue",
    "status",
    "paidBaselineAuthorized",
    "bindings",
    "model",
    "execution",
    "comparison",
    "scoring",
    "budget",
    "authority",
}
BINDING_KEYS = {
    "cases",
    "casesManifest",
    "contract",
    "holdoutDenylist",
    "environment",
    "localScreenPublication",
    "runpodCatalogSnapshot",
    "budgetLedger",
    "generator",
    "preflight",
    "runtime",
    "runner",
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
    "networkVolumeGb": 40,
    "maxWallClockSeconds": 9000,
    "maxReservationUsd": "1.50",
    "outputDir": ".artifacts/planner-v4-qwen-stock-baseline-v1",
    "requireCleanGit": True,
    "automaticRetry": False,
}
COMPARISON = {
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
}
AUTHORITY = {
    "developmentOnly": True,
    "qloraDecisionAuthority": True,
    "certificationAuthority": False,
    "trainingAuthority": False,
    "releaseAuthority": False,
    "deploymentAuthority": False,
}


@dataclass(frozen=True)
class StockBaselinePlan:
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
    reservationUsd: str
    projectedSpendUsd: str
    authorizationUsd: str
    paidBaselineAuthorized: bool
    sourceCommit: str
    outputDir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


GitProbe = Callable[[Path, Iterable[Path]], str]


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load stock baseline config {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS or value.get("schemaVersion") != 1:
        raise PreflightError("stock baseline config fields differ from schema v1")
    return value


def preflight(
    root: Path,
    config_path: Path,
    *,
    require_authorized: bool = True,
    git_probe: GitProbe | None = None,
) -> StockBaselinePlan:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_config(config_path)
    _validate_shape(config, require_authorized=require_authorized)

    bound: dict[str, Path] = {}
    for name, binding in config["bindings"].items():
        if name == "budgetLedger":
            if binding != {"path": "budgets/external-spend-v1.json"}:
                raise PreflightError("stock baseline budget binding drifted")
            continue
        allowed = {"path", "sha256", "count"} if name == "cases" else {"path", "sha256"}
        if not isinstance(binding, dict) or set(binding) != allowed:
            raise PreflightError(f"invalid stock baseline {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"stock baseline {name} digest mismatch")

    contract = load_contract(bound["contract"])
    identities, digests = load_denylist(bound["holdoutDenylist"])
    cases = load_jsonl(bound["cases"])
    report = validate_development(
        cases,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    if report.records != 120 or config["bindings"]["cases"]["count"] != 120:
        raise PreflightError("stock baseline requires the exact 120-case v4 gate")
    _validate_development_manifest(_object(bound["casesManifest"]), config, report.sha256, contract)
    _validate_environment(_object(bound["environment"]), config)
    _validate_local_screen(_object(bound["localScreenPublication"]), report.sha256)
    _validate_catalog_snapshot(_object(bound["runpodCatalogSnapshot"]), config)

    budget_path = _input_path(root, Path(config["bindings"]["budgetLedger"]["path"]))
    committed, reservation, projected, authorization = _validate_budget(
        config, _object(budget_path)
    )
    output = _output_path(root, Path(config["execution"]["outputDir"]))
    critical_paths = [config_path, budget_path, *bound.values()]
    source_commit = (git_probe or _git_probe)(root, critical_paths)
    imported = sorted(
        name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES
    )
    if imported:
        raise PreflightError(
            f"heavyweight modules imported before stock baseline preflight: {imported[0]}"
        )
    return StockBaselinePlan(
        schemaVersion=1,
        experimentId=EXPERIMENT_ID,
        candidateId=CANDIDATE_ID,
        configSha256=sha256_file(config_path),
        casesSha256=report.sha256,
        caseCount=report.records,
        contractId=contract["contractId"],
        modelRevision=config["model"]["revision"],
        environmentSha256=sha256_file(bound["environment"]),
        committedSpendUsd=str(committed),
        reservationUsd=str(reservation),
        projectedSpendUsd=str(projected),
        authorizationUsd=str(authorization),
        paidBaselineAuthorized=config["paidBaselineAuthorized"],
        sourceCommit=source_commit,
        outputDir=str(output.relative_to(root)),
    )


def _validate_shape(config: dict[str, Any], *, require_authorized: bool) -> None:
    if config["experimentId"] != EXPERIMENT_ID or config["issue"] != ISSUE:
        raise PreflightError("stock baseline identity drifted")
    expected_status = (
        "ready-for-paid-baseline"
        if config["paidBaselineAuthorized"]
        else "planned-no-paid-baseline-authorized"
    )
    if config["status"] != expected_status:
        raise PreflightError("stock baseline status and authorization differ")
    if require_authorized and not config["paidBaselineAuthorized"]:
        raise PreflightError("paid stock baseline is not authorized")
    if set(config["bindings"]) != BINDING_KEYS:
        raise PreflightError("stock baseline bindings differ from schema v1")
    if config["model"].get("candidateId") != CANDIDATE_ID:
        raise PreflightError("stock baseline candidate identity drifted")
    if config["execution"] != EXECUTION:
        raise PreflightError("stock baseline execution envelope drifted")
    if config["comparison"] != COMPARISON:
        raise PreflightError("stock baseline comparison protocol drifted")
    if config["scoring"] != SCORING:
        raise PreflightError("stock baseline scoring protocol drifted")
    if config["authority"] != AUTHORITY:
        raise PreflightError("stock baseline authority boundary drifted")


def _validate_development_manifest(
    manifest: dict[str, Any], config: dict[str, Any], cases_sha: str, contract: dict[str, Any]
) -> None:
    if (
        manifest.get("corpusId") != "planner-development-v4"
        or manifest.get("status") != "frozen-development-only-local-screen-exposed"
        or manifest.get("caseCount") != 120
        or manifest.get("casesSha256") != cases_sha
        or manifest.get("contractId") != contract["contractId"]
        or manifest.get("casesSha256") != config["bindings"]["cases"]["sha256"]
    ):
        raise PreflightError("stock baseline development manifest drifted")


def _validate_environment(environment: dict[str, Any], config: dict[str, Any]) -> None:
    artifact = environment.get("trainingArtifact", {})
    model = config["model"]
    if (
        environment.get("environmentId") != "qwen38-a40-v1"
        or environment.get("platform", {}).get("validatedSku") != EXECUTION["gpuSku"]
        or artifact.get("repository") != model.get("repository")
        or artifact.get("revision") != model.get("revision")
        or artifact.get("quantization") != model.get("quantization")
    ):
        raise PreflightError("stock baseline environment or model drifted")


def _validate_local_screen(publication: dict[str, Any], cases_sha: str) -> None:
    source = publication.get("sourceExperiment", {})
    qwen = publication.get("candidateEvidence", {}).get("qwen38-27b-mlx-nvfp4", {})
    if (
        publication.get("screenId") != "planner-v4-local-screen-v1"
        or publication.get("status") != "complete"
        or publication.get("externalCostUsd") != "0"
        or publication.get("decision", {}).get("outcome")
        != "local-screen-rejects-gemma-qwen-authoritative-baseline-required"
        or publication.get("authority", {}).get("trainingAuthority") is not False
        or qwen.get("failure", {}).get("kind") != "metal-out-of-memory"
        or not isinstance(source.get("sha256"), str)
    ):
        raise PreflightError("local screen does not require an authoritative Qwen baseline")
    summary = publication.get("summaries", {}).get("gemma4-12b-q4-k-m", {})
    if summary.get("caseCount") != 120 or summary.get("caseIdsSha256") is None:
        raise PreflightError("local screen Gemma evidence is incomplete")
    source_config = publication.get("sourceCommit")
    if not isinstance(source_config, str) or re.fullmatch(r"[0-9a-f]{40}", source_config) is None:
        raise PreflightError("local screen source commit is invalid")
    if cases_sha != "ae687cb6298bd248f5e5b857aab60076484f7b502ff556d645bf0bfbf1e64f34":
        raise PreflightError("local screen and stock baseline case identity differs")


def _validate_catalog_snapshot(snapshot: dict[str, Any], config: dict[str, Any]) -> None:
    if set(snapshot) != {
        "schemaVersion",
        "capturedAt",
        "provider",
        "source",
        "product",
        "candidate",
        "account",
        "externalCostUsd",
    } or snapshot.get("schemaVersion") != 1:
        raise PreflightError("Runpod catalog snapshot fields differ from schema v1")
    candidate = snapshot["candidate"]
    expected = {
        "id": EXECUTION["gpuSku"],
        "memoryGb": EXECUTION["minimumVramGb"],
        "gpuCount": 1,
        "cloud": EXECUTION["cloud"],
        "cudaVersion": EXECUTION["minimumCudaVersion"],
        "availability": "HIGH",
        "pricePerHourUsd": "0.49",
    }
    if (
        snapshot["provider"] != "runpod"
        or snapshot["source"] != "runpod-mcp-rest-v2"
        or snapshot["product"] != "POD"
        or snapshot["externalCostUsd"] != "0"
        or snapshot["account"] != {"activePodCount": 0}
        or candidate != expected
        or config["execution"]["gpuSku"] != candidate["id"]
    ):
        raise PreflightError("Runpod catalog snapshot differs from baseline plan")


def _validate_budget(
    config: dict[str, Any], ledger: dict[str, Any]
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    try:
        authorization = Decimal(ledger["authorizationUsd"])
        posted = Decimal(ledger["postedSpendUsd"])
        outstanding = Decimal(ledger["outstandingReservationsUsd"])
        committed = Decimal(ledger["committedSpendUsd"])
        reservation = Decimal(config["execution"]["maxReservationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("invalid stock baseline budget") from exc
    if posted + outstanding != committed:
        raise PreflightError("stock baseline budget ledger does not reconcile")
    if authorization != Decimal("40.00") or reservation != Decimal("1.50"):
        raise PreflightError("stock baseline authorization or reservation drifted")
    projected = committed + reservation
    if config["budget"] != {
        "aggregateAuthorizationUsd": str(authorization),
        "currentCommittedUsd": str(committed),
        "proposedReservationUsd": str(reservation),
        "projectedCommitmentUsd": str(projected),
        "remainingAfterMaximumUsd": str(authorization - projected),
    }:
        raise PreflightError("stock baseline budget projection drifted")
    if projected > authorization:
        raise PreflightError("stock baseline would exceed aggregate authorization")
    return committed, reservation, projected, authorization


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must be an object")
    return value
