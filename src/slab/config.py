"""Central paths and constants. Everything is overridable through environment variables
so the same code runs locally, in Docker and in CI."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("SLAB_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = Path(os.environ.get("SLAB_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("SLAB_DB_PATH", DATA_DIR / "tpch.duckdb"))
DBT_DIR = ROOT / "dbt"
GOLD_DIR = ROOT / "gold"
GLOSSARY_PATH = ROOT / "glossary" / "metrics.yaml"
RUNS_DIR = Path(os.environ.get("SLAB_RUNS_DIR", ROOT / "runs"))
RESULTS_TABLE = RUNS_DIR / "results_delta"

SCALE_FACTOR = float(os.environ.get("SLAB_SF", "1"))

# Raw TPC-H tables the raw-SQL arms may touch. Anything else (the dbt schema `sl`,
# information_schema tricks, file readers) is rejected by the SQL guard.
RAW_TABLES = (
    "lineitem",
    "orders",
    "customer",
    "nation",
    "region",
    "part",
    "supplier",
    "partsupp",
)
SEMANTIC_SCHEMA = "sl"

# Agent limits, identical for every arm (fairness).
MAX_TOOL_CALLS = int(os.environ.get("SLAB_MAX_TOOL_CALLS", "8"))
QUESTION_TIMEOUT_S = float(os.environ.get("SLAB_QUESTION_TIMEOUT_S", "60"))
SQL_TIMEOUT_S = float(os.environ.get("SLAB_SQL_TIMEOUT_S", "20"))
MAX_RESULT_ROWS = int(os.environ.get("SLAB_MAX_RESULT_ROWS", "200"))
