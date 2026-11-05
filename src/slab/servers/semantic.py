"""MCP server for arm C: the semantic layer (MetricFlow) as the only way to the data.

The agent picks metrics, dimensions, filters and ordering. It never writes SQL; the
semantic layer compiles it and the guarded connection executes it.
"""

from __future__ import annotations

import threading
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from slab import config
from slab.db import QueryTimeout, connect_readonly, run_query
from slab.jsonable import result_payload
from slab.semantic.engine import SEMANTIC_POLICY, MetricQuery, SemanticEngine, SemanticQueryError
from slab.sqlguard import validate

INSTRUCTIONS = (
    "Governed business metrics over a sales database. Discover metrics with list_metrics, "
    "the dimensions they can be grouped or filtered by with list_dimensions, and query with query_metrics."
)

QUERY_DOC = """Query governed metrics.

metrics: metric names from list_metrics.
group_by: dimension names from list_dimensions; time dimensions need a grain suffix,
  e.g. metric_time__month, order_line__ship_date__year.
where: filters, ANDed, in MetricFlow syntax, e.g.
  "{{ Dimension('customer__region') }} = 'EUROPE'"
  "{{ TimeDimension('metric_time', 'day') }} >= '1995-01-01'"
  "{{ Dimension('part__size') }} IN (1, 2, 3)"
order_by: names from metrics or group_by, prefix '-' for descending, e.g. "-net_revenue".
limit: optional row limit.
Returns at most {max_rows} rows."""


def build_server(db_path: str | None = None, engine: SemanticEngine | None = None) -> MCPServer:
    server = MCPServer("slab-semantic", instructions=INSTRUCTIONS)
    con = connect_readonly(db_path)
    engine = engine or SemanticEngine()
    lock = threading.Lock()

    @server.tool()
    def list_metrics() -> list[dict[str, str]]:
        """All governed metrics with their business definitions."""
        with lock:
            return engine.list_metrics()

    @server.tool()
    def list_dimensions(metrics: list[str]) -> list[dict[str, str]]:
        """Dimensions available to group or filter the given metrics."""
        with lock:
            try:
                return engine.list_dimensions(metrics)
            except SemanticQueryError as e:
                raise ToolError(str(e)) from e

    @server.tool(description=QUERY_DOC.format(max_rows=config.MAX_RESULT_ROWS))
    def query_metrics(
        metrics: list[str],
        group_by: list[str] | None = None,
        where: list[str] | None = None,
        order_by: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        q = MetricQuery.from_dict(
            {"metrics": metrics, "group_by": group_by, "where": where, "order_by": order_by, "limit": limit}
        )
        with lock:
            try:
                sql = engine.compile(q)
                validate(sql, SEMANTIC_POLICY)
                r = run_query(con, sql, max_rows=config.MAX_RESULT_ROWS)
            except SemanticQueryError as e:
                raise ToolError(str(e)) from e
            except QueryTimeout as e:
                raise ToolError(str(e)) from e
            except Exception as e:  # noqa: BLE001
                raise ToolError(str(e).splitlines()[0][:500]) from e
        return result_payload(r.columns, r.rows, r.truncated)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
