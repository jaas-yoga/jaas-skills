"""Tracing. Design ref: design.md §10.3 ("OpenTelemetry instrumentation for
request path and storage calls... span annotations for validation and policy
outcomes"), implementation-plan.md Phase 6 task 3.

Deliberately builds a local TracerProvider per app rather than installing a
process-wide global provider via `trace.set_tracer_provider` — OTel only
allows setting that once per process, which would make every test after the
first one silently share (or fight over) the same exporter. Passing a
`Tracer` around explicitly keeps each app/test isolated.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Tracer, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Status, StatusCode

from jaas_registry.common.errors import JaasError


def build_tracer(
    *,
    service_name: str = "jaas-registry",
    exporter: SpanExporter | None = None,
    batch: bool = False,
) -> Tracer:
    """`batch=False` (default) exports synchronously on the calling thread via
    SimpleSpanProcessor — correct for tests that assert on spans immediately
    after a `with` block exits. `batch=True` uses BatchSpanProcessor, which
    exports off-thread; a load test caught SimpleSpanProcessor adding
    meaningful per-request latency under concurrency (design.md §9.1's
    tuning task), so real serving/publishing paths opt into batching.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    processor_cls = BatchSpanProcessor if batch else SimpleSpanProcessor
    provider.add_span_processor(processor_cls(exporter or ConsoleSpanExporter()))
    return provider.get_tracer("jaas_registry")


def annotate_current_span_error(exc: JaasError) -> None:
    """Records a validation/policy outcome on whatever span is currently active
    (design.md §10.3.2). Safe to call unconditionally: `get_current_span()`
    returns a no-op span when nothing is tracing, so callers (validation rules,
    authz policy, trust verification) never need to know whether tracing is on.
    """
    span = trace.get_current_span()
    span.add_event("rejected", {"error.code": exc.code.value, "error.message": exc.message})
    span.set_status(Status(StatusCode.ERROR, exc.code.value))
