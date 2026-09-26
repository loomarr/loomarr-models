from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

from .current_baseline import MODEL, SCORING
from .current_contract import (
    assert_not_denylisted,
    load_current_denylist,
    read_jsonl,
    validate_approved_current_trace,
    validate_current_development_case,
    validate_disjoint_splits,
)
from .current_review import DEVELOPMENT_FIXTURE_ID, FIXTURE_ID
from .experiment import HEAVY_MODULE_PREFIXES, PreflightError, _git_probe, _input_path, _output_path, sha256_file


EXPERIMENT_ID = "planner-current-qwen38-qlora-v1"
ISSUE = "https://github.com/loomarr/loomarr-models/issues/20"
TRAINING_RESERVATION_USD = Decimal("1.50")
EVALUATION_RESERVATION_USD = Decimal("1.50")
COMBINED_RESERVATION_USD = TRAINING_RESERVATION_USD + EVALUATION_RESERVATION_USD
NO_AUTHORITY = {
    "modelDownloadAuthorized": False,
    "gpuAuthorized": False,
    "trainingAuthorized": False,
    "paidEvaluationAuthorized": False,
    "certificationAuthority": False,
    "deploymentAuthority": False,
    "releaseAuthority": False,
}
TRAINING_AUTHORITY = {
    **NO_AUTHORITY,
    "modelDownloadAuthorized": True,
    "gpuAuthorized": True,
    "trainingAuthorized": True,
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
    "outputDir": ".artifacts/planner-current-qwen38-qlora-v1",
    "requireCleanGit": True,
    "automaticRetry": False,
}
RUN = {
    "runId": "current-qwen38-qlora-a40-v1",
    "seed": 3407,
    "maxSeqLength": 8192,
    "maxSteps": 9,
    "perDeviceTrainBatchSize": 1,
    "gradientAccumulationSteps": 4,
    "warmupSteps": 1,
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
    "shuffle": "deterministic-seeded",
}
EVALUATION = {
    "status": "waiting-for-hash-bound-adapter",
    "candidateOrder": ["stock", "adapter"],
    "reusePublishedStockResults": True,
    "sameCasesAndOrderRequired": True,
    "comparison": {
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
    },
    "promotion": {
        "minimumHardFailureReduction": 8,
        "requiredQualityThresholds": SCORING["thresholds"],
        "maximumUnsupportedKeys": 0,
        "maximumAuthorityViolations": 0,
        "certificationAuthority": False,
        "deploymentAuthority": False,
        "releaseAuthority": False,
    },
}
EXPECTED_BINDING_PATHS = {
    "authorization": "reviews/planner-current-qwen38-qlora-v1/authorization.json",
    "authorizationTool": "scripts/authorize_planner_current_qwen38_qlora_v1.py",
    "budgetLedger": "budgets/external-spend-v1.json",
    "budgetReconciliation": "budgets/runpod-pod-billing-current-stock-baseline-v3-v1.json",
    "capacityChecker": "scripts/check_planner_current_training_capacity.py",
    "capacityReport": "reviews/planner-current-qwen38-qlora-v1/training-capacity-report.json",
    "contract": "contracts/planner-contract-v5.json",
    "corpus": "corpus/planner-current-v1/traces.jsonl",
    "corpusManifest": "corpus/planner-current-v1/manifest.json",
    "development": "evaluation/planner-current-v1/cases.jsonl",
    "developmentManifest": "evaluation/planner-current-v1/manifest.json",
    "documentation": "docs/planner-current-qwen38-qlora-v1.md",
    "environment": "environments/qwen38-a40-v1.json",
    "generator": "scripts/build_planner_current_qwen38_qlora_v1.py",
    "holdoutDenylist": "contracts/planner-holdout-denylist-v2.json",
    "preflight": "src/loomarr_models/current_training.py",
    "reviewPublication": "reviews/planner-current-v1/publication.json",
    "runbook": "docs/planner-current-qwen38-qlora-v1-runbook.md",
    "runner": "scripts/run_planner_current_qwen38_qlora_v1.py",
    "runtime": "src/loomarr_models/current_training_runtime.py",
    "stockPublication": "runs/planner-current-qwen-stock-baseline-v3/publication.json",
    "trainingData": "src/loomarr_models/training_data.py",
    "verifier": "scripts/verify_planner_current_qwen38_qlora_v1_artifact.py",
}
GitProbe = Callable[[Path, Iterable[Path]], str]


@dataclass(frozen=True)
class CurrentTrainingPlan:
    schemaVersion: int
    experimentId: str
    configSha256: str
    corpusSha256: str
    traceCount: int
    maximumRenderedTokens: int
    maxSeqLength: int
    environmentSha256: str
    trainingArtifactRevision: str
    stockPublicationSha256: str
    committedSpendUsd: str
    trainingReservationUsd: str
    evaluationReservationUsd: str
    combinedReservationUsd: str
    projectedCombinedSpendUsd: str
    authorizationUsd: str
    trainingAuthorized: bool
    sourceCommit: str
    outputDir: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load current QLoRA config {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise PreflightError("current QLoRA config differs from schema v1")
    return value


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
    if config.get("status") == "failed-settled":
        raise PreflightError("current QLoRA experiment is terminal and cannot be reexecuted")
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
            raise PreflightError(f"invalid current QLoRA {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"current QLoRA {name} digest mismatch")

    contract = _object(bound["contract"])
    if contract.get("schemaVersion") != 2 or contract.get("contractId") != "loomarr-planner-contract-v5":
        raise PreflightError("current QLoRA contract drifted")
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
        raise PreflightError("current QLoRA requires exact 24-row disjoint train/development splits")
    _validate_corpus(root, config, bound, traces, cases)
    _validate_stock_publication(bound["stockPublication"], cases)
    maximum_tokens = _validate_capacity(config, bound["capacityReport"], traces)
    environment = _object(bound["environment"])
    if (
        environment.get("environmentId") != "qwen38-a40-v1"
        or environment.get("platform", {}).get("validatedSku") != EXECUTION["gpuSku"]
        or environment.get("trainingArtifact", {}).get("repository") != MODEL["repository"]
        or environment.get("trainingArtifact", {}).get("revision") != MODEL["revision"]
    ):
        raise PreflightError("current QLoRA environment or model drifted")
    authorization = _object(bound["authorization"])
    _validate_authorization(authorization, config)
    ledger = _object(bound["budgetLedger"])
    committed, projected, aggregate = _validate_budget(config, ledger)
    output = _output_path(root, Path(config["execution"]["outputDir"]))
    source_commit = (git_probe or _git_probe)(root, [config_path, *bound.values()])
    imported = sorted(name for name in sys.modules if name.split(".", 1)[0] in HEAVY_MODULE_PREFIXES)
    if imported:
        raise PreflightError(f"heavyweight modules imported before current QLoRA preflight: {imported[0]}")
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
        or config["experimentId"] != EXPERIMENT_ID
        or config["issue"] != ISSUE
        or set(config["bindings"]) != set(EXPECTED_BINDING_PATHS)
        or config["model"] != MODEL
        or config["execution"] != EXECUTION
        or config["runs"] != [RUN]
        or config["evaluation"] != EVALUATION
    ):
        raise PreflightError("current QLoRA protocol drifted")
    expected_status = "ready-for-training" if config["authority"] == TRAINING_AUTHORITY else "planned-no-paid-run-authorized"
    if config["status"] != expected_status or config["authority"] not in (
        NO_AUTHORITY,
        TRAINING_AUTHORITY,
    ):
        raise PreflightError("current QLoRA status and authority differ")
    if require_authorized and config["authority"] != TRAINING_AUTHORITY:
        raise PreflightError("current QLoRA training is not authorized")


def _validate_corpus(
    root: Path,
    config: dict[str, Any],
    bound: dict[str, Path],
    traces: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> None:
    corpus_manifest = _object(bound["corpusManifest"])
    development_manifest = _object(bound["developmentManifest"])
    review = _object(bound["reviewPublication"])
    if (
        config["bindings"]["corpus"]["records"] != 24
        or corpus_manifest.get("records") != 24
        or corpus_manifest.get("sha256") != sha256_file(bound["corpus"])
        or corpus_manifest.get("reviewStatus") != "independently-approved"
        or corpus_manifest.get("trainingAuthorized") is not False
        or review.get("status") != "complete-independent-review"
        or review.get("summary") != {"approved": 24, "pending": 0, "rejected": 0}
        or review.get("bindings", {}).get("training") != {
            "path": config["bindings"]["corpus"]["path"],
            "sha256": config["bindings"]["corpus"]["sha256"],
        }
    ):
        raise PreflightError("current QLoRA corpus is not the exact independently approved artifact")
    if (
        config["bindings"]["development"]["records"] != 24
        or development_manifest.get("records") != 24
        or development_manifest.get("sha256") != sha256_file(bound["development"])
        or development_manifest.get("modelExposure") != "none"
        or development_manifest.get("certificationAuthority") is not False
    ):
        raise PreflightError("current QLoRA development gate drifted")


def _validate_stock_publication(path: Path, cases: list[dict[str, Any]]) -> None:
    publication = _object(path)
    if (
        publication.get("experimentId") != "planner-current-qwen-stock-baseline-v3"
        or publication.get("status") != "qlora-justified-settled"
        or publication.get("decision", {}).get("failureClass") != "model-quality"
        or publication["decision"].get("qloraJustified") is not True
        or publication["decision"].get("trainingAuthorized") is not False
        or publication.get("summary", {}).get("caseCount") != 24
    ):
        raise PreflightError("current QLoRA stock prerequisite is not a settled model-quality miss")
    if publication.get("summary", {}).get("caseIds") != [case["caseId"] for case in cases]:
        raise PreflightError("current QLoRA stock publication used a different development order")


def _validate_capacity(config: dict[str, Any], path: Path, traces: list[dict[str, Any]]) -> int:
    report = _object(path)
    required = {
        "schemaVersion", "experimentId", "status", "model", "tokenizerFiles",
        "environmentPackages", "rendering", "corpus", "measurements", "renderedTrainingSha256",
    }
    if (
        set(report) != required
        or report.get("schemaVersion") != 1
        or report.get("experimentId") != EXPERIMENT_ID
        or report.get("status") != "passed"
        or report.get("model") != {
            "repository": MODEL["repository"], "revision": MODEL["revision"]
        }
        or report.get("environmentPackages") != {
            "jinja2": "3.1.6", "markupsafe": "3.0.3", "tokenizers": "0.22.2"
        }
        or report.get("rendering") != {
            "addGenerationPrompt": False,
            "reasoningEffort": "low",
            "preserveThinking": True,
            "truncation": False,
        }
    ):
        raise PreflightError("current QLoRA capacity report identity drifted")
    tokenizer = report.get("tokenizerFiles")
    if not isinstance(tokenizer, dict) or set(tokenizer) != {
        "chat_template.jinja", "tokenizer.json", "tokenizer_config.json"
    } or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in tokenizer.values()):
        raise PreflightError("current QLoRA tokenizer identities are invalid")
    corpus = report.get("corpus")
    if corpus != {
        "path": config["bindings"]["corpus"]["path"],
        "sha256": config["bindings"]["corpus"]["sha256"],
        "records": 24,
    }:
        raise PreflightError("current QLoRA capacity corpus drifted")
    measurements = report.get("measurements")
    if not isinstance(measurements, list) or len(measurements) != len(traces):
        raise PreflightError("current QLoRA capacity coverage drifted")
    for trace, measurement in zip(traces, measurements, strict=True):
        if (
            not isinstance(measurement, dict)
            or set(measurement) != {"traceId", "renderedBytes", "tokens"}
            or measurement["traceId"] != trace["traceId"]
            or isinstance(measurement["tokens"], bool)
            or not isinstance(measurement["tokens"], int)
            or not 0 < measurement["tokens"] <= RUN["maxSeqLength"]
            or not isinstance(measurement["renderedBytes"], int)
            or measurement["renderedBytes"] <= 0
        ):
            raise PreflightError("current QLoRA capacity measurement drifted")
    maximum = max(item["tokens"] for item in measurements)
    if maximum != 5416 or re.fullmatch(r"[0-9a-f]{64}", report.get("renderedTrainingSha256", "")) is None:
        raise PreflightError("current QLoRA capacity maximum or rendered identity drifted")
    return maximum


def _validate_authorization(authorization: dict[str, Any], config: dict[str, Any]) -> None:
    base = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "trainingReservationUsd": str(TRAINING_RESERVATION_USD),
        "evaluationReservationUsd": str(EVALUATION_RESERVATION_USD),
        "maxCombinedReservationUsd": str(COMBINED_RESERVATION_USD),
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
            raise PreflightError("current QLoRA authorization evidence drifted")
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
        raise PreflightError("current QLoRA paid authorization evidence drifted")


def _validate_budget(config: dict[str, Any], ledger: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal]:
    try:
        posted = Decimal(ledger["postedSpendUsd"])
        outstanding = Decimal(ledger["outstandingReservationsUsd"])
        committed = Decimal(ledger["committedSpendUsd"])
        aggregate = Decimal(ledger["authorizationUsd"])
    except (KeyError, InvalidOperation) as exc:
        raise PreflightError("current QLoRA budget ledger is invalid") from exc
    projected = committed + COMBINED_RESERVATION_USD
    expected = {
        "aggregateAuthorizationUsd": str(aggregate),
        "currentCommittedUsd": str(committed),
        "outstandingReservationsUsd": str(outstanding),
        "trainingReservationUsd": str(TRAINING_RESERVATION_USD),
        "evaluationReservationUsd": str(EVALUATION_RESERVATION_USD),
        "maxCombinedReservationUsd": str(COMBINED_RESERVATION_USD),
        "projectedCombinedSpendUsd": str(projected),
        "remainingAfterCombinedUsd": str(aggregate - projected),
    }
    if posted + outstanding != committed or config["budget"] != expected or projected > aggregate:
        raise PreflightError("current QLoRA budget does not reconcile")
    return committed, projected, aggregate


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must contain one object")
    return value
