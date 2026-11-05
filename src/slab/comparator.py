"""Execution-accuracy comparator.

Decides whether an agent's result set answers the question the same way the reference
result does. A bug here invalidates every number in the report, so the rules are few,
explicit and property-tested (tests/test_comparator.py):

* Rows are compared as a multiset, unless the question is ordered (top-N, rankings).
* Column names and column order are ignored. Gold columns are matched to predicted
  columns by value; extra predicted columns are tolerated, missing ones are not.
* Numbers compare with a relative tolerance (DECIMAL vs DOUBLE, float summation order).
* Dates and midnight timestamps are the same value; a column of January-1st dates
  matches a column of integer years (MetricFlow returns DATE buckets, people write years).
* NULL equals NULL. Strings compare after stripping trailing spaces.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from typing import Any, Sequence

REL_TOL = 1e-4
ABS_TOL = 1e-6
MAX_ASSIGNMENTS = 5000


@dataclass(frozen=True)
class Verdict:
    correct: bool
    reason: str


def _norm(v: Any) -> Any:
    """Canonical scalar: floats for numbers, ISO strings for dates, stripped strings."""
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float, Decimal)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, dt.datetime):
        if v.time() == dt.time(0) and v.tzinfo is None:
            return v.date().isoformat()
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str):
        return v.rstrip()
    return str(v)


def _year_view(col: list[Any]) -> list[Any] | None:
    """If every non-null value is a YYYY-01-01 date string, return the integer-year view."""
    out = []
    seen = False
    for v in col:
        if v is None:
            out.append(None)
            continue
        if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[5:] == "01-01":
            out.append(float(v[:4]))
            seen = True
        else:
            return None
    return out if seen else None


def _eq(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def _col_variants(col: list[Any]) -> list[list[Any]]:
    variants = [col]
    yv = _year_view(col)
    if yv is not None:
        variants.append(yv)
    return variants


def _sort_key(v: Any) -> tuple:
    if v is None:
        return (0, 0)
    if isinstance(v, float):
        return (1, v)
    return (2, str(v))


def _signature_match(gold: list[Any], pred: list[Any]) -> bool:
    """Cheap necessary condition: same multiset of values (with tolerance)."""
    if len(gold) != len(pred):
        return False
    gs = sorted(gold, key=_sort_key)
    ps = sorted(pred, key=_sort_key)
    return all(_eq(a, b) for a, b in zip(gs, ps))


def _rows_equal(gold_rows: list[tuple], pred_rows: list[tuple], ordered: bool) -> bool:
    if len(gold_rows) != len(pred_rows):
        return False
    if ordered:
        return all(all(_eq(a, b) for a, b in zip(g, p)) for g, p in zip(gold_rows, pred_rows))
    # Multiset comparison with tolerance: sort both, then pairwise. Rows that differ only
    # inside tolerance sort the same way except in pathological near-ties, so fall back
    # to greedy matching when the sorted comparison fails.
    gs = sorted(gold_rows, key=lambda r: tuple(_sort_key(v) for v in r))
    ps = sorted(pred_rows, key=lambda r: tuple(_sort_key(v) for v in r))
    if all(all(_eq(a, b) for a, b in zip(g, p)) for g, p in zip(gs, ps)):
        return True
    remaining = list(pred_rows)
    for g in gold_rows:
        for i, p in enumerate(remaining):
            if all(_eq(a, b) for a, b in zip(g, p)):
                del remaining[i]
                break
        else:
            return False
    return True


def compare(
    gold_columns: Sequence[str],
    gold_rows: Sequence[Sequence[Any]],
    pred_columns: Sequence[str],
    pred_rows: Sequence[Sequence[Any]],
    ordered: bool = False,
) -> Verdict:
    del gold_columns, pred_columns  # names are deliberately ignored
    g = [[_norm(v) for v in r] for r in gold_rows]
    p = [[_norm(v) for v in r] for r in pred_rows]
    if len(g) != len(p):
        return Verdict(False, f"row count {len(p)} != expected {len(g)}")
    if not g:
        return Verdict(True, "both empty")
    n_gold, n_pred = len(g[0]), len(p[0])
    if n_pred < n_gold:
        return Verdict(False, f"{n_pred} columns, expected at least {n_gold}")

    gold_cols = [[r[i] for r in g] for i in range(n_gold)]
    pred_cols = [[r[j] for r in p] for j in range(n_pred)]

    # For each gold column: candidate (gold variant, pred column, pred variant) triples.
    gold_vars = [_col_variants(c) for c in gold_cols]
    pred_vars = [_col_variants(c) for c in pred_cols]
    candidates: list[list[tuple[int, int, int]]] = []
    for gi, gvs in enumerate(gold_vars):
        cands = [
            (gvi, j, pvi)
            for j, pvs in enumerate(pred_vars)
            for gvi, gv in enumerate(gvs)
            for pvi, pv in enumerate(pvs)
            if _signature_match(gv, pv)
        ]
        if not cands:
            return Verdict(False, "a reference column has no matching column in the answer")
        candidates.append(cands)

    tried = 0
    for assignment in product(*candidates):
        js = [a[1] for a in assignment]
        if len(set(js)) != len(js):
            continue
        tried += 1
        if tried > MAX_ASSIGNMENTS:
            return Verdict(False, "ambiguous column matching (too many candidates)")
        gcols = [gold_vars[gi][gvi] for gi, (gvi, _, _) in enumerate(assignment)]
        pcols = [pred_vars[j][pvi] for (_, j, pvi) in assignment]
        g_rows = [tuple(c[i] for c in gcols) for i in range(len(g))]
        p_rows = [tuple(c[i] for c in pcols) for i in range(len(p))]
        if _rows_equal(g_rows, p_rows, ordered):
            return Verdict(True, "match")
    return Verdict(False, "values differ" if not ordered else "values or order differ")
