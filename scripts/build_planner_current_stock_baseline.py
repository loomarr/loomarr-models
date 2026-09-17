#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("experiments/planner-current-qwen-stock-baseline-v2.json")
AUTHORIZATION_PATH = Path("reviews/planner-current-qwen-stock-baseline/authorization-v2.json")
EXPERIMENT_ID = "planner-current-qwen-stock-baseline-v2"


def encoded(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"


def sha(path: Path) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def binding(path: Path) -> dict[str, str]:
    return {"path": path.as_posix(), "sha256": sha(path)}


def authorization() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "status": "not-authorized",
        "maxReservationUsd": "0",
        "authorizedBy": None,
        "authorizedAt": None,
        "authorizedPlanCommit": None,
    }


def config(authorization_blob: bytes) -> dict[str, Any]:
    cases_path = Path("evaluation/planner-current-v1/cases.jsonl")
    budget_path = Path("budgets/external-spend-v1.json")
    budget = json.loads((ROOT / budget_path).read_text(encoding="utf-8"))
    committed = Decimal(budget["committedSpendUsd"])
    aggregate = Decimal(budget["authorizationUsd"])
    bindings: dict[str, Any] = {
        "authorization": {
            "path": AUTHORIZATION_PATH.as_posix(),
            "sha256": hashlib.sha256(authorization_blob).hexdigest(),
        },
        "budgetLedger": binding(budget_path),
        "cases": {**binding(cases_path), "records": 24},
        "casesManifest": binding(Path("evaluation/planner-current-v1/manifest.json")),
        "contract": binding(Path("contracts/planner-contract-v5.json")),
        "environment": binding(Path("environments/qwen38-a40-v1.json")),
        "generator": binding(Path("scripts/build_planner_current_stock_baseline.py")),
        "holdoutDenylist": binding(Path("contracts/planner-holdout-denylist-v2.json")),
        "preflight": binding(Path("src/loomarr_models/current_baseline.py")),
        "publisher": binding(Path("scripts/publish_planner_current_stock_baseline.py")),
        "runner": binding(Path("scripts/run_planner_current_stock_baseline.py")),
        "runtime": binding(Path("src/loomarr_models/current_stock_runtime.py")),
    }
    return {
        "schemaVersion": 2,
        "experimentId": EXPERIMENT_ID,
        "issue": "https://github.com/loomarr/loomarr-models/issues/25",
        "status": "planned-no-paid-execution-authorized",
        "bindings": bindings,
        "model": {
            "candidateId": "qwen38-27b-unsloth-bnb-4bit",
            "repository": "unsloth/Qwen3.8-27B-unsloth-bnb-4bit",
            "revision": "8aa5f05d26b7205477066e1449e0af13f762a299",
            "quantization": "unsloth-bnb-4bit",
        },
        "execution": {
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
            "outputDir": ".artifacts/planner-current-qwen-stock-baseline-v2",
            "requireCleanGit": True,
            "automaticRetry": False,
        },
        "comparison": {
            "seed": 3407,
            "maxSeqLength": 4096,
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
        },
        "scoring": {
            "scorerVersion": "planner-current-development-scorer-v2",
            "thresholds": {
                "maxP95ToolCalls": 2,
                "minCorrectToolOperationRate": 0.90,
                "minGroundedCompletionRate": 0.95,
                "minSchemaValidityRate": 0.98,
                "minDateMeaningAccuracyRate": 1.0,
                "minPolicyAccuracyRate": 0.95,
                "minProposalQualityRate": 0.90,
                "minRecoveryRate": 1.0,
            },
        },
        "decision": {
            "passingStockStopsTraining": True,
            "runtimeOrInfrastructureFailureJustifiesTraining": False,
            "requiresObservedRecoveryFault": True,
            "applicationRecoveryBlocker": "https://github.com/loomarr/loomarr/issues/1195",
        },
        "hostedProductionComparison": {
            "status": "preregistered-no-provider-inference-authorized",
            "exactCurrentContractRequired": True,
            "sameCasesAndOrderRequired": True,
            "historicalScoresComparable": False,
            "certificationAuthority": False,
        },
        "budget": {
            "aggregateAuthorizationUsd": str(aggregate),
            "currentCommittedUsd": str(committed),
            "outstandingReservationsUsd": budget["outstandingReservationsUsd"],
            "proposedReservationUsd": "0",
            "projectedCommitmentUsd": str(committed),
            "remainingAuthorizationUsd": str(aggregate - committed),
        },
        "authority": {
            "paidBaselineAuthorized": False,
            "modelDownloadAuthorized": False,
            "gpuAuthorized": False,
            "trainingAuthorized": False,
            "certificationAuthority": False,
            "deploymentAuthority": False,
            "releaseAuthority": False,
        },
    }


def outputs() -> dict[Path, bytes]:
    authorization_blob = encoded(authorization())
    return {
        AUTHORIZATION_PATH: authorization_blob,
        OUTPUT: encoded(config(authorization_blob)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = outputs()
    if args.check:
        drift = [path.as_posix() for path, expected in generated.items() if not (ROOT / path).is_file() or (ROOT / path).read_bytes() != expected]
        if drift:
            raise SystemExit("generated current stock baseline artifacts drifted: " + ", ".join(drift))
        return
    for path, content in generated.items():
        target = ROOT / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


if __name__ == "__main__":
    main()
