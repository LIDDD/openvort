"""LLM provider conversion tests."""

from openvort.core.engine.llm import OpenAICompatibleProvider


def _make_provider() -> OpenAICompatibleProvider:
    provider = object.__new__(OpenAICompatibleProvider)
    provider._convert_user_content_for_model = lambda content, model: content
    return provider


def test_openai_compatible_tool_call_message_uses_empty_string_content():
    provider = _make_provider()

    messages = [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "call_123",
                    "name": "node_shell",
                    "input": {"command": "pytest tests/"},
                }
            ],
        }
    ]

    converted = provider._convert_messages("system prompt", messages, "gpt-4o")

    assert converted[1]["role"] == "assistant"
    assert converted[1]["content"] == ""
    assert converted[1]["tool_calls"][0]["id"] == "call_123"


def test_openai_compatible_tool_call_message_keeps_text_content():
    provider = _make_provider()

    messages = [
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "我来处理。"},
                {
                    "type": "tool_use",
                    "id": "call_456",
                    "name": "node_shell",
                    "input": {"command": "tail -100 /var/log/app.log"},
                },
            ],
        }
    ]

    converted = provider._convert_messages("system prompt", messages, "gpt-4o")

    assert converted[1]["content"] == "我来处理。"
    assert converted[1]["tool_calls"][0]["function"]["name"] == "node_shell"


def test_openai_compatible_length_finish_reason_maps_to_max_tokens():
    data = {
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "node_file_write", "arguments": '{"path": "/a.java", "content": "cla'},
                }],
            },
            "finish_reason": "length",
        }],
        "usage": {},
    }

    resp = OpenAICompatibleProvider._parse_response(data)

    assert resp.stop_reason == "max_tokens"


def test_truncated_tool_results_skip_incomplete_tool_calls():
    from openvort.core.engine.agent import AgentRuntime
    from openvort.core.engine.llm import LLMResponse, ToolUseBlock

    resp = LLMResponse(
        content=[ToolUseBlock(id="call_1", name="node_file_write", input={})],
        stop_reason="max_tokens",
    )
    results = AgentRuntime._truncated_tool_results(resp)

    assert len(results) == 1
    assert results[0]["tool_use_id"] == "call_1"
    assert results[0]["is_error"] is True

    resp.stop_reason = "tool_use"
    assert AgentRuntime._truncated_tool_results(resp) == []
