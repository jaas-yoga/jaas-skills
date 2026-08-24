"""In-memory fake implementing GitHubApiClient's full Protocol (including
the drafts/git_sync.py-facing branch/commit/PR/release methods) — used by
both unit tests for git_sync.py and integration tests for the git-backed
draft routes. No real network call is ever made.
"""

from __future__ import annotations

from rune_registry.authn.github_client import GitHubPullRequest, GitHubRelease
from rune_registry.common.errors import ErrorCode, RuneError


class FakeGitHubApiClient:
    def __init__(self):
        # branch name -> "commit sha" (just an incrementing fake token)
        self.branches: dict[str, str] = {}
        # branch name -> {path: content}, mirrors what real git would hold
        self.file_contents: dict[str, dict[str, bytes]] = {}
        self.commit_log: list[tuple[str, str]] = []  # (branch, message)
        self._sha_counter = 0
        self.pull_requests: dict[int, dict] = {}
        self._pr_counter = 0
        self.releases: list[dict] = []
        # Test knobs
        self.mergeable: bool | None = True
        self.mergeable_after_polls: int = 0  # None until this many get_pull_request calls
        self.fail_commit_with: RuneError | None = None
        # ref -> {path: content} — separate from `branches`/`file_contents`
        # above (those model the OAuth-authenticated write path); this
        # models the unauthenticated public-read surface used by the
        # published-skill "browse source at tag" feature. A ref with no
        # entry here behaves like a private/unreachable repo.
        self.public_source: dict[str, dict[str, bytes]] = {}

    def seed_public_source(self, ref: str, files: dict[str, bytes]) -> None:
        self.public_source[ref] = dict(files)

    def seed_branch(self, branch: str, *, files: dict[str, bytes] | None = None) -> str:
        sha = self._next_sha()
        self.branches[branch] = sha
        self.file_contents[branch] = dict(files or {})
        return sha

    def _next_sha(self) -> str:
        self._sha_counter += 1
        return f"sha{self._sha_counter}"

    # -- branch/commit surface used by drafts/git_sync.py --

    def get_branch_sha(
        self, access_token: str, *, owner: str, repo: str, branch: str
    ) -> str | None:
        return self.branches.get(branch)

    def bootstrap_empty_repo(
        self, access_token: str, *, owner: str, repo: str, branch: str, changes: dict[str, bytes]
    ) -> str:
        sha = self._next_sha()
        self.branches[branch] = sha
        self.file_contents[branch] = dict(changes)
        return sha

    def create_branch(
        self, access_token: str, *, owner: str, repo: str, branch: str, from_sha: str
    ) -> None:
        if branch in self.branches:
            raise RuneError(
                ErrorCode.DRAFT_GIT_BRANCH_EXISTS, f"branch '{branch}' already exists"
            )
        source = next((b for b, sha in self.branches.items() if sha == from_sha), None)
        self.branches[branch] = from_sha
        self.file_contents[branch] = dict(self.file_contents.get(source, {})) if source else {}

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
        if self.fail_commit_with is not None:
            raise self.fail_commit_with
        contents = self.file_contents.setdefault(branch, {})
        for path, content in changes.items():
            if content is None:
                contents.pop(path, None)
            else:
                contents[path] = content
        new_sha = self._next_sha()
        self.branches[branch] = new_sha
        self.commit_log.append((branch, message))
        return new_sha

    # -- PR/release surface used by drafts/git_sync.py --

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
        self._pr_counter += 1
        number = self._pr_counter
        self.pull_requests[number] = {"head": head, "base": base, "polls": 0, "merged": False}
        return GitHubPullRequest(
            number=number,
            html_url=f"https://github.com/{owner}/{repo}/pull/{number}",
            mergeable=None,
        )

    def get_pull_request(
        self, access_token: str, *, owner: str, repo: str, number: int
    ) -> GitHubPullRequest:
        pr = self.pull_requests[number]
        pr["polls"] += 1
        mergeable = self.mergeable if pr["polls"] >= self.mergeable_after_polls else None
        return GitHubPullRequest(
            number=number,
            html_url=f"https://github.com/{owner}/{repo}/pull/{number}",
            mergeable=mergeable,
            merged=pr["merged"],
        )

    def merge_pull_request(
        self, access_token: str, *, owner: str, repo: str, number: int
    ) -> str:
        if self.mergeable is False:
            raise RuneError(
                ErrorCode.DRAFT_GIT_MERGE_CONFLICT,
                f"pull request #{number} could not be merged automatically",
                details={"prNumber": number},
            )
        pr = self.pull_requests[number]
        pr["merged"] = True
        merge_sha = self._next_sha()
        base_branch = pr["base"]
        self.branches[base_branch] = merge_sha
        self.file_contents[base_branch] = dict(self.file_contents.get(pr["head"], {}))
        return merge_sha

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
        self.releases.append(
            {
                "tag_name": tag_name,
                "target_commitish": target_commitish,
                "name": name,
                "body": body,
            }
        )
        return GitHubRelease(
            html_url=f"https://github.com/{owner}/{repo}/releases/tag/{tag_name}",
            tag_name=tag_name,
        )

    # -- unused-by-git_sync but required to satisfy GitHubApiClient callers
    # that pass this fake through api/deps.py's GitHubApiClientDep more
    # broadly (e.g. draft_routes.py's create-draft path also touches
    # nothing else) --

    def exchange_code_for_token(
        self, code: str, *, client_id: str, client_secret: str, redirect_uri: str
    ) -> str:
        raise NotImplementedError

    def get_authenticated_user(self, access_token: str):
        raise NotImplementedError

    def list_repos(self, access_token: str):
        raise NotImplementedError

    def list_branches(self, access_token: str, *, owner: str, repo: str):
        raise NotImplementedError

    def get_public_tree(self, *, owner: str, repo: str, ref: str) -> list[str]:
        files = self.public_source.get(ref)
        if files is None:
            raise RuneError(ErrorCode.GITHUB_API_ERROR, f"ref '{ref}' not found or not public")
        return sorted(files)

    def get_public_file_content(self, *, owner: str, repo: str, ref: str, path: str) -> bytes:
        files = self.public_source.get(ref)
        if files is None or path not in files:
            raise RuneError(ErrorCode.GITHUB_API_ERROR, f"'{path}' not found at ref '{ref}'")
        return files[path]
