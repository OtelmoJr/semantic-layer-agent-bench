"""Gold set: loading, deterministic dev/holdout split, hashing and validation.

The hash covers only what the question writers produced (id, category, coverage,
question, reference SQL, order flag). It is computed BEFORE the semantic layer exists and
pinned in gold/HASH; every run records it, so a result can always be traced to the exact
frozen questions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, model_validator
from sqlglot import exp

from slab import config
from slab.db import QueryTimeout, connect_readonly, run_query
from slab.sqlguard import SQLRejected, raw_policy, validate

Category = Literal["simple", "multi_join", "time", "business_definition", "out_of_coverage"]
Coverage = Literal["in", "raw_only", "none"]

TARGET_COUNTS: dict[str, int] = {
    "simple": 40,
    "multi_join": 40,
    "time": 25,
    "business_definition": 25,
    "out_of_coverage": 20,
}
DEV_FRACTION = 1 / 3


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    category: Category
    coverage: Coverage
    question: str
    reference_sql: str | None = None
    order_matters: bool = False

    @model_validator(mode="after")
    def _consistency(self) -> "Question":
        if self.coverage == "none" and self.reference_sql:
            raise ValueError(f"{self.id}: coverage=none must not have reference_sql")
        if self.coverage != "none" and not self.reference_sql:
            raise ValueError(f"{self.id}: reference_sql is required")
        if self.category != "out_of_coverage" and self.coverage != "in":
            raise ValueError(f"{self.id}: only out_of_coverage questions may be outside coverage")
        if self.category == "out_of_coverage" and self.coverage == "in":
            raise ValueError(f"{self.id}: out_of_coverage questions need coverage raw_only|none")
        return self

    def expected_outcome(self, arm: str) -> Literal["answer", "refuse"]:
        """What a correct agent does in a given arm."""
        if self.coverage == "none":
            return "refuse"
        if self.coverage == "raw_only" and arm == "C":
            return "refuse"
        return "answer"


def load_questions(gold_dir: Path = config.GOLD_DIR) -> list[Question]:
    questions: list[Question] = []
    for f in sorted((gold_dir / "questions").glob("*.yaml")):
        for item in yaml.safe_load(f.read_text()) or []:
            questions.append(Question(**item))
    ids = Counter(q.id for q in questions)
    dupes = [i for i, n in ids.items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate question ids: {dupes}")
    return sorted(questions, key=lambda q: q.id)


def gold_hash(questions: list[Question]) -> str:
    canonical = json.dumps([q.model_dump() for q in questions], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def split_of(question: Question, questions: list[Question]) -> Literal["dev", "holdout"]:
    """Deterministic stratified split: within each category, the third of ids with the
    smallest sha256 goes to dev. Nobody chooses which questions are dev."""
    same = sorted(
        (q.id for q in questions if q.category == question.category),
        key=lambda i: hashlib.sha256(i.encode()).hexdigest(),
    )
    n_dev = round(len(same) * DEV_FRACTION)
    return "dev" if question.id in same[:n_dev] else "holdout"


def splits(questions: list[Question]) -> dict[str, str]:
    return {q.id: split_of(q, questions) for q in questions}


# --------------------------------------------------------------------------- checks


def _tie_at_limit(con, sql: str) -> str | None:
    """For ORDER BY ... LIMIT n queries, detect a tie between row n and n+1 on the
    ORDER BY keys. A tie makes the 'right' top-n arbitrary, so the question is unfair."""
    tree = sqlglot.parse_one(sql, read="duckdb")
    if not isinstance(tree, exp.Select):
        return None
    limit = tree.args.get("limit")
    order = tree.args.get("order")
    if not limit or not order:
        return None
    try:
        n = int(limit.expression.name)
    except (AttributeError, ValueError):
        return None
    probe = tree.copy()
    keys = []
    for i, o in enumerate(order.expressions):
        alias = f"__ob_{i}"
        probe.select(exp.alias_(o.this.copy(), alias), copy=False)
        keys.append(alias)
    probe.set("limit", exp.Limit(expression=exp.Literal.number(n + 1)))
    wrapped = f"SELECT {', '.join(keys)} FROM ({probe.sql(dialect='duckdb')}) q"
    try:
        rows = con.execute(wrapped).fetchall()
    except Exception:  # noqa: BLE001 - best effort probe
        return None
    if len(rows) == n + 1 and rows[n - 1] == rows[n]:
        return f"tie between row {n} and {n + 1} on ORDER BY keys {rows[n]}"
    return None


def check(questions: list[Question], strict_counts: bool = True) -> list[str]:
    problems: list[str] = []
    counts = Counter(q.category for q in questions)
    if strict_counts:
        for cat, n in TARGET_COUNTS.items():
            if counts.get(cat, 0) != n:
                problems.append(f"category {cat}: {counts.get(cat, 0)} questions, expected {n}")
    pol = raw_policy(config.RAW_TABLES)
    con = connect_readonly()
    try:
        for q in questions:
            if q.reference_sql is None:
                continue
            try:
                validate(q.reference_sql, pol)
            except SQLRejected as e:
                problems.append(f"{q.id}: reference SQL rejected by raw guard: {e}")
                continue
            try:
                r1 = run_query(con, q.reference_sql, timeout_s=60)
                r2 = run_query(con, q.reference_sql, timeout_s=60)
            except (QueryTimeout, Exception) as e:  # noqa: BLE001
                problems.append(f"{q.id}: reference SQL failed: {str(e).splitlines()[0]}")
                continue
            if not r1.rows:
                problems.append(f"{q.id}: reference SQL returned no rows")
            if len(r1.rows) > config.MAX_RESULT_ROWS:
                problems.append(f"{q.id}: {len(r1.rows)} rows, max {config.MAX_RESULT_ROWS}")
            same = r1.rows == r2.rows if q.order_matters else sorted(map(repr, r1.rows)) == sorted(map(repr, r2.rows))
            if not same:
                problems.append(f"{q.id}: reference SQL is not deterministic")
            if len(set(r1.columns)) != len(r1.columns):
                problems.append(f"{q.id}: duplicate output column names")
            tie = _tie_at_limit(con, q.reference_sql)
            if tie:
                problems.append(f"{q.id}: {tie}")
            has_limit = "limit" in q.reference_sql.lower()
            if has_limit and not q.order_matters:
                problems.append(f"{q.id}: uses LIMIT, so order_matters must be true")
    finally:
        con.close()
    return problems


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Validate and hash the gold set")
    ap.add_argument("--freeze", action="store_true", help="write gold/HASH")
    ap.add_argument("--file", help="validate a single questions file (no count check)")
    args = ap.parse_args(argv)

    if args.file:
        qs = [Question(**i) for i in yaml.safe_load(Path(args.file).read_text()) or []]
        problems = check(qs, strict_counts=False)
    else:
        qs = load_questions()
        problems = check(qs)
    digest = gold_hash(qs)
    for p in problems:
        print(f"FAIL {p}")
    counts = Counter(q.category for q in qs)
    print(f"{len(qs)} questions {dict(sorted(counts.items()))}")
    print(f"sha256 {digest}")
    if problems:
        sys.exit(1)
    hash_file = config.GOLD_DIR / "HASH"
    if args.freeze:
        hash_file.write_text(digest + "\n")
        print(f"frozen -> {hash_file}")
    elif not args.file and hash_file.exists():
        pinned = hash_file.read_text().strip()
        if pinned != digest:
            print(f"FAIL gold set changed after freeze: pinned {pinned}")
            sys.exit(1)
        print("hash matches frozen gold set")
    print("OK")


if __name__ == "__main__":
    main()
