"""Unit tests for HttpGitHubApiClient — monkeypatches httpx.get/post module-
level functions, same style test_cli_release.py already uses for httpx, so
no real network call is ever made."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from rune_registry.authn.github_client import GitHubRepo, GitHubUser, HttpGitHubApiClient
from rune_registry.common.errors import ErrorCode, RuneError


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


@pytest.fixture
def api_client():
    return HttpGitHubApiClient()


class TestExchangeCodeForToken:
    def test_returns_the_access_token(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.post", lambda *a, **k: _FakeResponse(200, {"access_token": "gho_abc"})
        )

        token = api_client.exchange_code_for_token(
            "code123", client_id="cid", client_secret="csecret", redirect_uri="https://x/cb"
        )

        assert token == "gho_abc"

    def test_raises_when_github_returns_an_error_body(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.post",
            lambda *a, **k: _FakeResponse(
                200, {"error": "bad_verification_code", "error_description": "expired"}
            ),
        )

        with pytest.raises(RuneError, match="did not return an access token"):
            api_client.exchange_code_for_token(
                "code123", client_id="cid", client_secret="csecret", redirect_uri="https://x/cb"
            )

    def test_raises_on_http_error(self, api_client, monkeypatch):
        def _raise(*a, **k):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr("httpx.post", _raise)

        with pytest.raises(RuneError, match="GitHub API request failed"):
            api_client.exchange_code_for_token(
                "code123", client_id="cid", client_secret="csecret", redirect_uri="https://x/cb"
            )


class TestGetAuthenticatedUser:
    def test_parses_login_and_avatar(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.get",
            lambda *a, **k: _FakeResponse(
                200, {"login": "octocat", "avatar_url": "https://avatars.example/octocat.png"}
            ),
        )

        user = api_client.get_authenticated_user("gho_abc")

        assert user == GitHubUser(login="octocat", avatar_url="https://avatars.example/octocat.png")


def _repo(full_name, *, push=True):
    owner, name = full_name.split("/")
    return {
        "full_name": full_name,
        "owner": {"login": owner},
        "name": name,
        "private": False,
        "default_branch": "main",
        "permissions": {"push": push},
    }


class TestListRepos:
    def test_filters_out_repos_without_push_access(self, api_client, monkeypatch):
        page_1 = [_repo("acme/tool-x", push=True), _repo("acme/read-only", push=False)]
        monkeypatch.setattr("httpx.get", lambda *a, **k: _FakeResponse(200, page_1))

        repos = api_client.list_repos("gho_abc")

        assert repos == [
            GitHubRepo(full_name="acme/tool-x", owner="acme", name="tool-x", private=False,
                       default_branch="main")
        ]

    def test_stops_paginating_on_a_short_page(self, api_client, monkeypatch):
        calls = {"n": 0}

        def fake_get(url, *, headers, params, timeout):
            calls["n"] += 1
            if params["page"] == 1:
                return _FakeResponse(200, [_repo(f"acme/r{i}") for i in range(100)])
            return _FakeResponse(200, [_repo("acme/last")])

        monkeypatch.setattr("httpx.get", fake_get)

        repos = api_client.list_repos("gho_abc")

        assert calls["n"] == 2
        assert len(repos) == 101

    def test_raises_on_http_error(self, api_client, monkeypatch):
        def _raise(*a, **k):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr("httpx.get", _raise)

        with pytest.raises(RuneError, match="GitHub API request failed"):
            api_client.list_repos("gho_abc")


class TestListBranches:
    def test_returns_branch_names(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.get",
            lambda *a, **k: _FakeResponse(200, [{"name": "main"}, {"name": "staging"}]),
        )

        branches = api_client.list_branches("gho_abc", owner="acme", repo="tool-x")

        assert branches == ["main", "staging"]

    def test_stops_paginating_on_a_short_page(self, api_client, monkeypatch):
        calls = {"n": 0}

        def fake_get(url, *, headers, params, timeout):
            calls["n"] += 1
            if params["page"] == 1:
                return _FakeResponse(200, [{"name": f"b{i}"} for i in range(100)])
            return _FakeResponse(200, [{"name": "last"}])

        monkeypatch.setattr("httpx.get", fake_get)

        branches = api_client.list_branches("gho_abc", owner="acme", repo="tool-x")

        assert calls["n"] == 2
        assert len(branches) == 101


class TestGetBranchSha:
    def test_returns_the_head_sha(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.get", lambda *a, **k: _FakeResponse(200, {"object": {"sha": "abc123"}})
        )

        sha = api_client.get_branch_sha("gho_abc", owner="acme", repo="tool-x", branch="main")

        assert sha == "abc123"

    def test_returns_none_when_the_branch_does_not_exist(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.get", lambda *a, **k: _FakeResponse(404, {"message": "Not Found"})
        )

        sha = api_client.get_branch_sha("gho_abc", owner="acme", repo="tool-x", branch="main")

        assert sha is None

    def test_returns_none_when_the_repo_is_empty(self, api_client, monkeypatch):
        # GitHub's actual response for any ref lookup against a repo with
        # zero commits — distinct from a 404, but means the same thing here.
        monkeypatch.setattr(
            "httpx.get", lambda *a, **k: _FakeResponse(409, {"message": "Git Repository is empty."})
        )

        sha = api_client.get_branch_sha("gho_abc", owner="acme", repo="tool-x", branch="main")

        assert sha is None


class TestBootstrapEmptyRepo:
    def test_creates_one_file_per_change_via_the_contents_api(self, api_client, monkeypatch):
        calls = []

        def fake_put(url, *, headers, json, timeout):
            calls.append((url, json))
            return _FakeResponse(201, {"commit": {"sha": f"sha-for-{url.split('/')[-1]}"}})

        monkeypatch.setattr("httpx.put", fake_put)

        sha = api_client.bootstrap_empty_repo(
            "gho_abc",
            owner="acme",
            repo="tool-x",
            branch="main",
            changes={"manifest.yaml": b"id: x"},
        )

        assert sha == "sha-for-manifest.yaml"
        assert len(calls) == 1
        url, body = calls[0]
        assert url.endswith("/repos/acme/tool-x/contents/manifest.yaml")
        assert body["branch"] == "main"
        assert base64.b64decode(body["content"]) == b"id: x"

    def test_raises_when_given_no_files(self, api_client):
        with pytest.raises(RuneError, match="no files"):
            api_client.bootstrap_empty_repo(
                "gho_abc", owner="acme", repo="tool-x", branch="main", changes={}
            )

    def test_raises_on_http_error(self, api_client, monkeypatch):
        def _raise(*a, **k):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr("httpx.put", _raise)

        with pytest.raises(RuneError, match="GitHub API request failed"):
            api_client.bootstrap_empty_repo(
                "gho_abc",
                owner="acme",
                repo="tool-x",
                branch="main",
                changes={"manifest.yaml": b"id: x"},
            )


class TestCreateBranch:
    def test_raises_branch_exists_on_422(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.post", lambda *a, **k: _FakeResponse(422, {"message": "already exists"})
        )

        with pytest.raises(RuneError) as exc_info:
            api_client.create_branch(
                "gho_abc", owner="acme", repo="tool-x", branch="rune/draft/x", from_sha="abc123"
            )

        assert exc_info.value.code == ErrorCode.DRAFT_GIT_BRANCH_EXISTS

    def test_succeeds_on_201(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.post", lambda *a, **k: _FakeResponse(201, {"ref": "refs/heads/x"})
        )

        api_client.create_branch(
            "gho_abc", owner="acme", repo="tool-x", branch="x", from_sha="abc123"
        )


class TestCommitFileChanges:
    def test_builds_blob_tree_commit_and_updates_ref(self, api_client, monkeypatch):
        calls = []

        def fake_get(url, *, headers, timeout):
            calls.append(("GET", url))
            return _FakeResponse(200, {"tree": {"sha": "base-tree-sha"}})

        def fake_post(url, *, headers, json, timeout):
            calls.append(("POST", url, json))
            if url.endswith("/git/blobs"):
                return _FakeResponse(201, {"sha": "blob-sha-1"})
            if url.endswith("/git/trees"):
                return _FakeResponse(201, {"sha": "new-tree-sha"})
            if url.endswith("/git/commits"):
                return _FakeResponse(201, {"sha": "new-commit-sha"})
            raise AssertionError(f"unexpected POST {url}")

        def fake_patch(url, *, headers, json, timeout):
            calls.append(("PATCH", url, json))
            return _FakeResponse(200, {"ref": "refs/heads/main"})

        monkeypatch.setattr("httpx.get", fake_get)
        monkeypatch.setattr("httpx.post", fake_post)
        monkeypatch.setattr("httpx.patch", fake_patch)

        sha = api_client.commit_file_changes(
            "gho_abc",
            owner="acme",
            repo="tool-x",
            branch="main",
            base_sha="base-commit-sha",
            changes={"manifest.yaml": b"id: x", "old.yaml": None},
            message="Update",
        )

        assert sha == "new-commit-sha"
        tree_call = next(c for c in calls if c[0] == "POST" and c[1].endswith("/git/trees"))
        entries = tree_call[2]["tree"]
        assert {
            "path": "manifest.yaml",
            "mode": "100644",
            "type": "blob",
            "sha": "blob-sha-1",
        } in entries
        assert {"path": "old.yaml", "mode": "100644", "type": "blob", "sha": None} in entries
        assert tree_call[2]["base_tree"] == "base-tree-sha"
        patch_call = next(c for c in calls if c[0] == "PATCH")
        assert patch_call[2]["sha"] == "new-commit-sha"


class TestCreatePullRequest:
    def test_parses_pr_fields(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.post",
            lambda *a, **k: _FakeResponse(
                201,
                {
                    "number": 7,
                    "html_url": "https://github.com/acme/tool-x/pull/7",
                    "mergeable": None,
                },
            ),
        )

        pr = api_client.create_pull_request(
            "gho_abc", owner="acme", repo="tool-x", head="h", base="b", title="t", body="b"
        )

        assert pr.number == 7
        assert pr.mergeable is None


class TestMergePullRequest:
    def test_raises_merge_conflict_on_405(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.put", lambda *a, **k: _FakeResponse(405, {"message": "not mergeable"})
        )

        with pytest.raises(RuneError) as exc_info:
            api_client.merge_pull_request("gho_abc", owner="acme", repo="tool-x", number=1)

        assert exc_info.value.code == ErrorCode.DRAFT_GIT_MERGE_CONFLICT

    def test_returns_merge_sha_on_success(self, api_client, monkeypatch):
        monkeypatch.setattr("httpx.put", lambda *a, **k: _FakeResponse(200, {"sha": "merge-sha"}))

        sha = api_client.merge_pull_request("gho_abc", owner="acme", repo="tool-x", number=1)

        assert sha == "merge-sha"


class TestCreateRelease:
    def test_creates_a_release(self, api_client, monkeypatch):
        monkeypatch.setattr(
            "httpx.post",
            lambda *a, **k: _FakeResponse(
                201,
                {
                    "html_url": "https://github.com/acme/tool-x/releases/tag/v1.0.0",
                    "tag_name": "v1.0.0",
                },
            ),
        )

        release = api_client.create_release(
            "gho_abc",
            owner="acme",
            repo="tool-x",
            tag_name="v1.0.0",
            target_commitish="main",
            name="tool-x v1.0.0",
            body="notes",
        )

        assert release.tag_name == "v1.0.0"
