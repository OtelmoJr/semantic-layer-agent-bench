"""Statistics over the results table.

The unit of analysis is the QUESTION. Attempts of the same question are not independent
(same prompt, same data), so they are averaged per question first and the bootstrap
resamples questions, never attempts.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

BOOT_ITERS = 2000
SEED = 7


@dataclass
class ArmScore:
    model: str
    arm: str
    n_questions: int
    ex: float
    ci_low: float
    ci_high: float
    pass_all: float  # pass^k: every attempt correct


def per_question(rows: Iterable[dict], key=("model_id", "arm")) -> dict[tuple, dict[str, list[bool]]]:
    out: dict[tuple, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[tuple(r[k] for k in key)][r["question_id"]].append(bool(r["correct"]))
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap_ci(values: list[float], iters: int = BOOT_ITERS, seed: int = SEED) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    rnd = random.Random(seed)
    n = len(values)
    means = sorted(_mean([values[rnd.randrange(n)] for _ in range(n)]) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters) - 1]


def arm_scores(rows: list[dict]) -> list[ArmScore]:
    out = []
    for (model, arm), qs in sorted(per_question(rows).items()):
        q_scores = [_mean([float(c) for c in v]) for v in qs.values()]
        lo, hi = bootstrap_ci(q_scores)
        pass_all = _mean([float(all(v)) for v in qs.values()])
        out.append(ArmScore(model, arm, len(qs), _mean(q_scores), lo, hi, pass_all))
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on discordant pairs b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


@dataclass
class PairTest:
    model: str
    arm_x: str
    arm_y: str
    n: int
    x_only: int  # questions right in x, wrong in y (majority vote)
    y_only: int
    diff: float  # EX(y) - EX(x), question-averaged
    ci_low: float
    ci_high: float
    p_value: float


def _majority(v: list[bool]) -> bool:
    return sum(v) * 2 > len(v)


def paired_test(rows: list[dict], model: str, x: str, y: str) -> PairTest | None:
    pq = per_question(rows)
    a, b = pq.get((model, x)), pq.get((model, y))
    if not a or not b:
        return None
    common = sorted(set(a) & set(b))
    xa = [_mean([float(c) for c in a[q]]) for q in common]
    yb = [_mean([float(c) for c in b[q]]) for q in common]
    diffs = [yv - xv for xv, yv in zip(xa, yb)]
    lo, hi = bootstrap_ci(diffs)
    x_only = sum(1 for q in common if _majority(a[q]) and not _majority(b[q]))
    y_only = sum(1 for q in common if _majority(b[q]) and not _majority(a[q]))
    return PairTest(model, x, y, len(common), x_only, y_only, _mean(diffs), lo, hi,
                    mcnemar_exact(x_only, y_only))


def documentation_share(rows: list[dict], model: str, iters: int = BOOT_ITERS) -> tuple[float, float, float] | None:
    """H2: (B - A) / (C - A). Near 1: documentation explains the semantic layer's gain.
    Bootstrap CI over questions; None when C - A is ~0 (ratio undefined)."""
    pq = per_question(rows)
    A, B, C = pq.get((model, "A")), pq.get((model, "B")), pq.get((model, "C"))
    if not (A and B and C):
        return None
    common = sorted(set(A) & set(B) & set(C))
    trip = [(_mean([float(c) for c in A[q]]), _mean([float(c) for c in B[q]]), _mean([float(c) for c in C[q]]))
            for q in common]

    def ratio(sample):
        a = _mean([t[0] for t in sample]); b = _mean([t[1] for t in sample]); c = _mean([t[2] for t in sample])
        return None if abs(c - a) < 1e-9 else (b - a) / (c - a)

    point = ratio(trip)
    if point is None:
        return None
    rnd = random.Random(SEED)
    boots = []
    for _ in range(iters):
        r = ratio([trip[rnd.randrange(len(trip))] for _ in trip])
        if r is not None:
            boots.append(r)
    boots.sort()
    return point, boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]


def by_category(rows: list[dict]) -> dict[tuple[str, str, str], float]:
    acc: dict[tuple[str, str, str], dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        acc[(r["model_id"], r["arm"], r["category"])][r["question_id"]].append(bool(r["correct"]))
    return {k: _mean([_mean([float(c) for c in v]) for v in qs.values()]) for k, qs in acc.items()}


def operational(rows: list[dict]) -> dict[tuple[str, str], dict[str, float]]:
    g: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        g[(r["model_id"], r["arm"])].append(r)
    out = {}
    for k, rs in g.items():
        n = len(rs)
        out[k] = {
            "attempts": n,
            "refused": sum(r["status"] == "refused" for r in rs) / n,
            "no_submission": sum(r["status"] not in ("submitted", "refused") for r in rs) / n,
            "tool_error_rate": sum(r["tool_errors"] for r in rs) / max(1, sum(r["tool_calls"] for r in rs)),
            "protocol_errors": sum(r["protocol_errors"] for r in rs) / n,
            "tool_calls": _mean([r["tool_calls"] for r in rs]),
            "input_tokens": _mean([r["input_tokens"] for r in rs]),
            "output_tokens": _mean([r["output_tokens"] for r in rs]),
            "latency_s": _mean([r["latency_ms"] / 1000 for r in rs]),
        }
    return out
