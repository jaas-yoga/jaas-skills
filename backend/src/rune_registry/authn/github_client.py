"""GitHub REST API access for the "Connect GitHub" live repo/branch
picker (api/github_routes.py) — the code-exchange and API-call half of
the flow; see authn/github_oauth.py for the stateless state-signing half.

Also backs drafts/git_sync.py's write-through git mirror (branch/commit/
PR/release calls below) — same client, same tenant-level access token,
just a second consumer.

`GitHubApiClient` is a Protocol, same shape as guardrails/client.py's
`GuardrailsClient` — real HTTP implementation plus a fakeable interface,
so route tests never make a real network call (mirrors
authn/ci_credentials.py's injectable `JwkClient` pattern too).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

import httpx

from rune_registry.common.errors import ErrorCode, RuneError

GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE = "https://api.github.com"

# Repo/branch lists are capped, not searched via GitHub's separate (and
# separately rate-limited) search API — the picker's "type to filter" is a
# client-side substring match over this fetch. Plenty for what an admin
# realistically has to scroll; a tenant with more should use manual entry.
_MAX_REPOS = 200
_MAX_BRANCHES = 200
_PER_PAGE = 100


@dataclass(frozen=True)
class GitHubUser:
    login: str
    avatar_url: str | None


@dataclass(frozen=True)
class GitHubRepo:
    full_name: str
    owner: str
    name: str
    private: bool
    default_branch: str


@dataclass(frozen=True)
class GitHubPullRequest:
    number: int
    html_url: str
    # None means "GitHub hasn't finished computing this yet" — it's
    # calculated asynchronously after creation, so callers that need a
    # real answer must poll get_pull_request rather than trust this at
    # creation time. See drafts/git_sync.py's merge step.
    mergeable: bool | None
    merged: bool = False


@dataclass(frozen=True)
class GitHubRelease:
    html_url: str
    tag_name: str


class GitHubApiClient(Protocol):
    def exchange_code_for_token(
        self, code: str, *, client_id: str, client_secret: str, redirect_uri: str
    ) -> str: ...

    def get_authenticated_user(self, access_token: str) -> GitHubUser: ...

    def list_repos(self, access_token: str) -> list[GitHubRepo]: ...

    def list_branches(self, access_token: str, *, owner: str, repo: str) -> list[str]: ...

    def get_branch_sha(
        self, access_token: str, *, owner: str, repo: str, branch: str
    ) -> str | None: ...

    def create_branch(
        self, access_token: str, *, owner: str, repo: str, branch: str, from_sha: str
    ) -> None: ...

    def bootstrap_empty_repo(
        self, access_token: str, *, owner: str, repo: str, branch: str, changes: dict[str, bytes]
    ) -> str: ...

    def commit_file_changes(
        self,
        access_token: str,
        *,
        owner: str,
        repo: str,
        branch: str,
        base_sha: str,
        changes: dict[str, bytes | None],
        message: str,
    ) -> str: ...

    def create_pull_request(
        self,
        access_token: str,
        *,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> GitHubPullRequest: ...

    def get_pull_request(
        self, access_token: str, *, owner: str, repo: str, number: int
    ) -> GitHubPullRequest: ...

    def merge_pull_request(
        self, access_token: str, *, owner: str, repo: str, number: int
    ) -> str: ...

    def create_release(
        self,
        access_token: str,
        *,
        owner: str,
        repo: str,
        tag_name: str,
        target_commitish: str,
        name: str,
        body: str,
    ) -> GitHubRelease: ...

    def get_public_tree(self, *, owner: str, repo: str, ref: str) -> list[str]: ...

    def get_public_file_content(self, *, owner: str, repo: str, ref: str, path: str) -> bytes: ...


class HttpGitHubApiClient:
    """Stateless aside from `timeout` — client_id/client_secret are passed
    per-call to exchange_code_for_token, not bound at construction, since
    each tenant registers its own GitHub OAuth App
    (authn/github_oauth_apps.py) rather than sharing one deployment-wide
    app. Every other method only ever needs a per-tenant access_token."""

    def __init__(self, *, timeout: float = 10.0):
        self._timeout = timeout

    def _api_error(self, exc: Exception) -> RuneError:
        return RuneError(ErrorCode.GITHUB_API_ERROR, f"GitHub API request failed: {exc}")

    def exchange_code_for_token(
        self, code: str, *, client_id: str, client_secret: str, redirect_uri: str
    ) -> str:
        try:
            resp = httpx.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc

        access_token = body.get("access_token")
        if not access_token:
            raise RuneError(
                ErrorCode.GITHUB_API_ERROR,
                f"GitHub did not return an access token: {body.get('error_description', body)}",
            )
        return access_token

    def _auth_headers(self, access_token: str) -> dict:
        return {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}

    def get_authenticated_user(self, access_token: str) -> GitHubUser:
        try:
            resp = httpx.get(
                f"{GITHUB_API_BASE}/user",
                headers=self._auth_headers(access_token),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return GitHubUser(login=body["login"], avatar_url=body.get("avatar_url"))

    def list_repos(self, access_token: str) -> list[GitHubRepo]:
        repos: list[GitHubRepo] = []
        page = 1
        try:
            while len(repos) < _MAX_REPOS:
                resp = httpx.get(
                    f"{GITHUB_API_BASE}/user/repos",
                    headers=self._auth_headers(access_token),
                    params={
                        "per_page": _PER_PAGE,
                        "page": page,
                        "sort": "updated",
                        "affiliation": "owner,collaborator",
                    },
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                items = resp.json()
                if not items:
                    break
                for item in items:
                    # Only repos this token can actually push to are worth
                    # offering — release-routes.py's repo link is pointless
                    # against a repo the connecting admin can't tag/push.
                    if not item.get("permissions", {}).get("push", False):
                        continue
                    repos.append(
                        GitHubRepo(
                            full_name=item["full_name"],
                            owner=item["owner"]["login"],
                            name=item["name"],
                            private=item["private"],
                            default_branch=item["default_branch"],
                        )
                    )
                if len(items) < _PER_PAGE:
                    break
                page += 1
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return repos[:_MAX_REPOS]

    def list_branches(self, access_token: str, *, owner: str, repo: str) -> list[str]:
        branches: list[str] = []
        page = 1
        try:
            while len(branches) < _MAX_BRANCHES:
                resp = httpx.get(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/branches",
                    headers=self._auth_headers(access_token),
                    params={"per_page": _PER_PAGE, "page": page},
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                items = resp.json()
                if not items:
                    break
                branches.extend(item["name"] for item in items)
                if len(items) < _PER_PAGE:
                    break
                page += 1
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return branches[:_MAX_BRANCHES]

    def get_branch_sha(
        self, access_token: str, *, owner: str, repo: str, branch: str
    ) -> str | None:
        """None covers both "no such branch" (404) and "repo has zero
        commits at all" (409 — GitHub's actual response for any ref lookup
        against a brand-new, empty repo) — callers (drafts/git_sync.py)
        treat both the same way: there's nothing to branch off yet."""
        try:
            resp = httpx.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/ref/heads/{branch}",
                headers=self._auth_headers(access_token),
                timeout=self._timeout,
            )
            if resp.status_code in (404, 409):
                return None
            resp.raise_for_status()
            return resp.json()["object"]["sha"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise self._api_error(exc) from exc

    def bootstrap_empty_repo(
        self, access_token: str, *, owner: str, repo: str, branch: str, changes: dict[str, bytes]
    ) -> str:
        """The very first commit(s) in an otherwise-empty repository.

        This deliberately does NOT use the Git Data API (blobs/trees/
        commits) the way commit_file_changes does — GitHub's Data API
        returns 409 for *any* write against a repository with zero
        commits (there's no tree to build off, and even an empty
        `{"tree": []}` create-tree call 409s). The Contents API
        (`PUT .../contents/{path}`) is the one GitHub endpoint documented
        to handle this: its first call against an empty repo creates
        `branch` from nothing. One call per file in `changes`, in order;
        only the first actually does the bootstrapping, the rest are
        ordinary commits on the now-real branch."""
        headers = self._auth_headers(access_token)
        last_sha: str | None = None
        try:
            for path, content in changes.items():
                resp = httpx.put(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                    headers=headers,
                    json={
                        "message": "Initial commit via JaaS Skills",
                        "content": base64.b64encode(content).decode("ascii"),
                        "branch": branch,
                    },
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                last_sha = resp.json()["commit"]["sha"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise self._api_error(exc) from exc
        if last_sha is None:
            raise RuneError(
                ErrorCode.GITHUB_API_ERROR, "no files given to bootstrap an empty repo with"
            )
        return last_sha

    def create_branch(
        self, access_token: str, *, owner: str, repo: str, branch: str, from_sha: str
    ) -> None:
        try:
            resp = httpx.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/refs",
                headers=self._auth_headers(access_token),
                json={"ref": f"refs/heads/{branch}", "sha": from_sha},
                timeout=self._timeout,
            )
            if resp.status_code == 422:
                raise RuneError(
                    ErrorCode.DRAFT_GIT_BRANCH_EXISTS,
                    f"branch '{branch}' already exists in {owner}/{repo}",
                )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise self._api_error(exc) from exc

    def _get_commit_tree_sha(self, access_token: str, *, owner: str, repo: str, sha: str) -> str:
        resp = httpx.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/commits/{sha}",
            headers=self._auth_headers(access_token),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["tree"]["sha"]

    def commit_file_changes(
        self,
        access_token: str,
        *,
        owner: str,
        repo: str,
        branch: str,
        base_sha: str,
        changes: dict[str, bytes | None],
        message: str,
    ) -> str:
        """Blob -> tree -> commit -> ref update, atomically covering every
        path in `changes` in one commit (a `None` value removes that path).
        This is the Git Data API, not the simpler single-file Contents API,
        specifically so a save touching several files never produces
        several separate commits."""
        headers = self._auth_headers(access_token)
        try:
            base_tree_sha = self._get_commit_tree_sha(
                access_token, owner=owner, repo=repo, sha=base_sha
            )

            entries = []
            for path, content in changes.items():
                if content is None:
                    entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                    continue
                blob_resp = httpx.post(
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/blobs",
                    headers=headers,
                    json={
                        "content": base64.b64encode(content).decode("ascii"),
                        "encoding": "base64",
                    },
                    timeout=self._timeout,
                )
                blob_resp.raise_for_status()
                entries.append(
                    {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_resp.json()["sha"],
                    }
                )

            tree_resp = httpx.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees",
                headers=headers,
                json={"base_tree": base_tree_sha, "tree": entries},
                timeout=self._timeout,
            )
            tree_resp.raise_for_status()
            new_tree_sha = tree_resp.json()["sha"]

            commit_resp = httpx.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/commits",
                headers=headers,
                json={"message": message, "tree": new_tree_sha, "parents": [base_sha]},
                timeout=self._timeout,
            )
            commit_resp.raise_for_status()
            new_commit_sha = commit_resp.json()["sha"]

            ref_resp = httpx.patch(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/refs/heads/{branch}",
                headers=headers,
                json={"sha": new_commit_sha},
                timeout=self._timeout,
            )
            ref_resp.raise_for_status()
            return new_commit_sha
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise self._api_error(exc) from exc

    def create_pull_request(
        self,
        access_token: str,
        *,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> GitHubPullRequest:
        try:
            resp = httpx.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls",
                headers=self._auth_headers(access_token),
                json={"head": head, "base": base, "title": title, "body": body},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return GitHubPullRequest(
            number=data["number"], html_url=data["html_url"], mergeable=data.get("mergeable")
        )

    def get_pull_request(
        self, access_token: str, *, owner: str, repo: str, number: int
    ) -> GitHubPullRequest:
        try:
            resp = httpx.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}",
                headers=self._auth_headers(access_token),
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return GitHubPullRequest(
            number=data["number"],
            html_url=data["html_url"],
            mergeable=data.get("mergeable"),
            merged=data.get("merged", False),
        )

    def merge_pull_request(
        self, access_token: str, *, owner: str, repo: str, number: int
    ) -> str:
        try:
            resp = httpx.put(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/merge",
                headers=self._auth_headers(access_token),
                json={"merge_method": "squash"},
                timeout=self._timeout,
            )
            if resp.status_code in (405, 409):
                raise RuneError(
                    ErrorCode.DRAFT_GIT_MERGE_CONFLICT,
                    f"pull request #{number} could not be merged automatically",
                    details={"prNumber": number},
                )
            resp.raise_for_status()
            return resp.json()["sha"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise self._api_error(exc) from exc

    def create_release(
        self,
        access_token: str,
        *,
        owner: str,
        repo: str,
        tag_name: str,
        target_commitish: str,
        name: str,
        body: str,
    ) -> GitHubRelease:
        try:
            resp = httpx.post(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases",
                headers=self._auth_headers(access_token),
                json={
                    "tag_name": tag_name,
                    "target_commitish": target_commitish,
                    "name": name,
                    "body": body,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return GitHubRelease(html_url=data["html_url"], tag_name=data["tag_name"])

    def get_public_tree(self, *, owner: str, repo: str, ref: str) -> list[str]:
        """Unauthenticated by design, unlike every other method on this
        client — this backs read-only "browse the source repo" on a
        *published* skill page. Using a stored owner access token here
        would let a public skill page leak a private repo's full file
        listing to any viewer, regardless of whether they have GitHub
        access to it; going through the public API means a private repo
        (or a bad ref) just surfaces as unavailable instead."""
        try:
            resp = httpx.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{ref}",
                params={"recursive": "1"},
                headers={"Accept": "application/vnd.github+json"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        return sorted(item["path"] for item in data.get("tree", []) if item.get("type") == "blob")

    def get_public_file_content(self, *, owner: str, repo: str, ref: str, path: str) -> bytes:
        """Unauthenticated counterpart to get_public_tree — same reasoning
        applies."""
        try:
            resp = httpx.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref},
                headers={"Accept": "application/vnd.github+json"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._api_error(exc) from exc
        if data.get("encoding") != "base64" or "content" not in data:
            raise self._api_error(ValueError(f"unexpected content response for '{path}'"))
        return base64.b64decode(data["content"])
