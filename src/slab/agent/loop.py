"""The agent loop: identical for every arm and every provider.

The only things that vary by arm are (1) which MCP server's tools are exposed, (2) which
terminal tool submits the answer, and (3) whether the system prompt includes the glossary.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from slab import config
from slab.agent.prompts import SUBMIT_TOOL, system_prompt
from slab.agent.providers.base import Message, Provider, ProviderError, ToolSpec
from slab.tracing import tracer

MAX_TOOL_RESULT_CHARS = 12_000

TERMINAL_TOOLS: dict[str, ToolSpec] = {
    "submit_sql": ToolSpec(
        "submit_sql",
        "Submit your final answer as one SELECT query. Its result rows are your answer. Call once.",
        {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    ),
    "submit_metric_query": ToolSpec(
        "submit_metric_query",
        "Submit your final answer as a metric query (same arguments as query_metrics). "
        "Its result rows are your answer. Call once.",
        {
            "type": "object",
            "properties": {
                "metrics": {"type": "array", "items": {"type": "string"}},
                "group_by": {"type": "array", "items": {"type": "string"}},
                "where": {"type": "array", "items": {"type": "string"}},
                "order_by": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer"},
            },
            "required": ["metrics"],
        },
    ),
    "refuse": ToolSpec(
        "refuse",
        "Use when the question cannot be answered with the available data or tools.",
        {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    ),
}


class ToolBackend(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]: ...


@dataclass
class Attempt:
    status: str  # submitted | refused | no_answer | max_steps | timeout | provider_error | tool_protocol_error
    submission: dict[str, Any] | None = None
    tool_calls: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    protocol_errors: int = 0
    tool_errors: int = 0
    latency_ms: int = 0
    error: str | None = None
    transcript: list[dict[str, Any]] = field(default_factory=list)


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated]"


async def run_question(
    provider: Provider,
    backend: ToolBackend,
    arm: str,
    question_id: str,
    question: str,
    seed: int = 0,
    max_tool_calls: int = config.MAX_TOOL_CALLS,
    timeout_s: float = config.QUESTION_TIMEOUT_S,
) -> Attempt:
    try:
        return await asyncio.wait_for(
            _run(provider, backend, arm, question_id, question, seed, max_tool_calls), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        return Attempt(status="timeout", error=f"exceeded {timeout_s:.0f}s")


async def _run(provider: Provider, backend: ToolBackend, arm: str, question_id: str, question: str,
               seed: int, max_tool_calls: int) -> Attempt:
    t0 = time.monotonic()
    att = Attempt(status="no_answer")
    exploration = await backend.list_tools()
    submit = SUBMIT_TOOL[arm]
    tools = exploration + [TERMINAL_TOOLS[submit], TERMINAL_TOOLS["refuse"]]
    tool_names = {t.name for t in tools}
    system = system_prompt(arm)
    messages = [Message("user", question)]
    context = {"question_id": question_id, "arm": arm, "seed": seed}
    tr = tracer()

    def done() -> Attempt:
        att.latency_ms = int((time.monotonic() - t0) * 1000)
        att.transcript = [
            {"role": m.role, "text": m.text, "tool_calls": [c.__dict__ for c in m.tool_calls],
             "tool_name": m.tool_name, "is_error": m.is_error}
            for m in messages
        ]
        return att

    terminal_only = [TERMINAL_TOOLS[submit], TERMINAL_TOOLS["refuse"]]
    while True:
        # Once the exploration budget is spent, the model gets one last turn with only the
        # terminal tools, so it can still submit what it has.
        final_round = att.tool_calls >= max_tool_calls
        current_tools = terminal_only if final_round else tools
        with tr.start_as_current_span("gen_ai.chat") as span:
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", provider.name)
            span.set_attribute("gen_ai.request.model", provider.model)
            span.set_attribute("gen_ai.request.temperature", 0)
            try:
                turn = await asyncio.to_thread(provider.complete, system, messages, current_tools, context)
            except ProviderError as e:
                att.status, att.error = "provider_error", str(e)[:500]
                return done()
            span.set_attribute("gen_ai.usage.input_tokens", turn.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", turn.output_tokens)
            if turn.stop_reason:
                span.set_attribute("gen_ai.response.finish_reasons", [turn.stop_reason])
        att.llm_calls += 1
        att.input_tokens += turn.input_tokens
        att.output_tokens += turn.output_tokens
        messages.append(Message("assistant", turn.text, list(turn.tool_calls)))

        if not turn.tool_calls:
            att.status = "no_answer"
            return done()

        for call in turn.tool_calls:
            if call.name in (submit, "refuse"):
                if call.name == "refuse":
                    att.status = "refused"
                    att.submission = {"kind": "refuse", "reason": str(call.arguments.get("reason", ""))}
                else:
                    att.status = "submitted"
                    kind = "sql" if call.name == "submit_sql" else "metric_query"
                    att.submission = {"kind": kind, "payload": call.arguments}
                return done()

            if final_round:
                att.status = "max_steps"
                return done()
            att.tool_calls += 1
            if call.name not in tool_names or "__unparseable__" in call.arguments:
                att.protocol_errors += 1
                text, is_error = (f"unknown tool {call.name!r} or invalid arguments; available: "
                                  f"{sorted(tool_names)}"), True
            else:
                with tr.start_as_current_span("gen_ai.execute_tool") as span:
                    span.set_attribute("gen_ai.operation.name", "execute_tool")
                    span.set_attribute("gen_ai.tool.name", call.name)
                    text, is_error = await backend.call(call.name, call.arguments)
                    span.set_attribute("slab.tool.is_error", is_error)
                if is_error:
                    att.tool_errors += 1
            messages.append(Message("tool", _truncate(text), tool_call_id=call.id,
                                    tool_name=call.name, is_error=is_error))




def submission_json(att: Attempt) -> str:
    return json.dumps(att.submission, default=str) if att.submission else ""
