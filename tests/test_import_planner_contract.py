from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import import_planner_contract as importer


class ImportPlannerContractTests(unittest.TestCase):
    def test_v4_tool_schema_is_bound_to_the_production_digest(self):
        tool = importer.catalog_tool()
        self.assertEqual(importer.PROMPT_VERSION, "suggester-prompt-v4")
        self.assertEqual(importer.TOOL_SCHEMA_VERSION, "catalog-search-v4")
        self.assertEqual(
            hashlib.sha256(importer.go_tool_schema_bytes([tool])).hexdigest(),
            importer.TOOL_SCHEMA_SHA256,
        )
        properties = tool["Parameters"]["properties"]
        self.assertEqual(properties["network"]["description"], "exact TV network name; requires media_type=series")
        self.assertEqual(properties["cast"]["maxItems"], 4)
        self.assertEqual(properties["creators"]["maxItems"], 4)


if __name__ == "__main__":
    unittest.main()
