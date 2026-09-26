from __future__ import annotations

import json
from typing import Any


def to_huggingface_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["Name"],
                "description": tool["Description"],
                "parameters": tool["Parameters"],
            },
        }
        for tool in tools
    ]


def to_qwen_conversation(trace: dict[str, Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in trace["messages"]:
        role = message["role"]
        if role in {"system", "user"}:
            converted.append({"role": role, "content": message["content"]})
        elif role == "assistant" and "toolCalls" in message:
            converted.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"],
                            },
                        }
                        for call in message["toolCalls"]
                    ],
                }
            )
        elif role == "tool":
            content = message["content"]
            if not isinstance(content, str):
                content = json.dumps(content, sort_keys=True, separators=(",", ":"))
            tool_message = {
                "role": "tool",
                "tool_call_id": message["toolCallId"],
                "content": content,
            }
            if "name" in message:
                tool_message["name"] = message["name"]
            converted.append(tool_message)
        elif role == "assistant":
            converted.append({"role": "assistant", "content": message["content"]})
        else:
            raise ValueError(f"unsupported trace message role: {role!r}")
    return converted


def to_training_rows(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "trace_id": trace["traceId"],
            "conversations": to_qwen_conversation(trace),
            "tools": to_huggingface_tools(trace["tools"]),
        }
        for trace in traces
    ]
