import pytest

from rune_registry.observability.metrics import reset_metrics


@pytest.fixture
def clean_metrics():
    """Explicit opt-in fixture: the metrics registry is a process-wide singleton
    (Prometheus's own convention), so tests asserting on specific counter/gauge
    values need to start from zero rather than accumulating across the suite."""
    reset_metrics()
    yield
    reset_metrics()
