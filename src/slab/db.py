"""Guarded DuckDB access.

Gotcha this module exists for: `read_only=True` stops writes to the database file, but it
does NOT stop `SELECT * FROM read_csv('/etc/passwd')`. Local file access is a separate
switch (`enable_external_access`), and an agent with SQL could flip it back with `SET`
unless the configuration is locked afterwards. Both are applied at connect time here.

DuckDB has no statement timeout setting, so queries run under a timer that calls
`interrupt()` on the connection.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from slab import config

_LOCKED_CONFIG = {
    "enable_external_access": "false",
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
    "allow_community_extensions": "false",
    "threads": "4",
}


class QueryTimeout(Exception):
    pass


def connect_readonly(path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    path = Path(path or config.DB_PATH)
    if not path.exists():
        raise FileNotFoundError(f"database not found at {path}; run `make data` first")
    con = duckdb.connect(str(path), read_only=True, config=dict(_LOCKED_CONFIG))
    try:
        con.execute("SET lock_configuration = true")
    except duckdb.InvalidInputException as e:
        # A second connection in the same process shares the database instance, whose
        # configuration an earlier connection already locked. That is the state we want.
        if "locked" not in str(e):
            raise
    return con


@dataclass
class QueryResult:
    columns: list[str]
    types: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool = False


def run_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_s: float = config.SQL_TIMEOUT_S,
    max_rows: int | None = None,
) -> QueryResult:
    """Execute `sql` with a wall-clock timeout. `max_rows` truncates what is returned
    (and flags it) without changing the query the caller wrote."""
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        con.interrupt()

    timer = threading.Timer(timeout_s, _kill)
    timer.start()
    try:
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description]
        types = [str(d[1]) for d in cur.description]
        if max_rows is None:
            rows = cur.fetchall()
            truncated = False
        else:
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
        return QueryResult(columns, types, rows, truncated)
    except duckdb.InterruptException as e:
        if timed_out.is_set():
            raise QueryTimeout(f"query exceeded {timeout_s:.0f}s and was interrupted") from e
        raise
    finally:
        timer.cancel()
