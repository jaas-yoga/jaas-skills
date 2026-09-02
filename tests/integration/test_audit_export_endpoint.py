"""IMPLEMENTATION_PLAN.md Phase 3.3: GET /tenants/{id}/audit-export —
tenant-admin-only, scoped to that tenant's own audit records. Publish/
yank/share-grant events carry no tenant_id directly (common/audit.py), so
scoping for those is derived from the referenced skill's *current*
owner_tenant in the index; custom-guardrail-rule and GitHub-connection
events already carry tenant_id explicitly."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authn.models import TenantRole
from jaas_registry.authn.tenants import MembershipStore
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.audit import (
    new_custom_guardrail_rule_event,
    new_github_connection_event,
    new_publish_event,
    new_share_grant_event,
    new_yank_event,
)
from jaas_registry.common.audit_store import FileAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token


@pytest.fixture
def system(tmp_path):
    index = InMemoryIndex()
    index.put(
        make_entry(
            id="acme.text.summarizer",
            version="1.0.0",
            visibility=Visibility.PUBLIC,
            owner_user="usr_a",
            owner_tenant="tnt_a",
        )
    )
    index.put(
        make_entry(
            id="beta.text.other",
            version="1.0.0",
            visibility=Visibility.PUBLIC,
            owner_user="usr_b",
            owner_tenant="tnt_b",
        )
    )
    store = LocalFilesystemStore(tmp_path)
    settings = Settings(storage_root=tmp_path, policy_dir=tmp_path / "policy")
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    membership_store = MembershipStore(settings.policy_dir)
    membership_store.add(tenant_id="tnt_a", user_id="usr_a", role=TenantRole.ADMIN)
    membership_store.add(tenant_id="tnt_b", user_id="usr_b", role=TenantRole.ADMIN)
    app = create_app(index=index, store=store, settings=settings, authorizer=authorizer)

    sink = FileAuditSink(settings.audit_dir)
    sink.emit(
        new_publish_event(
            actor="usr_a", skill_id="acme.text.summarizer", version="1.0.0", digest="sha256:a"
        )
    )
    sink.emit(
        new_publish_event(
            actor="usr_b", skill_id="beta.text.other", version="1.0.0", digest="sha256:b"
        )
    )
    sink.emit_yank(
        new_yank_event(
            actor="usr_a",
            skill_id="acme.text.summarizer",
            version="1.0.0",
            action="yanked",
            reason="cve",
        )
    )
    sink.emit_share_grant_change(
        new_share_grant_event(
            actor="usr_b",
            skill_id="beta.text.other",
            grant_id="g1",
            grantee_type="user",
            grantee_id="carol",
            permission="read",
            action="granted",
        )
    )
    sink.emit_custom_guardrail_change(
        new_custom_guardrail_rule_event(
            actor="usr_a", tenant_id="tnt_a", rule_id="r1", action="created"
        )
    )
    sink.emit_custom_guardrail_change(
        new_custom_guardrail_rule_event(
            actor="usr_b", tenant_id="tnt_b", rule_id="r2", action="created"
        )
    )
    sink.emit_github_connection_change(
        new_github_connection_event(
            actor="usr_a", tenant_id="tnt_a", github_login="a", action="connected"
        )
    )

    return {"client": TestClient(app)}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_token(user_id: str, tenant: str):
    return make_token(subject=user_id, tenant=tenant, scopes=("skills:write",))


class TestAuditExport:
    def test_admin_sees_only_their_tenants_events(self, system):
        resp = system["client"].get(
            "/api/v1/tenants/tnt_a/audit-export", headers=_auth(_admin_token("usr_a", "tnt_a"))
        )
        assert resp.status_code == 200
        records = resp.json()

        event_types = sorted(r["event_type"] for r in records)
        assert event_types == [
            "custom_guardrail_change",
            "github_connection_change",
            "publish",
            "yank",
        ]
        assert all(
            r.get("tenant_id") == "tnt_a" or r.get("skill_id") == "acme.text.summarizer"
            for r in records
        )

    def test_other_tenants_events_are_excluded(self, system):
        resp = system["client"].get(
            "/api/v1/tenants/tnt_a/audit-export", headers=_auth(_admin_token("usr_a", "tnt_a"))
        )
        records = resp.json()

        assert not any(r.get("skill_id") == "beta.text.other" for r in records)
        assert not any(r.get("tenant_id") == "tnt_b" for r in records)

    def test_non_admin_member_cannot_export(self, system):
        member_token = make_token(subject="usr_member", tenant="tnt_a", scopes=("skills:write",))
        MembershipStore(system["client"].app.state.settings.policy_dir).add(
            tenant_id="tnt_a", user_id="usr_member", role=TenantRole.MEMBER
        )
        resp = system["client"].get(
            "/api/v1/tenants/tnt_a/audit-export", headers=_auth(member_token)
        )
        assert resp.status_code == 403

    def test_unauthenticated_request_is_rejected(self, system):
        resp = system["client"].get("/api/v1/tenants/tnt_a/audit-export")
        assert resp.status_code == 403
