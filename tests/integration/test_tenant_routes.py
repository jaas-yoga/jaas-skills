"""ui-implementation-plan.md Phase 6: tenant creation, member listing, and
invites (both the immediate-add and pending-until-sign-in paths).

Tokens here always come from a real POST /api/v1/auth/google sign-in (via
FakeGoogleIdentityVerifier), never a hand-minted JWT — a hand-minted token's
`sub` has no backing User record, and list_members legitimately skips a
membership whose user record doesn't exist (it only ever happens for a real
user in production, since AuthService is the only thing that mints tokens).
"""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.api.deps import get_google_verifier
from jaas_registry.authn.google import GoogleIdentity
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


class FakeGoogleIdentityVerifier:
    """Maps a raw "token" string directly to an identity — good enough for
    exercising sign-in without a real Google account."""

    def __init__(self, identities: dict[str, GoogleIdentity]):
        self._identities = identities

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        identity = self._identities.get(google_id_token_jwt)
        if identity is None:
            raise JaasError(ErrorCode.INVALID_GOOGLE_TOKEN, "unknown test token")
        return identity


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(
        index=index,
        store=store,
        settings=settings,
        authorizer=authorizer,
        guardrails_client=FakeGuardrailsClient(),
    )
    app.dependency_overrides[get_google_verifier] = lambda: FakeGoogleIdentityVerifier(
        {
            "alice-token": GoogleIdentity(
                sub="google-alice", email="alice@example.com", name="Alice", picture=None
            ),
            "bob-token": GoogleIdentity(
                sub="google-bob", email="bob@example.com", name="Bob", picture=None
            ),
            "outsider-token": GoogleIdentity(
                sub="google-outsider", email="outsider@example.com", name="Outsider", picture=None
            ),
        }
    )
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sign_in(client: TestClient, id_token: str) -> str:
    resp = client.post("/api/v1/auth/google", json={"idToken": id_token})
    assert resp.status_code == 200, resp.text
    return resp.json()["accessToken"]


def _member_scope_token():
    """The only case that legitimately needs a hand-minted, non-sign-in
    token: a caller with the base member scope but no tenant membership at
    all, proving invite_member's admin check runs (and 404s) before ever
    looking at role."""
    return make_token(subject="usr_no_membership", tenant="tnt_none", scopes=("skills:write",))


class TestCreateTenant:
    def test_creating_a_tenant_makes_the_caller_admin(self, client):
        token = _sign_in(client, "alice-token")
        resp = client.post("/api/v1/tenants", json={"name": "Acme Corp"}, headers=_auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Acme Corp"
        assert body["role"] == "admin"

    def test_requires_auth(self, client):
        resp = client.post("/api/v1/tenants", json={"name": "Acme Corp"})
        assert resp.status_code == 403


class TestMembers:
    def test_admin_can_list_members(self, client):
        token = _sign_in(client, "alice-token")
        tenant = client.post("/api/v1/tenants", json={"name": "Acme"}, headers=_auth(token)).json()

        resp = client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=_auth(token))

        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["role"] == "admin"
        assert resp.json()[0]["email"] == "alice@example.com"

    def test_non_member_gets_404_not_403(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        outsider_token = _sign_in(client, "outsider-token")
        resp = client.get(f"/api/v1/tenants/{tenant['id']}/members", headers=_auth(outsider_token))

        assert resp.status_code == 404
        assert resp.json()["code"] == "TENANT_NOT_FOUND"


class TestInvite:
    def test_caller_with_no_membership_gets_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "x@example.com"},
            headers=_auth(_member_scope_token()),
        )
        assert resp.status_code == 404

    def test_member_role_cannot_invite(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "outsider@example.com"},
            headers=_auth(bob_token),
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_inviting_an_existing_user_adds_them_immediately(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        _sign_in(client, "bob-token")  # bob has a User record now

        resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "added"

        members = client.get(
            f"/api/v1/tenants/{tenant['id']}/members", headers=_auth(admin_token)
        ).json()
        assert {m["email"] for m in members} == {"alice@example.com", "bob@example.com"}

    def test_inviting_the_same_existing_user_twice_is_rejected(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com"},
            headers=_auth(admin_token),
        )

        resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com"},
            headers=_auth(admin_token),
        )

        assert resp.status_code == 400

    def test_inviting_with_an_invalid_role_is_rejected(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "superadmin"},
            headers=_auth(admin_token),
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "SCHEMA_VALIDATION_FAILED"

    def test_inviting_an_unknown_email_creates_a_pending_invite_resolved_on_sign_in(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        invite_resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )
        assert invite_resp.json()["status"] == "pending"

        sign_in = client.post("/api/v1/auth/google", json={"idToken": "bob-token"})
        assert sign_in.status_code == 200
        tenant_ids = {t["id"] for t in sign_in.json()["tenants"]}
        assert tenant["id"] in tenant_ids

    def test_inviting_an_already_pending_email_twice_does_not_error(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        first = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com"},
            headers=_auth(admin_token),
        )
        second = client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com"},
            headers=_auth(admin_token),
        )
        assert first.status_code == 200
        assert second.status_code == 200


class TestGuardrailPolicy:
    def test_admin_can_get_and_put_policy(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        get_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy", headers=_auth(admin_token)
        )
        assert get_resp.status_code == 200
        assert "secret-scan" in get_resp.json()["enabledCheckIds"]

        put_resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy",
            json={"enabledCheckIds": ["pii-pattern-scan"]},
            headers=_auth(admin_token),
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["enabledCheckIds"] == ["pii-pattern-scan"]

    def test_put_silently_drops_mandatory_ids(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy",
            json={"enabledCheckIds": ["secret-scan", "pii-pattern-scan"]},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 200
        assert "secret-scan" not in resp.json()["enabledCheckIds"]
        assert "pii-pattern-scan" in resp.json()["enabledCheckIds"]

    def test_put_rejects_unknown_id(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy",
            json={"enabledCheckIds": ["not-a-real-check"]},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400

    def test_member_can_view_but_not_edit(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        get_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy", headers=_auth(bob_token)
        )
        assert get_resp.status_code == 200

        put_resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy",
            json={"enabledCheckIds": []},
            headers=_auth(bob_token),
        )
        assert put_resp.status_code == 403
        assert put_resp.json()["code"] == "UNAUTHORIZED"

    def test_non_member_gets_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        outsider_token = _sign_in(client, "outsider-token")

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/guardrail-policy", headers=_auth(outsider_token)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "TENANT_NOT_FOUND"


def _custom_rule_body(**overrides):
    body = {
        "slug": "no-todo",
        "name": "No TODO",
        "description": "Flags TODO comments.",
        "category": "CODE_SAFETY",
        "severity": "WARN",
        "standardRef": "",
        "kind": "regex_file_scan",
        "config": {"scope": "all_files", "patterns": [{"name": "todo", "regex": "TODO"}]},
    }
    body.update(overrides)
    return body


class TestCustomGuardrailRules:
    def test_admin_can_create_list_and_delete_a_rule(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        put_resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/no-todo",
            json=_custom_rule_body(),
            headers=_auth(admin_token),
        )
        assert put_resp.status_code == 200, put_resp.text
        assert put_resp.json()["id"] == f"custom:{tenant['id']}:no-todo"

        list_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails", headers=_auth(admin_token)
        )
        assert list_resp.status_code == 200
        assert [r["slug"] for r in list_resp.json()] == ["no-todo"]

        delete_resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/no-todo",
            headers=_auth(admin_token),
        )
        assert delete_resp.status_code == 204

        list_after = client.get(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails", headers=_auth(admin_token)
        )
        assert list_after.json() == []

    def test_delete_missing_rule_is_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/does-not-exist",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "CUSTOM_GUARDRAIL_NOT_FOUND"

    def test_member_can_list_and_validate_but_not_create(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        list_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails", headers=_auth(bob_token)
        )
        assert list_resp.status_code == 200

        validate_resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/validate",
            json=_custom_rule_body(),
            headers=_auth(bob_token),
        )
        assert validate_resp.status_code == 200
        assert validate_resp.json() == {"valid": True, "error": None}

        put_resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/no-todo",
            json=_custom_rule_body(),
            headers=_auth(bob_token),
        )
        assert put_resp.status_code == 403

    def test_slug_mismatch_between_url_and_body_is_rejected(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/wrong-slug",
            json=_custom_rule_body(slug="no-todo"),
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_CUSTOM_GUARDRAIL"

    def test_invalid_rule_is_rejected_by_the_guardrails_service_check(self, client):
        """The guardrails service (via FakeGuardrailsClient here) is the
        single source of truth for whether a rule is well-formed — this
        app never re-implements that check itself."""
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        client.app.state.guardrails_client._validate_error = "bad kind"

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails/no-todo",
            json=_custom_rule_body(),
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "INVALID_CUSTOM_GUARDRAIL"

    def test_non_member_gets_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        outsider_token = _sign_in(client, "outsider-token")

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/custom-guardrails", headers=_auth(outsider_token)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "TENANT_NOT_FOUND"


class TestRepoLinks:
    def test_admin_can_create_list_and_delete_a_link(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        create_resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/repo-links",
            json={"skillId": "acme.tool.x", "repoUrl": "https://github.com/acme/tool-x"},
            headers=_auth(admin_token),
        )
        assert create_resp.status_code == 200, create_resp.text
        assert create_resp.json()["skillId"] == "acme.tool.x"

        list_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/repo-links", headers=_auth(admin_token)
        )
        assert [r["skillId"] for r in list_resp.json()] == ["acme.tool.x"]

        delete_resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/repo-links/acme.tool.x", headers=_auth(admin_token)
        )
        assert delete_resp.status_code == 204

        assert (
            client.get(
                f"/api/v1/tenants/{tenant['id']}/repo-links", headers=_auth(admin_token)
            ).json()
            == []
        )

    def test_member_can_list_but_not_create(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        list_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/repo-links", headers=_auth(bob_token)
        )
        assert list_resp.status_code == 200

        create_resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/repo-links",
            json={"skillId": "acme.tool.x", "repoUrl": "https://github.com/acme/tool-x"},
            headers=_auth(bob_token),
        )
        assert create_resp.status_code == 403

    def test_delete_missing_link_is_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/repo-links/does-not-exist",
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "REPO_LINK_NOT_FOUND"

    def test_second_tenant_cannot_claim_an_already_linked_skill_id(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant_a = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        client.post(
            f"/api/v1/tenants/{tenant_a['id']}/repo-links",
            json={"skillId": "acme.tool.x", "repoUrl": "https://github.com/acme/tool-x"},
            headers=_auth(admin_token),
        )

        bob_token = _sign_in(client, "bob-token")
        tenant_b = client.post(
            "/api/v1/tenants", json={"name": "Bobco"}, headers=_auth(bob_token)
        ).json()
        resp = client.post(
            f"/api/v1/tenants/{tenant_b['id']}/repo-links",
            json={"skillId": "acme.tool.x", "repoUrl": "https://github.com/bob/steals-it"},
            headers=_auth(bob_token),
        )
        assert resp.status_code == 400

    def test_admin_can_create_with_and_update_release_branches(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        create_resp = client.post(
            f"/api/v1/tenants/{tenant['id']}/repo-links",
            json={
                "skillId": "acme.tool.x",
                "repoUrl": "https://github.com/acme/tool-x",
                "releaseBranches": ["main"],
            },
            headers=_auth(admin_token),
        )
        assert create_resp.json()["releaseBranches"] == ["main"]

        update_resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/repo-links/acme.tool.x",
            json={"releaseBranches": ["main", "staging"]},
            headers=_auth(admin_token),
        )
        assert update_resp.status_code == 200, update_resp.text
        assert sorted(update_resp.json()["releaseBranches"]) == ["main", "staging"]

    def test_member_cannot_update_release_branches(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        client.post(
            f"/api/v1/tenants/{tenant['id']}/repo-links",
            json={"skillId": "acme.tool.x", "repoUrl": "https://github.com/acme/tool-x"},
            headers=_auth(admin_token),
        )
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/repo-links/acme.tool.x",
            json={"releaseBranches": ["staging"]},
            headers=_auth(bob_token),
        )
        assert resp.status_code == 403

    def test_update_missing_link_is_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/repo-links/does-not-exist",
            json={"releaseBranches": ["main"]},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "REPO_LINK_NOT_FOUND"

    def test_tenant_b_cannot_update_tenant_as_link_via_its_own_admin_token(self, client):
        """The isolation case the user asked to double-check: tenant B's
        admin, hitting the PUT endpoint under tenant B's own id, must not
        be able to reach or mutate a skill id linked to tenant A — the
        route resolves the link by (tenant_id_from_path, skill_id), so it
        simply finds nothing rather than leaking or touching tenant A's
        row."""
        admin_token = _sign_in(client, "alice-token")
        tenant_a = client.post(
            "/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token)
        ).json()
        client.post(
            f"/api/v1/tenants/{tenant_a['id']}/repo-links",
            json={
                "skillId": "acme.tool.x",
                "repoUrl": "https://github.com/acme/tool-x",
                "releaseBranches": ["main"],
            },
            headers=_auth(admin_token),
        )

        bob_token = _sign_in(client, "bob-token")
        tenant_b = client.post(
            "/api/v1/tenants", json={"name": "Bobco"}, headers=_auth(bob_token)
        ).json()

        resp = client.put(
            f"/api/v1/tenants/{tenant_b['id']}/repo-links/acme.tool.x",
            json={"releaseBranches": ["evil"]},
            headers=_auth(bob_token),
        )
        assert resp.status_code == 404

        unchanged = client.get(
            f"/api/v1/tenants/{tenant_a['id']}/repo-links", headers=_auth(admin_token)
        ).json()
        assert unchanged[0]["releaseBranches"] == ["main"]
