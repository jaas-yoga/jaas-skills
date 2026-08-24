from rune_registry.observability import metrics as m


def _samples(collector):
    result = []
    for metric in collector.collect():
        result.extend(metric.samples)
    return result


def test_reset_metrics_zeroes_counters(clean_metrics):
    m.request_total.labels(endpoint="/x", status="200").inc()
    assert any(s.value > 0 for s in _samples(m.request_total) if s.name.endswith("_total"))

    m.reset_metrics()
    assert all(s.value == 0 for s in _samples(m.request_total) if s.name.endswith("_total"))


def test_request_total_labeled_by_endpoint_and_status(clean_metrics):
    m.request_total.labels(endpoint="/api/v1/skills", status="200").inc()
    m.request_total.labels(endpoint="/api/v1/skills", status="500").inc(2)

    samples = {
        (s.labels["endpoint"], s.labels["status"]): s.value
        for s in _samples(m.request_total)
        if s.name.endswith("_total")
    }
    assert samples[("/api/v1/skills", "200")] == 1
    assert samples[("/api/v1/skills", "500")] == 2


def test_index_event_apply_lag_gauge_records_latest_value(clean_metrics):
    m.index_event_apply_lag_seconds.set(1.5)
    m.index_event_apply_lag_seconds.set(3.25)
    samples = [s for s in _samples(m.index_event_apply_lag_seconds)]
    assert samples[0].value == 3.25


def test_signature_verification_failures_labeled_by_reason(clean_metrics):
    m.signature_verification_failures_total.labels(reason="CORRUPT_PAYLOAD").inc()
    samples = {
        s.labels["reason"]: s.value
        for s in _samples(m.signature_verification_failures_total)
        if s.name.endswith("_total")
    }
    assert samples["CORRUPT_PAYLOAD"] == 1
