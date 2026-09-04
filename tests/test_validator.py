from __future__ import annotations

import copy
import json
import hashlib
import unittest

from loomarr_models.validator import (
    ValidationError,
    validate_corpus,
    validate_tool_call_compatibility,
)


DENYLIST_IDENTITIES = {"planner-certification-v5", "planner-catalog-v1"}
DENYLIST_DIGESTS = {"36a393258d1b89a43de8e12c16eb90aa6c5f67096eaa8d34dd46ad2676426f1a"}
TEST_SYSTEM_PROMPT = "Use only catalog_search results; return proposal JSON."
TEST_PROPERTIES = {
    "query": {"type": "string"},
    "genres": {"type": "array", "items": {"type": "string"}},
    "keywords": {"type": "array", "items": {"type": "string"}},
    "era": {"type": "string"},
    "media_type": {"type": "string", "enum": ["movie", "series"]},
    "original_language": {"type": "string"},
    "origin_country": {"type": "string"},
    "runtime_min": {"type": "integer", "minimum": 1, "maximum": 1440},
    "runtime_max": {"type": "integer", "minimum": 1, "maximum": 1440},
    "vote_average_min": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
    "vote_count_min": {"type": "integer", "minimum": 1, "maximum": 100000000},
    "network": {"type": "string", "maxLength": 100},
    "cast": {
        "type": "array",
        "minItems": 1,
        "maxItems": 4,
        "items": {"type": "string", "maxLength": 100},
    },
    "creators": {
        "type": "array",
        "minItems": 1,
        "maxItems": 4,
        "items": {"type": "string", "maxLength": 100},
    },
}
TEST_TOOLS = [
    {
        "Name": "catalog_search",
        "Description": "Search the synthetic catalog fixture.",
        "Parameters": {"type": "object", "properties": TEST_PROPERTIES},
    }
]
TEST_CONTRACT = {
    "contractId": "loomarr-planner-contract-test-v4",
    "promptVersion": "test-prompt-v1",
    "systemPromptSha256": hashlib.sha256(TEST_SYSTEM_PROMPT.encode()).hexdigest(),
    "toolSchemaVersion": "test-tools-v1",
    "toolSchemaSha256": hashlib.sha256(
        json.dumps(TEST_TOOLS, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest(),
    "messageTemplateVersion": "test-messages-v1",
    "systemPrompt": TEST_SYSTEM_PROMPT,
    "tools": TEST_TOOLS,
}


def valid_trace() -> dict:
    final = {
        "channelName": "Neon Voyages",
        "rationale": "Synthetic space adventures with an optimistic tone.",
        "picks": [
            {
                "mediaType": "movie",
                "tmdbId": 900001,
                "name": "Voyage Beyond Neon",
                "rationale": "The synthetic overview matches the requested tone.",
                "confidence": 0.92,
            }
        ],
        "policy": {"genres": {"include": ["Science Fiction"]}},
    }
    return {
        "schemaVersion": 1,
        "traceId": "planner-smoke-title-001",
        "split": "train",
        "axes": ["title-search"],
        "contract": {
            "promptVersion": TEST_CONTRACT["promptVersion"],
            "systemPromptSha256": TEST_CONTRACT["systemPromptSha256"],
            "toolSchemaVersion": TEST_CONTRACT["toolSchemaVersion"],
            "toolSchemaSha256": TEST_CONTRACT["toolSchemaSha256"],
            "messageTemplateVersion": TEST_CONTRACT["messageTemplateVersion"],
            "fixtureId": "planner-synthetic-catalog-v1",
        },
        "tools": copy.deepcopy(TEST_TOOLS),
        "messages": [
            {"role": "system", "content": TEST_SYSTEM_PROMPT},
            {"role": "user", "content": "Build a channel: Voyage Beyond Neon."},
            {
                "role": "assistant",
                "toolCalls": [
                    {
                        "id": "call-1",
                        "name": "catalog_search",
                        "arguments": {"query": "Voyage Beyond Neon"},
                    }
                ],
            },
            {
                "role": "tool",
                "toolCallId": "call-1",
                "name": "catalog_search",
                "content": {
                    "candidates": [
                        {
                            "mediaType": "movie",
                            "tmdbId": 900001,
                            "name": "Voyage Beyond Neon",
                            "genres": ["Science Fiction"],
                            "overview": "Synthetic explorers cross a luminous frontier.",
                        }
                    ]
                },
            },
            {"role": "assistant", "content": json.dumps(final)},
        ],
        "review": {
            "status": "approved",
            "reviewer": "reviewer:test",
            "reviewedAt": "2026-09-03T00:00:00Z",
            "notes": "Fixture only.",
        },
        "provenance": {
            "source": "synthetic",
            "generator": "test-fixture-v1",
            "author": "author:test",
        },
    }


class ValidatorTests(unittest.TestCase):
    def validate(self, *traces: dict, allow_pending: bool = False):
        return validate_corpus(
            traces,
            denylisted_identities=DENYLIST_IDENTITIES,
            denylisted_sha256=DENYLIST_DIGESTS,
            contract_bundle=TEST_CONTRACT,
            allow_pending=allow_pending,
        )

    def test_accepts_reviewed_grounded_trace(self):
        report = self.validate(valid_trace())
        self.assertEqual((report.traces, report.approved, report.pending), (1, 1, 0))
        self.assertRegex(report.sha256, r"^[0-9a-f]{64}$")

    def test_rejects_unsupported_selected_id(self):
        trace = valid_trace()
        final = json.loads(trace["messages"][-1]["content"])
        final["picks"][0]["tmdbId"] = 999999
        trace["messages"][-1]["content"] = json.dumps(final)
        with self.assertRaisesRegex(ValidationError, "unsupported selected id"):
            self.validate(trace)

    def test_rejects_malformed_tool_arguments(self):
        trace = valid_trace()
        trace["messages"][2]["toolCalls"][0]["arguments"] = {
            "query": "Voyage Beyond Neon",
            "genres": ["Science Fiction"],
        }
        with self.assertRaisesRegex(ValidationError, "title query mixed"):
            self.validate(trace)

    def test_accepts_production_v4_search_modes(self):
        valid_arguments = (
            {"query": "Voyage Beyond Neon", "media_type": "movie"},
            {"era": "1990s", "origin_country": "US"},
            {"media_type": "series", "network": "ABC"},
            {"media_type": "movie", "cast": ["Jamie Lee Curtis"]},
            {
                "media_type": "movie",
                "cast": ["Tom Hanks", "Meg Ryan"],
                "creators": ["Nora Ephron"],
            },
        )
        for arguments in valid_arguments:
            with self.subTest(arguments=arguments):
                trace = valid_trace()
                trace["messages"][2]["toolCalls"][0]["arguments"] = arguments
                self.validate(trace)

    def test_rejects_invalid_v4_entity_routes_and_values(self):
        invalid_arguments = (
            ({"network": "ABC"}, "network requires media_type series"),
            ({"media_type": "movie", "network": "ABC"}, "network requires media_type series"),
            ({"cast": ["Tom Hanks"]}, "cast and creators require media_type movie"),
            (
                {"media_type": "series", "creators": ["David Simon"]},
                "cast and creators require media_type movie",
            ),
            (
                {"media_type": "series", "network": "HBO", "cast": ["Idris Elba"]},
                "network and person constraints cannot be combined",
            ),
            ({"media_type": "series", "network": "  "}, "invalid network"),
            ({"media_type": "movie", "cast": []}, "invalid cast"),
            ({"media_type": "movie", "cast": ["Tom Hanks", 31]}, "invalid cast"),
            (
                {"media_type": "movie", "creators": ["Nora Ephron", " nora ephron "]},
                "duplicate creators",
            ),
            ({"media_type": "series"}, "no search selector"),
        )
        for arguments, message in invalid_arguments:
            with self.subTest(arguments=arguments):
                trace = valid_trace()
                trace["messages"][2]["toolCalls"][0]["arguments"] = arguments
                with self.assertRaisesRegex(ValidationError, message):
                    self.validate(trace)

    def test_rejects_invalid_v4_scalar_qualifiers(self):
        invalid_arguments = (
            ({"era": "whenever"}, "invalid era"),
            ({"genres": ["Drama"], "original_language": "english"}, "invalid original_language"),
            ({"genres": ["Drama"], "origin_country": 44}, "invalid origin_country"),
            ({"genres": ["Drama"], "runtime_min": 20.5}, "invalid runtime_min"),
            (
                {"genres": ["Drama"], "runtime_min": 90, "runtime_max": 20},
                "runtime_min exceeds runtime_max",
            ),
            ({"genres": ["Drama"], "vote_average_min": 0}, "invalid vote_average_min"),
            ({"genres": ["Drama"], "vote_count_min": True}, "invalid vote_count_min"),
        )
        for arguments, message in invalid_arguments:
            with self.subTest(arguments=arguments):
                trace = valid_trace()
                trace["messages"][2]["toolCalls"][0]["arguments"] = arguments
                with self.assertRaisesRegex(ValidationError, message):
                    self.validate(trace)

    def test_target_contract_controls_compatible_argument_names(self):
        trace = valid_trace()
        trace["messages"][2]["toolCalls"][0]["arguments"] = {
            "media_type": "series",
            "network": "ABC",
        }
        report = validate_tool_call_compatibility([trace], target_contract_bundle=TEST_CONTRACT)
        self.assertEqual(
            (report.traces, report.tool_calls, report.target_contract_id),
            (1, 1, TEST_CONTRACT["contractId"]),
        )

        legacy_contract = copy.deepcopy(TEST_CONTRACT)
        del legacy_contract["tools"][0]["Parameters"]["properties"]["network"]
        with self.assertRaisesRegex(ValidationError, "not declared by target contract"):
            validate_tool_call_compatibility([trace], target_contract_bundle=legacy_contract)

    def test_rejects_holdout_identity_or_digest(self):
        for leaked in (next(iter(DENYLIST_IDENTITIES)), next(iter(DENYLIST_DIGESTS))):
            with self.subTest(leaked=leaked):
                trace = valid_trace()
                trace["review"]["notes"] = leaked
                with self.assertRaisesRegex(ValidationError, "holdout"):
                    self.validate(trace)

    def test_rejects_secret_or_household_path(self):
        for leaked in ("sk_exampleSecretToken123", "/Users/alice/private/library.db"):
            with self.subTest(leaked=leaked):
                trace = valid_trace()
                trace["messages"][1]["content"] += " " + leaked
                with self.assertRaisesRegex(ValidationError, "secret or household path"):
                    self.validate(trace)

    def test_rejects_duplicate_content_across_splits(self):
        first = valid_trace()
        second = copy.deepcopy(first)
        second["traceId"] = "planner-smoke-title-002"
        second["split"] = "development"
        with self.assertRaisesRegex(ValidationError, "duplicate content"):
            self.validate(first, second)

    def test_rejects_schema_invalid_final(self):
        trace = valid_trace()
        trace["messages"][-1]["content"] = json.dumps({"rationale": "No picks field."})
        with self.assertRaisesRegex(ValidationError, "lacks picks"):
            self.validate(trace)

    def test_rejects_prompt_or_tool_contract_drift(self):
        prompt_drift = valid_trace()
        prompt_drift["messages"][0]["content"] += " changed"
        with self.assertRaisesRegex(ValidationError, "frozen system prompt"):
            self.validate(prompt_drift)

        tool_drift = valid_trace()
        tool_drift["tools"][0]["Description"] += " changed"
        with self.assertRaisesRegex(ValidationError, "frozen bundle"):
            self.validate(tool_drift)

        identity_drift = valid_trace()
        identity_drift["contract"]["promptVersion"] = "untracked-prompt"
        with self.assertRaisesRegex(ValidationError, "contract promptVersion"):
            self.validate(identity_drift)

    def test_pending_trace_requires_explicit_draft_mode(self):
        trace = valid_trace()
        trace["split"] = "smoke"
        trace["review"] = {"status": "pending", "reviewer": "", "reviewedAt": None, "notes": ""}
        with self.assertRaisesRegex(ValidationError, "not approved"):
            self.validate(trace)
        report = self.validate(trace, allow_pending=True)
        self.assertEqual((report.approved, report.pending), (0, 1))

    def test_rejected_trace_never_enters_draft_or_artifact(self):
        trace = valid_trace()
        trace["review"] = {
            "status": "rejected",
            "reviewer": "reviewer:test",
            "reviewedAt": "2026-09-03T00:00:00Z",
            "notes": "Target violates the intent.",
        }
        with self.assertRaisesRegex(ValidationError, "not approved"):
            self.validate(trace, allow_pending=True)


if __name__ == "__main__":
    unittest.main()
