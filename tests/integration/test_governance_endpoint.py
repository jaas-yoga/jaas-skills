"""IMPLEMENTATION_PLAN.md Phase 3.3: PUT /skills/{id}/governance sets the
governance record; GET /skills/{id}/versions/{version} reflects it.
Authorization mirrors test_yank.py exactly, but with the skills:governance
scope instead of skills:write."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token

SKILL_ID = "acme.text.summarizer"


@pytest.fixture
def system(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id=SKILL_ID,
            version="1.0.0",
            visibility=Visibility.PUBLIC,
            owner_user="usr_owner",
            owner_tenant="tnt_owner",
        )
    )
    index.put(
        make_entry(
            id=SKILL_ID,
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
    return {"client": TestClient(app), "index": index}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _owner_token():
    return make_token(subject="usr_owner", tenant="tnt_owner", scopes=("skills:governance",))


def _outsider_token():
    return make_token(subject="usr_outsider", tenant="tnt_other", scopes=("skills:governance",))


class TestPutGovernance:
    def test_owner_can_set_governance_record(self, system):
        resp = system["client"].put(
            f"/api/v1/skills/{SKILL_ID}/governance",
            headers=_auth(_owner_token()),
            json={
                "businessPurpose": "Summarize customer support tickets",
                "systemsAccessed": ["zendesk", "s3"],
                "reviewDate": "2026-12-01",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["businessPurpose"] == "Summarize customer support tickets"
        assert body["systemsAccessed"] == ["zendesk", "s3"]
        assert body["reviewDate"] == "2026-12-01"
        assert body["updatedBy"] == "usr_owner"

    def test_governance_record_is_shared_across_all_versions(self, system):
        system["client"].put(
            f"/api/v1/skills/{SKILL_ID}/governance",
            headers=_auth(_owner_token()),
            json={"businessPurpose": "shared purpose", "systemsAccessed": [], "reviewDate": None},
        )

        entry_a = system["index"].get(SKILL_ID, "1.0.0")
        entry_b = system["index"].get(SKILL_ID, "1.1.0")
        assert entry_a.business_purpose == "shared purpose"
        assert entry_b.business_purpose == "shared purpose"

    def test_outsider_cannot_set_governance_record(self, system):
        resp = system["client"].put(
            f"/api/v1/skills/{SKILL_ID}/governance",
            headers=_auth(_outsider_token()),
            json={"businessPurpose": "hijack", "systemsAccessed": [], "reviewDate": None},
        )
        # JaasError(ErrorCode.UNAUTHORIZED, ...) maps to HTTP 403 in this
        # codebase, not literal 401 -- matches test_artifact_download.py's
        # test_download_unknown_token_is_401_style_unauthorized.
        assert resp.status_code == 403

    def test_unknown_skill_is_404(self, system):
        resp = system["client"].put(
            "/api/v1/skills/no.such.skill/governance",
            headers=_auth(_owner_token()),
            json={"businessPurpose": "x", "systemsAccessed": [], "reviewDate": None},
        )
        assert resp.status_code == 404


class TestMetadataReflectsGovernance:
    def test_get_skill_metadata_includes_governance_fields(self, system):
        system["client"].put(
            f"/api/v1/skills/{SKILL_ID}/governance",
            headers=_auth(_owner_token()),
            json={
                "businessPurpose": "Summarize tickets",
                "systemsAccessed": ["zendesk"],
                "reviewDate": "2026-12-01",
            },
        )

        resp = system["client"].get(f"/api/v1/skills/{SKILL_ID}/versions/1.0.0")

        assert resp.status_code == 200
        body = resp.json()
        assert body["businessPurpose"] == "Summarize tickets"
        assert body["systemsAccessed"] == ["zendesk"]
        assert body["governanceReviewDate"] == "2026-12-01"

    def test_metadata_defaults_are_none_and_empty_before_any_governance_update(self, system):
        resp = system["client"].get(f"/api/v1/skills/{SKILL_ID}/versions/1.0.0")

        assert resp.status_code == 200
        body = resp.json()
        assert body["businessPurpose"] is None
        assert body["systemsAccessed"] == []
        assert body["governanceReviewDate"] is None
