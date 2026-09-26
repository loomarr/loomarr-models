from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_planner_contract as importer


class ImportPlannerContractTests(unittest.TestCase):
    def test_current_tool_schema_is_bound_to_the_production_digest(self):
        tool = importer.catalog_tool()
        self.assertEqual(importer.PROMPT_VERSION, "suggester-prompt-v15")
        self.assertEqual(importer.TOOL_SCHEMA_VERSION, "catalog-search-v9")
        self.assertEqual(importer.MESSAGE_TEMPLATE_VERSION, "planner-tool-result-finalization-v3")
        self.assertEqual(importer.SOURCE_VERSION, "reference-source-v6")
        self.assertIn("internal/suggest/intent_coordinates.go", importer.SOURCE_PATHS)
        self.assertIn("internal/suggest/parse.go", importer.SOURCE_PATHS)
        self.assertEqual(
            hashlib.sha256(importer.go_tool_schema_bytes([tool])).hexdigest(),
            importer.TOOL_SCHEMA_SHA256,
        )
        properties = tool["Parameters"]["properties"]
        self.assertEqual(tool["Parameters"]["required"], ["dateMeaning"])
        self.assertNotIn("era", properties)
        self.assertEqual(properties["mode"]["enum"], ["collection"])
        self.assertEqual(properties["dateMeaning"]["required"], ["kind", "anchors", "axes"])
        self.assertEqual(properties["network"]["description"], "exact TV network name; requires media_type=series")
        self.assertEqual(properties["cast"]["maxItems"], 4)
        self.assertEqual(properties["creators"]["maxItems"], 4)

        contract = json.loads((ROOT / "contracts/planner-contract-v5.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["tools"], [tool])
        self.assertEqual(contract["systemPromptSha256"], hashlib.sha256(contract["systemPrompt"].encode()).hexdigest())
        self.assertEqual([item["path"] for item in contract["sourceBindings"]], list(importer.SOURCE_PATHS))
        self.assertTrue(all(len(item["sha256"]) == 64 for item in contract["sourceBindings"]))


if __name__ == "__main__":
    unittest.main()
