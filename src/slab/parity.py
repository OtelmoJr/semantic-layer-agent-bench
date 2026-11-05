"""Parity test: for every in-coverage question, the semantic layer query in
gold/mf_specs/*.yaml must return the same result as the reference SQL.

Without this, the semantic-layer arm could be punished for a modeling bug of mine rather
than for anything the agent did. Specs are written after the gold set is frozen and are
never shown to agents.
"""

from __future__ import annotations

import argparse
import sys

import yaml

from slab import config
from slab.comparator import compare
from slab.db import connect_readonly, run_query
from slab.gold import load_questions
from slab.semantic.engine import SEMANTIC_POLICY, MetricQuery, SemanticEngine
from slab.sqlguard import validate

SPECS_DIR = config.GOLD_DIR / "mf_specs"


def load_specs() -> dict[str, MetricQuery]:
    specs: dict[str, MetricQuery] = {}
    for f in sorted(SPECS_DIR.glob("*.yaml")):
        for qid, spec in (yaml.safe_load(f.read_text()) or {}).items():
            if qid in specs:
                raise ValueError(f"duplicate mf_spec for {qid}")
            specs[qid] = MetricQuery.from_dict(spec)
    return specs


def run(only: set[str] | None = None, verbose: bool = False) -> list[str]:
    questions = [q for q in load_questions() if q.coverage == "in"]
    if only:
        questions = [q for q in questions if q.id in only]
    specs = load_specs()
    engine = SemanticEngine()
    con = connect_readonly()
    problems = []
    for q in questions:
        spec = specs.get(q.id)
        if spec is None:
            problems.append(f"{q.id}: missing mf_spec")
            continue
        try:
            sql = engine.compile(spec)
            validate(sql, SEMANTIC_POLICY)
            got = run_query(con, sql, timeout_s=60)
            ref = run_query(con, q.reference_sql, timeout_s=60)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{q.id}: {type(e).__name__}: {str(e)[:300]}")
            continue
        v = compare(ref.columns, ref.rows, got.columns, got.rows, ordered=q.order_matters)
        if not v.correct:
            msg = f"{q.id}: {v.reason}"
            if verbose:
                msg += f"\n  ref {ref.columns} {ref.rows[:3]}\n  got {got.columns} {got.rows[:3]}"
            problems.append(msg)
    con.close()
    return problems


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", nargs="*")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    problems = run(set(args.ids) or None, args.verbose)
    for p in problems:
        print(f"FAIL {p}")
    total = len(args.ids) if args.ids else sum(1 for q in load_questions() if q.coverage == "in")
    print(f"parity: {total - len(problems)}/{total} match")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
