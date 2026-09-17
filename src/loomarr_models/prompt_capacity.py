from __future__ import annotations

import hashlib
import json
from typing import Any

from .current_baseline import finalization_prompt, render_user_prompt
from .eval_runtime import _to_huggingface_messages
from .experiment import PreflightError
from .training_data import to_huggingface_tools


def measure_prompt_capacity(
    tokenizer: Any,
    contract: dict[str, Any],
    cases: list[dict[str, Any]],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    max_sequence = comparison["maxSeqLength"]
    generation = comparison["maxNewTokens"]
    measurements: list[dict[str, Any]] = []
    tools = contract["tools"]
    huggingface_tools = to_huggingface_tools(tools)

    for case in cases:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": contract["systemPrompt"]},
            {"role": "user", "content": render_user_prompt(case)},
        ]
        for index, scripted in enumerate(case["script"], start=1):
            measurements.append(
                _measurement(
                    tokenizer,
                    messages,
                    huggingface_tools,
                    case["caseId"],
                    f"tool-call-{index}",
                    max_sequence,
                    generation,
                    comparison["reasoningEffort"],
                )
            )
            messages.append(
                {
                    "role": "assistant",
                    "toolCalls": [
                        {
                            "id": f"capacity-call-{index}",
                            "name": "catalog_search",
                            "arguments": scripted["arguments"],
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "toolCallId": f"capacity-call-{index}",
                    "name": "catalog_search",
                    "content": scripted["result"],
                }
            )
        accepted = case["script"][0]["arguments"]["dateMeaning"]
        messages.append({"role": "user", "content": finalization_prompt(accepted)})
        measurements.append(
            _measurement(
                tokenizer,
                messages,
                huggingface_tools,
                case["caseId"],
                "finalization",
                max_sequence,
                generation,
                comparison["reasoningEffort"],
            )
        )

    failing = [item for item in measurements if item["availableGenerationTokens"] < generation]
    report = {
        "schemaVersion": 1,
        "caseCount": len(cases),
        "stageCount": len(measurements),
        "maxSeqLength": max_sequence,
        "requiredGenerationTokens": generation,
        "maxInputTokens": max(item["inputTokens"] for item in measurements),
        "minAvailableGenerationTokens": min(
            item["availableGenerationTokens"] for item in measurements
        ),
        "measurements": measurements,
    }
    report["measurementsSha256"] = hashlib.sha256(
        json.dumps(measurements, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if failing:
        first = failing[0]
        raise PreflightError(
            "prompt capacity is insufficient at "
            f"{first['caseId']}:{first['stage']}: "
            f"{first['availableGenerationTokens']} available, {generation} required"
        )
    return report


def _measurement(
    tokenizer: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    case_id: str,
    stage: str,
    max_sequence: int,
    generation: int,
    reasoning_effort: str,
) -> dict[str, Any]:
    rendered = tokenizer.apply_chat_template(
        _to_huggingface_messages(messages),
        tools=tools,
        tokenize=False,
        add_generation_prompt=True,
        reasoning_effort=reasoning_effort,
    )
    encoded = tokenizer(text=rendered)
    input_ids = encoded["input_ids"]
    input_tokens = len(input_ids[0]) if input_ids and isinstance(input_ids[0], list) else len(input_ids)
    return {
        "caseId": case_id,
        "stage": stage,
        "inputTokens": input_tokens,
        "availableGenerationTokens": max_sequence - input_tokens,
        "requiredGenerationTokens": generation,
    }
