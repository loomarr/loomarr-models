from __future__ import annotations

import hashlib
import json
import unittest
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION_PATH = ROOT / "runs/planner-qwen38-smoke-v1/publication.json"


class RunPublicationTests(unittest.TestCase):
    def test_smoke_publication_is_hash_bound_budgeted_and_unreleased(self):
        publication = json.loads(PUBLICATION_PATH.read_text(encoding="utf-8"))
        manifest_path = ROOT / publication["runManifestPath"]
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        budget = json.loads(
            (ROOT / "budgets/external-spend-v1.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            hashlib.sha256(manifest_bytes).hexdigest(),
            publication["runManifestSha256"],
        )
        self.assertEqual(manifest["runId"], publication["runId"])
        self.assertEqual(
            publication["trackingIssue"],
            "https://github.com/loomarr/loomarr-models/issues/4",
        )
        self.assertEqual(publication["decision"], "continue-qlora-evaluation-no-release")
        self.assertEqual(
            manifest["adapterFiles"]["adapter_model.safetensors"],
            "08a166aa73ec1aaf965cf5a53af61a728d4542c841859b477af72305e5cb35f7",
        )
        self.assertEqual(
            manifest["preflight"]["sourceCommit"],
            "d0e96f269f55f9d3fa7b7158b069974250bc2be3",
        )
        self.assertEqual(manifest["runtime"]["gpu"][0]["name"], "NVIDIA A40")

        posted = Decimal(budget["postedSpendUsd"])
        outstanding = Decimal(budget["outstandingReservationsUsd"])
        committed = Decimal(budget["committedSpendUsd"])
        authorization = Decimal(budget["authorizationUsd"])
        self.assertEqual(posted + outstanding, committed)
        self.assertLessEqual(committed, authorization)

        if publication["status"] == "passed-pending-cost-settlement":
            self.assertIsNone(publication["providerCostUsd"])
            self.assertGreaterEqual(outstanding, Decimal(publication["reservationUsd"]))
        else:
            self.assertEqual(publication["status"], "passed-settled")
            self.assertGreaterEqual(Decimal(publication["providerCostUsd"]), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
