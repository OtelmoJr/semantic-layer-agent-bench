"""Provider-neutral chat types. Each provider translates them to its own API.

The loop is the same for every provider and every arm, so differences in accuracy cannot
come from the harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    """role: user | assistant | tool."""

    role: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    is_error: bool = False


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


class ProviderError(Exception):
    """Transport or API failure (not a model mistake)."""


class Provider(Protocol):
    name: str
    model: str

    def model_digest(self) -> str: ...

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        context: dict[str, Any],
    ) -> Turn: ...
