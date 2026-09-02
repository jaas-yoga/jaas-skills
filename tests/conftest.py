import pytest

from jaas_registry.observability.metrics import reset_metrics


@pytest.fixture(autouse=True)
def _isolated_audit_dir(tmp_path, monkeypatch):
    """common/audit_store.py::FileAuditSink (Phase 3.3) is a real, durable
    file writer, unlike the StructuredLogAuditSink it replaced at every
    call site — every test that exercises yank/unyank, share grant
    create/revoke, publish (any path), a custom guardrail rule PUT, or a
    GitHub connection change now writes real files. Settings.audit_dir
    defaults to a relative path (".local_registry/audit"), so without this,
    dozens of test fixtures across the suite that construct Settings(...)
    directly (most without ever mentioning audit_dir) would all share and
    pollute one real on-disk location relative to wherever pytest runs.
    Pydantic-settings reads JAAS_AUDIT_DIR for any Settings(...) call that
    doesn't explicitly pass audit_dir itself, so one global env var here
    isolates every one of those fixtures without editing each individually."""
    monkeypatch.setenv("JAAS_AUDIT_DIR", str(tmp_path / "audit"))


@pytest.fixture
def clean_metrics():
    """Explicit opt-in fixture: the metrics registry is a process-wide singleton
    (Prometheus's own convention), so tests asserting on specific counter/gauge
    values need to start from zero rather than accumulating across the suite."""
    reset_metrics()
    yield
    reset_metrics()
