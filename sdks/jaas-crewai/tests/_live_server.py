"""Runs a real jaas_registry FastAPI app on a real localhost TCP port, in a
background thread, for genuinely end-to-end SDK tests.

IMPLEMENTATION_PLAN.md Phase 4.1: jaas-client's own test_client_against_
real_api.py extracts FastAPI TestClient's internal `_transport` and wraps it
in a plain httpx.Client -- fast and works fine there. It does NOT work in
this package: langgraph/langchain-core pull in `httpx2` transitively (via
langsmith), and starlette.testclient auto-detects httpx2's presence and
switches TestClient's internal transport to an httpx2-flavored one,
which a classic httpx.Client can't consume (`assert isinstance(response.
stream, SyncByteStream)` fails -- confirmed by reproducing this with a
plain, langchain-free script inside this package's own venv). A real
socket sidesteps that entirely and is more representative of real
production usage anyway. Same pattern should be reused in jaas-crewai and
jaas-autogen's own real-interop tests, for the same reason.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn
from fastapi import FastAPI


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def run_app(app: FastAPI) -> Iterator[str]:
    """Yields the base URL of `app`, served for the duration of the `with`
    block on a real ephemeral localhost port."""
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn server did not start within 10s")
        time.sleep(0.02)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
