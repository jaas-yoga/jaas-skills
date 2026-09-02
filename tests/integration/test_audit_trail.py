"""IMPLEMENTATION_PLAN.md Phase 3.3: yank and share-grant changes are now
audited, durably, via common/audit_store.py::FileAuditSink. Authorization
setup mirrors test_yank.py/test_api_sharing.py exactly."""

import json

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
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(
        storage_root=tmp_path, policy_dir=tmp_path / "policy", audit_dir=tmp_path / "audit"
    )
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)
    return {"client": TestClient(app), "settings": settings}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _owner_token(scopes: tuple[str, ...]) -> str:
    return make_token(subject="usr_owner", tenant="tnt_owner", scopes=scopes)


def _audit_lines(settings) -> list[dict]:
    path = settings.audit_dir / "audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


class TestYankAuditTrail:
    def test_yank_writes_a_durable_audit_record(self, system):
        resp = system["client"].post(
            f"/api/v1/skills/{SKILL_ID}/versions/1.0.0/yank",
            headers=_auth(_owner_token(("skills:write",))),
            json={"reason": "security issue"},
        )
        assert resp.status_code == 200

        records = [r for r in _audit_lines(system["settings"]) if r["event_type"] == "yank"]
        assert len(records) == 1
        assert records[0]["skill_id"] == SKILL_ID
        assert records[0]["action"] == "yanked"
        assert records[0]["reason"] == "security issue"
        assert records[0]["actor"] == "usr_owner"

    def test_unyank_writes_a_separate_audit_record(self, system):
        headers = _auth(_owner_token(("skills:write",)))
        system["client"].post(
            f"/api/v1/skills/{SKILL_ID}/versions/1.0.0/yank", headers=headers, json={"reason": None}
        )
        resp = system["client"].post(
            f"/api/v1/skills/{SKILL_ID}/versions/1.0.0/unyank",
            headers=headers,
            json={"reason": None},
        )
        assert resp.status_code == 200

        records = [r for r in _audit_lines(system["settings"]) if r["event_type"] == "yank"]
        assert [r["action"] for r in records] == ["yanked", "unyanked"]


class TestShareGrantAuditTrail:
    def test_create_share_writes_a_durable_audit_record(self, system):
        resp = system["client"].post(
            f"/api/v1/skills/{SKILL_ID}/shares",
            headers=_auth(_owner_token(("skills:share",))),
            json={"granteeType": "user", "granteeId": "bob@acme.com", "permission": "read"},
        )
        assert resp.status_code == 200
        grant_id = resp.json()["id"]

        records = [
            r for r in _audit_lines(system["settings"]) if r["event_type"] == "share_grant_change"
        ]
        assert len(records) == 1
        assert records[0]["grant_id"] == grant_id
        assert records[0]["action"] == "granted"
        assert records[0]["grantee_id"] == "bob@acme.com"
        assert records[0]["actor"] == "usr_owner"

    def test_revoke_share_writes_a_durable_audit_record(self, system):
        headers = _auth(_owner_token(("skills:share",)))
        create_resp = system["client"].post(
            f"/api/v1/skills/{SKILL_ID}/shares",
            headers=headers,
            json={"granteeType": "user", "granteeId": "bob@acme.com", "permission": "read"},
        )
        grant_id = create_resp.json()["id"]

        resp = system["client"].delete(
            f"/api/v1/skills/{SKILL_ID}/shares/{grant_id}", headers=headers
        )
        assert resp.status_code == 204

        records = [
            r for r in _audit_lines(system["settings"]) if r["event_type"] == "share_grant_change"
        ]
        assert [r["action"] for r in records] == ["granted", "revoked"]
