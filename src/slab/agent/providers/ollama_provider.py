from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import httpx

from slab.agent.providers.base import Message, ProviderError, ToolCall, ToolSpec, Turn


class OllamaProvider:
    """Local models through Ollama's /api/chat with native tool calling."""

    name = "ollama"

    def __init__(self, model: str, host: str | None = None, timeout_s: float = 300, retries: int = 2) -> None:
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.retries = retries
        self._http = httpx.Client(timeout=timeout_s)

    def model_digest(self) -> str:
        try:
            tags = self._http.get(f"{self.host}/api/tags").json().get("models", [])
        except httpx.HTTPError as e:
            raise ProviderError(f"ollama not reachable at {self.host}: {e}") from e
        for m in tags:
            if m.get("name") == self.model or m.get("model") == self.model:
                return m.get("digest", "unknown")
        raise ProviderError(f"model {self.model!r} not pulled in ollama (ollama pull {self.model})")

    @staticmethod
    def _to_api(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "user":
                out.append({"role": "user", "content": m.text})
            elif m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.text}
                if m.tool_calls:
                    msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                         for c in m.tool_calls]
                out.append(msg)
            elif m.role == "tool":
                out.append({"role": "tool", "content": m.text, "tool_name": m.tool_name})
        return out

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec],
                 context: dict[str, Any]) -> Turn:
        body = {
            "model": self.model,
            "messages": self._to_api(system, messages),
            "tools": [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                         "parameters": t.parameters}} for t in tools],
            "stream": False,
            "options": {"temperature": 0, "seed": int(context.get("seed", 0))},
        }
        delay = 2.0
        for attempt in range(self.retries + 1):
            try:
                r = self._http.post(f"{self.host}/api/chat", json=body)
                r.raise_for_status()
                data = r.json()
                break
            except httpx.HTTPError as e:
                if attempt == self.retries:
                    raise ProviderError(f"ollama: {e}") from e
                time.sleep(delay)
                delay *= 2
        msg = data.get("message", {})
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"__unparseable__": args}
            calls.append(ToolCall(c.get("id") or uuid.uuid4().hex[:12], fn.get("name", ""), args))
        return Turn(msg.get("content", ""), calls, int(data.get("prompt_eval_count", 0)),
                    int(data.get("eval_count", 0)), data.get("done_reason"))
