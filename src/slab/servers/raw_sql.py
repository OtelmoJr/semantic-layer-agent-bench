"""MCP server for arms A and B: raw TPC-H schema behind a read-only SQL tool.

Arms A and B use this exact server. The only difference between them is the system
prompt (arm B also gets the business glossary), so any accuracy gap between A and B is
the effect of documentation alone.
"""

from __future__ import annotations

import threading
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from slab import config
from slab.db import QueryTimeout, connect_readonly, run_query
from slab.jsonable import result_payload
from slab.sqlguard import SQLRejected, raw_policy, validate

INSTRUCTIONS = (
    "Read-only access to a sales database (DuckDB SQL dialect). "
    "Explore with list_tables and describe_table, test queries with run_sql."
)


def build_server(db_path: str | None = None) -> MCPServer:
    server = MCPServer("slab-raw-sql", instructions=INSTRUCTIONS)
    con = connect_readonly(db_path)
    lock = threading.Lock()
    policy = raw_policy(config.RAW_TABLES)

    @server.tool()
    def list_tables() -> list[dict[str, Any]]:
        """List the tables in the database with their row counts."""
        with lock:
            out = []
            for t in config.RAW_TABLES:
                n = con.execute(f"SELECT count(*) FROM main.{t}").fetchone()[0]
                out.append({"table": t, "rows": n})
            return out

    @server.tool()
    def describe_table(table: str) -> list[dict[str, str]]:
        """Columns and types of one table."""
        t = table.strip().lower().removeprefix("main.")
        if t not in config.RAW_TABLES:
            raise ToolError(f"unknown table {table!r}; call list_tables")
        with lock:
            rows = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
                [t],
            ).fetchall()
        return [{"column": c, "type": ty} for c, ty in rows]

    @server.tool(
        description=f"Run one read-only SELECT (DuckDB dialect). Returns at most "
        f"{config.MAX_RESULT_ROWS} rows; `truncated` tells you if more exist."
    )
    def run_sql(sql: str) -> dict[str, Any]:
        try:
            checked = validate(sql, policy)
        except SQLRejected as e:
            raise ToolError(f"rejected: {e}") from e
        with lock:
            try:
                r = run_query(con, checked, max_rows=config.MAX_RESULT_ROWS)
            except QueryTimeout as e:
                raise ToolError(str(e)) from e
            except Exception as e:  # DuckDB errors go back to the agent as tool errors
                raise ToolError(str(e).splitlines()[0][:500]) from e
        return result_payload(r.columns, r.rows, r.truncated)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
