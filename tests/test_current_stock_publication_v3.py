from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from loomarr_models.current_baseline import (
    baseline_decision,
    evaluate_current_case,
    summarize_current_candidate,
)
from loomarr_models.current_baseline_v3 import preflight
from loomarr_models.current_contract import read_jsonl
from loomarr_models.current_publication_v3 import (
    settle_budget,
    validate_provider_evidence,
    validate_run,
)
from tests.test_current_stock_baseline import oracle


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v3.json"
sys.path.insert(0, str(ROOT / "scripts"))

import publish_planner_current_stock_baseline_v3 as publisher


class CurrentStockPublicationV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        contract = json.loads(
            (ROOT / cls.config["bindings"]["contract"]["path"]).read_text(encoding="utf-8")
        )
        cls.cases = read_jsonl(ROOT / cls.config["bindings"]["cases"]["path"])
        cls.plan = preflight(ROOT, CONFIG, git_probe=lambda *_: "a" * 40)
        cls.results = [
            evaluate_current_case(
                case,
                system_prompt=contract["systemPrompt"],
                tools=contract["tools"],
                generate=oracle(case),
                max_model_calls=cls.config["comparison"]["maxModelCallsPerCase"],
            )
            for case in cls.cases
        ]

    def fixture(self, directory: Path) -> dict:
        results_bytes = b"".join(
            json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for result in self.results
        )
        (directory / "results.jsonl").write_bytes(results_bytes)
        generations = [
            {"schemaVersion": 1, "modelCall": index + 1, "rawSha256": "b" * 64}
            for index in range(sum(result.modelCalls for result in self.results))
        ]
        generation_bytes = b"".join(
            json.dumps(item, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for item in generations
        )
        (directory / "generations.jsonl").write_bytes(generation_bytes)
        summary = summarize_current_candidate(
            self.plan.candidateId, self.results, peak_vram_bytes=20_000_000_000
        )
        environment = json.loads(
            (ROOT / self.config["bindings"]["environment"]["path"]).read_text(encoding="utf-8")
        )
        manifest = {
            "schemaVersion": 3,
            "experimentId": self.config["experimentId"],
            "status": "complete-unsettled",
            "completionClass": "complete-model-quality",
            "preflight": self.plan.as_dict(),
            "elapsedSeconds": 60,
            "packages": {
                "torch": f'{environment["container"]["pytorch"]}+cu128',
                "unsloth": environment["trainingPackages"]["unsloth"],
                "unsloth-zoo": environment["trainingPackages"]["unsloth_zoo"],
                "transformers": environment["trainingPackages"]["transformers"],
            },
            "runtime": {
                "python": "3.12.0",
                "cuda": "12.8",
                "gpu": {
                    "name": "NVIDIA A40",
                    "totalMemoryBytes": 48_000_000_000,
                    "peakReservedBytes": 20_000_000_000,
                },
            },
            "artifacts": {
                "results": {
                    "path": "results.jsonl",
                    "sha256": hashlib.sha256(results_bytes).hexdigest(),
                },
                "generations": {
                    "path": "generations.jsonl",
                    "sha256": hashlib.sha256(generation_bytes).hexdigest(),
                },
            },
            "summary": summary,
            "decision": baseline_decision(summary, self.config["scoring"]),
            "providerCostUsd": None,
            "authority": self.config["authority"],
        }
        (directory / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_replays_complete_hash_bound_redacted_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            expected = self.fixture(directory)
            manifest, summary, decision = validate_run(directory, self.config, self.plan)
            self.assertEqual(manifest, expected)
            self.assertEqual(summary["caseCount"], 24)
            self.assertFalse(decision["qloraJustified"])

            raw = directory / "generations.jsonl"
            raw.write_text('{"raw":"must not survive publication","rawSha256":"' + "b" * 64 + '"}\n')
            changed = json.loads((directory / "run-manifest.json").read_text())
            changed["artifacts"]["generations"]["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
            (directory / "run-manifest.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(Exception, "coverage|redacted"):
                validate_run(directory, self.config, self.plan)

    def test_provider_settlement_is_exact_bounded_and_deleted(self):
        evidence = {
            "schemaVersion": 3,
            "experimentId": self.config["experimentId"],
            "provider": "runpod",
            "status": "settled-resources-deleted",
            "capturedAt": "2026-09-17T01:00:00Z",
            "cloud": "SECURE",
            "dataCenterId": "US-SYNTHETIC-1",
            "gpuSku": "NVIDIA A40",
            "gpuHourlyUsd": "0.49",
            "createdAt": "2026-09-17T00:00:00Z",
            "deletedAt": "2026-09-17T01:00:00Z",
            "podIdSha256": "a" * 64,
            "zeroActivePods": True,
            "storageMode": "pod-persistent",
            "persistentStorageDeletedWithPod": True,
            "costUsd": {
                "gpu": "0.49",
                "disk": "0.01",
                "persistentStorage": "0.02",
                "total": "0.52",
            },
        }
        self.assertIs(validate_provider_evidence(evidence, self.config["execution"], self.plan), evidence)
        drifted = copy.deepcopy(evidence)
        drifted["zeroActivePods"] = False
        with self.assertRaisesRegex(Exception, "teardown"):
            validate_provider_evidence(drifted, self.config["execution"], self.plan)

    def test_budget_settlement_posts_only_exact_provider_cost(self):
        budget = json.loads(
            (ROOT / self.config["bindings"]["budgetLedger"]["path"]).read_text(encoding="utf-8")
        )
        settled = settle_budget(budget, Decimal("0.52"), self.plan)
        self.assertEqual(
            Decimal(settled["postedSpendUsd"]), Decimal(budget["postedSpendUsd"]) + Decimal("0.52")
        )
        with self.assertRaisesRegex(Exception, "exceeds authorization"):
            settle_budget(budget, Decimal("1.51"), self.plan)

    def test_publisher_refuses_before_reading_provider_evidence_when_unauthorized(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/publish_planner_current_stock_baseline_v3.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("paid current stock v3 execution is not authorized", result.stderr)

    def test_publisher_immutably_settles_and_terminalizes_each_quality_outcome(self):
        for justified in (False, True):
            with self.subTest(qlora_justified=justified), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                artifact_dir = root / ".artifacts/run"
                artifact_dir.mkdir(parents=True)
                (artifact_dir / "run-manifest.json").write_text("{}\n", encoding="utf-8")
                config_path = root / "experiment.json"
                config_path.write_text("{}\n", encoding="utf-8")
                authorization_path = root / "authorization.json"
                authorization_path.write_text(
                    json.dumps({"status": "authorized", "authorizedPlanCommit": "a" * 40}),
                    encoding="utf-8",
                )
                budget_path = root / "budget.json"
                budget_path.write_text(
                    json.dumps(
                        {
                            "postedSpendUsd": "29.00",
                            "outstandingReservationsUsd": "0",
                            "committedSpendUsd": "29.00",
                            "authorizationUsd": "40.00",
                        }
                    ),
                    encoding="utf-8",
                )
                provider_path = root / "provider.json"
                provider_path.write_text("{}\n", encoding="utf-8")
                runs = root / "runs/v3"
                plan = SimpleNamespace(outputDir=".artifacts/run", sourceCommit="b" * 40)
                config = {
                    "execution": {},
                    "authority": {
                        "paidBaselineAuthorized": True,
                        "modelDownloadAuthorized": True,
                        "gpuAuthorized": True,
                        "trainingAuthorized": False,
                        "certificationAuthority": False,
                        "deploymentAuthority": False,
                        "releaseAuthority": False,
                    },
                }
                provider = {
                    "capturedAt": "2026-09-17T05:00:00Z",
                    "costUsd": {"total": "0.52"},
                }
                settled = {
                    "postedSpendUsd": "29.52",
                    "outstandingReservationsUsd": "0",
                    "committedSpendUsd": "29.52",
                    "authorizationUsd": "40.00",
                }
                decision = {"qloraJustified": justified, "trainingAuthorized": False}
                terminal = b'{"status":"complete-settled"}\n'
                with (
                    patch.object(publisher, "ROOT", root),
                    patch.object(publisher, "RUNS", runs),
                    patch.object(publisher, "CONFIG", config_path),
                    patch.object(publisher, "AUTHORIZATION", authorization_path),
                    patch.object(publisher, "BUDGET", budget_path),
                    patch.object(publisher, "preflight", return_value=plan),
                    patch.object(publisher, "load_config", return_value=config),
                    patch.object(publisher, "_git_probe", return_value="c" * 40),
                    patch.object(
                        publisher,
                        "validate_run",
                        return_value=({}, {"caseCount": 24}, decision),
                    ),
                    patch.object(
                        publisher, "validate_provider_evidence", return_value=provider
                    ),
                    patch.object(publisher, "settle_budget", return_value=settled),
                    patch.object(publisher.builder, "content", return_value=terminal),
                ):
                    publication = publisher.publish(provider_path)

                expected_status = (
                    "qlora-justified-settled"
                    if justified
                    else "qlora-not-justified-settled"
                )
                self.assertEqual(publication["status"], expected_status)
                self.assertFalse(publication["authority"]["paidBaselineAuthorized"])
                self.assertFalse(publication["authority"]["trainingAuthorized"])
                self.assertTrue((runs / "evidence/run-manifest.json").is_file())
                self.assertTrue((runs / "source-experiment.json").is_file())
                self.assertTrue((runs / "provider-settlement.json").is_file())
                self.assertEqual(config_path.read_bytes(), terminal)
                completed = json.loads(authorization_path.read_text(encoding="utf-8"))
                self.assertEqual(completed["status"], "complete")
                self.assertEqual(completed["publicationPath"], "runs/v3/publication.json")
                posted = json.loads(budget_path.read_text(encoding="utf-8"))
                self.assertEqual(posted["postedSpendUsd"], "29.52")


if __name__ == "__main__":
    unittest.main()
