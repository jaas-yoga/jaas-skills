from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.observability.tracing import annotate_current_span_error, build_tracer


def test_build_tracer_produces_spans_via_supplied_exporter():
    exporter = InMemorySpanExporter()
    tracer = build_tracer(exporter=exporter)

    with tracer.start_as_current_span("demo") as span:
        span.set_attribute("foo", "bar")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "demo"
    assert spans[0].attributes["foo"] == "bar"


def test_build_tracer_tags_service_name():
    exporter = InMemorySpanExporter()
    tracer = build_tracer(service_name="rune-registry-test", exporter=exporter)

    with tracer.start_as_current_span("demo"):
        pass

    span = exporter.get_finished_spans()[0]
    assert span.resource.attributes["service.name"] == "rune-registry-test"


def test_annotate_current_span_error_records_event_and_error_status():
    exporter = InMemorySpanExporter()
    tracer = build_tracer(exporter=exporter)
    exc = RuneError(ErrorCode.INVALID_ID_FORMAT, "id is malformed")

    with tracer.start_as_current_span("demo"):
        annotate_current_span_error(exc)

    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert len(span.events) == 1
    assert span.events[0].name == "rejected"
    assert span.events[0].attributes["error.code"] == "INVALID_ID_FORMAT"


def test_annotate_current_span_error_is_a_safe_noop_without_an_active_span():
    exc = RuneError(ErrorCode.INVALID_ID_FORMAT, "id is malformed")
    annotate_current_span_error(exc)  # must not raise
