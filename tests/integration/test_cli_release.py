"""jaasctl release / jaasctl guardrails push|validate — pure HTTP clients
of the backend API and the guardrails service respectively, so these
tests monkeypatch httpx instead of standing up a real server."""

from __future__ import annotations

import json

import pytest

from jaas_registry.cli import main
from tests.fixtures.package_dir import write_package_dir


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JAAS_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("JAAS_POLICY_DIR", str(tmp_path / "policy"))


def _fake_ambient_sigstore_signing(monkeypatch, *, bundle_json: str = '{"fake": "bundle"}') -> None:
    """Stands in for a real ambient CI OIDC identity + a real Fulcio/Rekor
    round trip — neither is available in this test process. Patches at
    artifact/sigstore_sign.py's own boundary (detect_credential +
    sign_digest_with_sigstore), not deep inside the sigstore-python
    library, matching this repo's established fake-at-the-seam convention
    (e.g. tests/fixtures/fake_guardrails_client.py)."""
    monkeypatch.setattr(
        "jaas_registry.artifact.sigstore_sign.detect_credential", lambda: "raw-jwt-value"
    )
    monkeypatch.setattr(
        "jaas_registry.artifact.sigstore_sign.IdentityToken", lambda raw_token: raw_token
    )
    monkeypatch.setattr(
        "jaas_registry.artifact.sigstore_sign.sign_digest_with_sigstore",
        lambda digest, identity_token: bundle_json,
    )


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class TestCmdRelease:
    def test_successful_release(self, tmp_path, capsys, monkeypatch):
        write_package_dir(tmp_path / "pkg")

        def fake_post(url, *, json, headers, timeout):
            assert url == "http://127.0.0.1:8027/api/v1/skills/release"
            assert headers == {"Authorization": "Bearer tok123"}
            return _FakeResponse(
                200, {"id": "acme.text.summarizer", "version": "1.2.3", "digest": "sha256:abc"}
            )

        monkeypatch.setattr("httpx.post", fake_post)

        exit_code = main(
            [
                "release",
                str(tmp_path / "pkg"),
                "--tag",
                "v1.2.3",
                "--token",
                "tok123",
                "--repo-url",
                "https://github.com/acme/tool-x",
            ]
        )

        assert exit_code == 0
        assert "RELEASED: acme.text.summarizer@1.2.3" in capsys.readouterr().out

    def test_uses_oidc_header_when_oidc_token_given(self, tmp_path, monkeypatch):
        write_package_dir(tmp_path / "pkg")
        captured = {}
        _fake_ambient_sigstore_signing(monkeypatch)

        def fake_post(url, *, json, headers, timeout):
            captured["headers"] = headers
            return _FakeResponse(200, {"id": "x", "version": "1.0.0", "digest": "sha256:x"})

        monkeypatch.setattr("httpx.post", fake_post)

        main(["release", str(tmp_path / "pkg"), "--tag", "v1.0.0", "--oidc-token", "eyOIDC"])

        assert captured["headers"] == {"X-Jaas-OIDC-Token": "eyOIDC"}

    def test_oidc_path_attaches_a_sigstore_bundle_to_the_request_body(self, tmp_path, monkeypatch):
        """The --oidc-token path implies a CI OIDC identity is available —
        jaasctl release uses that same identity for keyless Sigstore
        signing (IMPLEMENTATION_PLAN.md Phase 1.2), attaching the bundle
        so the registry can verify it instead of falling back to
        server-side dev-RSA signing."""
        write_package_dir(tmp_path / "pkg")
        captured = {}
        _fake_ambient_sigstore_signing(monkeypatch, bundle_json='{"fake": "bundle"}')

        def fake_post(url, *, json, headers, timeout):
            captured["body"] = json
            return _FakeResponse(200, {"id": "x", "version": "1.0.0", "digest": "sha256:x"})

        monkeypatch.setattr("httpx.post", fake_post)

        main(["release", str(tmp_path / "pkg"), "--tag", "v1.0.0", "--oidc-token", "eyOIDC"])

        assert captured["body"]["sigstoreBundle"] == '{"fake": "bundle"}'

    def test_oidc_path_hard_fails_with_no_ambient_credential(self, tmp_path, capsys, monkeypatch):
        """No fallback to dev-RSA signing on this path — a caller passing
        --oidc-token is asserting a CI OIDC identity exists; if
        sigstore-python's own ambient detection can't find one, that's a
        real environment problem to surface, not silently paper over."""
        write_package_dir(tmp_path / "pkg")
        monkeypatch.setattr(
            "jaas_registry.artifact.sigstore_sign.detect_credential", lambda: None
        )

        exit_code = main(
            ["release", str(tmp_path / "pkg"), "--tag", "v1.0.0", "--oidc-token", "eyOIDC"]
        )

        assert exit_code == 1
        assert "no ambient CI OIDC credential" in capsys.readouterr().out

    def test_pat_path_does_not_attempt_sigstore_signing(self, tmp_path, monkeypatch):
        """The PAT auth path exists specifically for CI systems without an
        ambient OIDC identity — it must never even try Sigstore signing,
        let alone hard-fail for lacking one."""
        write_package_dir(tmp_path / "pkg")

        def _boom():
            raise AssertionError("PAT-path release must not touch Sigstore signing at all")

        monkeypatch.setattr("jaas_registry.artifact.sigstore_sign.detect_credential", _boom)
        monkeypatch.setattr(
            "httpx.post",
            lambda url, *, json, headers, timeout: _FakeResponse(
                200, {"id": "x", "version": "1.0.0", "digest": "sha256:x"}
            ),
        )

        exit_code = main(
            [
                "release",
                str(tmp_path / "pkg"),
                "--tag",
                "v1.0.0",
                "--token",
                "tok123",
                "--repo-url",
                "https://github.com/acme/tool-x",
            ]
        )

        assert exit_code == 0

    def test_release_branch_is_included_in_the_request_body(self, tmp_path, monkeypatch):
        write_package_dir(tmp_path / "pkg")
        captured = {}

        def fake_post(url, *, json, headers, timeout):
            captured["body"] = json
            return _FakeResponse(200, {"id": "x", "version": "1.2.3", "digest": "sha256:x"})

        monkeypatch.setattr("httpx.post", fake_post)

        main(
            [
                "release",
                str(tmp_path / "pkg"),
                "--tag",
                "v1.2.3",
                "--token",
                "tok123",
                "--repo-url",
                "https://github.com/acme/tool-x",
                "--release-branch",
                "staging",
            ]
        )

        assert captured["body"]["releaseBranch"] == "staging"

    def test_release_branch_with_oidc_token_prints_ignored_note(
        self, tmp_path, capsys, monkeypatch
    ):
        write_package_dir(tmp_path / "pkg")
        _fake_ambient_sigstore_signing(monkeypatch)
        monkeypatch.setattr(
            "httpx.post",
            lambda url, *, json, headers, timeout: _FakeResponse(
                200, {"id": "x", "version": "1.0.0", "digest": "sha256:x"}
            ),
        )

        main(
            [
                "release",
                str(tmp_path / "pkg"),
                "--tag",
                "v1.0.0",
                "--oidc-token",
                "eyOIDC",
                "--release-branch",
                "staging",
            ]
        )

        assert "is ignored with --oidc-token" in capsys.readouterr().out

    def test_requires_a_credential(self, tmp_path, capsys):
        write_package_dir(tmp_path / "pkg")

        exit_code = main(["release", str(tmp_path / "pkg"), "--tag", "v1.2.3"])

        assert exit_code == 1
        assert "one of --token or --oidc-token is required" in capsys.readouterr().out

    def test_error_response_is_printed_with_code(self, tmp_path, capsys, monkeypatch):
        write_package_dir(tmp_path / "pkg")

        def fake_post(url, *, json, headers, timeout):
            return _FakeResponse(
                400, {"code": "RELEASE_VERSION_MISMATCH", "message": "tag doesn't match"}
            )

        monkeypatch.setattr("httpx.post", fake_post)

        exit_code = main(
            ["release", str(tmp_path / "pkg"), "--tag", "v9.9.9", "--token", "tok"]
        )

        assert exit_code == 1
        out = capsys.readouterr().out
        assert "RELEASE_VERSION_MISMATCH" in out
        assert "tag doesn't match" in out

    def test_missing_package_directory(self, tmp_path, capsys):
        exit_code = main(
            ["release", str(tmp_path / "does-not-exist"), "--tag", "v1.0.0", "--token", "tok"]
        )
        assert exit_code == 1
        assert "MISSING_FILE" in capsys.readouterr().out


class TestCmdGuardrailsPush:
    def test_pushes_every_rule_file(self, tmp_path, capsys, monkeypatch):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "no-todo.yaml").write_text(
            "name: No TODO\ncategory: CODE_SAFETY\nseverity: WARN\nkind: regex_file_scan\n"
            "config: {scope: all_files, patterns: []}\n"
        )
        put_calls = []

        def fake_put(url, *, json, headers, timeout):
            put_calls.append((url, json))
            return _FakeResponse(200, {"id": "custom:tnt_1:no-todo"})

        monkeypatch.setattr("httpx.put", fake_put)

        exit_code = main(
            [
                "guardrails",
                "push",
                str(rules_dir),
                "--tenant-id",
                "tnt_1",
                "--token",
                "tok123",
            ]
        )

        assert exit_code == 0
        assert "PUSHED: no-todo" in capsys.readouterr().out
        assert len(put_calls) == 1
        url, body = put_calls[0]
        assert url == "http://127.0.0.1:8027/api/v1/tenants/tnt_1/custom-guardrails/no-todo"
        assert body["slug"] == "no-todo"

    def test_no_rule_files_found(self, tmp_path, capsys):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        exit_code = main(
            ["guardrails", "push", str(empty_dir), "--tenant-id", "tnt_1", "--token", "tok"]
        )

        assert exit_code == 1
        assert "no rule files found" in capsys.readouterr().out

    def test_failed_push_reports_failure_and_continues(self, tmp_path, capsys, monkeypatch):
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        (rules_dir / "bad.yaml").write_text("name: Bad\nkind: regex_file_scan\nconfig: {}\n")

        monkeypatch.setattr(
            "httpx.put", lambda *a, **k: _FakeResponse(400, {"code": "INVALID_CUSTOM_GUARDRAIL"})
        )

        exit_code = main(
            ["guardrails", "push", str(rules_dir), "--tenant-id", "tnt_1", "--token", "tok"]
        )

        assert exit_code == 1
        assert "FAILED [bad]" in capsys.readouterr().out


class TestCmdGuardrailsValidate:
    def test_valid_rule(self, tmp_path, capsys, monkeypatch):
        rule_file = tmp_path / "rule.yaml"
        rule_file.write_text(
            "id: custom:tnt_1:no-todo\nname: No TODO\ncategory: CODE_SAFETY\nseverity: WARN\n"
            "kind: regex_file_scan\nconfig: {scope: all_files, patterns: []}\n"
        )

        monkeypatch.setattr(
            "httpx.post", lambda *a, **k: _FakeResponse(200, {"valid": True, "error": None})
        )

        exit_code = main(["guardrails", "validate", str(rule_file)])

        assert exit_code == 0
        assert "VALID: custom:tnt_1:no-todo" in capsys.readouterr().out

    def test_invalid_rule(self, tmp_path, capsys, monkeypatch):
        rule_file = tmp_path / "rule.yaml"
        rule_file.write_text("id: bad\nkind: not_a_kind\nconfig: {}\n")

        monkeypatch.setattr(
            "httpx.post",
            lambda *a, **k: _FakeResponse(200, {"valid": False, "error": "unknown kind"}),
        )

        exit_code = main(["guardrails", "validate", str(rule_file)])

        assert exit_code == 1
        assert "INVALID: unknown kind" in capsys.readouterr().out
