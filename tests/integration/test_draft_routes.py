"""ui-implementation-plan.md Phase 5 backend: draft CRUD, validate, publish,
and fork-from-published-version, exercised over real HTTP requests."""

import json
import uuid

import pytest
import yaml
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.guardrails.models import GuardrailFinding, GuardrailScanResult, GuardrailSeverity
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.fake_github_client import FakeGitHubApiClient
from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient
from tests.fixtures.index_entries import make_entry
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token
from tests.fixtures.manifests import VALID_MANIFEST
from tests.fixtures.package_dir import write_package_dir

# drafts/store.py's _STARTER_FILES manifest id — the directory every
# `_create_git_draft`-made draft's files land under, since none of these
# tests customize manifest.yaml before connecting to git.
_STARTER_SKILL_DIR = "your-team/your-domain/your-skill"


@pytest.fixture
def fake_github_client():
    return FakeGitHubApiClient()


@pytest.fixture
def git_client(tmp_path, fake_github_client):
    """Same wiring as `client`, plus a fake GitHubApiClient and a
    pre-connected "tnt_owner" GitHub connection — the state every
    git-backed draft test starts from."""
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(
        index=index,
        store=store,
        settings=settings,
        authorizer=authorizer,
        guardrails_client=FakeGuardrailsClient(),
        github_api_client=fake_github_client,
    )
    app.state.github_connection_store.put(
        tenant_id="tnt_owner",
        access_token="gho_test",
        github_login="octocat",
        github_avatar_url=None,
        connected_by="usr_owner",
    )
    fake_github_client.seed_branch("main", files={})
    return TestClient(app)


@pytest.fixture
def client(tmp_path):
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(storage_root=tmp_path / "storage", policy_dir=tmp_path / "policy")
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(
        index=index,
        store=store,
        settings=settings,
        authorizer=authorizer,
        guardrails_client=FakeGuardrailsClient(),
    )
    app.state._test_index = index  # noqa: SLF001 - test-only hook for seeding
    app.state._test_store = store  # noqa: SLF001
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _write_token(subject="usr_owner", tenant="tnt_owner"):
    return make_token(subject=subject, tenant=tenant, scopes=("skills:write", "skills:share"))


def _publish_and_index(
    client: TestClient, *, visibility=Visibility.PUBLIC, owner_user="usr_publisher"
):
    """Publishes a real skill directly through the pipeline (not the draft
    API) and seeds the app's in-memory index — standing in for what
    bootstrap/the event consumer would normally do after a real publish."""
    keypair = generate_dev_keypair()
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    source_dir = client.app.state._test_store.root.parent / "fork-source"  # noqa: SLF001
    write_package_dir(source_dir)
    result = publish_skill(
        source_dir=source_dir,
        store=client.app.state._test_store,  # noqa: SLF001
        signing_key=keypair,
        trust_policy=trust_policy,
        actor=owner_user,
        audit_sink=InMemoryAuditSink(),
        owner_user=owner_user,
        owner_tenant="tnt_publisher",
        visibility=visibility,
    )
    client.app.state._test_index.put(  # noqa: SLF001
        make_entry(
            id=result.manifest.id,
            version=result.manifest.version,
            digest=result.manifest.digest,
            signature=result.manifest.signature,
            visibility=visibility,
            owner_user=owner_user,
            owner_tenant="tnt_publisher",
        )
    )
    return result


class TestDraftCrud:
    def test_create_requires_auth(self, client):
        resp = client.post("/api/v1/drafts", json={})
        assert resp.status_code == 403

    def test_create_blank_draft_seeds_a_starter_manifest(self, client):
        resp = client.post("/api/v1/drafts", json={}, headers=_auth(_write_token()))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"].startswith("draft_")
        assert body["files"] == ["manifest.yaml"]

    def test_list_only_returns_the_callers_own_drafts(self, client):
        mine_token = _write_token(subject="usr_mine", tenant="tnt_mine")
        other_token = _write_token(subject="usr_other", tenant="tnt_other")
        client.post("/api/v1/drafts", json={}, headers=_auth(mine_token))
        client.post("/api/v1/drafts", json={}, headers=_auth(other_token))

        resp = client.get("/api/v1/drafts", headers=_auth(mine_token))

        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_surfaces_the_manifests_own_skill_id(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\nname: Foo\n"},
            headers=_auth(token),
        )

        resp = client.get("/api/v1/drafts", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()[0]["skillId"] == "acme.text.foo"

    def test_owner_can_write_and_read_a_file(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]

        put_resp = client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\n"},
            headers=_auth(token),
        )
        assert put_resp.status_code == 200
        assert "manifest.yaml" in put_resp.json()["files"]

        get_resp = client.get(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml", headers=_auth(token)
        )
        assert get_resp.json()["content"] == "id: acme.text.foo\n"

    def test_non_owner_gets_404_not_403(self, client):
        owner_draft = client.post(
            "/api/v1/drafts", json={}, headers=_auth(_write_token())
        ).json()

        other_token = _write_token(subject="usr_other", tenant="tnt_other")
        resp = client.get(f"/api/v1/drafts/{owner_draft['id']}", headers=_auth(other_token))

        assert resp.status_code == 404
        assert resp.json()["code"] == "DRAFT_NOT_FOUND"

    def test_delete_file(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "x"},
            headers=_auth(token),
        )

        resp = client.delete(f"/api/v1/drafts/{draft_id}/files/manifest.yaml", headers=_auth(token))

        assert resp.status_code == 200
        assert "manifest.yaml" not in resp.json()["files"]

    def test_owner_can_delete_the_whole_draft(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]

        resp = client.delete(f"/api/v1/drafts/{draft_id}", headers=_auth(token))
        assert resp.status_code == 204

        get_resp = client.get(f"/api/v1/drafts/{draft_id}", headers=_auth(token))
        assert get_resp.status_code == 404
        assert get_resp.json()["code"] == "DRAFT_NOT_FOUND"

    def test_non_owner_cannot_delete_the_draft(self, client):
        owner_draft = client.post(
            "/api/v1/drafts", json={}, headers=_auth(_write_token())
        ).json()

        other_token = _write_token(subject="usr_other", tenant="tnt_other")
        resp = client.delete(f"/api/v1/drafts/{owner_draft['id']}", headers=_auth(other_token))

        assert resp.status_code == 404
        assert resp.json()["code"] == "DRAFT_NOT_FOUND"

    def test_deleting_a_missing_draft_is_404(self, client):
        resp = client.delete("/api/v1/drafts/draft_does_not_exist", headers=_auth(_write_token()))
        assert resp.status_code == 404

    def test_path_traversal_is_rejected(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]

        resp = client.put(
            f"/api/v1/drafts/{draft_id}/files/..%2f..%2f..%2fetc%2fpasswd",
            json={"content": "pwned"},
            headers=_auth(token),
        )

        assert resp.status_code in (400, 404)


class TestDraftValidation:
    def test_missing_files_fails_validation(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        # a blank draft is auto-seeded with starter files (see drafts/store.py)
        # to keep the very first Validate from failing this way — delete one
        # to genuinely exercise the missing-file path this test is for.
        client.delete(f"/api/v1/drafts/{draft_id}/files/manifest.yaml", headers=_auth(token))

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["errors"][0]["code"] == "MISSING_REQUIRED_FILE"

    def test_valid_documents_pass_validation(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["errors"] == []
        assert body["warnings"] == []
        # FAKE_CATALOG's default policy enables levels 1-2 but not the
        # opt-in level-3 pii-pattern-scan check, so certification is
        # capped there even though nothing failed.
        assert body["certification"]["highestCertifiedLevel"] == 2
        assert body["certification"]["levelStatuses"][2] == [3, "not_attempted"]

    def test_invalid_version_format_fails_validation_with_stable_code(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token, version="not-semver")

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.json()["valid"] is False
        assert resp.json()["errors"][0]["code"] == "INVALID_VERSION_FORMAT"

    def test_mandatory_guardrail_finding_fails_validation(self, client):
        """Real detection (does 'AKIA...' actually trip secret-scan) is the
        standalone guardrails service's own test suite's job — this only
        verifies that a BLOCK finding from the client fails validation."""
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)
        client.app.state.guardrails_client = FakeGuardrailsClient(
            scan_result=GuardrailScanResult(
                blocking=(
                    GuardrailFinding(
                        check_id="secret-scan",
                        file="manifest.yaml",
                        message="fake secret finding",
                        severity=GuardrailSeverity.BLOCK,
                    ),
                ),
                warnings=(),
            )
        )

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["errors"][0]["code"] == "GUARDRAIL_VIOLATION"

    def test_warn_only_guardrail_finding_still_passes_validation(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)
        client.app.state.guardrails_client = FakeGuardrailsClient(
            scan_result=GuardrailScanResult(
                blocking=(),
                warnings=(
                    GuardrailFinding(
                        check_id="unpinned-dependency-range",
                        file="dependencies.yaml",
                        message="fake warning",
                        severity=GuardrailSeverity.WARN,
                    ),
                ),
            )
        )

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert any(w["code"] == "unpinned-dependency-range" for w in body["warnings"])


class TestSkillGuardrailsConfig:
    """A draft's own .jaas/guardrails.yaml (guardrails/skill_config.py)
    applies tenant custom rules on top of the tenant's baseline policy —
    exercised here through both /validate and /publish, the same two
    call sites that already enforce the baseline policy itself."""

    def _seed_custom_rule(self, client, tenant_id="tnt_owner", slug="no-todo"):
        client.app.state.custom_guardrail_rule_store.put(
            tenant_id=tenant_id,
            slug=slug,
            name="No TODO",
            description="",
            category="CODE_SAFETY",
            severity="WARN",
            standard_ref="",
            kind="regex_file_scan",
            config={"scope": "all_files", "patterns": []},
            created_by="usr_owner",
        )

    def test_validate_reaches_the_scan_with_the_applied_custom_rule(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)
        self._seed_custom_rule(client)
        client.put(
            f"/api/v1/drafts/{draft_id}/files/.jaas/guardrails.yaml",
            json={"content": "apply:\n  - custom:tnt_owner:no-todo\n"},
            headers=_auth(token),
        )

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.status_code == 200
        fake = client.app.state.guardrails_client
        applied_ids = {r.id for r in fake.last_scan_kwargs["custom_rules"]}
        assert "custom:tnt_owner:no-todo" in applied_ids

    def test_publish_reaches_the_scan_with_the_applied_custom_rule(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)
        self._seed_custom_rule(client)
        client.put(
            f"/api/v1/drafts/{draft_id}/files/.jaas/guardrails.yaml",
            json={"content": "apply:\n  - custom:tnt_owner:no-todo\n"},
            headers=_auth(token),
        )

        resp = client.post(
            f"/api/v1/drafts/{draft_id}/publish",
            json={"visibility": "private"},
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        fake = client.app.state.guardrails_client
        applied_ids = {r.id for r in fake.last_scan_kwargs["custom_rules"]}
        assert "custom:tnt_owner:no-todo" in applied_ids

    def test_applying_an_unknown_rule_id_fails_validation_clearly(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)
        client.put(
            f"/api/v1/drafts/{draft_id}/files/.jaas/guardrails.yaml",
            json={"content": "apply:\n  - custom:tnt_owner:does-not-exist\n"},
            headers=_auth(token),
        )

        resp = client.post(f"/api/v1/drafts/{draft_id}/validate", headers=_auth(token))

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["errors"][0]["code"] == "INVALID_CUSTOM_GUARDRAIL"


class TestDraftPublish:
    def test_publish_creates_a_real_skill_and_deletes_the_draft(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)

        resp = client.post(
            f"/api/v1/drafts/{draft_id}/publish",
            json={"visibility": "private"},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "acme.text.summarizer"
        assert body["digest"].startswith("sha256:")
        # FAKE_CATALOG's default policy skips the opt-in level-3 check —
        # certified through level 2, same ceiling as the Validate-time
        # projection (test_valid_documents_pass_validation).
        assert body["guardrailCertifiedLevel"] == 2
        assert body["guardrailLevelStatuses"][2] == [3, "not_attempted"]

        # the draft is gone after a successful publish
        assert client.get(f"/api/v1/drafts/{draft_id}", headers=_auth(token)).status_code == 404

        # ...and it's immediately visible via the metadata and search
        # endpoints too, in this same (never-restarted) server process —
        # publish_skill() only writes the blob/tag, so the route itself
        # must re-index synchronously or this stays 404/absent forever.
        meta_resp = client.get(
            "/api/v1/skills/acme.text.summarizer/versions/1.2.3", headers=_auth(token)
        )
        assert meta_resp.status_code == 200
        assert meta_resp.json()["guardrailCertifiedLevel"] == 2

        search_resp = client.get(
            "/api/v1/skills", params={"query": "acme.text.summarizer"}, headers=_auth(token)
        )
        assert any(item["id"] == "acme.text.summarizer" for item in search_resp.json()["items"])

    def test_publish_with_invalid_documents_is_rejected(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        # starter files are auto-seeded and valid as-is (see drafts/store.py)
        # — delete one so this genuinely exercises the missing-file path.
        client.delete(f"/api/v1/drafts/{draft_id}/files/manifest.yaml", headers=_auth(token))

        resp = client.post(
            f"/api/v1/drafts/{draft_id}/publish", json={}, headers=_auth(token)
        )

        assert resp.status_code >= 400

    def test_publish_rejected_by_mandatory_guardrail(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]
        _fill_valid_draft(client, draft_id, token)
        client.app.state.guardrails_client = FakeGuardrailsClient(
            scan_result=GuardrailScanResult(
                blocking=(
                    GuardrailFinding(
                        check_id="secret-scan",
                        file="manifest.yaml",
                        message="fake secret finding",
                        severity=GuardrailSeverity.BLOCK,
                    ),
                ),
                warnings=(),
            )
        )

        resp = client.post(
            f"/api/v1/drafts/{draft_id}/publish", json={}, headers=_auth(token)
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "GUARDRAIL_VIOLATION"
        # nothing published: the draft still exists
        assert client.get(f"/api/v1/drafts/{draft_id}", headers=_auth(token)).status_code == 200


class TestForkFromPublished:
    def test_fork_copies_files_from_the_published_version(self, client):
        publish_result = _publish_and_index(client, visibility=Visibility.PUBLIC)
        token = _write_token()

        resp = client.post(
            "/api/v1/drafts",
            json={
                "forkFrom": {
                    "id": publish_result.manifest.id,
                    "version": publish_result.manifest.version,
                }
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["forkedFromId"] == publish_result.manifest.id
        assert set(body["files"]) == {
            "manifest.yaml",
            "schema.json",
            "permissions.yaml",
            "dependencies.yaml",
        }

    def test_cannot_fork_a_private_skill_you_cannot_view(self, client):
        publish_result = _publish_and_index(
            client, visibility=Visibility.PRIVATE, owner_user="usr_owner_of_private"
        )
        outsider_token = _write_token(subject="usr_outsider", tenant="tnt_outsider")

        resp = client.post(
            "/api/v1/drafts",
            json={
                "forkFrom": {
                    "id": publish_result.manifest.id,
                    "version": publish_result.manifest.version,
                }
            },
            headers=_auth(outsider_token),
        )

        assert resp.status_code == 404

    def test_owner_can_fork_their_own_private_skill(self, client):
        publish_result = _publish_and_index(
            client, visibility=Visibility.PRIVATE, owner_user="usr_owner"
        )
        owner_token = _write_token(subject="usr_owner", tenant="tnt_publisher")

        resp = client.post(
            "/api/v1/drafts",
            json={
                "forkFrom": {
                    "id": publish_result.manifest.id,
                    "version": publish_result.manifest.version,
                }
            },
            headers=_auth(owner_token),
        )

        assert resp.status_code == 200


class TestDraftGitIntegration:
    def _register_repo(
        self, git_client, *, tenant_id="tnt_owner", repo_url="https://github.com/acme/tool-x"
    ):
        """A repo must already be Connected (repo_links.py) before a draft
        can be created against it — seeded directly via app.state, same
        pattern TestSkillGuardrailsConfig._seed_custom_rule uses, since
        these tests mint JWTs directly rather than going through the real
        membership/admin HTTP flow create_repo_link would require."""
        git_client.app.state.repo_link_store.create(
            tenant_id=tenant_id,
            skill_id=f"acme.text.{uuid.uuid4().hex[:8]}",
            repo_url=repo_url,
            created_by="usr_owner",
        )

    def _create_git_draft(
        self,
        git_client,
        fake_github_client,
        *,
        working_branch="jaas/draft/wb",
        token=None,
        register_repo=True,
    ):
        token = token or _write_token()
        if register_repo:
            self._register_repo(git_client)
        resp = git_client.post(
            "/api/v1/drafts",
            json={
                "git": {
                    "provider": "github",
                    "repoUrl": "https://github.com/acme/tool-x",
                    "targetBranch": "main",
                    "workingBranch": working_branch,
                }
            },
            headers=_auth(token),
        )
        return resp, token

    def test_create_rejects_an_unregistered_repo(self, git_client, fake_github_client):
        resp, token = self._create_git_draft(git_client, fake_github_client, register_repo=False)

        assert resp.status_code == 403
        assert resp.json()["code"] == "REPO_LINK_REQUIRED"
        assert git_client.get("/api/v1/drafts", headers=_auth(token)).json() == []

    def test_create_against_an_empty_repo_asks_for_confirmation_first(
        self, git_client, fake_github_client
    ):
        fake_github_client.branches.clear()  # simulate a brand-new repo with zero commits
        token = _write_token()
        self._register_repo(git_client)

        resp = git_client.post(
            "/api/v1/drafts",
            json={
                "git": {
                    "provider": "github",
                    "repoUrl": "https://github.com/acme/tool-x",
                    "targetBranch": "main",
                    "workingBranch": "jaas/draft/wb",
                }
            },
            headers=_auth(token),
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "DRAFT_GIT_EMPTY_REPO"
        assert fake_github_client.branches == {}
        assert git_client.get("/api/v1/drafts", headers=_auth(token)).json() == []

    def test_create_against_an_empty_repo_succeeds_once_confirmed(
        self, git_client, fake_github_client
    ):
        fake_github_client.branches.clear()
        token = _write_token()
        self._register_repo(git_client)

        resp = git_client.post(
            "/api/v1/drafts",
            json={
                "git": {
                    "provider": "github",
                    "repoUrl": "https://github.com/acme/tool-x",
                    "targetBranch": "main",
                    "workingBranch": "jaas/draft/wb",
                    "confirmInitializeEmptyRepo": True,
                }
            },
            headers=_auth(token),
        )

        assert resp.status_code == 200, resp.text
        assert "main" in fake_github_client.branches
        assert "jaas/draft/wb" in fake_github_client.branches
        # working_branch has the seed-file commit on top of the shared
        # root commit; target_branch stays at the bare root commit until
        # publish merges into it — they're expected to diverge here.
        tree = fake_github_client.file_contents["jaas/draft/wb"]
        assert tree[f"{_STARTER_SKILL_DIR}/manifest.yaml"]

    def test_create_creates_working_branch_and_seed_commit(
        self, git_client, fake_github_client
    ):
        resp, _ = self._create_git_draft(git_client, fake_github_client)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["provider"] == "github"
        assert body["repoUrl"] == "https://github.com/acme/tool-x"
        assert body["targetBranch"] == "main"
        assert body["workingBranch"] == "jaas/draft/wb"
        assert body["gitSyncStatus"] == "synced"
        assert body["gitSubdirectory"] == _STARTER_SKILL_DIR
        assert "jaas/draft/wb" in fake_github_client.branches
        tree = fake_github_client.file_contents["jaas/draft/wb"]
        assert tree[f"{_STARTER_SKILL_DIR}/manifest.yaml"]

    def test_create_rolls_back_when_github_not_connected(self, git_client, fake_github_client):
        outsider_token = _write_token(subject="usr_other", tenant="tnt_other")

        resp, _ = self._create_git_draft(git_client, fake_github_client, token=outsider_token)

        assert resp.status_code == 404
        assert resp.json()["code"] == "GITHUB_NOT_CONNECTED"
        # no orphaned local draft left behind
        assert git_client.get("/api/v1/drafts", headers=_auth(outsider_token)).json() == []

    def test_create_rolls_back_on_branch_name_collision(self, git_client, fake_github_client):
        fake_github_client.seed_branch("jaas/draft/wb")

        resp, token = self._create_git_draft(git_client, fake_github_client)

        assert resp.status_code == 409
        assert resp.json()["code"] == "DRAFT_GIT_BRANCH_EXISTS"
        assert git_client.get("/api/v1/drafts", headers=_auth(token)).json() == []

    def test_save_file_commits_to_the_working_branch(self, git_client, fake_github_client):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]

        put_resp = git_client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\n"},
            headers=_auth(token),
        )

        assert put_resp.status_code == 200
        assert put_resp.json()["gitSyncStatus"] == "synced"
        assert (
            fake_github_client.file_contents["jaas/draft/wb"][f"{_STARTER_SKILL_DIR}/manifest.yaml"]
            == b"id: acme.text.foo\n"
        )

    def test_save_file_still_succeeds_locally_when_git_sync_fails(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]
        fake_github_client.fail_commit_with = JaasError(
            ErrorCode.GITHUB_API_ERROR, "rate limited"
        )

        put_resp = git_client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\n"},
            headers=_auth(token),
        )

        assert put_resp.status_code == 200
        assert put_resp.json()["gitSyncStatus"] == "error"
        assert put_resp.json()["gitSyncError"] == "rate limited"
        get_resp = git_client.get(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml", headers=_auth(token)
        )
        assert get_resp.json()["content"] == "id: acme.text.foo\n"

    def test_save_with_sync_to_git_false_writes_locally_without_committing(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]
        seeded_content = fake_github_client.file_contents["jaas/draft/wb"][
            f"{_STARTER_SKILL_DIR}/manifest.yaml"
        ]
        commits_before = len(fake_github_client.commit_log)

        put_resp = git_client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\n", "syncToGit": False},
            headers=_auth(token),
        )

        assert put_resp.status_code == 200
        assert len(fake_github_client.commit_log) == commits_before
        assert (
            fake_github_client.file_contents["jaas/draft/wb"][f"{_STARTER_SKILL_DIR}/manifest.yaml"]
            == seeded_content
        )
        get_resp = git_client.get(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml", headers=_auth(token)
        )
        assert get_resp.json()["content"] == "id: acme.text.foo\n"

    def test_save_honors_a_custom_commit_message(self, git_client, fake_github_client):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]

        put_resp = git_client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\n", "commitMessage": "Rename skill id"},
            headers=_auth(token),
        )

        assert put_resp.status_code == 200
        assert fake_github_client.commit_log[-1] == ("jaas/draft/wb", "Rename skill id")

    def test_move_to_directory_migrates_a_pre_existing_flat_draft(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]

        # Give it a real skill id, then simulate the state this migration
        # exists for: a draft connected before per-skill directories
        # existed — flat git history, no git_subdirectory recorded yet.
        git_client.put(
            f"/api/v1/drafts/{draft_id}/files/manifest.yaml",
            json={"content": "id: acme.text.foo\nversion: 1.0.0\n", "syncToGit": False},
            headers=_auth(token),
        )
        git_client.app.state.draft_store._replace(draft_id, git_subdirectory=None)  # noqa: SLF001
        fake_github_client.file_contents["jaas/draft/wb"] = {
            "manifest.yaml": b"id: acme.text.foo\nversion: 1.0.0\n",
        }

        resp = git_client.post(
            f"/api/v1/drafts/{draft_id}/git/move-to-directory", headers=_auth(token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["gitSubdirectory"] == "acme/text/foo"
        assert resp.json()["gitSyncStatus"] == "synced"
        tree = fake_github_client.file_contents["jaas/draft/wb"]
        assert "manifest.yaml" not in tree
        assert tree["acme/text/foo/manifest.yaml"] == b"id: acme.text.foo\nversion: 1.0.0\n"

    def test_move_to_directory_rejects_a_draft_that_already_has_one(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]

        resp = git_client.post(
            f"/api/v1/drafts/{draft_id}/git/move-to-directory", headers=_auth(token)
        )

        assert resp.status_code == 409
        assert resp.json()["code"] == "DRAFT_GIT_ALREADY_HAS_DIRECTORY"

    def test_move_to_directory_rejects_a_local_only_draft(self, client):
        token = _write_token()
        draft_id = client.post("/api/v1/drafts", json={}, headers=_auth(token)).json()["id"]

        resp = client.post(
            f"/api/v1/drafts/{draft_id}/git/move-to-directory", headers=_auth(token)
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "DRAFT_GIT_NOT_CONNECTED"

    def test_publish_opens_merges_and_releases_then_deletes_the_draft(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]
        _fill_valid_draft(git_client, draft_id, token, version="2.0.0")

        publish_resp = git_client.post(
            f"/api/v1/drafts/{draft_id}/publish",
            json={"visibility": "private"},
            headers=_auth(token),
        )

        assert publish_resp.status_code == 200, publish_resp.text
        body = publish_resp.json()
        assert body["prUrl"] is not None
        assert body["releaseUrl"] is not None
        assert fake_github_client.releases[0]["tag_name"] == "v2.0.0"
        assert fake_github_client.pull_requests[1]["merged"] is True
        assert git_client.get(f"/api/v1/drafts/{draft_id}", headers=_auth(token)).status_code == 404

    def test_publish_merge_conflict_leaves_pr_and_draft_intact(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]
        _fill_valid_draft(git_client, draft_id, token)
        fake_github_client.mergeable = False
        fake_github_client.mergeable_after_polls = 0

        publish_resp = git_client.post(
            f"/api/v1/drafts/{draft_id}/publish",
            json={"visibility": "private"},
            headers=_auth(token),
        )

        assert publish_resp.status_code == 409
        assert publish_resp.json()["code"] == "DRAFT_GIT_MERGE_CONFLICT"
        assert publish_resp.json()["details"]["prUrl"]
        # nothing published, draft still exists
        assert git_client.get(f"/api/v1/drafts/{draft_id}", headers=_auth(token)).status_code == 200

    def test_publish_still_blocked_by_guardrails_before_any_git_call(
        self, git_client, fake_github_client
    ):
        resp, token = self._create_git_draft(git_client, fake_github_client)
        draft_id = resp.json()["id"]
        _fill_valid_draft(git_client, draft_id, token)
        git_client.app.state.guardrails_client = FakeGuardrailsClient(
            scan_result=GuardrailScanResult(
                blocking=(
                    GuardrailFinding(
                        check_id="secret-scan",
                        file="manifest.yaml",
                        message="fake secret finding",
                        severity=GuardrailSeverity.BLOCK,
                    ),
                ),
                warnings=(),
            )
        )

        publish_resp = git_client.post(
            f"/api/v1/drafts/{draft_id}/publish",
            json={"visibility": "private"},
            headers=_auth(token),
        )

        assert publish_resp.status_code == 400
        assert publish_resp.json()["code"] == "GUARDRAIL_VIOLATION"
        assert fake_github_client.pull_requests == {}

    def test_local_only_draft_reports_no_git_status(self, client):
        token = _write_token()
        resp = client.post("/api/v1/drafts", json={}, headers=_auth(token))

        body = resp.json()
        assert body["repoUrl"] is None
        assert body["gitSyncStatus"] is None


def _fill_valid_draft(client: TestClient, draft_id: str, token: str, *, version: str = "1.2.3"):
    manifest = dict(VALID_MANIFEST)
    manifest["version"] = version
    files = {
        "manifest.yaml": yaml.safe_dump(manifest),
        "schema.json": json.dumps(
            {
                "inputs": {"type": "object", "properties": {}},
                "outputs": {"type": "object", "properties": {}},
            }
        ),
        "permissions.yaml": yaml.safe_dump([]),
        "dependencies.yaml": yaml.safe_dump([]),
    }
    for name, content in files.items():
        resp = client.put(
            f"/api/v1/drafts/{draft_id}/files/{name}",
            json={"content": content},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
