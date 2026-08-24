"""ui-implementation-plan.md Phase 2 exit criterion 5: permission-matrix
coverage across {public, private} x {no grant, user grant, tenant grant} x
{owner, grantee, unrelated user}.
"""

import pytest

from rune_registry.authn.models import TenantRole
from rune_registry.authn.pat import PatStore
from rune_registry.authn.tenants import MembershipStore
from rune_registry.common.config import Settings
from rune_registry.index.models import Visibility
from rune_registry.sharing.access import (
    ANONYMOUS,
    CallerContext,
    can_manage_sharing,
    can_view,
    resolve_caller_context,
)
from rune_registry.sharing.grants import GrantStore
from rune_registry.sharing.models import GranteeType, SharePermission
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token

OWNER = CallerContext(user_id="usr_owner", tenant_id="tnt_owner")
GRANTEE_USER = CallerContext(user_id="usr_grantee", tenant_id="tnt_other")
GRANTEE_TENANT_MEMBER = CallerContext(user_id="usr_member", tenant_id="tnt_grantee")
UNRELATED = CallerContext(user_id="usr_unrelated", tenant_id="tnt_unrelated")


def _entry(visibility: Visibility):
    return make_entry(owner_user="usr_owner", owner_tenant="tnt_owner", visibility=visibility)


class TestPublicVisibility:
    def test_anyone_can_view_a_public_skill(self):
        entry = _entry(Visibility.PUBLIC)
        for caller in (ANONYMOUS, OWNER, UNRELATED):
            assert can_view(entry, caller=caller) is True


class TestPrivateVisibilityNoGrant:
    def test_anonymous_cannot_view(self):
        entry = _entry(Visibility.PRIVATE)
        assert can_view(entry, caller=ANONYMOUS) is False

    def test_owning_tenant_member_can_view(self):
        entry = _entry(Visibility.PRIVATE)
        assert can_view(entry, caller=OWNER) is True

    def test_unrelated_user_cannot_view(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)  # empty
        assert can_view(entry, caller=UNRELATED, grants=grants) is False


class TestPrivateVisibilityWithUserGrant:
    def test_the_granted_user_can_view(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id=entry.id,
            grantee_type=GranteeType.USER,
            grantee_id="usr_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        assert can_view(entry, caller=GRANTEE_USER, grants=grants) is True

    def test_no_one_else_in_the_grantees_tenant_gains_access(self, tmp_path):
        """A user-level grant is scoped to exactly that user, not their tenant."""
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id=entry.id,
            grantee_type=GranteeType.USER,
            grantee_id="usr_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        other_member_of_same_tenant = CallerContext(user_id="usr_other", tenant_id="tnt_other")
        assert can_view(entry, caller=other_member_of_same_tenant, grants=grants) is False

    def test_unrelated_user_still_cannot_view(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id=entry.id,
            grantee_type=GranteeType.USER,
            grantee_id="usr_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        assert can_view(entry, caller=UNRELATED, grants=grants) is False


class TestPrivateVisibilityWithTenantGrant:
    def test_any_member_of_the_granted_tenant_can_view(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id=entry.id,
            grantee_type=GranteeType.TENANT,
            grantee_id="tnt_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        assert can_view(entry, caller=GRANTEE_TENANT_MEMBER, grants=grants) is True

    def test_unrelated_user_still_cannot_view(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)
        grants.create(
            skill_id=entry.id,
            grantee_type=GranteeType.TENANT,
            grantee_id="tnt_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        assert can_view(entry, caller=UNRELATED, grants=grants) is False


class TestRevocation:
    def test_revoking_a_grant_immediately_removes_visibility(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        grants = GrantStore(tmp_path)
        grant = grants.create(
            skill_id=entry.id,
            grantee_type=GranteeType.USER,
            grantee_id="usr_grantee",
            permission=SharePermission.READ,
            granted_by="usr_owner",
        )
        assert can_view(entry, caller=GRANTEE_USER, grants=grants) is True

        grants.revoke(skill_id=entry.id, grant_id=grant.id)

        assert can_view(entry, caller=GRANTEE_USER, grants=grants) is False


class TestCanManageSharing:
    def test_owner_can_manage_sharing(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        memberships = MembershipStore(tmp_path)  # owner check short-circuits before touching this
        assert can_manage_sharing(entry, caller=OWNER, memberships=memberships) is True

    def test_tenant_admin_can_manage_sharing(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        memberships = MembershipStore(tmp_path)
        memberships.add(tenant_id="tnt_owner", user_id="usr_admin", role=TenantRole.ADMIN)
        admin_caller = CallerContext(user_id="usr_admin", tenant_id="tnt_owner")

        assert can_manage_sharing(entry, caller=admin_caller, memberships=memberships) is True

    def test_tenant_member_without_admin_role_cannot_manage_sharing(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        memberships = MembershipStore(tmp_path)
        memberships.add(tenant_id="tnt_owner", user_id="usr_member", role=TenantRole.MEMBER)
        member_caller = CallerContext(user_id="usr_member", tenant_id="tnt_owner")

        assert can_manage_sharing(entry, caller=member_caller, memberships=memberships) is False

    def test_unrelated_user_cannot_manage_sharing(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        memberships = MembershipStore(tmp_path)
        assert can_manage_sharing(entry, caller=UNRELATED, memberships=memberships) is False

    def test_anonymous_cannot_manage_sharing(self, tmp_path):
        entry = _entry(Visibility.PRIVATE)
        memberships = MembershipStore(tmp_path)
        assert can_manage_sharing(entry, caller=ANONYMOUS, memberships=memberships) is False


class TestResolveCallerContext:
    @pytest.fixture
    def settings(self):
        return Settings(
            jwt_secret=DEFAULT_SECRET, jwt_issuer=DEFAULT_ISSUER, jwt_audience=DEFAULT_AUDIENCE
        )

    def test_no_token_is_anonymous(self, settings):
        assert resolve_caller_context(None, settings=settings) == ANONYMOUS

    def test_valid_token_resolves_identity(self, settings):
        token = make_token(subject="usr_1", tenant="tnt_1")
        caller = resolve_caller_context(token, settings=settings)
        assert caller == CallerContext(user_id="usr_1", tenant_id="tnt_1")

    def test_garbage_token_degrades_to_anonymous_not_an_error(self, settings):
        assert resolve_caller_context("not-a-real-jwt", settings=settings) == ANONYMOUS

    def test_expired_token_degrades_to_anonymous(self, settings):
        token = make_token(subject="usr_1", expires_in=-10)
        assert resolve_caller_context(token, settings=settings) == ANONYMOUS

    def test_token_for_a_different_secret_degrades_to_anonymous(self, settings):
        token = make_token(subject="usr_1", secret="a-completely-different-secret-32-bytes!")
        assert resolve_caller_context(token, settings=settings) == ANONYMOUS

    def test_active_pat_resolves_identity(self, settings, tmp_path):
        pat_store = PatStore(tmp_path)
        pat = pat_store.create(owner_user="usr_1", name="laptop", ttl_seconds=3600)
        token = make_token(subject="usr_1", tenant="tnt_1", pat_id=pat.id)

        caller = resolve_caller_context(token, settings=settings, pat_store=pat_store)

        assert caller == CallerContext(user_id="usr_1", tenant_id="tnt_1")

    def test_revoked_pat_degrades_to_anonymous(self, settings, tmp_path):
        pat_store = PatStore(tmp_path)
        pat = pat_store.create(owner_user="usr_1", name="laptop", ttl_seconds=3600)
        pat_store.revoke(pat_id=pat.id, owner_user="usr_1")
        token = make_token(subject="usr_1", pat_id=pat.id)

        assert resolve_caller_context(token, settings=settings, pat_store=pat_store) == ANONYMOUS
