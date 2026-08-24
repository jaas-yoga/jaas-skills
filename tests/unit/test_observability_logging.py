import json
import logging

from rune_registry.observability.logging import (
    JsonFormatter,
    configure_logging,
    get_correlation_id,
    redact,
    reset_correlation_id,
    set_correlation_id,
)


def test_correlation_id_set_get_reset_roundtrip():
    assert get_correlation_id() is None
    token = set_correlation_id("abc-123")
    assert get_correlation_id() == "abc-123"
    reset_correlation_id(token)
    assert get_correlation_id() is None


def test_redact_masks_jwt_shaped_strings():
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.c2lnbmF0dXJl"
    message = f"invalid token: {fake_jwt}"
    assert fake_jwt not in redact(message)
    assert "<redacted-token>" in redact(message)


def test_redact_leaves_normal_text_untouched():
    assert redact("plain error message") == "plain error message"


def test_json_formatter_produces_valid_json_with_expected_fields():
    token = set_correlation_id("corr-1")
    try:
        record = logging.LogRecord(
            name="rune_registry.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="something happened",
            args=(),
            exc_info=None,
        )
        formatted = JsonFormatter().format(record)
    finally:
        reset_correlation_id(token)

    payload = json.loads(formatted)
    assert payload["message"] == "something happened"
    assert payload["level"] == "INFO"
    assert payload["correlation_id"] == "corr-1"


def test_json_formatter_redacts_token_shaped_messages():
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.c2lnbmF0dXJl"
    record = logging.LogRecord(
        name="rune_registry.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=f"rejected: {fake_jwt}",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert fake_jwt not in payload["message"]


def test_configure_logging_installs_json_formatter_on_root_logger():
    root = logging.getLogger()
    original_handlers = root.handlers
    original_level = root.level
    try:
        configure_logging(level=logging.WARNING)
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_json_formatter_includes_extra_fields():
    record = logging.LogRecord(
        name="rune_registry.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.extra_fields = {"status": 200, "duration_ms": 12.5}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["status"] == 200
    assert payload["duration_ms"] == 12.5
