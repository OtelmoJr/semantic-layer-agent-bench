"""Benchmark runner: questions x arms x attempts, resumable and idempotent.

Questions are iterated question-major (all arms of a question before the next question)
so that slow drift in a hosted model or in machine load hits every arm equally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from slab import config, tracing
from slab.agent.backend import MCPBackend
from slab.agent.loop import run_question, submission_json
from slab.agent.providers.base import Provider
from slab.gold import Question, gold_hash, load_questions, splits
from slab.harness.evaluate import Evaluator
from slab.harness.store import ResultStore

log = logging.getLogger("slab.runner")
FLUSH_EVERY = 10
PRICES_PATH = config.ROOT / "config" / "prices.yaml"


class BudgetExceeded(RuntimeError):
    pass


def make_provider(name: str, model: str | None) -> Provider:
    if name == "stub":
        from slab.agent.providers.stub_provider import StubProvider

        return StubProvider()
    if name == "ollama":
        from slab.agent.providers.ollama_provider import OllamaProvider

        if not model:
            raise SystemExit("--model is required for ollama (e.g. qwen3:8b)")
        return OllamaProvider(model)
    if name == "anthropic":
        from slab.agent.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model)
    raise SystemExit(f"unknown provider {name}")


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _prices(model: str) -> tuple[float, float] | None:
    if not PRICES_PATH.exists():
        return None
    table = yaml.safe_load(PRICES_PATH.read_text()) or {}
    p = table.get(model)
    if not p:
        return None
    return float(p["input_usd_per_mtok"]), float(p["output_usd_per_mtok"])


@dataclass
class RunConfig:
    run_id: str
    provider: str
    model: str | None
    arms: tuple[str, ...] = ("A", "B", "C")
    split: str = "holdout"
    attempts: int = 3
    ids: tuple[str, ...] = ()
    transport: str = "stdio"
    budget_usd: float | None = None
    assumed_tokens_per_task: tuple[int, int] = (8000, 800)


def select_questions(cfg: RunConfig) -> tuple[list[Question], dict[str, str]]:
    qs = load_questions()
    sp = splits(qs)
    if cfg.ids:
        wanted = set(cfg.ids)
        unknown = wanted - {q.id for q in qs}
        if unknown:
            raise SystemExit(f"unknown question ids: {sorted(unknown)}")
        sel = [q for q in qs if q.id in wanted]
    elif cfg.split == "all":
        sel = qs
    else:
        sel = [q for q in qs if sp[q.id] == cfg.split]
    return sel, sp


async def run(cfg: RunConfig) -> dict[str, Any]:
    all_qs = load_questions()
    digest = gold_hash(all_qs)
    pinned = (config.GOLD_DIR / "HASH").read_text().strip()
    if digest != pinned:
        raise SystemExit(f"gold set changed after freeze ({digest} != {pinned}); refusing to run")

    provider = make_provider(cfg.provider, cfg.model)
    model_digest = provider.model_digest()
    questions, sp = select_questions(cfg)
    run_dir = config.RUNS_DIR / cfg.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tracing.setup(run_dir)
    store = ResultStore()
    done = store.done_keys(cfg.run_id)
    git_sha = _git_sha()

    tasks = [(q, arm, a) for q in questions for arm in cfg.arms for a in range(1, cfg.attempts + 1)
             if (cfg.run_id, arm, provider.model, q.id, a) not in done]

    prices = _prices(provider.model)
    if cfg.budget_usd is not None:
        if prices is None and provider.name == "anthropic":
            raise SystemExit(f"no price for {provider.model} in {PRICES_PATH}; cannot enforce --budget-usd")
        if prices:
            est = len(tasks) * (cfg.assumed_tokens_per_task[0] * prices[0]
                                + cfg.assumed_tokens_per_task[1] * prices[1]) / 1e6
            log.info("estimated cost for %d tasks: $%.2f (budget $%.2f)", len(tasks), est, cfg.budget_usd)
            if est > cfg.budget_usd:
                raise SystemExit(f"estimated ${est:.2f} exceeds budget ${cfg.budget_usd:.2f}; "
                                 "run a subset (--ids/--split dev --attempts 1) to calibrate first")

    manifest = {
        "run_id": cfg.run_id, "provider": provider.name, "model": provider.model,
        "model_digest": model_digest, "arms": list(cfg.arms), "split": cfg.split,
        "attempts": cfg.attempts, "questions": len(questions), "gold_hash": digest,
        "git_sha": git_sha, "transport": cfg.transport,
        "limits": {"max_tool_calls": config.MAX_TOOL_CALLS, "question_timeout_s": config.QUESTION_TIMEOUT_S,
                   "sql_timeout_s": config.SQL_TIMEOUT_S, "max_result_rows": config.MAX_RESULT_ROWS},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))
    log.info("run %s: %d tasks to do (%d already done)", cfg.run_id, len(tasks), len(done))

    evaluator = Evaluator()
    tr = tracing.tracer()
    pending: list[dict[str, Any]] = []
    spent = 0.0
    transcripts = (run_dir / "transcripts.jsonl").open("a")
    try:
        async with AsyncExitStack() as stack:
            backends = {arm: await stack.enter_async_context(MCPBackend(arm, cfg.transport)) for arm in cfg.arms}
            for i, (q, arm, attempt) in enumerate(tasks, 1):
                started = datetime.now(timezone.utc)
                with tr.start_as_current_span("slab.question") as span:
                    span.set_attribute("slab.run_id", cfg.run_id)
                    span.set_attribute("slab.arm", arm)
                    span.set_attribute("slab.question_id", q.id)
                    span.set_attribute("slab.attempt", attempt)
                    span.set_attribute("gen_ai.request.model", provider.model)
                    att = await run_question(provider, backends[arm], arm, q.id, q.question, seed=attempt)
                    score = evaluator.score(q, arm, att)
                    span.set_attribute("gen_ai.evaluation.name", "execution_accuracy")
                    span.set_attribute("gen_ai.evaluation.score.value", 1.0 if score.correct else 0.0)
                    span.set_attribute("gen_ai.evaluation.score.label", "correct" if score.correct else "wrong")
                    span.set_attribute("slab.status", att.status)
                    trace_id = tracing.trace_id_hex(span)
                row = {
                    "run_id": cfg.run_id, "arm": arm, "provider": provider.name, "model_id": provider.model,
                    "model_digest": model_digest, "question_id": q.id, "category": q.category,
                    "coverage": q.coverage, "split": sp[q.id], "attempt": attempt,
                    "expected_outcome": q.expected_outcome(arm), "status": att.status,
                    "submission": submission_json(att), "correct": score.correct, "reason": score.reason,
                    "tool_calls": att.tool_calls, "llm_calls": att.llm_calls, "tool_errors": att.tool_errors,
                    "protocol_errors": att.protocol_errors, "input_tokens": att.input_tokens,
                    "output_tokens": att.output_tokens, "latency_ms": att.latency_ms, "trace_id": trace_id,
                    "gold_hash": digest, "git_sha": git_sha, "started_at": started, "error": att.error,
                }
                pending.append(row)
                transcripts.write(json.dumps({"run_id": cfg.run_id, "arm": arm, "question_id": q.id,
                                              "attempt": attempt, "trace_id": trace_id,
                                              "transcript": att.transcript}, default=str) + "\n")
                log.info("[%d/%d] %s %s #%d %s -> %s (%s)", i, len(tasks), arm, q.id, attempt, att.status,
                         "OK" if score.correct else "wrong", score.reason)
                if prices:
                    spent += (att.input_tokens * prices[0] + att.output_tokens * prices[1]) / 1e6
                if len(pending) >= FLUSH_EVERY:
                    store.upsert(pending)
                    pending.clear()
                    transcripts.flush()
                if cfg.budget_usd is not None and spent > cfg.budget_usd:
                    raise BudgetExceeded(f"spent ${spent:.2f} > budget ${cfg.budget_usd:.2f}; resume later")
    finally:
        store.upsert(pending)
        transcripts.close()
        tracing.shutdown()
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["spent_usd_estimate"] = round(spent, 4) if prices else None
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def run_sync(cfg: RunConfig) -> dict[str, Any]:
    return asyncio.run(run(cfg))


def results_dir() -> Path:
    return config.RUNS_DIR
