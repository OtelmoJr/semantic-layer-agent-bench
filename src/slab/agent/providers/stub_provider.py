"""Deterministic scripted provider for CI and smoke tests.

It exercises the full pipeline (loop -> MCP -> DuckDB/MetricFlow -> store -> comparator ->
report) with no model and no network. On SMOKE_IDS it answers 7 of 10 correctly in every
arm, so the expected execution accuracy of a smoke run is exactly 70%.
"""

from __future__ import annotations

from typing import Any

from slab.agent.providers.base import Message, ToolCall, ToolSpec, Turn
from slab.gold import load_questions

SMOKE_IDS = (
    "sim001", "sim007", "mj001", "mj004", "tim001",
    "tim018", "bd001", "bd003", "ooc001", "ooc013",
)
WRONG_IDS = frozenset({"mj001", "tim001", "bd003"})
EXPECTED_SMOKE_EX = 0.7


class StubProvider:
    name = "stub"
    model = "stub-scripted-v1"

    def __init__(self) -> None:
        from slab.parity import load_specs

        self._questions = {q.id: q for q in load_questions()}
        self._specs = load_specs()

    def model_digest(self) -> str:
        return "stub"

    def _plan(self, qid: str, arm: str) -> list[tuple[str, dict[str, Any]]]:
        q = self._questions[qid]
        expected = q.expected_outcome(arm)
        if qid in WRONG_IDS:
            if arm == "C":
                return [("refuse", {"reason": "scripted wrong answer"})]
            return [("run_sql", {"sql": "SELECT 1 AS wrong_answer"}),
                    ("submit_sql", {"sql": "SELECT 1 AS wrong_answer"})]
        if expected == "refuse":
            return [("refuse", {"reason": "not answerable with the available tools"})]
        if arm == "C":
            spec = self._specs[qid].to_dict()
            return [("query_metrics", spec), ("submit_metric_query", spec)]
        return [("run_sql", {"sql": q.reference_sql}), ("submit_sql", {"sql": q.reference_sql})]

    def complete(self, system: str, messages: list[Message], tools: list[ToolSpec],
                 context: dict[str, Any]) -> Turn:
        plan = self._plan(context["question_id"], context["arm"])
        step = sum(1 for m in messages if m.role == "assistant")
        name, args = plan[min(step, len(plan) - 1)]
        return Turn("", [ToolCall(f"stub-{step}", name, args)], input_tokens=100, output_tokens=20,
                    stop_reason="tool_use")
