from __future__ import annotations

import os
import time
from typing import Any

from slab.agent.providers.base import Message, ProviderError, ToolCall, ToolSpec, Turn

DEFAULT_MODEL = "claude-sonnet-5-5"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None, max_tokens: int = 2048, retries: int = 4) -> None:
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        self.model = model or os.environ.get("SLAB_ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.max_tokens = max_tokens
        self.retries = retries
        self._client = anthropic.Anthropic()
        self._anthropic = anthropic

    def model_digest(self) -> str:
        return self.model  # API model ids are immutable snapshots

    @staticmethod
    def _to_api(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                blocks: list[dict[str, Any]] = []
                if m.text:
                    blocks.append({"type": "text", "text": m.text})
                for c in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
                out.append({"role": "assistant", "content": blocks})
            elif m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.text,
                         "is_error": m.is_error}
                # consecutive tool results belong in one user message
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec],
                 context: dict[str, Any]) -> Turn:
        api_tools = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=0,
                    system=system,
                    messages=self._to_api(messages),
                    tools=api_tools,
                )
                break
            except (self._anthropic.RateLimitError, self._anthropic.APIConnectionError,
                    self._anthropic.InternalServerError) as e:
                if attempt == self.retries:
                    raise ProviderError(str(e)) from e
                time.sleep(delay)
                delay *= 2
            except self._anthropic.APIError as e:
                raise ProviderError(str(e)) from e
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return Turn(text, calls, resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason)
