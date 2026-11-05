"""Providers are not called live in CI (no keys, no GPU). These tests pin the message
translation, which is where tool-calling integrations usually break."""
import json

import httpx

from slab.agent.providers.anthropic_provider import AnthropicProvider
from slab.agent.providers.base import Message, ToolCall, ToolSpec
from slab.agent.providers.ollama_provider import OllamaProvider

HISTORY = [
    Message("user", "q?"),
    Message("assistant", "thinking", [ToolCall("c1", "run_sql", {"sql": "select 1"}),
                                      ToolCall("c2", "list_tables", {})]),
    Message("tool", '{"rows": [[1]]}', tool_call_id="c1", tool_name="run_sql"),
    Message("tool", "err", tool_call_id="c2", tool_name="list_tables", is_error=True),
]


def test_anthropic_groups_parallel_tool_results_in_one_user_turn():
    api = AnthropicProvider._to_api(HISTORY)
    assert [m["role"] for m in api] == ["user", "assistant", "user"]
    assert [b["type"] for b in api[1]["content"]] == ["text", "tool_use", "tool_use"]
    results = api[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["c1", "c2"]
    assert results[1]["is_error"] is True


def test_ollama_roundtrip_with_mock_server():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "submit_sql", "arguments": {"sql": "select 2"}}},
                                       {"function": {"name": "run_sql", "arguments": "{not json"}}]},
            "prompt_eval_count": 123, "eval_count": 7, "done_reason": "stop"})

    p = OllamaProvider("some-model", host="http://ollama")
    p._http = httpx.Client(transport=httpx.MockTransport(handler))
    turn = p.complete("sys", HISTORY, [ToolSpec("run_sql", "d", {"type": "object"})], {"seed": 3})
    assert seen["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["messages"][3] == {"role": "tool", "content": '{"rows": [[1]]}', "tool_name": "run_sql"}
    assert seen["options"] == {"temperature": 0, "seed": 3}
    assert turn.tool_calls[0].name == "submit_sql" and turn.tool_calls[0].arguments == {"sql": "select 2"}
    assert "__unparseable__" in turn.tool_calls[1].arguments  # counted as protocol error by the loop
    assert (turn.input_tokens, turn.output_tokens) == (123, 7)
