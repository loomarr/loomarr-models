from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from loomarr_models.current_baseline import (
    AUTHORITY,
    baseline_decision,
    evaluate_current_case,
    preflight,
    summarize_current_candidate,
)
from loomarr_models.current_contract import read_jsonl


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_planner_current_stock_baseline as publication
import publish_planner_current_stock_failure as failure_publication
from tests.test_current_stock_baseline import oracle


CONFIG = ROOT / "experiments/planner-current-qwen-stock-baseline-v2.json"


class CurrentStockPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.contract = json.loads(
            (ROOT / cls.config["bindings"]["contract"]["path"]).read_text(encoding="utf-8")
        )
        cls.cases = read_jsonl(ROOT / cls.config["bindings"]["cases"]["path"])
        cls.plan = preflight(ROOT, CONFIG, require_authorized=False, git_probe=lambda *_: "a" * 40)
        cls.results = [
            evaluate_current_case(
                case,
                system_prompt=cls.contract["systemPrompt"],
                tools=cls.contract["tools"],
                generate=oracle(case),
                max_model_calls=cls.config["comparison"]["maxModelCallsPerCase"],
            )
            for case in cls.cases
        ]

    def fixture(self, directory: Path):
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
            "schemaVersion": 2,
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
                "results": {"path": "results.jsonl", "sha256": hashlib.sha256(results_bytes).hexdigest()},
                "generations": {"path": "generations.jsonl", "sha256": hashlib.sha256(generation_bytes).hexdigest()},
            },
            "summary": summary,
            "decision": baseline_decision(summary, self.config["scoring"]),
            "providerCostUsd": None,
            "authority": AUTHORITY,
        }
        (directory / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_replays_hash_bound_redacted_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            expected = self.fixture(directory)
            manifest, summary, decision = publication.validate_run(
                directory, self.config, self.plan
            )
            self.assertEqual(manifest, expected)
            self.assertEqual(summary["caseCount"], 24)
            self.assertFalse(decision["qloraJustified"])

            raw = directory / "generations.jsonl"
            values = [json.loads(line) for line in raw.read_text().splitlines()]
            values[0]["raw"] = "must not survive publication"
            blob = b"".join(json.dumps(item).encode() + b"\n" for item in values)
            raw.write_bytes(blob)
            changed = json.loads((directory / "run-manifest.json").read_text())
            changed["artifacts"]["generations"]["sha256"] = hashlib.sha256(blob).hexdigest()
            (directory / "run-manifest.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(Exception, "safely redacted"):
                publication.validate_run(directory, self.config, self.plan)

    def test_provider_evidence_is_bounded_by_authorized_reservation(self):
        evidence = {
            "schemaVersion": 2,
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
            "costUsd": {"gpu": "0.49", "disk": "0.01", "persistentStorage": "0.02", "total": "0.52"},
        }
        self.assertIs(
            publication.validate_provider_evidence(evidence, self.config["execution"], self.plan),
            evidence,
        )
        charged = copy.deepcopy(evidence)
        charged["costUsd"]["disk"] = "1.00"
        charged["costUsd"]["persistentStorage"] = "0.02"
        charged["costUsd"]["total"] = "1.51"
        with self.assertRaisesRegex(Exception, "reservation"):
            publication.validate_provider_evidence(charged, self.config["execution"], self.plan)

    def test_settlement_posts_exact_cost_without_consuming_a_reservation(self):
        budget = {
            "authorizationUsd": "40.00",
            "postedSpendUsd": "28.6967677051754599875",
            "outstandingReservationsUsd": "0",
            "committedSpendUsd": "28.6967677051754599875",
        }
        plan = SimpleNamespace(
            committedSpendUsd="28.6967677051754599875",
            reservationUsd="1.50",
        )
        settled = publication.settle_budget(budget, Decimal("0.52"), plan)
        self.assertEqual(settled["postedSpendUsd"], "29.2167677051754599875")
        self.assertEqual(settled["committedSpendUsd"], "29.2167677051754599875")
        self.assertEqual(settled["outstandingReservationsUsd"], "0")

        with self.assertRaisesRegex(Exception, "exceeds authorization"):
            publication.settle_budget(budget, Decimal("1.51"), plan)

    def test_runtime_failure_publication_requires_hash_bound_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            bindings = {}
            for name, filename in (
                ("archive", "failure.tgz"),
                ("baselineLog", "baseline.log"),
                ("setupLog", "setup.log"),
            ):
                artifact = directory / filename
                artifact.write_bytes(name.encode())
                bindings[name] = {
                    "path": filename,
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            manifest = {
                "schemaVersion": 1,
                "experimentId": self.config["experimentId"],
                "status": "failed-unsettled",
                "completionClass": "runtime-configuration-failure",
                "sourceCommit": "a" * 40,
                "sourceConfigSha256": "b" * 64,
                "providerCostUsd": None,
                "error": {
                    "exitCode": 2,
                    "message": "evaluation prompt leaves only -729 generation tokens within context",
                },
                "artifacts": bindings,
                "authority": AUTHORITY,
            }
            path = directory / "failure-manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(failure_publication.validate_failure(path), manifest)
            (directory / "baseline.log").write_text("drift", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "digest mismatch"):
                failure_publication.validate_failure(path)


if __name__ == "__main__":
    unittest.main()
