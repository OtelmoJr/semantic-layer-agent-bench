"""MCP contract: tool surface per server is pinned, and arms are isolated."""
import json

import anyio
import pytest
from mcp import Client

pytestmark = [pytest.mark.data, pytest.mark.semantic]

EXPECTED = {
    "raw": {"list_tables": [], "describe_table": ["table"], "run_sql": ["sql"]},
    "semantic": {"list_metrics": [], "list_dimensions": ["metrics"], "query_metrics": ["metrics"]},
}


def _surface(server):
    async def go():
        async with Client(server) as c:
            tools = (await c.list_tools()).tools
            return {t.name: sorted(t.input_schema.get("required", [])) for t in tools}
    return anyio.run(go)


def _call(server, name, args):
    async def go():
        async with Client(server) as c:
            r = await c.call_tool(name, args)
            return r.is_error, "\n".join(x.text for x in r.content)
    return anyio.run(go)


def test_raw_server_surface():
    from slab.servers.raw_sql import build_server
    assert _surface(build_server()) == EXPECTED["raw"]


def test_semantic_server_surface():
    from slab.servers.semantic import build_server
    assert _surface(build_server()) == EXPECTED["semantic"]


def test_raw_server_cannot_read_semantic_models():
    from slab.servers.raw_sql import build_server
    err, text = _call(build_server(), "run_sql", {"sql": "SELECT count(*) FROM sl.fct_order_lines"})
    assert err and "not allowed" in text


def test_raw_server_rejects_file_access_with_message():
    from slab.servers.raw_sql import build_server
    err, text = _call(build_server(), "run_sql", {"sql": "SELECT * FROM read_csv('/etc/passwd')"})
    assert err and "read_csv" in text


def test_describe_unknown_table():
    from slab.servers.raw_sql import build_server
    err, text = _call(build_server(), "describe_table", {"table": "sl.dim_customers"})
    assert err and "unknown table" in text


def test_semantic_query_returns_rows_and_errors_are_readable():
    from slab.servers.semantic import build_server
    srv = build_server()
    err, text = _call(srv, "query_metrics", {"metrics": ["order_count"], "group_by": ["customer__region"]})
    assert not err and len(json.loads(text)["rows"]) == 5
    err, text = _call(srv, "query_metrics", {"metrics": ["profit"]})
    assert err and "metric" in text.lower()
