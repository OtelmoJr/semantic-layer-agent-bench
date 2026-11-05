from datetime import datetime, timezone

from slab.harness.store import ResultStore


def row(q, attempt=1, correct=True):
    return {"run_id": "r1", "arm": "A", "provider": "stub", "model_id": "m", "model_digest": "d",
            "question_id": q, "category": "simple", "coverage": "in", "split": "dev", "attempt": attempt,
            "expected_outcome": "answer", "status": "submitted", "submission": "{}", "correct": correct,
            "reason": "", "tool_calls": 1, "llm_calls": 2, "tool_errors": 0, "protocol_errors": 0,
            "input_tokens": 10, "output_tokens": 2, "latency_ms": 5, "trace_id": "t", "gold_hash": "h",
            "git_sha": "g", "started_at": datetime.now(timezone.utc), "error": None}


def test_upsert_is_idempotent_and_updates(tmp_path):
    s = ResultStore(tmp_path / "res")
    s.upsert([row("q1"), row("q2")])
    s.upsert([row("q1"), row("q2")])
    assert s.read().num_rows == 2
    s.upsert([row("q1", correct=False)])
    t = s.read().to_pylist()
    assert len(t) == 2
    assert {r["question_id"]: r["correct"] for r in t} == {"q1": False, "q2": True}
    assert s.done_keys("r1") == {("r1", "A", "m", "q1", 1), ("r1", "A", "m", "q2", 1)}
    assert s.done_keys("other") == set()
