"""MCP tool backend: the agent only reaches data through an MCP client session.

`stdio` (default for real runs) spawns the server as a subprocess, which is the real
deployment shape. `inproc` connects to the same server object in-process (tests, CI).
"""

from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from slab.agent.providers.base import ToolSpec

SERVER_MODULE = {"A": "slab.servers.raw_sql", "B": "slab.servers.raw_sql", "C": "slab.servers.semantic"}


def _content_text(result: Any) -> str:
    parts = []
    for c in result.content or []:
        text = getattr(c, "text", None)
        parts.append(text if text is not None else json.dumps(c.model_dump(), default=str))
    return "\n".join(parts)


class MCPBackend:
    def __init__(self, arm: str, transport: str = "stdio") -> None:
        self.arm = arm
        self.transport = transport
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._tools: list[ToolSpec] | None = None

    async def __aenter__(self) -> "MCPBackend":
        self._stack = AsyncExitStack()
        if self.transport == "inproc":
            if SERVER_MODULE[self.arm] == "slab.servers.semantic":
                from slab.servers.semantic import build_server
            else:
                from slab.servers.raw_sql import build_server
            target: Any = build_server()
        else:
            target = StdioServerParameters(command=sys.executable, args=["-m", SERVER_MODULE[self.arm]])
        self._client = await self._stack.enter_async_context(Client(target, read_timeout_seconds=120))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def list_tools(self) -> list[ToolSpec]:
        if self._tools is None:
            assert self._client is not None
            res = await self._client.list_tools()
            self._tools = [ToolSpec(t.name, t.description or "", t.input_schema) for t in res.tools]
        return self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        assert self._client is not None
        try:
            res = await self._client.call_tool(name, arguments)
        except Exception as e:  # noqa: BLE001 - protocol-level failure reported to the model
            return f"tool call failed: {str(e)[:500]}", True
        return _content_text(res), bool(res.is_error)
