"""Endpoints: search, metadata, artifact-token, artifact download. Design ref: design.md §5."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jaas_registry.api.deps import (
    AuthorizerDep,
    GitHubApiClientDep,
    GrantStoreDep,
    IndexDep,
    MembershipStoreDep,
    PatStoreDep,
    SettingsDep,
    StoreDep,
    TokenIssuerDep,
    TrustPolicyDep,
)
from jaas_registry.api.schemas import (
    ArtifactTokenResponse,
    CreateShareGrantRequest,
    FileContentResponse,
    GovernanceResponse,
    GovernanceUpdateRequest,
    OwnerResponse,
    PageMeta,
    ResolvedDependency,
    RuntimeCompatibilityResponse,
    SearchResponse,
    SearchResultItem,
    ShareGrantResponse,
    SkillMetadataResponse,
    SourceFilesResponse,
    YankRequest,
    YankResponse,
)
from jaas_registry.artifact.governance import (
    GovernanceRecord,
    apply_governance,
    write_governance,
)
from jaas_registry.artifact.packaging import extract_archive
from jaas_registry.artifact.sigstore_trust import load_sigstore_trust_policy
from jaas_registry.artifact.verify import verify_artifact
from jaas_registry.artifact.yank import YankRecord, write_status
from jaas_registry.authn.tenants import MembershipStore
from jaas_registry.authz.base import Authorizer
from jaas_registry.common.audit import new_share_grant_event, new_yank_event
from jaas_registry.common.audit_store import FileAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.drafts.git_sync import parse_github_repo_url
from jaas_registry.index.models import ArtifactStatus, IndexEntry
from jaas_registry.index.query import search as run_search
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.sharing.access import can_manage_sharing, can_view, resolve_caller_context
from jaas_registry.sharing.models import GranteeType, ShareGrant, SharePermission
from jaas_registry.storage.base import ObjectStore
from jaas_registry.storage.keys import blob_key

router = APIRouter(prefix="/api/v1")
_bearer_scheme = HTTPBearer(auto_error=False)


def _bearer_token(authorization: str | None) -> str | None:
    """Cheap manual parse for the two high-traffic, auth-optional endpoints
    (search, metadata) — HTTPBearer's async security-dependency machinery is
    real per-request overhead not worth paying where a bad/missing header is
    never an error, just a fallback to anonymous (design.md §9.1 SLOs;
    ui-design.md §5.4). Endpoints where auth is actually *required*
    (artifact-token, shares) keep using HTTPBearer for its stricter,
    documented scheme validation."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def _require_entry(index: InMemoryIndex, skill_id: str, version: str):
    entry = index.get_resolved(skill_id, version)
    if entry is not None:
        return entry
    if not index.list_versions(skill_id):
        raise JaasError(ErrorCode.SKILL_NOT_FOUND, f"skill '{skill_id}' not found")
    raise JaasError(ErrorCode.VERSION_NOT_FOUND, f"version '{version}' not found for '{skill_id}'")


@router.get("/skills", response_model=SearchResponse)
def search_skills(
    index: IndexDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    query: str | None = Query(default=None),
    runtime: str | None = Query(default=None),
    versionConstraint: str | None = Query(default=None),  # noqa: N803 - matches design.md §5.1
    tags: str | None = Query(default=None),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),  # noqa: N803 - matches design.md §5.1
    authorization: Annotated[str | None, Header()] = None,
) -> SearchResponse:
    # ui-design.md §5.4: stays reachable without auth (unchanged from before
    # the visibility model), just scoped to PUBLIC-only for an anonymous or
    # unresolvable caller — see resolve_caller_context.
    caller = resolve_caller_context(
        _bearer_token(authorization), settings=settings, pat_store=pat_store
    )
    tag_list = [t for t in tags.split(",") if t] if tags else None
    result = run_search(
        index,
        query=query,
        tags=tag_list,
        category=category,
        runtime=runtime,
        version_constraint=versionConstraint,
        page=page,
        page_size=pageSize,
        caller=caller,
        grants=grants,
    )
    items = [
        SearchResultItem(
            id=scored.entry.id,
            name=scored.entry.name,
            version=scored.entry.version,
            category=scored.entry.category,
            tags=list(scored.entry.tags),
            runtime=list(scored.entry.runtime_families),
            digest=scored.entry.digest,
            score=scored.score,
            visibility=scored.entry.visibility.value,
            ownerUser=scored.entry.owner_user,
            ownerTenant=scored.entry.owner_tenant,
            status=scored.entry.status.value,
        )
        for scored in result.items
    ]
    return SearchResponse(
        items=items, page=PageMeta(total=result.total, nextPageToken=result.next_page_token)
    )


@router.get("/skills/{skill_id}/versions/{version}", response_model=SkillMetadataResponse)
def get_skill_metadata(
    skill_id: str,
    version: str,
    index: IndexDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    authorization: Annotated[str | None, Header()] = None,
) -> SkillMetadataResponse:
    entry = _require_entry(index, skill_id, version)

    caller = resolve_caller_context(
        _bearer_token(authorization), settings=settings, pat_store=pat_store
    )
    if not can_view(entry, caller=caller, grants=grants):
        # 404, not 403 (ui-design.md §5.4): don't reveal that a private skill
        # id even exists to a caller who can't see it.
        raise JaasError(ErrorCode.SKILL_NOT_FOUND, f"skill '{skill_id}' not found")

    dependencies = []
    for dep_id, constraint in entry.dependencies:
        resolved = index.get_resolved(dep_id, constraint)
        dependencies.append(
            ResolvedDependency(
                id=dep_id,
                versionConstraint=constraint,
                resolvedVersion=resolved.version if resolved else None,
            )
        )

    return SkillMetadataResponse(
        id=entry.id,
        name=entry.name,
        version=entry.version,
        description=entry.description,
        owner=OwnerResponse(team=entry.owner_team),
        category=entry.category,
        tags=list(entry.tags),
        runtime=[
            RuntimeCompatibilityResponse(family=f, versionRange=entry.runtime_ranges[f])
            for f in entry.runtime_families
        ],
        digest=entry.digest,
        dependencies=dependencies,
        visibility=entry.visibility.value,
        ownerUser=entry.owner_user,
        ownerTenant=entry.owner_tenant,
        sourceRepo=entry.source_repo,
        sourceCommit=entry.source_commit,
        sourceTag=entry.source_tag,
        sourceBranch=entry.source_branch,
        sourcePath=entry.source_path,
        ciRunUrl=entry.ci_run_url,
        guardrailCertifiedLevel=entry.guardrail_certified_level,
        guardrailLevelStatuses=list(entry.guardrail_level_statuses),
        guardrailWarningCheckIds=list(entry.guardrail_warning_check_ids),
        status=entry.status.value,
        businessPurpose=entry.business_purpose,
        systemsAccessed=list(entry.systems_accessed),
        governanceReviewDate=entry.governance_review_date,
    )


def _require_viewable_entry(
    index: IndexDep,
    skill_id: str,
    version: str,
    *,
    settings: Settings,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    authorization: str | None,
) -> IndexEntry:
    entry = _require_entry(index, skill_id, version)
    caller = resolve_caller_context(
        _bearer_token(authorization), settings=settings, pat_store=pat_store
    )
    if not can_view(entry, caller=caller, grants=grants):
        # 404, not 403 — same rule as get_skill_metadata.
        raise JaasError(ErrorCode.SKILL_NOT_FOUND, f"skill '{skill_id}' not found")
    return entry


@router.get("/skills/{skill_id}/versions/{version}/files", response_model=list[str])
def list_skill_files(
    skill_id: str,
    version: str,
    index: IndexDep,
    store: StoreDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    authorization: Annotated[str | None, Header()] = None,
) -> list[str]:
    """Read-only file listing for a published version — this is the
    *packaged* archive's contents only: manifest.yaml, whichever of
    schema.json/permissions.yaml/dependencies.yaml were real vs. defaulted
    at publish time, and the entrypoint file if one existed on disk at
    publish time (see artifact/publish.py's load_source_documents). Any
    other file present in the skill's source directory but not named by
    `entrypoint` (README.md, changelog.md, tests/, examples/, ...) is still
    never archived and never appears here."""
    entry = _require_viewable_entry(
        index,
        skill_id,
        version,
        settings=settings,
        grants=grants,
        pat_store=pat_store,
        authorization=authorization,
    )
    archive_bytes = store.read(blob_key(entry.digest))
    return sorted(extract_archive(archive_bytes))


@router.get(
    "/skills/{skill_id}/versions/{version}/files/{file_path:path}",
    response_model=FileContentResponse,
)
def get_skill_file(
    skill_id: str,
    version: str,
    file_path: str,
    index: IndexDep,
    store: StoreDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    authorization: Annotated[str | None, Header()] = None,
) -> FileContentResponse:
    entry = _require_viewable_entry(
        index,
        skill_id,
        version,
        settings=settings,
        grants=grants,
        pat_store=pat_store,
        authorization=authorization,
    )
    archive_bytes = store.read(blob_key(entry.digest))
    content = extract_archive(archive_bytes).get(file_path)
    if content is None:
        raise JaasError(
            ErrorCode.SKILL_FILE_NOT_FOUND,
            f"file '{file_path}' is not part of the published package for "
            f"'{skill_id}@{version}'",
        )
    return FileContentResponse(path=file_path, content=content.decode("utf-8", errors="replace"))


def _scope_to_source_path(files: list[str], source_path: str | None) -> list[str] | None:
    """A `source_repo` can host more than one skill (design.md's "Per-Skill
    Git Directories"), so the raw GitHub tree must be narrowed to this
    skill's own subdirectory and re-relativized to match the Package tab's
    skill-relative paths — otherwise a sibling skill's files would leak
    into this one's "browse source" view. `None` distinguishes "recorded a
    source_path but nothing under it matched at this ref" (stale/renamed
    directory — worth surfacing as unavailable) from a legitimately empty
    list. No source_path recorded at all means the repo root *is* the
    skill (the reference CI workflow's convention) — the tree is used
    as-is."""
    if not source_path:
        return files
    prefix = f"{source_path.strip('/')}/"
    scoped = [f[len(prefix) :] for f in files if f.startswith(prefix)]
    return scoped if scoped else None


@router.get(
    "/skills/{skill_id}/versions/{version}/source-files", response_model=SourceFilesResponse
)
def list_skill_source_files(
    skill_id: str,
    version: str,
    index: IndexDep,
    github_api_client: GitHubApiClientDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    authorization: Annotated[str | None, Header()] = None,
) -> SourceFilesResponse:
    """Browsing-only view of the *full* repo tree at this version's
    release ref — separate from `/files` above, which is only ever the
    narrow, signed, downloadable package (manifest.yaml + 3 docs +
    entrypoint). Fetched live from GitHub's unauthenticated public API,
    never a stored owner access token — see
    GitHubApiClient.get_public_tree's docstring for why: a private source
    repo just shows as unavailable rather than risking leaking its
    contents to a viewer of an otherwise-public skill."""
    entry = _require_viewable_entry(
        index,
        skill_id,
        version,
        settings=settings,
        grants=grants,
        pat_store=pat_store,
        authorization=authorization,
    )
    if not entry.source_repo:
        return SourceFilesResponse(
            available=False, reason="this version has no source repository recorded"
        )
    ref = entry.source_commit or entry.source_tag
    if not ref:
        return SourceFilesResponse(
            available=False,
            repoUrl=entry.source_repo,
            reason="this version has no source commit or tag recorded",
        )
    try:
        owner, repo = parse_github_repo_url(entry.source_repo)
    except JaasError:
        return SourceFilesResponse(
            available=False,
            repoUrl=entry.source_repo,
            ref=ref,
            reason="source repository URL is not a recognized GitHub URL",
        )
    try:
        raw_files = github_api_client.get_public_tree(owner=owner, repo=repo, ref=ref)
    except JaasError:
        return SourceFilesResponse(
            available=False,
            repoUrl=entry.source_repo,
            ref=ref,
            reason="source repository is private, was deleted, or GitHub is unreachable",
        )
    files = _scope_to_source_path(raw_files, entry.source_path)
    if files is None:
        return SourceFilesResponse(
            available=False,
            repoUrl=entry.source_repo,
            ref=ref,
            reason=(
                f"no files found under '{entry.source_path}' in the source "
                "repository at this ref"
            ),
        )
    return SourceFilesResponse(available=True, files=files, repoUrl=entry.source_repo, ref=ref)


@router.get(
    "/skills/{skill_id}/versions/{version}/source-files/{file_path:path}",
    response_model=FileContentResponse,
)
def get_skill_source_file(
    skill_id: str,
    version: str,
    file_path: str,
    index: IndexDep,
    github_api_client: GitHubApiClientDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    pat_store: PatStoreDep,
    authorization: Annotated[str | None, Header()] = None,
) -> FileContentResponse:
    entry = _require_viewable_entry(
        index,
        skill_id,
        version,
        settings=settings,
        grants=grants,
        pat_store=pat_store,
        authorization=authorization,
    )
    ref = entry.source_commit or entry.source_tag
    if not entry.source_repo or not ref:
        raise JaasError(
            ErrorCode.SKILL_FILE_NOT_FOUND,
            f"'{skill_id}@{version}' has no source repository available to browse",
        )
    owner, repo = parse_github_repo_url(entry.source_repo)
    # file_path is skill-relative (matches what /source-files just listed);
    # re-add the source_path prefix to get the real repo-relative path
    # GitHub's API needs — see _scope_to_source_path above.
    real_path = f"{entry.source_path.strip('/')}/{file_path}" if entry.source_path else file_path
    try:
        content = github_api_client.get_public_file_content(
            owner=owner, repo=repo, ref=ref, path=real_path
        )
    except JaasError as exc:
        raise JaasError(
            ErrorCode.SKILL_FILE_NOT_FOUND,
            f"could not fetch '{file_path}' from the source repository: {exc.message}",
        ) from exc
    return FileContentResponse(path=file_path, content=content.decode("utf-8", errors="replace"))


@router.post(
    "/skills/{skill_id}/versions/{version}/artifact-token", response_model=ArtifactTokenResponse
)
def create_artifact_token(
    skill_id: str,
    version: str,
    index: IndexDep,
    settings: SettingsDep,
    token_issuer: TokenIssuerDep,
    authorizer: AuthorizerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> ArtifactTokenResponse:
    entry = _require_entry(index, skill_id, version)
    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=x_tenant_id,
        required_permissions=entry.permissions,
    )

    record = token_issuer.issue(
        blob_key=blob_key(entry.digest),
        digest=entry.digest,
        signature=entry.signature,
        signature_kind=entry.signature_kind,
    )
    return ArtifactTokenResponse(
        token=record.token,
        expiresAt=datetime.fromtimestamp(record.expires_at, tz=UTC).isoformat(),
        ttlSeconds=settings.artifact_url_ttl_seconds,
    )


def _require_share_management_access(
    *,
    index: InMemoryIndex,
    skill_id: str,
    settings: Settings,
    authorizer: Authorizer,
    memberships: MembershipStore,
    credentials: HTTPAuthorizationCredentials | None,
    x_tenant_id: str | None,
    required_permissions: tuple[str, ...] = ("skills:share",),
) -> IndexEntry:
    """Common guard for the /shares endpoints (ui-design.md §7, §5.2) AND
    /yank, /unyank (IMPLEMENTATION_PLAN.md Phase 1.3, skills:write instead):
    caller must hold `required_permissions` AND either own the skill or
    administer its owning tenant — scope alone doesn't restrict *which*
    skill, so it's necessary but not sufficient on its own."""
    versions = index.list_versions(skill_id)
    if not versions:
        raise JaasError(ErrorCode.SKILL_NOT_FOUND, f"skill '{skill_id}' not found")
    # Deliberately index.get(), not get_resolved(): this is only used to look
    # up owner_user/owner_tenant, which don't vary by version, so it must not
    # come back None just because every version happens to be yanked right
    # now (get_resolved excludes yanked versions from unconstrained
    # resolution) — that would lock a skill's own owner out of unyanking it.
    entry = index.get(skill_id, versions[-1])
    assert entry is not None  # versions[-1] came from list_versions itself

    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=x_tenant_id,
        required_permissions=required_permissions,
    )
    caller = resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )
    if not can_manage_sharing(entry, caller=caller, memberships=memberships):
        raise JaasError(
            ErrorCode.UNAUTHORIZED, "caller does not own this skill or administer its tenant"
        )
    return entry


def _grant_to_response(grant: ShareGrant) -> ShareGrantResponse:
    return ShareGrantResponse(
        id=grant.id,
        skillId=grant.skill_id,
        granteeType=grant.grantee_type.value,
        granteeId=grant.grantee_id,
        permission=grant.permission.value,
        grantedBy=grant.granted_by,
        grantedAt=grant.granted_at,
    )


@router.get("/skills/{skill_id}/shares", response_model=list[ShareGrantResponse])
def list_shares(
    skill_id: str,
    index: IndexDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    authorizer: AuthorizerDep,
    memberships: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> list[ShareGrantResponse]:
    _require_share_management_access(
        index=index,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        memberships=memberships,
        credentials=credentials,
        x_tenant_id=x_tenant_id,
    )
    return [_grant_to_response(g) for g in grants.list_for_skill(skill_id)]


@router.post("/skills/{skill_id}/shares", response_model=ShareGrantResponse)
def create_share(
    skill_id: str,
    body: CreateShareGrantRequest,
    index: IndexDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    authorizer: AuthorizerDep,
    memberships: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> ShareGrantResponse:
    _require_share_management_access(
        index=index,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        memberships=memberships,
        credentials=credentials,
        x_tenant_id=x_tenant_id,
    )
    caller = resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )
    try:
        grantee_type = GranteeType(body.granteeType)
        permission = SharePermission(body.permission)
    except ValueError as exc:
        raise JaasError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    grant = grants.create(
        skill_id=skill_id,
        grantee_type=grantee_type,
        grantee_id=body.granteeId,
        permission=permission,
        granted_by=caller.user_id or "",
    )
    # IMPLEMENTATION_PLAN.md Phase 3.3: sharing-grant changes were the other
    # security-relevant action left unaudited since Phase 1.3.
    FileAuditSink(settings.audit_dir).emit_share_grant_change(
        new_share_grant_event(
            actor=caller.user_id or "",
            skill_id=skill_id,
            grant_id=grant.id,
            grantee_type=grant.grantee_type.value,
            grantee_id=grant.grantee_id,
            permission=grant.permission.value,
            action="granted",
        )
    )
    return _grant_to_response(grant)


@router.delete("/skills/{skill_id}/shares/{grant_id}", status_code=204)
def revoke_share(
    skill_id: str,
    grant_id: str,
    index: IndexDep,
    settings: SettingsDep,
    grants: GrantStoreDep,
    authorizer: AuthorizerDep,
    memberships: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> Response:
    _require_share_management_access(
        index=index,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        memberships=memberships,
        credentials=credentials,
        x_tenant_id=x_tenant_id,
    )
    # Fetched before revoke() deletes the grant file — need its details for
    # the audit record below.
    existing = grants.get(skill_id=skill_id, grant_id=grant_id)
    grants.revoke(skill_id=skill_id, grant_id=grant_id)
    if existing is not None:
        caller = resolve_caller_context(
            credentials.credentials if credentials else None, settings=settings
        )
        FileAuditSink(settings.audit_dir).emit_share_grant_change(
            new_share_grant_event(
                actor=caller.user_id or "",
                skill_id=skill_id,
                grant_id=grant_id,
                grantee_type=existing.grantee_type.value,
                grantee_id=existing.grantee_id,
                permission=existing.permission.value,
                action="revoked",
            )
        )
    return Response(status_code=204)


def _yank_response(skill_id: str, version: str, record: YankRecord) -> YankResponse:
    return YankResponse(
        id=skill_id,
        version=version,
        status=record.status.value,
        reason=record.reason,
        actor=record.actor,
        at=record.at,
    )


def _set_version_status(
    *,
    skill_id: str,
    version: str,
    status: ArtifactStatus,
    reason: str | None,
    index: InMemoryIndex,
    store: ObjectStore,
    settings: Settings,
    credentials: HTTPAuthorizationCredentials | None,
) -> YankResponse:
    """Shared body for /yank and /unyank — same status-sidecar write, same
    direct index.put() the other publish-adjacent routes use (release_routes.py,
    draft_routes.py don't route through the event bus either; see
    IMPLEMENTATION_PLAN.md Phase 1.3 for why this doesn't either)."""
    entry = index.get(skill_id, version)
    if entry is None:
        if not index.list_versions(skill_id):
            raise JaasError(ErrorCode.SKILL_NOT_FOUND, f"skill '{skill_id}' not found")
        raise JaasError(
            ErrorCode.VERSION_NOT_FOUND, f"version '{version}' not found for '{skill_id}'"
        )

    caller = resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )
    record = YankRecord(
        status=status, reason=reason, actor=caller.user_id or "", at=datetime.now(UTC).isoformat()
    )
    write_status(store, skill_id=skill_id, version=version, record=record)
    index.put(dataclasses.replace(entry, status=status))
    # IMPLEMENTATION_PLAN.md Phase 3.3: yank/unyank is a security-relevant
    # state change that Phase 1.3 left unaudited — closes that gap. Fresh
    # sink instance per call, same convention as tenant_routes.py/
    # github_routes.py's existing audit call sites.
    FileAuditSink(settings.audit_dir).emit_yank(
        new_yank_event(
            actor=caller.user_id or "",
            skill_id=skill_id,
            version=version,
            action="yanked" if status == ArtifactStatus.YANKED else "unyanked",
            reason=reason,
        )
    )
    return _yank_response(skill_id, version, record)


@router.post("/skills/{skill_id}/versions/{version}/yank", response_model=YankResponse)
def yank_skill_version(
    skill_id: str,
    version: str,
    body: YankRequest,
    index: IndexDep,
    store: StoreDep,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    memberships: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> YankResponse:
    """IMPLEMENTATION_PLAN.md Phase 1.3: flag a published version as insecure
    or broken after the fact, without touching its immutable manifest.
    Idempotent — yanking an already-yanked version just refreshes the
    reason/actor/at and returns 200, never an error."""
    _require_share_management_access(
        index=index,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        memberships=memberships,
        credentials=credentials,
        x_tenant_id=x_tenant_id,
        required_permissions=("skills:write",),
    )
    return _set_version_status(
        skill_id=skill_id,
        version=version,
        status=ArtifactStatus.YANKED,
        reason=body.reason,
        index=index,
        store=store,
        settings=settings,
        credentials=credentials,
    )


@router.post("/skills/{skill_id}/versions/{version}/unyank", response_model=YankResponse)
def unyank_skill_version(
    skill_id: str,
    version: str,
    body: YankRequest,
    index: IndexDep,
    store: StoreDep,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    memberships: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> YankResponse:
    """Reverses a yank — same authorization tier, same idempotent shape."""
    _require_share_management_access(
        index=index,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        memberships=memberships,
        credentials=credentials,
        x_tenant_id=x_tenant_id,
        required_permissions=("skills:write",),
    )
    return _set_version_status(
        skill_id=skill_id,
        version=version,
        status=ArtifactStatus.ACTIVE,
        reason=body.reason,
        index=index,
        store=store,
        settings=settings,
        credentials=credentials,
    )


@router.get("/artifacts/{token}")
def download_artifact(
    token: str,
    store: StoreDep,
    settings: SettingsDep,
    token_issuer: TokenIssuerDep,
    trust_policy: TrustPolicyDep,
) -> Response:
    """Redeem a short-lived artifact token for the packaged bytes. Stands in for
    following a presigned S3 URL / OCI pull reference (design.md §3.3.2) — the
    token's possession within its TTL is the access control, matching how a
    presigned URL works; see design.md §5.3 and §5.4.
    """
    record = token_issuer.redeem(token)
    if record is None:
        raise JaasError(ErrorCode.UNAUTHORIZED, "artifact token is invalid or has expired")

    archive_bytes = store.read(record.blob_key)

    if settings.feature_flags.high_assurance_signature_recheck:
        sigstore_trust_policy = (
            load_sigstore_trust_policy(identity_issuer=settings.sigstore_identity_issuer)
            if record.signature_kind == "sigstore"
            else None
        )
        verify_artifact(
            archive_bytes=archive_bytes,
            digest=record.digest,
            signature=record.signature,
            signature_kind=record.signature_kind,
            trust_policy=trust_policy,
            sigstore_trust_policy=sigstore_trust_policy,
        )

    return Response(content=archive_bytes, media_type="application/x-tar")


@router.put("/skills/{skill_id}/governance", response_model=GovernanceResponse)
def put_skill_governance(
    skill_id: str,
    body: GovernanceUpdateRequest,
    index: IndexDep,
    store: StoreDep,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    memberships: MembershipStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> GovernanceResponse:
    """IMPLEMENTATION_PLAN.md Phase 3.3: set/update this skill's governance
    record (business purpose, systems accessed, review date) — a distinct
    permission scope from skills:write/skills:share, since this is a
    compliance concern, not a publish or sharing action. Same owner-or-
    tenant-admin authorization tier as yank/shares. Unlike yank (per-
    version), this overlays onto *every* published version of the skill —
    see artifact/governance.py's module docstring for why."""
    _require_share_management_access(
        index=index,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        memberships=memberships,
        credentials=credentials,
        x_tenant_id=x_tenant_id,
        required_permissions=("skills:governance",),
    )
    caller = resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )
    record = GovernanceRecord(
        business_purpose=body.businessPurpose,
        systems_accessed=tuple(body.systemsAccessed),
        review_date=body.reviewDate,
        updated_by=caller.user_id or "",
        updated_at=datetime.now(UTC).isoformat(),
    )
    write_governance(store, skill_id=skill_id, record=record)
    for version in index.list_versions(skill_id):
        entry = index.get(skill_id, version)
        if entry is not None:
            index.put(apply_governance(entry, record))

    return GovernanceResponse(
        id=skill_id,
        businessPurpose=record.business_purpose,
        systemsAccessed=list(record.systems_accessed),
        reviewDate=record.review_date,
        updatedBy=record.updated_by,
        updatedAt=record.updated_at,
    )
