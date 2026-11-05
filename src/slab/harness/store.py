"""Results store: a Delta table written with delta-rs, upserted by MERGE.

Key: (run_id, arm, model_id, question_id, attempt). Re-running a run, or resuming one
after a crash, never duplicates rows. No partitioning: a full run is ~2.7k rows, and
partitions would only produce small files. Revisit past ~1e6 rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from slab import config

KEY = ("run_id", "arm", "model_id", "question_id", "attempt")

SCHEMA = pa.schema([
    ("run_id", pa.string()),
    ("arm", pa.string()),
    ("provider", pa.string()),
    ("model_id", pa.string()),
    ("model_digest", pa.string()),
    ("question_id", pa.string()),
    ("category", pa.string()),
    ("coverage", pa.string()),
    ("split", pa.string()),
    ("attempt", pa.int32()),
    ("expected_outcome", pa.string()),
    ("status", pa.string()),
    ("submission", pa.string()),
    ("correct", pa.bool_()),
    ("reason", pa.string()),
    ("tool_calls", pa.int32()),
    ("llm_calls", pa.int32()),
    ("tool_errors", pa.int32()),
    ("protocol_errors", pa.int32()),
    ("input_tokens", pa.int64()),
    ("output_tokens", pa.int64()),
    ("latency_ms", pa.int64()),
    ("trace_id", pa.string()),
    ("gold_hash", pa.string()),
    ("git_sha", pa.string()),
    ("started_at", pa.timestamp("us", tz="UTC")),
    ("error", pa.string()),
])


class ResultStore:
    def __init__(self, path: Path = config.RESULTS_TABLE) -> None:
        self.path = Path(path)

    def _exists(self) -> bool:
        return (self.path / "_delta_log").exists()

    def upsert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        batch = pa.Table.from_pylist(rows, schema=SCHEMA)
        if not self._exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_deltalake(str(self.path), batch, mode="error")
            return
        predicate = " AND ".join(f"t.{k} = s.{k}" for k in KEY)
        (
            DeltaTable(str(self.path))
            .merge(batch, predicate=predicate, source_alias="s", target_alias="t")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )

    def done_keys(self, run_id: str) -> set[tuple]:
        if not self._exists():
            return set()
        t = DeltaTable(str(self.path)).to_pyarrow_table(
            columns=list(KEY), filters=[("run_id", "=", run_id)]
        )
        return set(zip(*(t.column(k).to_pylist() for k in KEY)))

    def read(self, run_ids: list[str] | None = None) -> pa.Table:
        if not self._exists():
            return SCHEMA.empty_table()
        dt = DeltaTable(str(self.path))
        if run_ids:
            return dt.to_pyarrow_table(filters=[("run_id", "in", run_ids)])
        return dt.to_pyarrow_table()
