"""Thin wrapper around MetricFlow: metadata for the agent and compile-to-SQL.

MetricFlow is used only as a compiler. It runs against a dbt target backed by an
in-memory DuckDB (`compile` in dbt/profiles.yml), so it never holds a read-write handle on
the real database file. The SQL it emits is then executed by the same guarded read-only
connection the raw arms use, with a policy that only allows the semantic layer's models.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import pathlib
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import sqlglot
from sqlglot import exp

from slab import config
from slab.sqlguard import TablePolicy

# Metrics that exist only as building blocks of ratio metrics. Hidden from the agent
# because the glossary does not define them as business metrics.
INTERNAL_METRICS = {"discounted_revenue_all", "late_lines"}

SEMANTIC_TABLES = frozenset(
    {
        ("sl", "fct_order_lines"),
        ("sl", "dim_customers"),
        ("sl", "dim_suppliers"),
        ("sl", "dim_parts"),
        ("sl", "metricflow_time_spine"),
    }
)
SEMANTIC_POLICY = TablePolicy(tables=SEMANTIC_TABLES, default_schema="sl", catalogs=frozenset({None}))

TIME_GRAINS = ("day", "week", "month", "quarter", "year")


class SemanticQueryError(ValueError):
    pass


@dataclass(frozen=True)
class MetricQuery:
    metrics: tuple[str, ...]
    group_by: tuple[str, ...] = ()
    where: tuple[str, ...] = ()
    order_by: tuple[str, ...] = ()
    limit: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MetricQuery":
        def tup(key: str) -> tuple[str, ...]:
            v = d.get(key) or ()
            if isinstance(v, str):
                v = [v]
            return tuple(str(x) for x in v)

        limit = d.get("limit")
        return cls(tup("metrics"), tup("group_by"), tup("where"), tup("order_by"),
                   int(limit) if limit not in (None, "") else None)

    def to_dict(self) -> dict[str, Any]:
        return {"metrics": list(self.metrics), "group_by": list(self.group_by),
                "where": list(self.where), "order_by": list(self.order_by), "limit": self.limit}


def _strip_catalogs(sql: str) -> str:
    """MetricFlow qualifies tables with the catalog of the compile target (`memory`).
    Drop the catalog so the SQL runs against whatever database the executor attached."""
    tree = sqlglot.parse_one(sql, read="duckdb")
    for table in tree.find_all(exp.Table):
        if table.args.get("catalog") is not None:
            table.set("catalog", None)
    return tree.sql(dialect="duckdb")


class SemanticEngine:
    def __init__(self, dbt_dir: pathlib.Path = config.DBT_DIR) -> None:
        self.dbt_dir = pathlib.Path(dbt_dir)
        manifest = self.dbt_dir / "target" / "semantic_manifest.json"
        if not manifest.exists():
            raise FileNotFoundError(f"{manifest} missing; run `make semantic` (dbt parse) first")

    @cached_property
    def _mf(self):
        from dbt_metricflow.cli.cli_configuration import CLIConfiguration

        os.environ.setdefault("DBT_PROFILES_DIR", str(self.dbt_dir))
        os.environ["DBT_TARGET"] = "compile"
        cfg = CLIConfiguration()
        # dbt/MetricFlow are chatty on stdout; an MCP stdio server must keep stdout clean.
        with contextlib.redirect_stdout(io.StringIO()):
            cfg.setup(self.dbt_dir, self.dbt_dir, configure_file_logging=False)
            mf = cfg.mf
        for name in ("dbt", "metricflow", "metricflow_semantics"):
            logging.getLogger(name).setLevel(logging.WARNING)
        return mf

    def list_metrics(self) -> list[dict[str, str]]:
        out = []
        for m in self._mf.list_metrics():
            if m.name in INTERNAL_METRICS:
                continue
            out.append({"name": m.name, "description": m.description or "", "type": str(m.type.value)})
        return sorted(out, key=lambda x: x["name"])

    def list_dimensions(self, metrics: list[str]) -> list[dict[str, str]]:
        names = {m["name"] for m in self.list_metrics()}
        unknown = [m for m in metrics if m not in names]
        if unknown:
            raise SemanticQueryError(f"unknown metrics: {unknown}. Use list_metrics.")
        dims = self._mf.simple_dimensions_for_metrics(list(metrics), without_any_property=[])
        out: dict[str, dict[str, str]] = {}
        for d in dims:
            name = d.dunder_name
            if name.startswith("metric_time__"):
                out["metric_time"] = {
                    "name": "metric_time",
                    "description": "Order date, the reference date of every metric. Use metric_time__<grain> "
                                   "with grain in day|week|month|quarter|year. Buckets are DATEs at bucket start.",
                    "type": "time",
                }
                continue
            entry = {"name": name, "description": d.description or "", "type": str(d.type.value).lower()}
            if entry["type"] == "time":
                entry["description"] += f" Group by {name}__<grain> with grain in day|week|month|quarter|year."
            out[name] = entry
        return sorted(out.values(), key=lambda x: x["name"])

    def compile(self, q: MetricQuery) -> str:
        from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

        if not q.metrics:
            raise SemanticQueryError("at least one metric is required")
        hidden = [m for m in q.metrics if m in INTERNAL_METRICS]
        if hidden:
            raise SemanticQueryError(f"unknown metrics: {hidden}")
        req = MetricFlowQueryRequest.create(
            metric_names=list(q.metrics),
            group_by_names=list(q.group_by) or None,
            where_constraints=list(q.where) or None,
            order_by_names=list(q.order_by) or None,
            limit=q.limit,
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                sql = self._mf.explain(req).sql_statement.sql
        except Exception as e:  # MetricFlow raises many exception types; surface the message
            msg = str(e).strip().splitlines()
            raise SemanticQueryError(" ".join(msg[:6])[:1200]) from e
        return _strip_catalogs(sql)
