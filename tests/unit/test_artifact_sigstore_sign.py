"""Client-side Sigstore signing (artifact/sigstore_sign.py) — the
counterpart to artifact/signing.py's dev-RSA sign_digest, used only by
`jaasctl release` on the --oidc-token path. detect_ambient_identity_token()
is a thin wrapper over sigstore.oidc.detect_credential(); real ambient
detection is sigstore-python's own concern, so this only tests our wrapper
returns None cleanly when nothing is detected — see cli.py's own tests for
how the hard-fail message surfaces to a caller."""

from __future__ import annotations

from jaas_registry.artifact.sigstore_sign import detect_ambient_identity_token


def test_returns_none_when_no_ambient_credential_is_present(monkeypatch):
    monkeypatch.setattr(
        "jaas_registry.artifact.sigstore_sign.detect_credential", lambda: None
    )
    assert detect_ambient_identity_token() is None


def test_wraps_a_detected_raw_token_as_an_identity_token(monkeypatch):
    monkeypatch.setattr(
        "jaas_registry.artifact.sigstore_sign.detect_credential", lambda: "raw-jwt-value"
    )
    # IdentityToken parses the JWT it's given (checks exp/structure) — a
    # bare placeholder string isn't a real JWT, so constructing one from it
    # is expected to fail; this test only confirms detect_ambient_identity_token
    # actually attempts that wrap (doesn't short-circuit to None) once a
    # credential is present.
    try:
        detect_ambient_identity_token()
    except Exception:
        pass
    else:
        raise AssertionError("expected IdentityToken construction to reject a non-JWT string")
