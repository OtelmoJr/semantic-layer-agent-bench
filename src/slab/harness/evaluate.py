"""Score one attempt: execute the submitted query with the harness's own connection and
compare it to the reference result."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from slab import config
from slab.agent.loop import Attempt
from slab.comparator import compare
from slab.db import QueryResult, connect_readonly, run_query
from slab.gold import Question
from slab.semantic.engine import SEMANTIC_POLICY, MetricQuery, SemanticEngine
from slab.sqlguard import raw_policy, validate


@dataclass(frozen=True)
class Score:
    correct: bool
    reason: str


class Evaluator:
    def __init__(self) -> None:
        self.con = connect_readonly()
        self._engine: SemanticEngine | None = None
        self._raw_policy = raw_policy(config.RAW_TABLES)

    @property
    def engine(self) -> SemanticEngine:
        if self._engine is None:
            self._engine = SemanticEngine()
        return self._engine

    @lru_cache(maxsize=512)
    def reference(self, question: Question) -> QueryResult:
        assert question.reference_sql
        return run_query(self.con, question.reference_sql, timeout_s=120)

    def score(self, question: Question, arm: str, att: Attempt) -> Score:
        expected = question.expected_outcome(arm)
        if att.status == "refused":
            return Score(expected == "refuse", "correct refusal" if expected == "refuse" else "refused an answerable question")
        if att.status != "submitted" or att.submission is None:
            return Score(False, f"no submission ({att.status})")
        if expected == "refuse":
            return Score(False, "answered a question that should be refused")
        payload = att.submission.get("payload") or {}
        try:
            if att.submission["kind"] == "sql":
                sql = validate(str(payload.get("sql", "")), self._raw_policy)
            else:
                sql = self.engine.compile(MetricQuery.from_dict(payload))
                validate(sql, SEMANTIC_POLICY)
            got = run_query(self.con, sql, timeout_s=config.SQL_TIMEOUT_S, max_rows=5000)
        except Exception as e:  # noqa: BLE001 - an invalid submission is simply wrong
            return Score(False, f"submission failed: {str(e).splitlines()[0][:200]}")
        ref = self.reference(question)
        v = compare(ref.columns, ref.rows, got.columns, got.rows, ordered=question.order_matters)
        return Score(v.correct, v.reason)
