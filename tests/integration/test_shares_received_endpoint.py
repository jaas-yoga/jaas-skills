"""IMPLEMENTATION_PLAN.md Phase 3.4: GET /shares/received — the frontend
half of ui-design.md's "shared with me" case (sharing/grants.py's
GrantStore.list_for_grantee, previously built but never exposed by any
route). Matches grants made directly to the caller's user id, and grants
made to the caller's tenant."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.sharing.models import GranteeType, SharePermission
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


@pytest.fixture
def system(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id="acme.text.summarizer",
            name="Summarizer",
            category="nlp",
            version="1.0.0",
            visibility=Visibility.PRIVATE,
            owner_user="usr_owner",
            owner_tenant="tnt_owner",
        )
    )
    index.put(
        make_entry(
            id="acme.text.other",
            name="Other Skill",
            category="text",
            version="1.0.0",
            visibility=Visibility.PRIVATE,
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
    client = TestClient(app)

    grants = app.state.grant_store
    grants.create(
        skill_id="acme.text.summarizer",
        grantee_type=GranteeType.USER,
        grantee_id="usr_bob",
        permission=SharePermission.READ,
        granted_by="usr_owner",
    )
    grants.create(
        skill_id="acme.text.other",
        grantee_type=GranteeType.TENANT,
        grantee_id="tnt_bob",
        permission=SharePermission.READ_WRITE,
        granted_by="usr_owner",
    )
    return {"client": client}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestSharesReceived:
    def test_sees_grants_made_directly_to_the_user(self, system):
        token = make_token(subject="usr_bob", tenant="tnt_bob", scopes=())
        resp = system["client"].get("/api/v1/shares/received", headers=_auth(token))

        assert resp.status_code == 200
        skill_ids = {r["skillId"] for r in resp.json()}
        assert "acme.text.summarizer" in skill_ids

    def test_sees_grants_made_to_the_users_tenant(self, system):
        token = make_token(subject="usr_bob", tenant="tnt_bob", scopes=())
        resp = system["client"].get("/api/v1/shares/received", headers=_auth(token))

        skill_ids = {r["skillId"] for r in resp.json()}
        assert "acme.text.other" in skill_ids

    def test_response_is_enriched_with_skill_name_and_category(self, system):
        token = make_token(subject="usr_bob", tenant="tnt_bob", scopes=())
        resp = system["client"].get("/api/v1/shares/received", headers=_auth(token))

        by_skill = {r["skillId"]: r for r in resp.json()}
        assert by_skill["acme.text.summarizer"]["skillName"] == "Summarizer"
        assert by_skill["acme.text.summarizer"]["skillCategory"] == "nlp"

    def test_unrelated_user_sees_no_grants(self, system):
        token = make_token(subject="usr_carol", tenant="tnt_carol", scopes=())
        resp = system["client"].get("/api/v1/shares/received", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json() == []

    def test_unauthenticated_request_is_rejected(self, system):
        resp = system["client"].get("/api/v1/shares/received")
        assert resp.status_code == 403
