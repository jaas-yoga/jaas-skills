"""Tenant creation and membership management. ui-design.md §7, §10.6.

Distinct from auth_routes.py: that module is about *identity* (who is this
caller); this one is about *tenant administration* (who else belongs to a
tenant this caller is already in).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jaas_registry.api.deps import (
    AuthorizerDep,
    CustomGuardrailRuleStoreDep,
    GuardrailCatalogDep,
    GuardrailPolicyStoreDep,
    GuardrailsClientDep,
    IndexDep,
    InviteStoreDep,
    MembershipStoreDep,
    RepoLinkStoreDep,
    SettingsDep,
    TenantStoreDep,
    UserStoreDep,
)
from jaas_registry.api.schemas import (
    CreateTenantRequest,
    CustomGuardrailRuleRequest,
    CustomGuardrailRuleResponse,
    InviteMemberRequest,
    InviteMemberResponse,
    MemberResponse,
    RepoLinkRequest,
    RepoLinkResponse,
    TenantGuardrailPolicyRequest,
    TenantGuardrailPolicyResponse,
    TenantMembershipResponse,
    UpdateRepoLinkRequest,
    ValidateCustomGuardrailRuleResponse,
)
from jaas_registry.authn.models import TenantRole
from jaas_registry.authn.tenants import MembershipStore
from jaas_registry.authz.base import Authorizer
from jaas_registry.common.audit import new_custom_guardrail_rule_event
from jaas_registry.common.audit_store import FileAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.sharing.access import CallerContext, resolve_caller_context

router = APIRouter(prefix="/api/v1/tenants")
_bearer_scheme = HTTPBearer(auto_error=False)


def _require_caller(
    *, settings: Settings, authorizer: Authorizer, credentials: HTTPAuthorizationCredentials | None
) -> CallerContext:
    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=None,
        required_permissions=("skills:write",),
    )
    return resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )


def _require_membership(memberships: MembershipStore, tenant_id: str, caller: CallerContext):
    membership = memberships.get(tenant_id=tenant_id, user_id=caller.user_id or "")
    if membership is None:
        # 404, not 403 — same "don't confirm existence" posture as private
        # skills and other people's drafts.
        raise JaasError(ErrorCode.TENANT_NOT_FOUND, f"tenant '{tenant_id}' not found")
    return membership


def _require_admin(memberships: MembershipStore, tenant_id: str, caller: CallerContext):
    membership = _require_membership(memberships, tenant_id, caller)
    if membership.role is not TenantRole.ADMIN:
        raise JaasError(
            ErrorCode.UNAUTHORIZED, "only a tenant admin may manage its membership"
        )
    return membership


@router.post("", response_model=TenantMembershipResponse)
def create_tenant(
    body: CreateTenantRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    tenant_store: TenantStoreDep,
    membership_store: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> TenantMembershipResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    tenant = tenant_store.create(name=body.name)
    membership_store.add(tenant_id=tenant.id, user_id=caller.user_id or "", role=TenantRole.ADMIN)
    return TenantMembershipResponse(id=tenant.id, name=tenant.name, role=TenantRole.ADMIN.value)


@router.get("/{tenant_id}/members", response_model=list[MemberResponse])
def list_members(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    user_store: UserStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[MemberResponse]:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)

    members = []
    for membership in membership_store.list_for_tenant(tenant_id):
        user = user_store.get(membership.user_id)
        if user is None:
            continue  # pragma: no cover - defensive; membership always created for a real user
        members.append(
            MemberResponse(
                userId=user.id, email=user.email, name=user.name, role=membership.role.value
            )
        )
    return members


@router.post("/{tenant_id}/members", response_model=InviteMemberResponse)
def invite_member(
    tenant_id: str,
    body: InviteMemberRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    user_store: UserStoreDep,
    invite_store: InviteStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> InviteMemberResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    try:
        role = TenantRole(body.role)
    except ValueError as exc:
        raise JaasError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    normalized_email = body.email.strip().lower()
    existing_user = user_store.find_by_email(normalized_email)

    if existing_user is not None:
        if membership_store.get(tenant_id=tenant_id, user_id=existing_user.id) is not None:
            raise JaasError(
                ErrorCode.SCHEMA_VALIDATION_FAILED, f"{normalized_email} is already a member"
            )
        # Fast path: this person already has an account, so they can join
        # immediately — no need to wait for a future sign-in to resolve a
        # pending invite (ui-design.md §10.5).
        membership_store.add(tenant_id=tenant_id, user_id=existing_user.id, role=role)
        return InviteMemberResponse(email=normalized_email, role=role.value, status="added")

    # Not signed up yet: store a pending invite, resolved automatically on
    # this email's first Google sign-in (AuthService.sign_in_with_google).
    invite_store.create(
        tenant_id=tenant_id, email=normalized_email, role=role, invited_by=caller.user_id or ""
    )
    return InviteMemberResponse(email=normalized_email, role=role.value, status="pending")


@router.get("/{tenant_id}/guardrail-policy", response_model=TenantGuardrailPolicyResponse)
def get_guardrail_policy(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    guardrail_policy_store: GuardrailPolicyStoreDep,
    guardrail_catalog: GuardrailCatalogDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> TenantGuardrailPolicyResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)  # any member may view

    policy = guardrail_policy_store.get(tenant_id, guardrail_catalog)
    return TenantGuardrailPolicyResponse(
        tenantId=policy.tenant_id, enabledCheckIds=sorted(policy.enabled_check_ids)
    )


@router.put("/{tenant_id}/guardrail-policy", response_model=TenantGuardrailPolicyResponse)
def put_guardrail_policy(
    tenant_id: str,
    body: TenantGuardrailPolicyRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    guardrail_policy_store: GuardrailPolicyStoreDep,
    guardrail_catalog: GuardrailCatalogDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> TenantGuardrailPolicyResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)  # admin only, same 403 path as invite

    policy = guardrail_policy_store.put(
        tenant_id=tenant_id,
        enabled_check_ids=frozenset(body.enabledCheckIds),
        catalog=guardrail_catalog,
    )
    return TenantGuardrailPolicyResponse(
        tenantId=policy.tenant_id, enabledCheckIds=sorted(policy.enabled_check_ids)
    )


def _rule_to_response(rule) -> CustomGuardrailRuleResponse:
    return CustomGuardrailRuleResponse(
        id=rule.id,
        tenantId=rule.tenant_id,
        slug=rule.slug,
        name=rule.name,
        description=rule.description,
        category=rule.category,
        severity=rule.severity,
        standardRef=rule.standard_ref,
        kind=rule.kind,
        config=rule.config,
        createdBy=rule.created_by,
        createdAt=rule.created_at,
    )


@router.get(
    "/{tenant_id}/custom-guardrails", response_model=list[CustomGuardrailRuleResponse]
)
def list_custom_guardrail_rules(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    custom_rule_store: CustomGuardrailRuleStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[CustomGuardrailRuleResponse]:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)  # any member may view
    return [_rule_to_response(r) for r in custom_rule_store.list_for_tenant(tenant_id)]


@router.post(
    "/{tenant_id}/custom-guardrails/validate", response_model=ValidateCustomGuardrailRuleResponse
)
def validate_custom_guardrail_rule(
    tenant_id: str,
    body: CustomGuardrailRuleRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    guardrails_client: GuardrailsClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> ValidateCustomGuardrailRuleResponse:
    """Dry-run check only — never saved. Any member may call this (fast
    feedback while authoring a rule), not just an admin."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)

    error = guardrails_client.validate_rule(
        id=f"custom:{tenant_id}:{body.slug}",
        name=body.name,
        description=body.description,
        category=body.category,
        severity=body.severity,
        standard_ref=body.standardRef,
        kind=body.kind,
        config=body.config,
    )
    return ValidateCustomGuardrailRuleResponse(valid=error is None, error=error)


@router.put(
    "/{tenant_id}/custom-guardrails/{slug}", response_model=CustomGuardrailRuleResponse
)
def put_custom_guardrail_rule(
    tenant_id: str,
    slug: str,
    body: CustomGuardrailRuleRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    custom_rule_store: CustomGuardrailRuleStoreDep,
    guardrails_client: GuardrailsClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> CustomGuardrailRuleResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)  # admin only, same as guardrail-policy

    if slug != body.slug:
        raise JaasError(
            ErrorCode.INVALID_CUSTOM_GUARDRAIL, "slug in the URL and request body must match"
        )
    is_new = custom_rule_store.get(tenant_id, slug) is None

    # Single source of truth for "is this rule well-formed" lives in the
    # guardrails service (schema + kind + regex-compile check) — never
    # duplicated here. A rule is only ever persisted once it passes.
    error = guardrails_client.validate_rule(
        id=f"custom:{tenant_id}:{slug}",
        name=body.name,
        description=body.description,
        category=body.category,
        severity=body.severity,
        standard_ref=body.standardRef,
        kind=body.kind,
        config=body.config,
    )
    if error is not None:
        raise JaasError(ErrorCode.INVALID_CUSTOM_GUARDRAIL, error)

    rule = custom_rule_store.put(
        tenant_id=tenant_id,
        slug=slug,
        name=body.name,
        description=body.description,
        category=body.category,
        severity=body.severity,
        standard_ref=body.standardRef,
        kind=body.kind,
        config=body.config,
        created_by=caller.user_id or "",
    )
    FileAuditSink(settings.audit_dir).emit_custom_guardrail_change(
        new_custom_guardrail_rule_event(
            actor=caller.user_id or "",
            tenant_id=tenant_id,
            rule_id=rule.id,
            action="created" if is_new else "updated",
        )
    )
    return _rule_to_response(rule)


@router.delete("/{tenant_id}/custom-guardrails/{slug}", status_code=204)
def delete_custom_guardrail_rule(
    tenant_id: str,
    slug: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    custom_rule_store: CustomGuardrailRuleStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    found = custom_rule_store.delete(tenant_id, slug)
    if not found:
        raise JaasError(
            ErrorCode.CUSTOM_GUARDRAIL_NOT_FOUND, f"custom guardrail rule '{slug}' not found"
        )
    FileAuditSink(settings.audit_dir).emit_custom_guardrail_change(
        new_custom_guardrail_rule_event(
            actor=caller.user_id or "",
            tenant_id=tenant_id,
            rule_id=f"custom:{tenant_id}:{slug}",
            action="deleted",
        )
    )


def _repo_link_to_response(link) -> RepoLinkResponse:
    return RepoLinkResponse(
        id=link.id,
        tenantId=link.tenant_id,
        skillId=link.skill_id,
        repoUrl=link.repo_url,
        createdBy=link.created_by,
        createdAt=link.created_at,
        releaseBranches=list(link.release_branches),
    )


@router.get("/{tenant_id}/repo-links", response_model=list[RepoLinkResponse])
def list_repo_links(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    repo_link_store: RepoLinkStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[RepoLinkResponse]:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_membership(membership_store, tenant_id, caller)  # any member may view
    return [_repo_link_to_response(link) for link in repo_link_store.list_for_tenant(tenant_id)]


@router.post("/{tenant_id}/repo-links", response_model=RepoLinkResponse)
def create_repo_link(
    tenant_id: str,
    body: RepoLinkRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    repo_link_store: RepoLinkStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> RepoLinkResponse:
    """A tenant admin must register (skill id -> repo url) *before* CI can
    ever release under that skill id — see authn/repo_links.py's docstring
    for why this exists (anti-squatting). Same admin-only posture as
    inviting a member or editing guardrail policy."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    link = repo_link_store.create(
        tenant_id=tenant_id,
        skill_id=body.skillId,
        repo_url=body.repoUrl,
        created_by=caller.user_id or "",
        release_branches=tuple(body.releaseBranches),
    )
    return _repo_link_to_response(link)


@router.put("/{tenant_id}/repo-links/{skill_id}", response_model=RepoLinkResponse)
def update_repo_link(
    tenant_id: str,
    skill_id: str,
    body: UpdateRepoLinkRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    repo_link_store: RepoLinkStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> RepoLinkResponse:
    """Full-replace of the allowed release branches — same admin-only
    posture as every other repo-link write. Only ever touches a link this
    tenant already owns (RepoLinkStoreDep.get is tenant-scoped), so this
    can't be used to reach into another tenant's link."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    link = repo_link_store.update_release_branches(
        tenant_id=tenant_id, skill_id=skill_id, release_branches=tuple(body.releaseBranches)
    )
    return _repo_link_to_response(link)


@router.delete("/{tenant_id}/repo-links/{skill_id}", status_code=204)
def delete_repo_link(
    tenant_id: str,
    skill_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    repo_link_store: RepoLinkStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    found = repo_link_store.delete(tenant_id=tenant_id, skill_id=skill_id)
    if not found:
        raise JaasError(ErrorCode.REPO_LINK_NOT_FOUND, f"no repo link for skill id '{skill_id}'")


def _record_belongs_to_tenant(record: dict, *, tenant_id: str, index) -> bool:
    """PublishAuditEvent/YankAuditEvent/ShareGrantAuditEvent carry no
    tenant_id of their own (common/audit.py) — scope those by the
    referenced skill's *current* owner_tenant in the index instead.
    CustomGuardrailRuleAuditEvent/GitHubConnectionAuditEvent already carry
    tenant_id directly. A skill_id that no longer resolves to any version
    (shouldn't happen — publishing is immutable/append-only) is excluded
    rather than included, so a lookup failure can never leak a record into
    the wrong tenant's export."""
    if "tenant_id" in record:
        return bool(record["tenant_id"] == tenant_id)
    skill_id = record.get("skill_id")
    if skill_id is None:
        return False
    versions = index.list_versions(skill_id)
    if not versions:
        return False
    entry = index.get(skill_id, versions[-1])
    return entry is not None and entry.owner_tenant == tenant_id


@router.get("/{tenant_id}/audit-export")
def export_audit_trail(
    tenant_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    membership_store: MembershipStoreDep,
    index: IndexDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[dict]:
    """IMPLEMENTATION_PLAN.md Phase 3.3: durable audit records for this
    tenant, oldest first. Admin-only — an audit trail is itself sensitive
    (who did what, when), same tier as guardrail-policy/custom-guardrail-
    rule management. Records are heterogeneous by event_type (see
    common/audit.py's event dataclasses), so this deliberately returns raw
    dicts rather than a single fixed response_model."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_admin(membership_store, tenant_id, caller)

    all_records = FileAuditSink(settings.audit_dir).read_all()
    return [
        record
        for record in all_records
        if _record_belongs_to_tenant(record, tenant_id=tenant_id, index=index)
    ]
