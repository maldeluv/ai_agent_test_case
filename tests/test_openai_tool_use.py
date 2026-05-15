from __future__ import annotations

from types import SimpleNamespace

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


def test_openai_key_controls_active_llm_key_detection() -> None:
    assert Settings(openai_api_key="sk-test").has_active_llm_api_key() is True
    assert Settings(llm_provider="anthropic", anthropic_api_key="sk-ant").has_active_llm_api_key() is True
