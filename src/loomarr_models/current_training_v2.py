from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

from .current_baseline import MODEL
from .current_contract import (
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_approved_current_trace,
    validate_current_development_case,
    validate_disjoint_splits,
)
from .current_review import DEVELOPMENT_FIXTURE_ID, FIXTURE_ID
from .current_training import (
    EVALUATION,
    NO_AUTHORITY,
    RUN as V1_RUN,
    TRAINING_AUTHORITY,
    CurrentTrainingPlan,
    _object,
    _validate_capacity,
    _validate_corpus,
    _validate_stock_publication,
    load_config,
)
from .experiment import HEAVY_MODULE_PREFIXES, PreflightError, _git_probe, _input_path, _output_path, sha256_file


EXPERIMENT_ID = "planner-current-qwen38-qlora-v2"
ISSUE = "https://github.com/loomarr/loomarr-models/issues/20"
TRAINING_RESERVATION_USD = Decimal("1.50")
EVALUATION_RESERVATION_USD = Decimal("1.50")
COMBINED_RESERVATION_USD = TRAINING_RESERVATION_USD + EVALUATION_RESERVATION_USD
EXECUTION = {
    "platform": "linux-amd64",
    "cloud": "SECURE",
    "gpuSku": "NVIDIA A40",
    "gpuCount": 1,
    "minimumVramGb": 48,
    "minimumCudaVersion": "12.8",
    "containerImage": "runpod/pytorch@sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851",
    "containerDiskGb": 40,
    "environmentInstallDir": "/opt/loomarr-venv",
    "persistentVolumeGb": 80,
    "storageMode": "pod-persistent",
    "modelCacheDir": "/workspace/hf-cache",
    "minimumFreePersistentGbBeforeDownload": 70,
    "environment": {
        "HF_HOME": "/workspace/hf-cache",
        "HF_HUB_DISABLE_XET": "1",
    },
    "maxWallClockSeconds": 9000,
    "outputDir": ".artifacts/planner-current-qwen38-qlora-v2",
    "requireCleanGit": True,
    "automaticRetry": False,
}
RUN = {**V1_RUN, "runId": "current-qwen38-qlora-a40-v2"}
EXPECTED_BINDING_PATHS = {
    "authorization": "reviews/planner-current-qwen38-qlora-v2/authorization.json",
    "authorizationTool": "scripts/authorize_planner_current_qwen38_qlora_v2.py",
    "budgetLedger": "budgets/external-spend-v1.json",
    "budgetReconciliation": "budgets/runpod-pod-billing-current-qwen38-qlora-v1-failure-v1.json",
    "capacityReport": "reviews/planner-current-qwen38-qlora-v1/training-capacity-report.json",
    "contract": "contracts/planner-contract-v5.json",
    "corpus": "corpus/planner-current-v1/traces.jsonl",
    "corpusManifest": "corpus/planner-current-v1/manifest.json",
    "development": "evaluation/planner-current-v1/cases.jsonl",
    "developmentManifest": "evaluation/planner-current-v1/manifest.json",
    "documentation": "docs/planner-current-qwen38-qlora-v2.md",
    "environment": "environments/qwen38-a40-v1.json",
    "failurePublication": "runs/planner-current-qwen38-qlora-v1/publication.json",
    "generator": "scripts/build_planner_current_qwen38_qlora_v2.py",
    "holdoutDenylist": "contracts/planner-holdout-denylist-v2.json",
    "preflight": "src/loomarr_models/current_training_v2.py",
    "reviewPublication": "reviews/planner-current-v1/publication.json",
    "runbook": "docs/planner-current-qwen38-qlora-v2-runbook.md",
    "runner": "scripts/run_planner_current_qwen38_qlora_v2.py",
    "runtime": "src/loomarr_models/current_training_runtime.py",
    "stockPublication": "runs/planner-current-qwen-stock-baseline-v3/publication.json",
    "trainingData": "src/loomarr_models/training_data.py",
    "verifier": "scripts/verify_planner_current_qwen38_qlora_v2_artifact.py",
}
GitProbe = Callable[[Path, Iterable[Path]], str]


def preflight(
    root: Path,
    config_path: Path,
    *,
    require_authorized: bool = True,
    git_probe: GitProbe | None = None,
) -> CurrentTrainingPlan:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_config(config_path)
    _validate_shape(config, require_authorized=require_authorized)
    bound: dict[str, Path] = {}
    for name, binding in config["bindings"].items():
        allowed = {"path", "sha256", "records"} if name in {"corpus", "development"} else {"path", "sha256"}
        if (
            name not in EXPECTED_BINDING_PATHS
            or not isinstance(binding, dict)
            or set(binding) != allowed
            or binding["path"] != EXPECTED_BINDING_PATHS[name]
        ):
            raise PreflightError(f"invalid corrected current QLoRA {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"corrected current QLoRA {name} digest mismatch")

    contract = _object(bound["contract"])
    if contract.get("schemaVersion") != 2 or contract.get("contractId") != "loomarr-planner-contract-v5":
        raise PreflightError("corrected current QLoRA contract drifted")
    exact, normalized, minimum, protected = load_current_denylist(bound["holdoutDenylist"])
    traces = read_jsonl(bound["corpus"])
    cases = read_jsonl(bound["development"])
    for trace in traces:
        validate_approved_current_trace(trace, contract, FIXTURE_ID)
        assert_not_denylisted(trace["traceId"], trace, exact, normalized, minimum, protected)
    for case in cases:
        validate_current_development_case(case, contract, DEVELOPMENT_FIXTURE_ID)
        assert_not_denylisted(case["caseId"], case, exact, normalized, minimum, protected)
    validate_disjoint_splits({"current-training": traces, "current-development": cases})
    if len(traces) != 24 or len(cases) != 24:
        raise PreflightError("corrected current QLoRA requires exact 24-row disjoint splits")
    _validate_corpus(root, config, bound, traces, cases)
    _validate_stock_publication(bound["stockPublication"], cases)
    maximum_tokens = _validate_capacity(config, bound["capacityReport"], traces)
    _validate_environment(bound["environment"])
    _validate_failure_publication(_object(bound["failurePublication"]))
    _validate_authorization(_object(bound["authorization"]), config)
    committed, projected, aggregate = _validate_budget(config, _object(bound["budgetLedger"]))
    output = _output_path(root, Path(config["execution"]["outputDir"]))
    source_commit = (git_probe or _git_probe)(root, [config_path, *bound.values()])
    imported = sorted(name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES)
    if imported:
        raise PreflightError(
            f"heavyweight modules imported before corrected current QLoRA preflight: {imported[0]}"
        )
    return CurrentTrainingPlan(
        schemaVersion=1,
        experimentId=EXPERIMENT_ID,
        configSha256=sha256_file(config_path),
        corpusSha256=sha256_file(bound["corpus"]),
        traceCount=len(traces),
        maximumRenderedTokens=maximum_tokens,
        maxSeqLength=RUN["maxSeqLength"],
        environmentSha256=sha256_file(bound["environment"]),
        trainingArtifactRevision=MODEL["revision"],
        stockPublicationSha256=sha256_file(bound["stockPublication"]),
        committedSpendUsd=str(committed),
        trainingReservationUsd=str(TRAINING_RESERVATION_USD),
        evaluationReservationUsd=str(EVALUATION_RESERVATION_USD),
        combinedReservationUsd=str(COMBINED_RESERVATION_USD),
        projectedCombinedSpendUsd=str(projected),
        authorizationUsd=str(aggregate),
        trainingAuthorized=config["authority"]["trainingAuthorized"],
        sourceCommit=source_commit,
        outputDir=str(output.relative_to(root)),
    )


def _validate_shape(config: dict[str, Any], *, require_authorized: bool) -> None:
    required = {
        "schemaVersion", "experimentId", "issue", "status", "bindings", "model",
        "execution", "runs", "evaluation", "budget", "authority",
    }
    if (
        set(config) != required
        or config.get("experimentId") != EXPERIMENT_ID
        or config.get("issue") != ISSUE
        or set(config.get("bindings", {})) != set(EXPECTED_BINDING_PATHS)
        or config.get("model") != MODEL
        or config.get("execution") != EXECUTION
        or config.get("runs") != [RUN]
        or config.get("evaluation") != EVALUATION
    ):
        raise PreflightError("corrected current QLoRA protocol drifted")
    expected_status = (
        "ready-for-training"
        if config.get("authority") == TRAINING_AUTHORITY
        else "planned-no-paid-run-authorized"
    )
    if config.get("status") != expected_status or config.get("authority") not in (
        NO_AUTHORITY,
        TRAINING_AUTHORITY,
    ):
        raise PreflightError("corrected current QLoRA status and authority differ")
    if require_authorized and config["authority"] != TRAINING_AUTHORITY:
        raise PreflightError("corrected current QLoRA training is not authorized")


def _validate_environment(path: Path) -> None:
    environment = _object(path)
    if (
        environment.get("environmentId") != "qwen38-a40-v1"
        or environment.get("platform", {}).get("validatedSku") != EXECUTION["gpuSku"]
        or environment.get("trainingArtifact", {}).get("repository") != MODEL["repository"]
        or environment.get("trainingArtifact", {}).get("revision") != MODEL["revision"]
    ):
        raise PreflightError("corrected current QLoRA environment or model drifted")


def _validate_failure_publication(publication: dict[str, Any]) -> None:
    failure = publication.get("failureEvidence", {})
    if (
        publication.get("experimentId") != "planner-current-qwen38-qlora-v1"
        or publication.get("status") != "failed-settled"
        or publication.get("failureClass") != "model-download-storage-exhausted"
        or publication.get("providerCostUsd") != "0.160050047095865"
        or failure.get("exitCode") != 1
        or failure.get("optimizerSteps") != 0
        or failure.get("adapterProduced") is not False
        or publication.get("evaluationDisposition") != "not-run-no-adapter"
        or any(publication.get("authority", {}).values())
    ):
        raise PreflightError("corrected current QLoRA failure prerequisite drifted")


def _validate_authorization(authorization: dict[str, Any], config: dict[str, Any]) -> None:
    base = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "trainingReservationUsd": "1.50",
        "evaluationReservationUsd": "1.50",
        "maxCombinedReservationUsd": "3.00",
    }
    if config["status"] == "planned-no-paid-run-authorized":
        expected = {
            **base,
            "status": "not-authorized",
            "authorizedBy": None,
            "authorizedAt": None,
            "authorizedPlanCommit": None,
            "authorizationReference": None,
        }
        if authorization != expected:
            raise PreflightError("corrected current QLoRA authorization evidence drifted")
        return
    if (
        set(authorization) != set(base) | {
            "status", "authorizedBy", "authorizedAt", "authorizedPlanCommit", "authorizationReference"
        }
        or any(authorization.get(key) != value for key, value in base.items())
        or authorization.get("status") != "training-authorized"
        or authorization.get("authorizedBy") != "loomarr-maintainer"
        or re.fullmatch(r"[0-9a-f]{40}", authorization.get("authorizedPlanCommit", "")) is None
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", authorization.get("authorizedAt", "")) is None
        or re.fullmatch(
            r"https://github\.com/loomarr/loomarr-models/issues/20#issuecomment-\d+",
            authorization.get("authorizationReference", ""),
        ) is None
    ):
        raise PreflightError("corrected current QLoRA paid authorization evidence drifted")


def _validate_budget(config: dict[str, Any], ledger: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    try:
        posted = Decimal(ledger["postedSpendUsd"])
        outstanding = Decimal(ledger["outstandingReservationsUsd"])
        committed = Decimal(ledger["committedSpendUsd"])
        aggregate = Decimal(ledger["authorizationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("corrected current QLoRA budget ledger is invalid") from exc
    projected = committed + COMBINED_RESERVATION_USD
    expected = {
        "aggregateAuthorizationUsd": str(aggregate),
        "currentCommittedUsd": str(committed),
        "outstandingReservationsUsd": str(outstanding),
        "trainingReservationUsd": "1.50",
        "evaluationReservationUsd": "1.50",
        "maxCombinedReservationUsd": "3.00",
        "projectedCombinedSpendUsd": str(projected),
        "remainingAfterCombinedUsd": str(aggregate - projected),
    }
    if posted + outstanding != committed or config.get("budget") != expected or projected > aggregate:
        raise PreflightError("corrected current QLoRA budget does not reconcile")
    return committed, projected, aggregate
