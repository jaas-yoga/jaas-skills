"""Unit tests for drafts/git_sync.py's orchestration functions, against
FakeGitHubApiClient — no real network calls, no FastAPI involved."""

from __future__ import annotations

import pytest

from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.drafts import git_sync
from tests.fixtures.fake_github_client import FakeGitHubApiClient


class TestParseGithubRepoUrl:
    def test_parses_owner_and_repo(self):
        assert git_sync.parse_github_repo_url("https://github.com/acme/tool-x") == (
            "acme",
            "tool-x",
        )

    def test_strips_dot_git_suffix(self):
        assert git_sync.parse_github_repo_url("https://github.com/acme/tool-x.git") == (
            "acme",
            "tool-x",
        )

    def test_rejects_a_non_github_url(self):
        with pytest.raises(JaasError, match="not a GitHub repo URL"):
            git_sync.parse_github_repo_url("https://bitbucket.org/acme/tool-x")


class TestSkillDirectoryName:
    def test_splits_a_dotted_id_into_nested_segments(self):
        manifest = b"id: acme.hr.leave-balance\nversion: 1.0.0\n"
        assert (
            git_sync.skill_directory_name(manifest, fallback="fb")
            == "acme/hr/leave-balance"
        )

    def test_sibling_ids_nest_under_a_shared_parent(self):
        leave = git_sync.skill_directory_name(b"id: acme.hr.leave-balance\n", fallback="fb")
        timesheet = git_sync.skill_directory_name(b"id: acme.hr.timesheet\n", fallback="fb")
        assert leave == "acme/hr/leave-balance"
        assert timesheet == "acme/hr/timesheet"

    def test_sanitizes_unsafe_characters_per_segment(self):
        manifest = b"id: 'acme.hr dept.leave balance!'\n"
        assert (
            git_sync.skill_directory_name(manifest, fallback="fb")
            == "acme/hr-dept/leave-balance"
        )

    def test_missing_manifest_uses_fallback(self):
        assert git_sync.skill_directory_name(None, fallback="fb") == "fb"

    def test_unparsable_manifest_uses_fallback(self):
        assert git_sync.skill_directory_name(b"not: [valid yaml\n", fallback="fb") == "fb"

    def test_missing_id_field_uses_fallback(self):
        assert git_sync.skill_directory_name(b"version: 1.0.0\n", fallback="fb") == "fb"

    def test_empty_segment_from_consecutive_dots_uses_fallback(self):
        assert git_sync.skill_directory_name(b"id: acme..leave-balance\n", fallback="fb") == "fb"

    def test_empty_segment_from_leading_dot_uses_fallback(self):
        assert git_sync.skill_directory_name(b"id: .acme.leave-balance\n", fallback="fb") == "fb"

    def test_empty_segment_from_trailing_dot_uses_fallback(self):
        assert git_sync.skill_directory_name(b"id: acme.leave-balance.\n", fallback="fb") == "fb"

    def test_segment_collapsing_to_dot_dot_uses_fallback(self):
        # '-' is stripped from both ends of each cleaned segment, so a
        # segment of bare dashes collapses to '' (caught by the empty
        # check) and a segment like '..' can never survive as literal
        # dots (dots are the split delimiter, never segment content) —
        # this exercises the explicit '..'/'.' guard defensively in case
        # a future sanitizer change ever lets one through.
        assert git_sync.skill_directory_name(b"id: acme.--.leave-balance\n", fallback="fb") == "fb"

    def test_too_many_segments_uses_fallback(self):
        manifest = b"id: a.b.c.d.e.f.g\n"
        assert git_sync.skill_directory_name(manifest, fallback="fb") == "fb"

    def test_at_max_segments_is_allowed(self):
        manifest = b"id: a.b.c.d.e.f\n"
        assert git_sync.skill_directory_name(manifest, fallback="fb") == "a/b/c/d/e/f"

    def test_overly_long_path_uses_fallback(self):
        segment = "x" * 50
        manifest = f"id: {segment}.{segment}.{segment}.{segment}\n".encode()
        assert git_sync.skill_directory_name(manifest, fallback="fb") == "fb"


class TestCreateWorkingBranch:
    def test_branches_off_the_target_branchs_head(self):
        client = FakeGitHubApiClient()
        client.seed_branch("main", files={"manifest.yaml": b"id: x"})

        sha, seeded = git_sync.create_working_branch(
            client, "tok", owner="acme", repo="tool-x", target_branch="main",
            working_branch="jaas/draft/abc", seed_changes={},
        )

        assert sha == client.branches["main"]
        assert seeded is False
        assert client.branches["jaas/draft/abc"] == sha
        assert client.file_contents["jaas/draft/abc"] == {"manifest.yaml": b"id: x"}

    def test_raises_when_the_branch_name_already_exists(self):
        client = FakeGitHubApiClient()
        client.seed_branch("main")
        client.seed_branch("jaas/draft/abc")

        with pytest.raises(JaasError) as exc_info:
            git_sync.create_working_branch(
                client, "tok", owner="acme", repo="tool-x", target_branch="main",
                working_branch="jaas/draft/abc", seed_changes={},
            )
        assert exc_info.value.code == ErrorCode.DRAFT_GIT_BRANCH_EXISTS

    def test_empty_repo_raises_instead_of_silently_initializing(self):
        client = FakeGitHubApiClient()  # no branches seeded — a brand-new, empty repo

        with pytest.raises(JaasError) as exc_info:
            git_sync.create_working_branch(
                client, "tok", owner="acme", repo="tool-x", target_branch="main",
                working_branch="jaas/draft/abc", seed_changes={"manifest.yaml": b"id: x"},
            )

        assert exc_info.value.code == ErrorCode.DRAFT_GIT_EMPTY_REPO
        assert client.branches == {}

    def test_empty_repo_initializes_with_the_seed_files_when_explicitly_allowed(self):
        client = FakeGitHubApiClient()

        sha, seeded = git_sync.create_working_branch(
            client, "tok", owner="acme", repo="tool-x", target_branch="main",
            working_branch="jaas/draft/abc", seed_changes={"manifest.yaml": b"id: x"},
            allow_empty_repo_init=True,
        )

        assert seeded is True
        assert client.branches["main"] == sha
        assert client.branches["jaas/draft/abc"] == sha
        assert client.file_contents["main"] == {"manifest.yaml": b"id: x"}
        assert client.file_contents["jaas/draft/abc"] == {"manifest.yaml": b"id: x"}


class TestCommitFiles:
    def test_writes_and_deletes_in_one_commit(self):
        client = FakeGitHubApiClient()
        client.seed_branch("jaas/draft/abc", files={"old.yaml": b"stale"})

        new_sha = git_sync.commit_files(
            client, "tok", owner="acme", repo="tool-x", branch="jaas/draft/abc",
            changes={"manifest.yaml": b"id: x", "old.yaml": None},
            message="Update files",
        )

        assert new_sha == client.branches["jaas/draft/abc"]
        assert client.file_contents["jaas/draft/abc"] == {"manifest.yaml": b"id: x"}
        assert client.commit_log == [("jaas/draft/abc", "Update files")]

    def test_propagates_a_failure_without_partial_state_confusion(self):
        client = FakeGitHubApiClient()
        client.seed_branch("jaas/draft/abc")
        client.fail_commit_with = JaasError(ErrorCode.GITHUB_API_ERROR, "rate limited")

        with pytest.raises(JaasError, match="rate limited"):
            git_sync.commit_files(
                client, "tok", owner="acme", repo="tool-x", branch="jaas/draft/abc",
                changes={"manifest.yaml": b"id: x"}, message="Update",
            )


class TestMergePublishPr:
    def test_merges_immediately_when_already_mergeable(self):
        client = FakeGitHubApiClient()
        client.seed_branch("main", files={})
        client.seed_branch("jaas/draft/abc", files={"manifest.yaml": b"id: x"})
        pr = client.create_pull_request(
            "tok", owner="acme", repo="tool-x", head="jaas/draft/abc", base="main",
            title="t", body="b",
        )
        client.mergeable = True
        client.mergeable_after_polls = 0

        sha = git_sync.merge_publish_pr(
            client, "tok", owner="acme", repo="tool-x", number=pr.number
        )

        assert sha == client.branches["main"]
        assert client.pull_requests[pr.number]["merged"] is True

    def test_polls_until_mergeability_is_known(self, monkeypatch):
        monkeypatch.setattr(git_sync.time, "sleep", lambda _: None)
        client = FakeGitHubApiClient()
        client.seed_branch("main")
        client.seed_branch("jaas/draft/abc")
        pr = client.create_pull_request(
            "tok", owner="acme", repo="tool-x", head="jaas/draft/abc", base="main",
            title="t", body="b",
        )
        client.mergeable = True
        client.mergeable_after_polls = 3

        git_sync.merge_publish_pr(client, "tok", owner="acme", repo="tool-x", number=pr.number)

        assert client.pull_requests[pr.number]["polls"] >= 3

    def test_conflict_raises_and_leaves_the_pr_open(self, monkeypatch):
        monkeypatch.setattr(git_sync.time, "sleep", lambda _: None)
        client = FakeGitHubApiClient()
        client.seed_branch("main")
        client.seed_branch("jaas/draft/abc")
        pr = client.create_pull_request(
            "tok", owner="acme", repo="tool-x", head="jaas/draft/abc", base="main",
            title="t", body="b",
        )
        client.mergeable = False
        client.mergeable_after_polls = 1

        with pytest.raises(JaasError) as exc_info:
            git_sync.merge_publish_pr(client, "tok", owner="acme", repo="tool-x", number=pr.number)

        assert exc_info.value.code == ErrorCode.DRAFT_GIT_MERGE_CONFLICT
        assert exc_info.value.details["prUrl"] == pr.html_url
        assert client.pull_requests[pr.number]["merged"] is False


class TestCreateRelease:
    def test_tags_with_a_v_prefixed_version(self):
        client = FakeGitHubApiClient()

        release = git_sync.create_release(
            client, "tok", owner="acme", repo="tool-x", target_branch="main",
            skill_id="acme.text.summarizer", version="1.2.3", warning_count=2,
        )

        assert release.tag_name == "v1.2.3"
        assert client.releases[0]["target_commitish"] == "main"
        assert "2 warning" in client.releases[0]["body"]
