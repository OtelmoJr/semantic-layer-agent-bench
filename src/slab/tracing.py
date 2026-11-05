"""OpenTelemetry tracing with GenAI semantic-convention attributes.

Spans always go to a local JSONL file (runs/<run_id>/spans.jsonl) so traces exist with no
backend running, and additionally to an OTLP/HTTP endpoint when
OTEL_EXPORTER_OTLP_ENDPOINT is set (Phoenix in docker-compose).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Sequence

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._lock, self.path.open("a") as f:
            for s in spans:
                f.write(json.dumps({
                    "trace_id": format(s.context.trace_id, "032x"),
                    "span_id": format(s.context.span_id, "016x"),
                    "parent_id": format(s.parent.span_id, "016x") if s.parent else None,
                    "name": s.name,
                    "start_ns": s.start_time,
                    "end_ns": s.end_time,
                    "status": s.status.status_code.name,
                    "attributes": dict(s.attributes or {}),
                }, default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # noqa: D102
        pass


_provider: TracerProvider | None = None


def setup(run_dir: Path, service_name: str = "semantic-layer-agent-bench") -> TracerProvider:
    global _provider
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(run_dir / "spans.jsonl")))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    _provider = provider
    return provider


def tracer() -> trace.Tracer:
    if _provider is None:
        return trace.get_tracer("slab")
    return _provider.get_tracer("slab")


def shutdown() -> None:
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()


def trace_id_hex(span: trace.Span) -> str:
    return format(span.get_span_context().trace_id, "032x")
