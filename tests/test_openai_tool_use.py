from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm.openai_client import OpenAIClient
from app.llm.tool_use import tool_definitions_for_openai
from app.tools.registry import create_default_tool_registry


def test_tool_definitions_for_openai_use_function_tools() -> None:
    registry = create_default_tool_registry()

    tools = tool_definitions_for_openai(registry)
    finish_task = next(tool for tool in tools if tool["name"] == "finish_task")

    assert finish_task["type"] == "function"
    assert finish_task["parameters"]["type"] == "object"
    assert "status" in finish_task["parameters"]["properties"]


def test_openai_client_normalizes_function_call_response() -> None:
    client = OpenAIClient.__new__(OpenAIClient)
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(type="output_text", text="I will inspect the page.")
                ],
            ),
            SimpleNamespace(
                type="function_call",
                call_id="call_123",
                name="get_current_page_info",
                arguments="{}",
            ),
        ]
    )

    blocks = client._content_blocks_from_response(response)

    assert blocks == [
        {"type": "text", "text": "I will inspect the page."},
        {
            "type": "tool_use",
            "id": "call_123",
            "name": "get_current_page_info",
            "input": {},
        },
    ]


def test_openai_client_builds_function_call_outputs_after_first_response() -> None:
    client = OpenAIClient.__new__(OpenAIClient)
    client._previous_response_id = "resp_123"
    messages = [
        {"role": "user", "content": "Task"},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_123",
                    "content": '{"ok": true}',
                }
            ],
        },
    ]

    input_items = client._build_input_items(messages)

    assert input_items == [
        {
            "type": "function_call_output",
            "call_id": "call_123",
            "output": '{"ok": true}',
        }
    ]


def test_openai_client_keeps_compact_state_text_with_tool_outputs() -> None:
    client = OpenAIClient.__new__(OpenAIClient)
    client._previous_response_id = "resp_123"
    messages = [
        {"role": "user", "content": "Task"},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_123",
                    "content": '{"ok": true}',
                },
                {
                    "type": "text",
                    "text": "Compact execution summary",
                },
            ],
        },
    ]

    input_items = client._build_input_items(messages)

    assert input_items[-1] == {
        "role": "user",
        "content": "Compact execution summary",
    }


def test_openai_client_stateless_mode_keeps_compact_state_without_previous_chain() -> None:
    client = OpenAIClient.__new__(OpenAIClient)
    client._use_previous_response_id = False
    client._previous_response_id = "resp_123"
    messages = [
        {"role": "user", "content": "Compact execution summary: before tool"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_123",
                    "name": "get_current_page_info",
                    "input": {},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_123",
                    "content": '{"ok": true}',
                },
                {
                    "type": "text",
                    "text": "Compact execution summary: after tool",
                },
            ],
        },
    ]

    input_items = client._build_input_items(messages)

    assert {"role": "user", "content": "Compact execution summary: before tool"} in input_items
    assert {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": '{"ok": true}',
    } in input_items
    assert input_items[-1] == {
        "role": "user",
        "content": "Compact execution summary: after tool",
    }


def test_openai_client_converts_image_blocks_to_multimodal_input() -> None:
    client = OpenAIClient.__new__(OpenAIClient)
    client._use_previous_response_id = False
    client._previous_response_id = None
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is visible?"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "abc123",
                    },
                },
            ],
        }
    ]

    input_items = client._build_input_items(messages)

    assert input_items == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is visible?"},
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64,abc123",
                },
            ],
        }
    ]


class FakeResponses:
    def __init__(self) -> None:
        self.request: dict[str, object] | None = None

    async def create(self, **request: object) -> object:
        self.request = request
        return SimpleNamespace(id="resp_next", output=[])


@pytest.mark.asyncio
async def test_openai_client_does_not_send_previous_response_id_by_default() -> None:
    responses = FakeResponses()
    client = OpenAIClient.__new__(OpenAIClient)
    client.model = "gpt-test"
    client.max_output_tokens = 1000
    client._client = SimpleNamespace(responses=responses)
    client._use_previous_response_id = False
    client._previous_response_id = "resp_123"

    await client.create_message(
        system="system",
        messages=[{"role": "user", "content": "Compact execution summary"}],
        tools=[],
    )

    assert responses.request is not None
    assert "previous_response_id" not in responses.request
    assert responses.request["input"] == [
        {"role": "user", "content": "Compact execution summary"}
    ]


def test_openai_key_controls_active_llm_key_detection() -> None:
    assert Settings(openai_api_key="sk-test").has_active_llm_api_key() is True
    assert Settings(llm_provider="anthropic", anthropic_api_key="sk-ant").has_active_llm_api_key() is True
