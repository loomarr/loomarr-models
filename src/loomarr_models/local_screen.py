from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .experiment import PreflightError, _git_probe, _input_path, sha256_file
from .planner_v4 import DEVELOPMENT_BEHAVIORS, validate_development
from .validator import load_contract, load_denylist, load_jsonl


SCREEN_ID = "planner-v4-local-screen-v1"
CANDIDATE_IDS = ("qwen38-27b-mlx-nvfp4", "gemma4-12b-q4-k-m")
CONFIG_KEYS = {
    "schemaVersion",
    "screenId",
    "issue",
    "status",
    "externalCostUsd",
    "bindings",
    "candidates",
    "execution",
    "comparison",
    "scoring",
    "authority",
}
BINDING_KEYS = {
    "cases",
    "casesManifest",
    "contract",
    "holdoutDenylist",
    "developmentExposure",
    "ollamaSnapshot",
    "v4Generator",
    "v4Validator",
    "scorer",
    "preflight",
    "runtime",
    "planGenerator",
    "runner",
    "publisher",
}
EXECUTION = {
    "platform": "darwin-arm64",
    "minimumMemoryBytes": 25769803776,
    "apiBaseUrl": "http://127.0.0.1:11434",
    "outputDir": ".artifacts/planner-v4-local-screen-v1",
    "maxWallClockSecondsPerCandidate": 21600,
    "requestTimeoutSeconds": 600,
    "keepAlive": "5m",
    "requireCleanGit": True,
    "externalNetworkAllowed": False,
}
COMPARISON = {
    "candidateOrder": list(CANDIDATE_IDS),
    "seed": 3407,
    "numCtx": 4096,
    "numPredict": 768,
    "temperature": 0,
    "think": "low",
    "maxModelCallsPerCase": 5,
    "trials": 1,
    "automaticRetry": False,
}
SCORING = {
    "scorerVersion": "planner-development-scorer-v1",
    "qualityMargin": 0.02,
    "weights": {
        "groundedCompletion": 0.2,
        "correctToolOperation": 0.2,
        "schemaValidity": 0.1,
        "policyAccuracy": 0.15,
        "proposalQuality": 0.25,
        "recovery": 0.1,
    },
    "thresholds": {
        "minGroundedCompletionRate": 0.95,
        "minCorrectToolOperationRate": 0.9,
        "minSchemaValidityRate": 0.98,
        "minPolicyAccuracyRate": 0.95,
        "minProposalQualityRate": 0.9,
        "minRecoveryRate": 0.8,
        "maxP95ToolCalls": 3,
    },
}
AUTHORITY = {
    "screenOnly": True,
    "certificationAuthority": False,
    "trainingAuthority": False,
    "releaseAuthority": False,
    "purpose": "zero-cost base-model selection and QLoRA necessity screen",
}


@dataclass(frozen=True)
class LocalScreenPlan:
    schemaVersion: int
    screenId: str
    configSha256: str
    casesSha256: str
    caseCount: int
    contractId: str
    sourceCommit: str
    outputDir: str
    candidateIds: tuple[str, ...]
    externalCostUsd: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


GitProbe = Callable[[Path, Iterable[Path]], str]


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot load local screen config {path}: {exc}") from exc
    if not isinstance(value, dict) or set(value) != CONFIG_KEYS or value.get("schemaVersion") != 1:
        raise PreflightError("local screen config fields differ from schema v1")
    return value


def build_plan(
    root: Path,
    config_path: Path,
    *,
    git_probe: GitProbe | None = None,
) -> tuple[dict[str, Any], LocalScreenPlan, dict[str, Any]]:
    root = root.resolve(strict=True)
    config_path = _input_path(root, config_path)
    config = load_config(config_path)
    _validate_shape(config)
    bindings = config["bindings"]
    bound: dict[str, Path] = {}
    for name, binding in bindings.items():
        allowed = {"path", "sha256", "count"} if name == "cases" else {"path", "sha256"}
        if not isinstance(binding, dict) or set(binding) != allowed:
            raise PreflightError(f"invalid local screen {name} binding")
        bound[name] = _input_path(root, Path(binding["path"]))
        if sha256_file(bound[name]) != binding["sha256"]:
            raise PreflightError(f"local screen {name} digest mismatch")

    contract = load_contract(bound["contract"])
    identities, digests = load_denylist(bound["holdoutDenylist"])
    cases = load_jsonl(bound["cases"])
    report = validate_development(
        cases,
        contract=contract,
        denylisted_identities=identities,
        denylisted_sha256=digests,
    )
    if report.records != 120 or bindings["cases"]["count"] != 120:
        raise PreflightError("local screen requires the exact 120-case v4 gate")
    manifest = _object(bound["casesManifest"])
    if (
        manifest.get("corpusId") != "planner-development-v4"
        or manifest.get("status") != "frozen-development-only-no-model-exposure"
        or manifest.get("caseCount") != 120
        or manifest.get("casesSha256") != report.sha256
        or manifest.get("contractId") != contract["contractId"]
    ):
        raise PreflightError("local screen development manifest is not pristine")
    exposure = _object(bound["developmentExposure"])
    if exposure != {
        "schemaVersion": 1,
        "corpusId": "planner-development-v4",
        "status": "unexposed",
        "exposures": [],
    }:
        raise PreflightError("local screen development gate was already exposed")
    snapshot = _object(bound["ollamaSnapshot"])
    _validate_snapshot(snapshot, config["candidates"])
    source_commit = (git_probe or _git_probe)(
        root,
        [config_path, *bound.values()],
    )
    return (
        config,
        LocalScreenPlan(
            schemaVersion=1,
            screenId=SCREEN_ID,
            configSha256=sha256_file(config_path),
            casesSha256=report.sha256,
            caseCount=report.records,
            contractId=contract["contractId"],
            sourceCommit=source_commit,
            outputDir=config["execution"]["outputDir"],
            candidateIds=tuple(CANDIDATE_IDS),
            externalCostUsd="0",
        ),
        snapshot,
    )


def _validate_shape(config: dict[str, Any]) -> None:
    if (
        config["screenId"] != SCREEN_ID
        or config["issue"] != "https://github.com/loomarr/loomarr-models/issues/22"
        or config["status"] != "ready-for-local-screen"
        or config["externalCostUsd"] != "0"
    ):
        raise PreflightError("local screen identity or status drifted")
    if set(config["bindings"]) != BINDING_KEYS:
        raise PreflightError("local screen bindings differ from schema v1")
    if config["execution"] != EXECUTION:
        raise PreflightError("local screen execution envelope drifted")
    if config["comparison"] != COMPARISON:
        raise PreflightError("local screen comparison protocol drifted")
    if config["scoring"] != SCORING:
        raise PreflightError("local screen scoring protocol drifted")
    if config["authority"] != AUTHORITY:
        raise PreflightError("local screen authority boundary drifted")


def _validate_snapshot(snapshot: dict[str, Any], candidates: Any) -> None:
    if set(snapshot) != {
        "schemaVersion",
        "capturedAt",
        "endpoint",
        "serverVersion",
        "host",
        "candidates",
    } or snapshot.get("schemaVersion") != 1:
        raise PreflightError("Ollama snapshot fields differ from schema v1")
    if snapshot["endpoint"] != EXECUTION["apiBaseUrl"]:
        raise PreflightError("Ollama snapshot endpoint is not loopback")
    expected_host = {
        "platform": EXECUTION["platform"],
        "chip": "Apple M5 Pro",
        "memoryBytes": EXECUTION["minimumMemoryBytes"],
    }
    if snapshot["host"] != expected_host:
        raise PreflightError("Ollama snapshot host differs from the local screen envelope")
    frozen = snapshot["candidates"]
    if candidates != frozen or not isinstance(frozen, list) or len(frozen) != 2:
        raise PreflightError("local screen candidates differ from the Ollama snapshot")
    if [candidate.get("candidateId") for candidate in frozen] != list(CANDIDATE_IDS):
        raise PreflightError("local screen candidate order drifted")
    for candidate in frozen:
        if not {"completion", "tools", "thinking"} <= set(candidate.get("capabilities", [])):
            raise PreflightError("local screen candidate lacks required Ollama capabilities")
        if not isinstance(candidate.get("digest"), str) or len(candidate["digest"]) != 64:
            raise PreflightError("local screen candidate digest is invalid")


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PreflightError(f"{path.name} must be an object")
    return value
