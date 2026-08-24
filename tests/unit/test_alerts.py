from jaas_registry.observability import alerts
from jaas_registry.observability import metrics as m


def test_no_alerts_on_clean_metrics(clean_metrics):
    assert alerts.evaluate_all() == []


def test_error_rate_spike_fires_above_threshold(clean_metrics):
    m.request_total.labels(endpoint="/x", status="200").inc(9)
    m.request_total.labels(endpoint="/x", status="500").inc(2)

    alert = alerts.evaluate_error_rate_spike(threshold=0.1)
    assert alert is not None
    assert alert.name == "error_rate_spike"
    assert alert.severity == "critical"


def test_error_rate_spike_does_not_fire_below_threshold(clean_metrics):
    m.request_total.labels(endpoint="/x", status="200").inc(99)
    m.request_total.labels(endpoint="/x", status="500").inc(1)

    assert alerts.evaluate_error_rate_spike(threshold=0.1) is None


def test_error_rate_spike_no_data_does_not_fire(clean_metrics):
    assert alerts.evaluate_error_rate_spike() is None


def test_index_lag_breach_fires_above_threshold(clean_metrics):
    m.index_event_apply_lag_seconds.set(45.0)
    alert = alerts.evaluate_index_lag_breach(threshold_seconds=30.0)
    assert alert is not None
    assert alert.name == "index_lag_breach"


def test_index_lag_breach_does_not_fire_below_threshold(clean_metrics):
    m.index_event_apply_lag_seconds.set(5.0)
    assert alerts.evaluate_index_lag_breach(threshold_seconds=30.0) is None


def test_signature_verification_anomaly_fires_on_any_failure(clean_metrics):
    m.signature_verification_failures_total.labels(reason="CORRUPT_PAYLOAD").inc()
    alert = alerts.evaluate_signature_verification_anomaly()
    assert alert is not None
    assert alert.name == "signature_verification_anomaly"


def test_signature_verification_anomaly_silent_with_no_failures(clean_metrics):
    assert alerts.evaluate_signature_verification_anomaly() is None


def test_evaluate_all_returns_every_firing_alert(clean_metrics):
    m.request_total.labels(endpoint="/x", status="500").inc(5)
    m.request_total.labels(endpoint="/x", status="200").inc(1)
    m.index_event_apply_lag_seconds.set(999)
    m.signature_verification_failures_total.labels(reason="INVALID_SIGNATURE").inc()

    fired = {a.name for a in alerts.evaluate_all()}
    assert fired == {"error_rate_spike", "index_lag_breach", "signature_verification_anomaly"}
