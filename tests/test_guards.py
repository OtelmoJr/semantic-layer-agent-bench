import time

import pytest

from slab import config
from slab.db import QueryTimeout, connect_readonly, run_query
from slab.sqlguard import SQLRejected, TablePolicy, raw_policy, validate

POL = raw_policy(config.RAW_TABLES)

ALLOWED = [
    "SELECT count(*) FROM lineitem",
    "select n_name from nation where n_regionkey = 1",
    "WITH t AS (SELECT o_orderkey FROM orders) SELECT count(*) FROM t",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT l.l_orderkey FROM main.lineitem l JOIN tpch.main.orders o ON o.o_orderkey = l.l_orderkey LIMIT 1",
]

REJECTED = {
    "empty": "",
    "two statements": "SELECT 1; SELECT 2",
    "insert": "INSERT INTO nation VALUES (1, 'x', 1, 'y')",
    "ddl": "CREATE TABLE x AS SELECT 1",
    "drop": "DROP TABLE nation",
    "copy out": "COPY lineitem TO 'out.csv'",
    "attach": "ATTACH 'other.duckdb'",
    "set": "SET enable_external_access = true",
    "pragma": "PRAGMA database_list",
    "install": "INSTALL httpfs",
    "load": "LOAD httpfs",
    "call": "CALL dbgen(sf=1)",
    "read_csv": "SELECT * FROM read_csv('/etc/passwd')",
    "read_csv in subquery": "SELECT (SELECT count(*) FROM read_csv_auto('/etc/passwd'))",
    "file path as table": "SELECT * FROM '/etc/passwd'",
    "getenv": "SELECT getenv('HOME')",
    "semantic schema": "SELECT * FROM sl.fct_order_lines",
    "catalog functions": "SELECT * FROM duckdb_tables()",
    "information_schema": "SELECT table_name FROM information_schema.tables",
    "unknown table": "SELECT * FROM secrets",
    "other catalog": "SELECT * FROM other.main.lineitem",
}


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    validate(sql, POL)


@pytest.mark.parametrize("name", REJECTED)
def test_rejected(name):
    with pytest.raises(SQLRejected):
        validate(REJECTED[name], POL)


def test_semantic_policy_blocks_raw_tables():
    pol = TablePolicy(tables=frozenset({("sl", "fct_order_lines")}), default_schema="sl",
                      catalogs=frozenset({None, "tpch"}))
    validate("SELECT 1 FROM tpch.sl.fct_order_lines", pol)
    with pytest.raises(SQLRejected):
        validate("SELECT 1 FROM main.lineitem", pol)


@pytest.mark.data
class TestConnection:
    """Second layer: even SQL that slipped past the guard cannot escape the connection."""

    def test_external_access_disabled(self):
        con = connect_readonly()
        with pytest.raises(Exception, match="(?i)disabled|permission"):
            con.execute("SELECT count(*) FROM read_csv('/etc/passwd')").fetchall()

    def test_config_locked(self):
        con = connect_readonly()
        with pytest.raises(Exception, match="(?i)cannot change"):
            con.execute("SET enable_external_access = true")

    def test_read_only(self):
        con = connect_readonly()
        with pytest.raises(Exception):
            con.execute("CREATE TABLE x (a INT)")

    def test_timeout_interrupts_runaway_query(self):
        con = connect_readonly()
        t0 = time.monotonic()
        with pytest.raises(QueryTimeout):
            run_query(con, "SELECT count(*) FROM lineitem a, lineitem b", timeout_s=1)
        assert time.monotonic() - t0 < 10
        # connection still usable afterwards
        assert run_query(con, "SELECT 1").rows == [(1,)]

    def test_truncation_flag(self):
        con = connect_readonly()
        r = run_query(con, "SELECT n_name FROM nation", max_rows=10)
        assert r.truncated and len(r.rows) == 10
