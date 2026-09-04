#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "planner-qwen38-qlora-v2"
PAID_TRAINING_AUTHORIZED = False
CONFIG_PATH = ROOT / f"experiments/{EXPERIMENT_ID}.json"
EVAL_PLAN_PATH = ROOT / "experiments/planner-adapter-eval-v2-plan.json"
INDEX_PATH = ROOT / f"runs/{EXPERIMENT_ID}/index.json"
DOC_PATH = ROOT / "docs/planner-qwen38-qlora-v2.md"
CORPUS_PATH = ROOT / "corpus/planner-behavior-v2/traces.jsonl"
CORPUS_MANIFEST_PATH = ROOT / "corpus/planner-behavior-v2/manifest.json"
CASES_PATH = ROOT / "evaluation/planner-behavior-development-v2/cases.jsonl"
CASES_MANIFEST_PATH = ROOT / "evaluation/planner-behavior-development-v2/manifest.json"
CONTRACT_PATH = ROOT / "contracts/planner-contract-v3.json"
DENYLIST_PATH = ROOT / "contracts/holdout-denylist-v1.json"
ENVIRONMENT_PATH = ROOT / "environments/qwen38-a40-v1.json"
BUDGET_PATH = ROOT / "budgets/external-spend-v1.json"


def pretty(value: Any) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"


def binding(path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **extra,
    }


def build_outputs() -> dict[Path, bytes]:
    budget = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    posted = Decimal(budget["postedSpendUsd"])
    outstanding = Decimal(budget["outstandingReservationsUsd"])
    committed = Decimal(budget["committedSpendUsd"])
    authorization = Decimal(budget["authorizationUsd"])
    if posted + outstanding != committed or authorization != Decimal("40.00"):
        raise ValueError("aggregate budget ledger is invalid or unauthorized")
    training_reservation = Decimal("1.50")
    evaluation_reservation = Decimal("3.00")
    after_training = committed + training_reservation
    after_evaluation = after_training + evaluation_reservation
    if after_evaluation > authorization:
        raise ValueError("training and evaluation reservations exceed aggregate authorization")

    corpus_manifest = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    cases_manifest = json.loads(CASES_MANIFEST_PATH.read_text(encoding="utf-8"))
    environment = json.loads(ENVIRONMENT_PATH.read_text(encoding="utf-8"))
    if (
        corpus_manifest.get("status") != "reviewed-frozen-training-only"
        or corpus_manifest.get("traceCount") != 120
        or corpus_manifest.get("trainingAuthorized") is not False
        or corpus_manifest.get("tracesSha256") != hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()
    ):
        raise ValueError("targeted training corpus is not the exact reviewed frozen artifact")
    if (
        cases_manifest.get("status") != "frozen-development-only"
        or cases_manifest.get("caseCount") != 60
        or cases_manifest.get("casesSha256") != hashlib.sha256(CASES_PATH.read_bytes()).hexdigest()
    ):
        raise ValueError("development gate is not the exact frozen 60-case artifact")

    config = {
        "schemaVersion": 1,
        "experimentId": EXPERIMENT_ID,
        "issue": "https://github.com/loomarr/loomarr-models/issues/20",
        "status": "ready-for-training" if PAID_TRAINING_AUTHORIZED else "planned-no-paid-run-authorized",
        "bindings": {
            "corpus": binding(CORPUS_PATH, traceCount=120, requireApproved=True),
            "corpusManifest": binding(CORPUS_MANIFEST_PATH),
            "contract": binding(CONTRACT_PATH),
            "denylist": binding(DENYLIST_PATH),
            "environment": binding(ENVIRONMENT_PATH),
            "budget": {"path": str(BUDGET_PATH.relative_to(ROOT))},
        },
        "models": {
            "upstream": {
                "repository": environment["baseModel"]["repository"],
                "revision": environment["baseModel"]["revision"],
            },
            "trainingArtifact": {
                "repository": environment["trainingArtifact"]["repository"],
                "revision": environment["trainingArtifact"]["revision"],
            },
        },
        "execution": {
            "platform": "linux-amd64",
            "gpuSku": "NVIDIA A40",
            "gpuCount": 1,
            "minimumVramGb": 48,
            "maxWallClockSeconds": 9000,
            "maxReservationUsd": "1.50",
            "outputDir": ".artifacts/planner-qwen38-qlora-v2",
            "requireCleanGit": True,
        },
        "runs": [
            {
                "runId": "qwen38-qlora-a40-v2",
                "seed": 3407,
                "maxSeqLength": 4096,
                "maxSteps": 45,
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
        ],
    }
    config_bytes = pretty(config)
    eval_plan = {
        "schemaVersion": 1,
        "experimentId": "planner-adapter-eval-v2",
        "issue": "https://github.com/loomarr/loomarr-models/issues/20",
        "status": "waiting-for-hash-bound-adapter",
        "paidEvaluationAuthorized": False,
        "bindings": {
            "cases": binding(CASES_PATH, caseCount=60),
            "casesManifest": binding(CASES_MANIFEST_PATH),
            "trainingCorpus": binding(CORPUS_PATH),
            "contract": binding(CONTRACT_PATH),
            "denylist": binding(DENYLIST_PATH),
            "environment": binding(ENVIRONMENT_PATH),
            "trainingConfig": {
                "path": str(CONFIG_PATH.relative_to(ROOT)),
                "sha256": hashlib.sha256(config_bytes).hexdigest(),
            },
        },
        "candidateOrder": ["stock", "adapter"],
        "comparison": {
            "seed": 3407,
            "maxSeqLength": 4096,
            "maxNewTokens": 768,
            "maxModelCallsPerCase": 5,
            "disableCompile": True,
            "offloadEmbedding": False,
            "reasoningEffort": "low",
            "doSample": False,
            "trials": 1,
        },
        "adapterBinding": None,
        "budget": {
            "aggregateAuthorizationUsd": str(authorization),
            "currentCommittedUsd": str(committed),
            "trainingReservationUsd": str(training_reservation),
            "evaluationReservationUsd": str(evaluation_reservation),
            "maximumAggregateCommitmentUsd": str(after_evaluation),
            "remainingAfterMaximumUsd": str(authorization - after_evaluation),
        },
        "promotion": {
            "requireMeaningfulAggregateGain": True,
            "requireTargetFamilyImprovement": True,
            "maximumUnsupportedIds": 0,
            "maximumAuthorityViolations": 0,
            "maximumExecutableEnvelopeRegressions": 0,
            "certifiedPillars": ["channel-curation"],
            "uncertifiedPillars": ["channel-recommendation", "filler-curation"],
        },
    }
    eval_bytes = pretty(eval_plan)
    outputs = {CONFIG_PATH: config_bytes, EVAL_PLAN_PATH: eval_bytes}
    index_inputs = {
        **outputs,
        CORPUS_PATH: CORPUS_PATH.read_bytes(),
        CORPUS_MANIFEST_PATH: CORPUS_MANIFEST_PATH.read_bytes(),
        CASES_PATH: CASES_PATH.read_bytes(),
        CASES_MANIFEST_PATH: CASES_MANIFEST_PATH.read_bytes(),
        ENVIRONMENT_PATH: ENVIRONMENT_PATH.read_bytes(),
        DOC_PATH: DOC_PATH.read_bytes(),
    }
    index = {
        "schemaVersion": 1,
        "publicationId": EXPERIMENT_ID,
        "status": config["status"],
        "paidTrainingAuthorized": PAID_TRAINING_AUTHORIZED,
        "artifacts": [
            {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in sorted(index_inputs.items(), key=lambda item: str(item[0]))
        ],
        "generator": binding(Path(__file__)),
        "budget": eval_plan["budget"],
        "nextGate": (
            "publish the exact authorization commit and wait for CI before provisioning"
            if PAID_TRAINING_AUTHORIZED
            else "review and separately authorize the exact training reservation"
        ),
        "trainingAuthorized": PAID_TRAINING_AUTHORIZED,
        "releaseAuthorized": False,
    }
    outputs[INDEX_PATH] = pretty(index)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the targeted Qwen3.8 QLoRA v2 plan")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, data in outputs.items()
            if not path.exists() or path.read_bytes() != data
        ]
        if stale:
            raise SystemExit("stale QLoRA v2 plan artifacts: " + ", ".join(stale))
        return
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


if __name__ == "__main__":
    main()
