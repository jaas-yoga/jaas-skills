"""Operational endpoints: Prometheus metrics exposition. Design ref: design.md §10.1."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from jaas_registry.observability.metrics import registry

router = APIRouter()


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
