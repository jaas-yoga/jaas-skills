"""Per-request cross-cutting concerns: correlation ID, structured access log,
request metrics, and a request-path trace span.

Design ref: design.md §10.2 ("Correlation IDs propagated through all
handlers"), §10.3 ("OpenTelemetry instrumentation for request path"),
implementation-plan.md Phase 6 tasks 1 and 3.
"""

from __future__ import annotations

import logging
import time

from opentelemetry.trace import Tracer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from jaas_registry.observability.logging import (
    log_event,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from jaas_registry.observability.metrics import request_latency_seconds, request_total

_access_logger = logging.getLogger("jaas_registry.access")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, tracer: Tracer):
        super().__init__(app)
        self._tracer = tracer

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or new_correlation_id()
        ctx_token = set_correlation_id(correlation_id)

        start = time.monotonic()
        try:
            with self._tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
                span.set_attribute("http.method", request.method)
                response = await call_next(request)

                route = request.scope.get("route")
                endpoint_label = route.path if route is not None else request.url.path
                span.update_name(f"{request.method} {endpoint_label}")
                span.set_attribute("http.route", endpoint_label)
                span.set_attribute("http.status_code", response.status_code)
        finally:
            reset_correlation_id(ctx_token)

        duration_seconds = time.monotonic() - start
        status = str(response.status_code)
        request_total.labels(endpoint=endpoint_label, status=status).inc()
        request_latency_seconds.labels(endpoint=endpoint_label, status=status).observe(
            duration_seconds
        )

        log_event(
            _access_logger,
            "request completed",
            method=request.method,
            path=endpoint_label,
            status=response.status_code,
            duration_ms=round(duration_seconds * 1000, 2),
            correlation_id=correlation_id,
        )

        response.headers["X-Correlation-Id"] = correlation_id
        return response
