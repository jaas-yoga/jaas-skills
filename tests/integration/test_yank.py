"""IMPLEMENTATION_PLAN.md Phase 1.3: reversible version-yank endpoints,
exercised over real HTTP requests. Authorization mirrors test_api_sharing.py's
TestShareGrantEndpoints exactly — yank reuses the same owner-or-tenant-admin
guard as /shares, just with the skills:write scope instead of skills:share."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authn.models import TenantRole
from jaas_registry.authn.tenants import MembershipStore
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.index.models import ArtifactStatus, Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id="acme.text.summarizer",
            version="1.0.0",
            visibility=Visibility.PUBLIC,
            owner_user="usr_owner",
            owner_tenant="tnt_owner",
        )
    )
    index.put(
        make_entry(
            id="acme.text.summarizer",
            version="1.1.0",
            visibility=Visibility.PUBLIC,
            owner_user="usr_owner",
            owner_tenant="tnt_owner",
        )
    )
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path, policy_dir=tmp_path / "policy")
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    test_client = TestClient(app)
    test_client.jaas_index = index
    test_client.policy_dir = settings.policy_dir
    return test_client


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _owner_token():
    return make_token(subject="usr_owner", tenant="tnt_owner", scopes=("skills:write",))


class TestYankEndpoint:
    def test_owner_can_yank_a_version(self, client):
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=_auth(_owner_token()),
            json={"reason": "CVE-2026-1234"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "yanked"
        assert body["reason"] == "CVE-2026-1234"
        assert body["actor"] == "usr_owner"

        entry = client.jaas_index.get("acme.text.summarizer", "1.1.0")
        assert entry.status == ArtifactStatus.YANKED

    def test_yanking_is_idempotent_on_an_already_yanked_version(self, client):
        headers = _auth(_owner_token())
        first = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=headers,
            json={"reason": "first reason"},
        )
        second = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=headers,
            json={"reason": "second reason"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["reason"] == "second reason"

    def test_yanking_an_unknown_version_is_404(self, client):
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/9.9.9/yank",
            headers=_auth(_owner_token()),
            json={},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "VERSION_NOT_FOUND"

    def test_yanking_an_unknown_skill_is_404(self, client):
        resp = client.post(
            "/api/v1/skills/no.such.skill/versions/1.0.0/yank",
            headers=_auth(_owner_token()),
            json={},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "SKILL_NOT_FOUND"

    def test_non_owner_with_the_right_scope_cannot_yank_a_skill_they_dont_own(self, client):
        other_token = make_token(subject="usr_other", tenant="tnt_other", scopes=("skills:write",))
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=_auth(other_token),
            json={},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_missing_scope_is_rejected_before_the_ownership_check(self, client):
        owner_without_scope = make_token(subject="usr_owner", tenant="tnt_owner", scopes=())
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=_auth(owner_without_scope),
            json={},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "UNAUTHORIZED"

    def test_tenant_admin_can_yank_without_being_the_owner_user(self, client):
        MembershipStore(client.policy_dir).add(
            tenant_id="tnt_owner", user_id="usr_admin", role=TenantRole.ADMIN
        )
        admin_token = make_token(subject="usr_admin", tenant="tnt_owner", scopes=("skills:write",))
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=_auth(admin_token),
            json={},
        )
        assert resp.status_code == 200

    def test_yank_status_survives_even_when_every_version_of_the_skill_is_yanked(self, client):
        """Regression guard: the ownership lookup inside the auth guard must
        not itself depend on get_resolved() finding a non-yanked version —
        yanking the *last* remaining active version must not lock out the
        very next yank/unyank call on that skill."""
        headers = _auth(_owner_token())
        client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.0.0/yank", headers=headers, json={}
        )
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank", headers=headers, json={}
        )
        assert resp.status_code == 200


class TestUnyankEndpoint:
    def test_owner_can_unyank_a_yanked_version(self, client):
        headers = _auth(_owner_token())
        client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank", headers=headers, json={}
        )
        resp = client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/unyank", headers=headers, json={}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        entry = client.jaas_index.get("acme.text.summarizer", "1.1.0")
        assert entry.status == ArtifactStatus.ACTIVE

    def test_unyanked_version_is_resolvable_again_by_latest(self, client):
        headers = _auth(_owner_token())
        client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank", headers=headers, json={}
        )
        assert (
            client.get("/api/v1/skills/acme.text.summarizer/versions/1.0.0").json()["version"]
            == "1.0.0"
        )
        client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/unyank", headers=headers, json={}
        )
        resolved = client.jaas_index.get_resolved("acme.text.summarizer", None)
        assert resolved.version == "1.1.0"


class TestYankAffectsResolutionAndMetadata:
    def test_search_no_longer_surfaces_a_yanked_version_as_the_resolved_one(self, client):
        client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=_auth(_owner_token()),
            json={},
        )
        resp = client.get("/api/v1/skills", params={"query": "summarizer"})
        item = next(i for i in resp.json()["items"] if i["id"] == "acme.text.summarizer")
        assert item["version"] == "1.0.0"

    def test_metadata_for_a_yanked_version_is_still_directly_reachable_and_flagged(self, client):
        client.post(
            "/api/v1/skills/acme.text.summarizer/versions/1.1.0/yank",
            headers=_auth(_owner_token()),
            json={"reason": "broken"},
        )
        resp = client.get("/api/v1/skills/acme.text.summarizer/versions/1.1.0")
        assert resp.status_code == 200
        assert resp.json()["status"] == "yanked"

    def test_metadata_for_an_untouched_version_reports_active(self, client):
        resp = client.get("/api/v1/skills/acme.text.summarizer/versions/1.0.0")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
