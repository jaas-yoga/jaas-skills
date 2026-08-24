"""ui-implementation-plan.md Phase 2: visibility filtering + sharing endpoints
exercised over real HTTP requests, not just the underlying functions."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authn.models import TenantRole
from jaas_registry.authn.tenants import MembershipStore
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id="acme.text.public",
            category="nlp",
            version="1.0.0",
            visibility=Visibility.PUBLIC,
            owner_user="usr_owner",
            owner_tenant="tnt_owner",
        )
    )
    index.put(
        make_entry(
            id="acme.text.private",
            category="nlp",
            version="1.0.0",
            visibility=Visibility.PRIVATE,
            owner_user="usr_owner",
            owner_tenant="tnt_owner",
            permissions=("fs:read",),
        )
    )
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path, policy_dir=tmp_path / "policy")
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    test_client = TestClient(app)
    test_client.policy_dir = settings.policy_dir  # for tests needing raw store access
    return test_client


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestSearchVisibility:
    def test_anonymous_search_only_returns_public_skill(self, client):
        resp = client.get("/api/v1/skills")
        ids = [i["id"] for i in resp.json()["items"]]
        assert ids == ["acme.text.public"]

    def test_owning_tenant_member_sees_both_skills(self, client):
        token = make_token(subject="usr_owner", tenant="tnt_owner")
        resp = client.get("/api/v1/skills", headers=_auth(token))
        ids = {i["id"] for i in resp.json()["items"]}
        assert ids == {"acme.text.public", "acme.text.private"}

    def test_unrelated_authenticated_user_only_sees_public_skill(self, client):
        token = make_token(subject="usr_other", tenant="tnt_other")
        resp = client.get("/api/v1/skills", headers=_auth(token))
        ids = [i["id"] for i in resp.json()["items"]]
        assert ids == ["acme.text.public"]

    def test_garbage_bearer_token_degrades_to_anonymous_not_a_500(self, client):
        resp = client.get("/api/v1/skills", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 200
        assert [i["id"] for i in resp.json()["items"]] == ["acme.text.public"]


class TestMetadataVisibility:
    def test_unrelated_user_gets_404_not_403_for_a_private_skill(self, client):
        token = make_token(subject="usr_other", tenant="tnt_other")
        resp = client.get(
            "/api/v1/skills/acme.text.private/versions/1.0.0", headers=_auth(token)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "SKILL_NOT_FOUND"

    def test_anonymous_gets_404_for_a_private_skill(self, client):
        resp = client.get("/api/v1/skills/acme.text.private/versions/1.0.0")
        assert resp.status_code == 404

    def test_owner_can_fetch_the_private_skills_metadata(self, client):
        token = make_token(subject="usr_owner", tenant="tnt_owner")
        resp = client.get(
            "/api/v1/skills/acme.text.private/versions/1.0.0", headers=_auth(token)
        )
        assert resp.status_code == 200


class TestShareGrantEndpoints:
    def _owner_token(self):
        return make_token(subject="usr_owner", tenant="tnt_owner", scopes=("skills:share",))

    def test_owner_can_create_list_and_revoke_a_grant(self, client):
        owner_token = self._owner_token()

        create_resp = client.post(
            "/api/v1/skills/acme.text.private/shares",
            headers=_auth(owner_token),
            json={"granteeType": "user", "granteeId": "usr_grantee", "permission": "read"},
        )
        assert create_resp.status_code == 200
        grant = create_resp.json()
        assert grant["granteeId"] == "usr_grantee"

        list_resp = client.get(
            "/api/v1/skills/acme.text.private/shares", headers=_auth(owner_token)
        )
        assert [g["id"] for g in list_resp.json()] == [grant["id"]]

        # the grantee can now see the previously-invisible private skill
        grantee_token = make_token(subject="usr_grantee", tenant="tnt_grantee")
        search_resp = client.get("/api/v1/skills", headers=_auth(grantee_token))
        assert "acme.text.private" in {i["id"] for i in search_resp.json()["items"]}

        revoke_resp = client.delete(
            f"/api/v1/skills/acme.text.private/shares/{grant['id']}", headers=_auth(owner_token)
        )
        assert revoke_resp.status_code == 204

        # revocation takes effect immediately
        search_resp_after = client.get("/api/v1/skills", headers=_auth(grantee_token))
        assert "acme.text.private" not in {i["id"] for i in search_resp_after.json()["items"]}

    def test_non_owner_with_the_right_scope_cannot_manage_a_skill_they_dont_own(self, client):
        other_token = make_token(subject="usr_other", tenant="tnt_other", scopes=("skills:share",))

        resp = client.post(
            "/api/v1/skills/acme.text.private/shares",
            headers=_auth(other_token),
            json={"granteeType": "user", "granteeId": "usr_grantee", "permission": "read"},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_missing_scope_is_rejected_before_the_ownership_check(self, client):
        owner_without_scope = make_token(subject="usr_owner", tenant="tnt_owner", scopes=())

        resp = client.post(
            "/api/v1/skills/acme.text.private/shares",
            headers=_auth(owner_without_scope),
            json={"granteeType": "user", "granteeId": "usr_grantee", "permission": "read"},
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_sharing_on_an_unknown_skill_is_404(self, client):
        resp = client.get(
            "/api/v1/skills/no.such.skill/shares", headers=_auth(self._owner_token())
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "SKILL_NOT_FOUND"

    def test_tenant_admin_can_manage_sharing_without_being_the_owner_user(self, client):
        # usr_admin is a *different* user than usr_owner (the skill's actual owner_user),
        # but is registered as an admin of tnt_owner (the skill's owner_tenant).
        MembershipStore(client.policy_dir).add(
            tenant_id="tnt_owner", user_id="usr_admin", role=TenantRole.ADMIN
        )
        admin_token = make_token(subject="usr_admin", tenant="tnt_owner", scopes=("skills:share",))

        resp = client.post(
            "/api/v1/skills/acme.text.private/shares",
            headers=_auth(admin_token),
            json={"granteeType": "user", "granteeId": "usr_grantee", "permission": "read"},
        )

        assert resp.status_code == 200
