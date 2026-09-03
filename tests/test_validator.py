from __future__ import annotations

import copy
import json
import hashlib
import unittest

from loomarr_models.validator import ValidationError, validate_corpus


DENYLIST_IDENTITIES = {"planner-certification-v5", "planner-catalog-v1"}
DENYLIST_DIGESTS = {"36a393258d1b89a43de8e12c16eb90aa6c5f67096eaa8d34dd46ad2676426f1a"}
TEST_SYSTEM_PROMPT = "Use only catalog_search results; return proposal JSON."
TEST_TOOLS = [
    {
        "Name": "catalog_search",
        "Description": "Search the synthetic catalog fixture.",
        "Parameters": {"type": "object"},
    }
]
TEST_CONTRACT = {
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
