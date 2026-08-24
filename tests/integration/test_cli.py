import logging

import pytest

from jaas_registry.cli import main
from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JAAS_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("JAAS_POLICY_DIR", str(tmp_path / "policy"))
    return tmp_path


@pytest.fixture
def _restore_root_logger():
    """`cmd_serve` calls `configure_logging()`, which mutates the *global*
    root logger (installs a JsonFormatter handler, sets its level). Without
    restoring it, every other test in the same pytest process — anything
    that logs at INFO afterward, including third-party libraries like httpx —
    would suddenly pay for JSON formatting/redaction on every log call. This
    once caused order-dependent flakiness in the load test suite."""
    root = logging.getLogger()
    original_handlers, original_level = root.handlers, root.level
    yield
    root.handlers = original_handlers
    root.setLevel(original_level)


def test_validate_valid_package_succeeds(tmp_path, capsys):
    write_package_dir(tmp_path / "pkg")
    exit_code = main(
        ["validate", str(tmp_path / "pkg")], guardrails_client=FakeGuardrailsClient()
    )
    assert exit_code == 0
    assert "VALID" in capsys.readouterr().out


def test_validate_invalid_package_fails_with_code(tmp_path, capsys):
    import copy

    bad_manifest = copy.deepcopy(VALID_MANIFEST)
    bad_manifest["version"] = "not-semver"
    write_package_dir(tmp_path / "pkg", manifest=bad_manifest)

    exit_code = main(["validate", str(tmp_path / "pkg")])
    assert exit_code == 1
    assert "INVALID_VERSION_FORMAT" in capsys.readouterr().out


def test_validate_missing_directory_reports_missing_file(tmp_path, capsys):
    exit_code = main(["validate", str(tmp_path / "does-not-exist")])
    assert exit_code == 1
    assert "MISSING_FILE" in capsys.readouterr().out


def test_publish_then_republish_is_rejected_as_duplicate(tmp_path, capsys):
    write_package_dir(tmp_path / "pkg")

    first = main(
        ["publish", str(tmp_path / "pkg"), "--actor", "test-user"],
        guardrails_client=FakeGuardrailsClient(),
    )
    assert first == 0
    assert "PUBLISHED" in capsys.readouterr().out

    second = main(
        ["publish", str(tmp_path / "pkg"), "--actor", "test-user"],
        guardrails_client=FakeGuardrailsClient(),
    )
    assert second == 1
    assert "DUPLICATE_PUBLISH" in capsys.readouterr().out


def test_publish_missing_directory_reports_missing_file(tmp_path, capsys):
    exit_code = main(["publish", str(tmp_path / "does-not-exist")])
    assert exit_code == 1
    assert "MISSING_FILE" in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    exit_code = main([])
    assert exit_code == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_serve_wires_up_uvicorn(tmp_path, monkeypatch, _restore_root_logger):
    write_package_dir(tmp_path / "pkg")
    assert main(["publish", str(tmp_path / "pkg")], guardrails_client=FakeGuardrailsClient()) == 0

    calls = {}

    def fake_run(app, host, port):
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port

    monkeypatch.setattr("uvicorn.run", fake_run)
    exit_code = main(["serve", "--host", "0.0.0.0", "--port", "9000"])  # noqa: S104

    assert exit_code == 0
    assert calls["host"] == "0.0.0.0"  # noqa: S104
    assert calls["port"] == 9000
    # the bootstrapped index inside the app should already contain the published skill
    assert calls["app"].state.index.get(VALID_MANIFEST["id"], VALID_MANIFEST["version"]) is not None
