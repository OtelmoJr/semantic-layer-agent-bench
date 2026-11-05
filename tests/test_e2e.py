"""End to end with the scripted stub provider: runner -> MCP -> DuckDB/MetricFlow ->
Delta store -> comparator -> report. No model, no network, deterministic."""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from slab import config
from slab.agent.providers.stub_provider import EXPECTED_SMOKE_EX, SMOKE_IDS

pytestmark = [pytest.mark.data, pytest.mark.semantic]


@pytest.fixture()
def isolated_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "RESULTS_TABLE", tmp_path / "runs" / "results_delta")
    import slab.harness.store as store
    monkeypatch.setattr(store.ResultStore.__init__, "__defaults__", (config.RESULTS_TABLE,))
    return tmp_path


def _run(run_id, transport="inproc", attempts=1):
    from slab.harness.runner import RunConfig, run_sync
    return run_sync(RunConfig(run_id=run_id, provider="stub", model=None, ids=SMOKE_IDS,
                              attempts=attempts, transport=transport))


def test_smoke_exact_accuracy_and_idempotency(isolated_runs):
    from slab.harness import stats
    from slab.harness.store import ResultStore

    _run("smoke")
    rows = ResultStore().read(["smoke"]).to_pylist()
    assert len(rows) == 30
    for s in stats.arm_scores(rows):
        assert s.ex == pytest.approx(EXPECTED_SMOKE_EX), s

    _run("smoke")  # rerun: nothing new, no duplicates
    assert ResultStore().read(["smoke"]).num_rows == 30

    # every result row points at a trace that exists, with LLM and tool spans under it
    spans = [json.loads(line) for line in (config.RUNS_DIR / "smoke" / "spans.jsonl").read_text().splitlines()]
    by_trace = {}
    for s in spans:
        by_trace.setdefault(s["trace_id"], set()).add(s["name"])
    for r in rows:
        assert "slab.question" in by_trace[r["trace_id"]]
        assert "gen_ai.chat" in by_trace[r["trace_id"]]
    roots = [s for s in spans if s["name"] == "slab.question"]
    assert all("gen_ai.evaluation.score.value" in s["attributes"] for s in roots)


def test_report_builds(isolated_runs):
    from slab.harness.report import build
    _run("rep")
    path = build(["rep"], config.RUNS_DIR / "report", split=None)
    text = path.read_text()
    assert "70.0%" in text and (path.parent / "ex_by_arm.png").exists()


def test_aa_same_arm_two_runs_not_significant(isolated_runs):
    from slab.harness.report import aa_test
    _run("aa1")
    _run("aa2")
    t = aa_test("aa1", "aa2", "A")
    assert t.p_value == 1.0 and t.diff == 0


def test_gold_changed_after_freeze_refuses_to_run(isolated_runs, monkeypatch):
    import slab.harness.runner as runner
    monkeypatch.setattr(runner, "gold_hash", lambda qs: "0" * 64)
    with pytest.raises(SystemExit, match="gold set changed"):
        _run("tampered")


@pytest.mark.slow
def test_kill_9_mid_run_then_resume_has_no_duplicates_or_gaps(isolated_runs):
    from slab.harness.store import ResultStore
    env = dict(os.environ, SLAB_RUNS_DIR=str(config.RUNS_DIR))
    cmd = [sys.executable, "-m", "slab.cli", "bench", "--provider", "stub", "--ids", ",".join(SMOKE_IDS),
           "--attempts", "2", "--run-id", "crash", "--transport", "inproc"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = config.RESULTS_TABLE / "_delta_log"
    deadline = time.time() + 120
    while time.time() < deadline and not (log.exists() and any(log.glob("*.json"))):
        time.sleep(0.2)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    partial = ResultStore().read(["crash"]).num_rows
    assert 0 < partial < 60
    subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = ResultStore().read(["crash"]).to_pylist()
    keys = [(r["arm"], r["question_id"], r["attempt"]) for r in rows]
    assert len(keys) == 60 and len(set(keys)) == 60
