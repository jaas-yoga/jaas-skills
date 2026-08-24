"""Draft authoring workspace endpoints. Design ref: ui-design.md §7, §11.

Auth is required outright here (unlike search/metadata) — a draft is
inherently private scratch space, never a "maybe public" resource. Ownership
is owner-only for this iteration (no draft-sharing grants yet, unlike
published skills) — a real simplification vs. ui-design.md §11.5's "shared
draft" scenario, called out rather than silently assumed.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from rune_registry.api.deps import (
    AuthorizerDep,
    CustomGuardrailRuleStoreDep,
    DraftStoreDep,
    GitHubApiClientDep,
    GitHubConnectionStoreDep,
    GrantStoreDep,
    GuardrailCatalogDep,
    GuardrailPolicyStoreDep,
    GuardrailsClientDep,
    IndexDep,
    RepoLinkStoreDep,
    SettingsDep,
    StoreDep,
)
from rune_registry.api.schemas import (
    CertificationSummaryResponse,
    CreateDraftRequest,
    DraftPublishRequest,
    DraftPublishResponse,
    DraftResponse,
    DraftSummaryResponse,
    FileContentResponse,
    PutFileRequest,
    ValidationErrorItem,
    ValidationResultResponse,
)
from rune_registry.artifact.packaging import DEFAULT_PACKAGE_FILE_CONTENTS
from rune_registry.artifact.publish import publish_skill
from rune_registry.artifact.signing import load_or_create_keypair
from rune_registry.artifact.trust import ensure_key_registered, load_trust_policy
from rune_registry.authn.github_client import GitHubApiClient
from rune_registry.authn.github_connections import GitHubConnectionStore
from rune_registry.authn.repo_links import RepoLinkStore
from rune_registry.common.audit import StructuredLogAuditSink
from rune_registry.common.config import Settings
from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.drafts import git_sync
from rune_registry.drafts.models import Draft
from rune_registry.drafts.store import DraftStore
from rune_registry.guardrails.certification import compute_certification, flatten_certification
from rune_registry.guardrails.policy import GuardrailPolicy
from rune_registry.guardrails.skill_config import (
    GUARDRAILS_CONFIG_PATH,
    parse_skill_guardrail_config,
    resolve_guardrails_for_skill,
)
from rune_registry.index.ingest import parse_published_record
from rune_registry.index.models import Visibility
from rune_registry.sharing.access import CallerContext, can_view, resolve_caller_context
from rune_registry.storage.keys import blob_key
from rune_registry.validation.package import validate_skill_package

router = APIRouter(prefix="/api/v1/drafts")
_bearer_scheme = HTTPBearer(auto_error=False)


def _require_caller(
    *,
    settings: Settings,
    authorizer,
    credentials: HTTPAuthorizationCredentials | None,
) -> CallerContext:
    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=None,
        required_permissions=("skills:write",),
    )
    return resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )


def _require_owned_draft(drafts: DraftStore, draft_id: str, caller: CallerContext) -> Draft:
    draft = drafts.get(draft_id)
    # 404 either way — consistent with the private-skill precedent (design.md
    # §7.2 item 4): don't reveal that a draft you don't own even exists.
    if draft is None or draft.owner_user != caller.user_id:
        raise RuneError(ErrorCode.DRAFT_NOT_FOUND, f"draft '{draft_id}' not found")
    return draft


def _to_response(draft: Draft, drafts: DraftStore) -> DraftResponse:
    git_sync_status = None
    if draft.repo_url is not None:
        git_sync_status = "error" if draft.git_sync_error else "synced"
    return DraftResponse(
        id=draft.id,
        ownerUser=draft.owner_user,
        ownerTenant=draft.owner_tenant,
        createdAt=draft.created_at,
        forkedFromId=draft.forked_from_id,
        forkedFromVersion=draft.forked_from_version,
        files=drafts.list_files(draft.id),
        provider=draft.provider,
        repoUrl=draft.repo_url,
        targetBranch=draft.target_branch,
        workingBranch=draft.working_branch,
        gitSyncStatus=git_sync_status,
        gitSyncError=draft.git_sync_error,
        gitSubdirectory=draft.git_subdirectory,
    )


def _is_repo_connected(repo_links: RepoLinkStore, *, tenant_id: str, owner: str, repo: str) -> bool:
    """A repo must already be registered under Connected Repos (Tenant
    Settings → Repositories) before a draft can be created against it —
    same admin-curated allow-list CI releases already require, just
    matched by repo rather than skill id (a repo can carry several links,
    for different skill ids, and a brand-new draft has none yet)."""
    target = (owner.lower(), repo.lower())
    for link in repo_links.list_for_tenant(tenant_id):
        try:
            link_owner, link_repo = git_sync.parse_github_repo_url(link.repo_url)
        except RuneError:
            continue  # a manually-entered non-GitHub URL can never match
        if (link_owner.lower(), link_repo.lower()) == target:
            return True
    return False


def _connect_draft_to_git(
    draft: Draft,
    *,
    request_git,
    drafts: DraftStore,
    github_connections: GitHubConnectionStore,
    github_api_client: GitHubApiClient,
    repo_links: RepoLinkStore,
) -> Draft:
    """Best-effort is not good enough here: any failure rolls the whole
    draft creation back (drafts.delete) rather than leaving a local draft
    that silently isn't what the user asked for."""
    if request_git.provider != "github":
        drafts.delete(draft.id)
        raise RuneError(
            ErrorCode.SCHEMA_VALIDATION_FAILED,
            f"unsupported git provider '{request_git.provider}' (only 'github' today)",
        )
    connection = github_connections.get(draft.owner_tenant)
    if connection is None:
        drafts.delete(draft.id)
        raise RuneError(ErrorCode.GITHUB_NOT_CONNECTED, "this tenant has not connected GitHub")

    try:
        owner, repo = git_sync.parse_github_repo_url(request_git.repoUrl)
    except RuneError:
        drafts.delete(draft.id)
        raise

    if not _is_repo_connected(repo_links, tenant_id=draft.owner_tenant, owner=owner, repo=repo):
        drafts.delete(draft.id)
        raise RuneError(
            ErrorCode.REPO_LINK_REQUIRED,
            f"'{owner}/{repo}' is not a connected repo — register it under "
            "Tenant Settings → Repositories first",
        )

    try:
        working_branch = (
            request_git.workingBranch or f"rune/draft/{draft.id.removeprefix('draft_')}"
        )
        seed_changes: dict[str, bytes] = {
            name: content
            for name in drafts.list_files(draft.id)
            if (content := drafts.read_file(draft.id, name)) is not None
        }
        # One folder per skill (design intent: several skills can share a
        # repo) — every path committed for this draft, from the very first
        # commit onward, lives under this directory.
        subdirectory = git_sync.skill_directory_name(
            seed_changes.get("manifest.yaml"), fallback=draft.id.removeprefix("draft_")
        )
        prefixed_seed_changes = git_sync.prefix_changes(seed_changes, subdirectory)
        base_sha, already_seeded = git_sync.create_working_branch(
            github_api_client,
            connection.access_token,
            owner=owner,
            repo=repo,
            target_branch=request_git.targetBranch,
            working_branch=working_branch,
            seed_changes=prefixed_seed_changes,
            allow_empty_repo_init=request_git.confirmInitializeEmptyRepo,
        )
        if already_seeded:
            new_sha = base_sha
        else:
            new_sha = git_sync.commit_files(
                github_api_client,
                connection.access_token,
                owner=owner,
                repo=repo,
                branch=working_branch,
                changes=prefixed_seed_changes,
                message="Initial draft commit via JaaS Skills",
            )
    except RuneError:
        drafts.delete(draft.id)
        raise

    return drafts.set_git_connection(
        draft.id,
        provider="github",
        repo_url=request_git.repoUrl,
        git_owner=owner,
        git_repo=repo,
        target_branch=request_git.targetBranch,
        working_branch=working_branch,
        last_synced_sha=new_sha,
        git_subdirectory=subdirectory,
    )


def _sync_file_change(
    draft: Draft,
    *,
    changes: dict[str, bytes | None],
    message: str,
    drafts: DraftStore,
    github_connections: GitHubConnectionStore,
    github_api_client: GitHubApiClient,
) -> Draft:
    """Best-effort write-through to git for an already-successful local
    write/delete. Never raises — a sync failure is recorded on the draft
    and surfaced via DraftResponse.gitSyncStatus, but the local save this
    is called after has already succeeded and must not be undone."""
    if draft.repo_url is None:
        return draft
    # A draft connected before per-skill directories existed has no
    # git_subdirectory yet — its history is already flat at the repo root,
    # so ongoing saves stay flat too until move_draft_to_git_directory
    # explicitly migrates it (never implied here).
    if draft.git_subdirectory:
        changes = git_sync.prefix_changes(changes, draft.git_subdirectory)
    try:
        connection = github_connections.get(draft.owner_tenant)
        if connection is None:
            raise RuneError(ErrorCode.GITHUB_NOT_CONNECTED, "this tenant has not connected GitHub")
        new_sha = git_sync.commit_files(
            github_api_client,
            connection.access_token,
            owner=draft.git_owner,
            repo=draft.git_repo,
            branch=draft.working_branch,
            changes=changes,
            message=message,
        )
        return drafts.set_sync_status(draft.id, sha=new_sha)
    except RuneError as exc:
        return drafts.set_sync_status(draft.id, error=exc.message)


@router.post("", response_model=DraftResponse)
def create_draft(
    body: CreateDraftRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    store: StoreDep,
    index: IndexDep,
    grants: GrantStoreDep,
    github_connections: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    repo_links: RepoLinkStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> DraftResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)

    fork_archive_bytes = None
    forked_from_id = None
    forked_from_version = None
    if body.forkFrom is not None:
        entry = index.get_resolved(body.forkFrom.id, body.forkFrom.version)
        if entry is None:
            raise RuneError(
                ErrorCode.SKILL_NOT_FOUND,
                f"skill '{body.forkFrom.id}' version '{body.forkFrom.version}' not found",
            )
        # ui-design.md §5.4: forking a skill you can't view would leak its
        # contents outside the visibility rule entirely — same check as the
        # metadata endpoint, not a separate/weaker one.
        if not can_view(entry, caller=caller, grants=grants):
            raise RuneError(
                ErrorCode.SKILL_NOT_FOUND,
                f"skill '{body.forkFrom.id}' version '{body.forkFrom.version}' not found",
            )
        fork_archive_bytes = store.read(blob_key(entry.digest))
        forked_from_id = entry.id
        forked_from_version = entry.version

    draft = drafts.create(
        owner_user=caller.user_id or "",
        owner_tenant=caller.tenant_id or "",
        fork_archive_bytes=fork_archive_bytes,
        forked_from_id=forked_from_id,
        forked_from_version=forked_from_version,
    )

    if body.git is not None:
        draft = _connect_draft_to_git(
            draft,
            request_git=body.git,
            drafts=drafts,
            github_connections=github_connections,
            github_api_client=github_api_client,
            repo_links=repo_links,
        )

    return _to_response(draft, drafts)


def _peek_skill_id(drafts: DraftStore, draft_id: str) -> str | None:
    """Best-effort read of manifest.yaml's own `id` — just for display
    (the drafts list), so a bad/missing manifest is None, never an error."""
    manifest_bytes = drafts.read_file(draft_id, "manifest.yaml")
    if manifest_bytes is None:
        return None
    try:
        data = yaml.safe_load(manifest_bytes)
    except yaml.YAMLError:
        return None
    skill_id = data.get("id") if isinstance(data, dict) else None
    return skill_id if isinstance(skill_id, str) and skill_id else None


@router.get("", response_model=list[DraftSummaryResponse])
def list_drafts(
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> list[DraftSummaryResponse]:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    return [
        DraftSummaryResponse(
            id=d.id,
            createdAt=d.created_at,
            forkedFromId=d.forked_from_id,
            forkedFromVersion=d.forked_from_version,
            repoUrl=d.repo_url,
            skillId=_peek_skill_id(drafts, d.id),
        )
        for d in drafts.list_for_user(caller.user_id or "")
    ]


@router.get("/{draft_id}", response_model=DraftResponse)
def get_draft(
    draft_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> DraftResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    draft = _require_owned_draft(drafts, draft_id, caller)
    return _to_response(draft, drafts)


@router.delete("/{draft_id}", status_code=204)
def delete_draft(
    draft_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> None:
    """Discard a draft outright — unlike delete_draft_file (one file), this
    removes the whole scratch workspace. Irreversible: there is no trash/
    undo, matching drafts.delete()'s existing use as post-publish cleanup."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_owned_draft(drafts, draft_id, caller)
    drafts.delete(draft_id)


@router.get("/{draft_id}/files/{file_path:path}", response_model=FileContentResponse)
def get_draft_file(
    draft_id: str,
    file_path: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> FileContentResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    _require_owned_draft(drafts, draft_id, caller)
    content = drafts.read_file(draft_id, file_path)
    if content is None:
        raise RuneError(ErrorCode.DRAFT_NOT_FOUND, f"file '{file_path}' not found in draft")
    return FileContentResponse(path=file_path, content=content.decode("utf-8", errors="replace"))


@router.put("/{draft_id}/files/{file_path:path}", response_model=DraftResponse)
def put_draft_file(
    draft_id: str,
    file_path: str,
    body: PutFileRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    github_connections: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> DraftResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    draft = _require_owned_draft(drafts, draft_id, caller)
    content = body.content.encode("utf-8")
    drafts.write_file(draft_id, file_path, content)
    if body.syncToGit:
        draft = _sync_file_change(
            draft,
            changes={file_path: content},
            message=body.commitMessage or f"Update {file_path}",
            drafts=drafts,
            github_connections=github_connections,
            github_api_client=github_api_client,
        )
    return _to_response(draft, drafts)


@router.delete("/{draft_id}/files/{file_path:path}", response_model=DraftResponse)
def delete_draft_file(
    draft_id: str,
    file_path: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    github_connections: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> DraftResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    draft = _require_owned_draft(drafts, draft_id, caller)
    drafts.delete_file(draft_id, file_path)
    draft = _sync_file_change(
        draft,
        changes={file_path: None},
        message=f"Delete {file_path}",
        drafts=drafts,
        github_connections=github_connections,
        github_api_client=github_api_client,
    )
    return _to_response(draft, drafts)


@router.post("/{draft_id}/git/move-to-directory", response_model=DraftResponse)
def move_draft_to_git_directory(
    draft_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    github_connections: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> DraftResponse:
    """One-time migration for a draft that was git-connected before every
    skill got its own `<id>/` folder (git_sync.skill_directory_name) — so
    one repo can host several skills without their files colliding at the
    root. Unlike _sync_file_change, this is a deliberate user action, not a
    best-effort side effect of a save: a failure here is raised, not
    swallowed, and git_subdirectory is only ever persisted after the actual
    commit has landed — so a failed attempt is safe to just retry."""
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    draft = _require_owned_draft(drafts, draft_id, caller)

    if draft.repo_url is None:
        raise RuneError(ErrorCode.DRAFT_GIT_NOT_CONNECTED, "this draft is not connected to a repo")
    if draft.git_subdirectory:
        raise RuneError(
            ErrorCode.DRAFT_GIT_ALREADY_HAS_DIRECTORY,
            f"this draft's files already live under '{draft.git_subdirectory}/'",
        )
    connection = github_connections.get(draft.owner_tenant)
    if connection is None:
        raise RuneError(ErrorCode.GITHUB_NOT_CONNECTED, "this tenant has not connected GitHub")

    current_files: dict[str, bytes] = {
        name: content
        for name in drafts.list_files(draft.id)
        if (content := drafts.read_file(draft.id, name)) is not None
    }
    subdirectory = git_sync.skill_directory_name(
        current_files.get("manifest.yaml"), fallback=draft.id.removeprefix("draft_")
    )
    # Every currently-tracked file moves from its flat, at-the-root path to
    # the same path nested under `subdirectory/` — one commit, so the
    # working branch never has a moment with both copies or neither.
    changes: dict[str, bytes | None] = {name: None for name in current_files}
    changes.update(git_sync.prefix_changes(current_files, subdirectory))

    new_sha = git_sync.commit_files(
        github_api_client,
        connection.access_token,
        owner=draft.git_owner,
        repo=draft.git_repo,
        branch=draft.working_branch,
        changes=changes,
        message=f"Move skill files into {subdirectory}/",
    )
    draft = drafts.set_git_subdirectory(draft.id, subdirectory)
    draft = drafts.set_sync_status(draft.id, sha=new_sha)
    return _to_response(draft, drafts)


def _load_draft_documents(drafts: DraftStore, draft_id: str):
    """Mirrors artifact/packaging.py's collect_package_files exactly: only
    manifest.yaml is a hard requirement, the other three documents default
    to DEFAULT_PACKAGE_FILE_CONTENTS when the draft doesn't have them, so
    /validate and /publish never disagree about what's missing.

    Also returns the draft's full file set — every other file the draft
    happens to contain (an entrypoint, README, etc.) — so guardrail checks
    that scan "all files" or the entrypoint specifically (design.md §4.5)
    see the same content /publish will actually archive. A bad path in a
    file name here is a real trust boundary (drafts.list_files/read_file
    already guard against traversal via DraftStore._safe_file_path), so
    letting a RuneError from that path surface is correct — /validate's own
    `except RuneError` branch already reports it cleanly."""
    manifest_bytes = drafts.read_file(draft_id, "manifest.yaml")
    if manifest_bytes is None:
        raise FileNotFoundError("draft is missing required file 'manifest.yaml'")

    def _read_or_default(name: str) -> bytes:
        content = drafts.read_file(draft_id, name)
        return content if content is not None else DEFAULT_PACKAGE_FILE_CONTENTS[name]

    schema_bytes = _read_or_default("schema.json")
    permissions_bytes = _read_or_default("permissions.yaml")
    dependencies_bytes = _read_or_default("dependencies.yaml")

    manifest_data = yaml.safe_load(manifest_bytes)
    io_schema_data = json.loads(schema_bytes)
    permissions_data = yaml.safe_load(permissions_bytes) or []
    dependencies_data = yaml.safe_load(dependencies_bytes) or []

    files: dict[str, bytes] = {}
    for name in drafts.list_files(draft_id):
        content = drafts.read_file(draft_id, name)
        if content is not None:
            files[name] = content

    return manifest_data, io_schema_data, permissions_data, dependencies_data, files


@router.post("/{draft_id}/validate", response_model=ValidationResultResponse)
def validate_draft(
    draft_id: str,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    guardrail_policy_store: GuardrailPolicyStoreDep,
    guardrail_catalog: GuardrailCatalogDep,
    guardrails_client: GuardrailsClientDep,
    custom_rule_store: CustomGuardrailRuleStoreDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> ValidationResultResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    draft = _require_owned_draft(drafts, draft_id, caller)

    try:
        manifest_data, io_schema_data, permissions_data, dependencies_data, files = (
            _load_draft_documents(drafts, draft.id)
        )
        docs = validate_skill_package(
            manifest=manifest_data,
            io_schema=io_schema_data,
            permissions=permissions_data,
            dependencies=dependencies_data,
        )
    except RuneError as exc:
        return ValidationResultResponse(
            valid=False, errors=[ValidationErrorItem(code=exc.code.value, message=exc.message)]
        )
    except FileNotFoundError as exc:
        error = ValidationErrorItem(code=ErrorCode.MISSING_REQUIRED_FILE.value, message=str(exc))
        return ValidationResultResponse(valid=False, errors=[error])

    tenant_id = caller.tenant_id or ""
    policy = guardrail_policy_store.get(tenant_id, guardrail_catalog)
    try:
        skill_config = parse_skill_guardrail_config(files.get(GUARDRAILS_CONFIG_PATH))
        enabled_ids, custom_rules = resolve_guardrails_for_skill(
            tenant_id=tenant_id,
            skill_id=docs.manifest.id,
            policy=policy,
            catalog_ids=frozenset(d.id for d in guardrail_catalog),
            skill_config=skill_config,
            custom_rule_store=custom_rule_store,
        )
    except RuneError as exc:
        return ValidationResultResponse(
            valid=False, errors=[ValidationErrorItem(code=exc.code.value, message=exc.message)]
        )
    scan = guardrails_client.scan(
        files=files,
        manifest=docs.manifest,
        permissions=docs.permissions.root,
        dependencies=docs.dependencies.root,
        enabled_check_ids=enabled_ids,
        custom_rules=custom_rules,
    )
    if scan.blocking:
        errors = [
            ValidationErrorItem(
                code=ErrorCode.GUARDRAIL_VIOLATION.value, message=f.message, file=f.file
            )
            for f in scan.blocking
        ]
        return ValidationResultResponse(valid=False, errors=errors)

    warnings = [
        ValidationErrorItem(code=f.check_id, message=f.message, file=f.file)
        for f in scan.warnings
    ]
    # The certification this draft would receive if published right now —
    # a projection, using the exact same pure function the real publish
    # path uses (artifact/publish.py), just never persisted from here.
    certification = compute_certification(
        scan=scan, enabled_check_ids=enabled_ids, catalog=guardrail_catalog
    )
    certification_summary = (
        CertificationSummaryResponse(
            highestCertifiedLevel=certification.highest_certified_level,
            levelStatuses=[(level, status.value) for level, status in certification.level_statuses],
        )
        if certification is not None
        else None
    )
    return ValidationResultResponse(
        valid=True, errors=[], warnings=warnings, certification=certification_summary
    )


@router.post("/{draft_id}/publish", response_model=DraftPublishResponse)
def publish_draft(
    draft_id: str,
    body: DraftPublishRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    drafts: DraftStoreDep,
    store: StoreDep,
    index: IndexDep,
    guardrail_policy_store: GuardrailPolicyStoreDep,
    guardrail_catalog: GuardrailCatalogDep,
    guardrails_client: GuardrailsClientDep,
    custom_rule_store: CustomGuardrailRuleStoreDep,
    github_connections: GitHubConnectionStoreDep,
    github_api_client: GitHubApiClientDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> DraftPublishResponse:
    caller = _require_caller(settings=settings, authorizer=authorizer, credentials=credentials)
    draft = _require_owned_draft(drafts, draft_id, caller)

    try:
        visibility = Visibility(body.visibility)
    except ValueError as exc:
        raise RuneError(ErrorCode.SCHEMA_VALIDATION_FAILED, str(exc)) from exc

    # A lightweight pre-read of just the manifest id — publish_skill() does
    # the real, full validation itself; this only exists to resolve this
    # skill's own .rune/guardrails.yaml before that call.
    manifest_bytes = drafts.read_file(draft.id, "manifest.yaml")
    manifest_peek = yaml.safe_load(manifest_bytes) if manifest_bytes else {}
    skill_id = manifest_peek.get("id", "") if isinstance(manifest_peek, dict) else ""

    tenant_id = caller.tenant_id or ""
    policy = guardrail_policy_store.get(tenant_id, guardrail_catalog)
    skill_config = parse_skill_guardrail_config(
        drafts.read_file(draft.id, GUARDRAILS_CONFIG_PATH)
    )
    enabled_ids, custom_rules = resolve_guardrails_for_skill(
        tenant_id=tenant_id,
        skill_id=skill_id,
        policy=policy,
        catalog_ids=frozenset(d.id for d in guardrail_catalog),
        skill_config=skill_config,
        custom_rule_store=custom_rule_store,
    )

    pr_url: str | None = None
    release_url: str | None = None
    if draft.repo_url is not None:
        # Same structural + guardrail pre-check validate_draft() runs
        # independently — needed here to get a validated manifest version
        # (for the tag name) and to fail *before* opening a PR, not after.
        # publish_skill() below re-runs this exact scan; that duplication
        # already exists for the Validate button and is accepted as-is.
        try:
            manifest_data, io_schema_data, permissions_data, dependencies_data, files = (
                _load_draft_documents(drafts, draft.id)
            )
            docs = validate_skill_package(
                manifest=manifest_data,
                io_schema=io_schema_data,
                permissions=permissions_data,
                dependencies=dependencies_data,
            )
        except FileNotFoundError as exc:
            raise RuneError(ErrorCode.MISSING_REQUIRED_FILE, str(exc)) from exc

        scan = guardrails_client.scan(
            files=files,
            manifest=docs.manifest,
            permissions=docs.permissions.root,
            dependencies=docs.dependencies.root,
            enabled_check_ids=enabled_ids,
            custom_rules=custom_rules,
        )
        if scan.blocking:
            raise RuneError(
                ErrorCode.GUARDRAIL_VIOLATION,
                "; ".join(f.message for f in scan.blocking),
            )

        connection = github_connections.get(tenant_id)
        if connection is None:
            raise RuneError(ErrorCode.GITHUB_NOT_CONNECTED, "this tenant has not connected GitHub")

        pr = git_sync.open_publish_pr(
            github_api_client,
            connection.access_token,
            owner=draft.git_owner,
            repo=draft.git_repo,
            working_branch=draft.working_branch,
            target_branch=draft.target_branch,
            skill_id=docs.manifest.id,
            version=docs.manifest.version,
        )
        git_sync.merge_publish_pr(
            github_api_client,
            connection.access_token,
            owner=draft.git_owner,
            repo=draft.git_repo,
            number=pr.number,
        )
        release = git_sync.create_release(
            github_api_client,
            connection.access_token,
            owner=draft.git_owner,
            repo=draft.git_repo,
            target_branch=draft.target_branch,
            skill_id=docs.manifest.id,
            version=docs.manifest.version,
            warning_count=len(scan.warnings),
        )
        pr_url = pr.html_url
        release_url = release.html_url

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for name in drafts.list_files(draft.id):
            content = drafts.read_file(draft.id, name)
            if content is None:
                continue
            dest = tmp_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

        keypair = load_or_create_keypair(settings.policy_dir / "signing_key.pem")
        ensure_key_registered(settings.policy_dir, keypair.public_key_pem())
        # Always reload from disk, not the app-wide TrustPolicyDep (which is
        # a fixed snapshot from create_app() time, taken for the artifact
        # download endpoint's high-assurance recheck): `or` can't fall
        # through to this when that snapshot is an empty-but-non-None
        # TrustPolicy() — an empty object is still truthy in Python. This
        # mirrors cli.py's cmd_publish, which never uses the app-level
        # dependency at all for exactly this reason.
        fresh_trust_policy = load_trust_policy(settings.policy_dir)

        try:
            result = publish_skill(
                source_dir=tmp_dir,
                store=store,
                signing_key=keypair,
                trust_policy=fresh_trust_policy,
                actor=caller.user_id or "",
                audit_sink=StructuredLogAuditSink(),
                owner_user=caller.user_id,
                owner_tenant=caller.tenant_id,
                visibility=visibility,
                guardrail_policy=GuardrailPolicy(
                    tenant_id=tenant_id, enabled_check_ids=enabled_ids
                ),
                custom_rules=custom_rules,
                guardrails_client=guardrails_client,
            )
        except FileNotFoundError as exc:
            raise RuneError(ErrorCode.MISSING_REQUIRED_FILE, str(exc)) from exc

    drafts.delete(draft.id)

    # publish_skill() only writes the blob/tag — this app's index is a
    # single in-process InMemoryIndex with no background consumer wired to
    # it (index/consumer.py's IndexEventConsumer exists for a future multi-
    # replica deployment, not this one), so without this the newly
    # published version would be invisible to search/metadata lookups
    # until the next process restart re-runs bootstrap_index().
    index.put(parse_published_record(store.read(result.tag_key)))

    certified_level, level_statuses, warning_ids = flatten_certification(result.certification)
    return DraftPublishResponse(
        id=result.manifest.id,
        version=result.manifest.version,
        digest=result.manifest.digest,
        prUrl=pr_url,
        releaseUrl=release_url,
        guardrailCertifiedLevel=certified_level,
        guardrailLevelStatuses=level_statuses,
        guardrailWarningCheckIds=warning_ids,
    )
