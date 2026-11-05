from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any


def to_jsonable(v: Any) -> Any:
    """Values from DuckDB rows into JSON-safe types without losing meaning."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_jsonable(x) for k, x in v.items()}
    return str(v)


def result_payload(columns: list[str], rows: list[tuple], truncated: bool) -> dict[str, Any]:
    return {
        "columns": columns,
        "rows": [to_jsonable(r) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }
