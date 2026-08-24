"""Write-through git mirror for repo-connected drafts. Plan ref: "Git-Backed
Draft Storage" (2026-08-09).

Local disk (drafts/store.py) stays the source of truth for reads — this
module only pushes local writes out to GitHub as real commits, and drives
the publish-time PR/merge/release sequence. Every function here is a thin
orchestration layer over authn/github_client.py's `GitHubApiClient`; no
HTTP happens directly in this file.
"""

from __future__ import annotations

import re
import time

import yaml

from jaas_registry.authn.github_client import GitHubApiClient, GitHubPullRequest, GitHubRelease
from jaas_registry.common.errors import ErrorCode, JaasError

# https://github.com/acme/tool-x(.git)? -> ("acme", "tool-x") — same shape
# as repo-links-editor.tsx's client-side parseGithubRepoUrl, kept in sync
# deliberately since both only ever accept this one URL form.
_GITHUB_URL_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")

_MERGEABILITY_POLL_ATTEMPTS = 5
_MERGEABILITY_POLL_DELAY_SECONDS = 1.0

_UNSAFE_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9_-]+")

# Defensive caps on the *derived* nested path, not on id format itself
# (validation/models.py's ID_PATTERN is the source of truth for what a
# published id may look like, and allows unlimited dot-segments) — this
# function runs on manifest.yaml content that hasn't necessarily passed
# that validation yet, so a pathological or hostile id must degrade to
# `fallback` rather than produce something unsafe or unwieldy. 180 chars
# leaves headroom under Windows' ~260-char MAX_PATH once a repo checkout
# prefix and a skill's own nested filenames are added on top.
_MAX_DIRECTORY_DEPTH = 6
_MAX_DIRECTORY_LENGTH = 180


def parse_github_repo_url(url: str) -> tuple[str, str]:
    match = _GITHUB_URL_RE.match(url)
    if not match:
        raise JaasError(ErrorCode.SCHEMA_VALIDATION_FAILED, f"not a GitHub repo URL: '{url}'")
    return match.group(1), match.group(2)


def skill_directory_name(manifest_bytes: bytes | None, *, fallback: str) -> str:
    """The subdirectory a draft's files live under once committed — lets one
    repo host several skills (each in its own folder) instead of every
    draft dumping its files at the repo root and colliding. Derived from
    manifest.yaml's own `id`, split on '.' into real nested path segments
    (e.g. id `acme.hr.leave-balance` -> directory `acme/hr/leave-balance`)
    so skills sharing a vendor/domain prefix nest under a shared parent
    folder instead of each getting an opaque dotted top-level name.
    `fallback` (the draft's own id suffix, always a single flat segment)
    covers a manifest that's missing, unparsable, hasn't had its id set
    yet, or whose id can't be turned into a safe path (see below).

    manifest.yaml is arbitrary user-edited draft content read *before*
    publish-time validation ever runs, so `id` cannot be trusted to already
    satisfy ID_PATTERN — this must defend itself. Each dot-separated piece
    is sanitized independently, and the whole thing falls back to `fallback`
    (rather than emitting a partially-cleaned path) if any piece is empty
    or resolves to '.'/'..' after cleaning (both would otherwise be a real
    directory-traversal/collapse hazard once dots become path separators),
    or if the id has too many segments or is too long overall.

    Fixed once at connect/migrate time — a later id rename in manifest.yaml
    does *not* rename the git folder too (that would mean moving already-
    published history), so the directory name can drift from the current id
    over time. This mirrors the already-accepted "no distributed rollback"
    posture elsewhere in this write-through mirror."""
    if manifest_bytes is not None:
        try:
            data = yaml.safe_load(manifest_bytes)
        except yaml.YAMLError:
            data = None
        candidate = data.get("id") if isinstance(data, dict) else None
        if isinstance(candidate, str):
            segments: list[str] = []
            for raw_segment in candidate.strip().split("."):
                cleaned = _UNSAFE_SEGMENT_CHARS.sub("-", raw_segment).strip("-")
                if not cleaned or cleaned in (".", ".."):
                    segments = []
                    break
                segments.append(cleaned)
            if segments and len(segments) <= _MAX_DIRECTORY_DEPTH:
                directory = "/".join(segments)
                if len(directory) <= _MAX_DIRECTORY_LENGTH:
                    return directory
    return fallback


def prefix_changes(changes: dict[str, bytes | None], directory: str) -> dict[str, bytes | None]:
    return {f"{directory}/{path}": content for path, content in changes.items()}


def create_working_branch(
    client: GitHubApiClient,
    access_token: str,
    *,
    owner: str,
    repo: str,
    target_branch: str,
    working_branch: str,
    seed_changes: dict[str, bytes],
    allow_empty_repo_init: bool = False,
) -> tuple[str, bool]:
    """Branches `working_branch` off `target_branch`'s current head.
    Raises DRAFT_GIT_BRANCH_EXISTS (via the client) if the name collides —
    the caller (api/draft_routes.py) rolls the whole draft creation back
    on any failure here, so a partial branch is never left dangling.

    A brand-new repo has no commits at all, so `target_branch` itself
    doesn't exist yet — `get_branch_sha` returns None for that. Rather than
    silently creating one, this raises DRAFT_GIT_EMPTY_REPO unless the
    caller has already gotten explicit admin confirmation
    (`allow_empty_repo_init=True`, from CreateDraftGitRequest.
    confirmInitializeEmptyRepo), in which case `seed_changes` becomes the
    repo's very first commit (via bootstrap_empty_repo — GitHub's Git Data
    API can't write to a repo with zero commits at all, so this can't go
    through the same blob/tree/commit path commit_files uses).

    Returns (sha, seeded): `seeded` is True only for the empty-repo path,
    telling the caller `seed_changes` are already committed as of `sha` —
    calling commit_files() with the same changes again would be a
    redundant, content-identical commit."""
    base_sha = client.get_branch_sha(access_token, owner=owner, repo=repo, branch=target_branch)
    if base_sha is None:
        if not allow_empty_repo_init:
            raise JaasError(
                ErrorCode.DRAFT_GIT_EMPTY_REPO,
                f"'{owner}/{repo}' has no commits yet on '{target_branch}'",
            )
        base_sha = client.bootstrap_empty_repo(
            access_token, owner=owner, repo=repo, branch=target_branch, changes=seed_changes
        )
        client.create_branch(
            access_token, owner=owner, repo=repo, branch=working_branch, from_sha=base_sha
        )
        return base_sha, True
    client.create_branch(
        access_token, owner=owner, repo=repo, branch=working_branch, from_sha=base_sha
    )
    return base_sha, False


def commit_files(
    client: GitHubApiClient,
    access_token: str,
    *,
    owner: str,
    repo: str,
    branch: str,
    changes: dict[str, bytes | None],
    message: str,
) -> str:
    """One atomic commit covering every path in `changes` (None = delete).
    Always re-reads the branch's current head first, so this is safe to
    call repeatedly without the caller tracking the previous sha itself."""
    base_sha = client.get_branch_sha(access_token, owner=owner, repo=repo, branch=branch)
    if base_sha is None:
        # Shouldn't happen in practice — create_working_branch() above
        # always establishes `branch` with a real commit before this is
        # ever called — but a clear error beats a confusing 404 from
        # commit_file_changes building a URL with a None sha in it.
        raise JaasError(
            ErrorCode.DRAFT_GIT_SYNC_FAILED, f"branch '{branch}' does not exist in {owner}/{repo}"
        )
    return client.commit_file_changes(
        access_token,
        owner=owner,
        repo=repo,
        branch=branch,
        base_sha=base_sha,
        changes=changes,
        message=message,
    )


def open_publish_pr(
    client: GitHubApiClient,
    access_token: str,
    *,
    owner: str,
    repo: str,
    working_branch: str,
    target_branch: str,
    skill_id: str,
    version: str,
) -> GitHubPullRequest:
    return client.create_pull_request(
        access_token,
        owner=owner,
        repo=repo,
        head=working_branch,
        base=target_branch,
        title=f"Publish {skill_id}@{version}",
        body="Opened automatically by JaaS Skills on publish.",
    )


def merge_publish_pr(
    client: GitHubApiClient, access_token: str, *, owner: str, repo: str, number: int
) -> str:
    """Polls mergeability briefly (GitHub computes it asynchronously right
    after PR creation, so an immediate merge attempt can spuriously look
    unmergeable) then merges (squash). Raises DRAFT_GIT_MERGE_CONFLICT,
    with the PR left open, if it genuinely can't be merged — the caller
    must not delete the draft in that case."""
    pr = client.get_pull_request(access_token, owner=owner, repo=repo, number=number)
    attempts = 1
    while pr.mergeable is None and attempts < _MERGEABILITY_POLL_ATTEMPTS:
        time.sleep(_MERGEABILITY_POLL_DELAY_SECONDS)
        pr = client.get_pull_request(access_token, owner=owner, repo=repo, number=number)
        attempts += 1

    if pr.mergeable is False:
        raise JaasError(
            ErrorCode.DRAFT_GIT_MERGE_CONFLICT,
            f"pull request #{number} has conflicts with {owner}/{repo}",
            details={"prNumber": number, "prUrl": pr.html_url},
        )

    try:
        return client.merge_pull_request(access_token, owner=owner, repo=repo, number=number)
    except JaasError as exc:
        if exc.code == ErrorCode.DRAFT_GIT_MERGE_CONFLICT:
            raise JaasError(
                exc.code, exc.message, details={**exc.details, "prUrl": pr.html_url}
            ) from exc
        raise


def create_release(
    client: GitHubApiClient,
    access_token: str,
    *,
    owner: str,
    repo: str,
    target_branch: str,
    skill_id: str,
    version: str,
    warning_count: int,
) -> GitHubRelease:
    tag_name = f"v{version}"
    return client.create_release(
        access_token,
        owner=owner,
        repo=repo,
        tag_name=tag_name,
        target_commitish=target_branch,
        name=f"{skill_id} {tag_name}",
        body=(
            f"Published via JaaS Skills. Guardrail scan passed with 0 blocking "
            f"findings, {warning_count} warning(s)."
        ),
    )
