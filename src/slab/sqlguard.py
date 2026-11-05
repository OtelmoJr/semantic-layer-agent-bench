"""Static validation of agent-written SQL before it reaches DuckDB.

Defense in depth: the connection is already read-only with external access disabled
(see db.py). This layer additionally pins *what* may be read, so the raw arms cannot
peek at the semantic layer's dbt models (schema `sl`) and the semantic arm cannot read
raw tables directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)

# Table functions and scalar functions that touch files, settings or the catalog.
DENIED_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "parquet_scan", "read_json",
    "read_json_auto", "read_ndjson", "read_text", "read_blob", "glob", "sniff_csv",
    "getenv", "current_setting", "query", "query_table", "duckdb_settings",
    "duckdb_tables", "duckdb_columns", "duckdb_databases", "duckdb_extensions",
    "duckdb_functions", "pragma_table_info", "load_extension", "iceberg_scan",
    "delta_scan", "read_xlsx", "sqlite_scan", "postgres_scan",
}


# Nested statements (e.g. a data-modifying CTE). Resolved by name so the module keeps
# working across sqlglot versions that add or rename expression classes.
_DENIED_NODES = tuple(
    getattr(exp, n)
    for n in ("Command", "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter",
              "Set", "Pragma", "Copy", "Attach", "Detach", "Use", "Install", "Load")
    if hasattr(exp, n)
)


class SQLRejected(ValueError):
    pass


@dataclass(frozen=True)
class TablePolicy:
    """Tables a caller may read, as (schema, table). `catalogs` lists acceptable
    catalog qualifiers (None = unqualified)."""

    tables: frozenset[tuple[str, str]]
    default_schema: str = "main"
    catalogs: frozenset[str | None] = frozenset({None})


def _function_name(node: exp.Expression) -> str | None:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    if isinstance(node, exp.Func):
        return node.sql_name().lower()
    return None


def validate(sql: str, policy: TablePolicy) -> str:
    """Return the normalized SQL if allowed, raise SQLRejected otherwise."""
    if not sql or not sql.strip():
        raise SQLRejected("empty SQL")
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SQLRejected(f"could not parse SQL: {str(e).splitlines()[0]}") from e
    if len(statements) != 1:
        raise SQLRejected("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, ALLOWED_ROOTS):
        raise SQLRejected(f"only SELECT queries are allowed (got {tree.key.upper()})")
    for node in tree.walk():
        if isinstance(node, _DENIED_NODES):
            raise SQLRejected(f"statement type not allowed: {node.key.upper()}")
        name = _function_name(node)
        if name and name in DENIED_FUNCTIONS:
            raise SQLRejected(f"function not allowed: {name}")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SQLRejected("table functions are not allowed in FROM")
        name = table.name.lower()
        schema = (table.db or "").lower() or None
        catalog = (table.catalog or "").lower() or None
        if schema is None and catalog is None and name in cte_names:
            continue
        if catalog not in policy.catalogs:
            raise SQLRejected(f"catalog not allowed: {catalog}")
        key = (schema or policy.default_schema, name)
        if key not in policy.tables:
            raise SQLRejected(f"table not allowed: {'.'.join(k for k in key if k)}")
    return tree.sql(dialect="duckdb")


def raw_policy(tables: tuple[str, ...], db_name: str = "tpch") -> TablePolicy:
    return TablePolicy(
        tables=frozenset(("main", t) for t in tables),
        default_schema="main",
        catalogs=frozenset({None, db_name}),
    )
