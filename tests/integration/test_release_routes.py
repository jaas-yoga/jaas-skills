"""End-to-end tests for POST /api/v1/skills/release — both the PAT auth
path and the GitHub Actions OIDC path (with a fake JWK client so no
network call is ever made; see authn/ci_credentials.py for the real
signature-verification tests)."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

import jwt as pyjwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.authn.ci_credentials import GITHUB_OIDC_ISSUER, GitHubOidcVerifier
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import FeatureFlags, Settings
from jaas_registry.guardrails.models import GuardrailFinding, GuardrailScanResult, GuardrailSeverity
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.fake_github_client import FakeGitHubApiClient
from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET, make_token
from tests.fixtures.manifests import (
    VALID_DEPENDENCIES,
    VALID_IO_SCHEMA,
    VALID_MANIFEST,
    VALID_PERMISSIONS,
)

AUDIENCE = "jaas-registry"


@dataclass
class _FakeSigningKey:
    key: object


class _FakeJwkClient:
    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(key=self._public_key)


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _oidc_token(private_key, **overrides) -> str:
    claims = {
        "iss": GITHUB_OIDC_ISSUER,
        "aud": AUDIENCE,
        "sub": "repo:acme/tool-x:ref:refs/tags/v1.2.3",
        "sha": "abc123",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return pyjwt.encode(claims, private_key, algorithm="RS256")


@pytest.fixture
def client(tmp_path, rsa_keypair):
    _, public_key = rsa_keypair
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(
        storage_root=tmp_path / "storage",
        policy_dir=tmp_path / "policy",
        release_oidc_audience=AUDIENCE,
    )
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(
        index=index,
        store=store,
        settings=settings,
        authorizer=authorizer,
        guardrails_client=FakeGuardrailsClient(),
        oidc_verifier=GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key)),
    )
    return TestClient(app)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _files_b64(*, version="1.2.3") -> dict:
    manifest = dict(VALID_MANIFEST)
    manifest["version"] = version
    raw = {
        "manifest.yaml": yaml.safe_dump(manifest).encode(),
        "schema.json": json.dumps(VALID_IO_SCHEMA).encode(),
        "permissions.yaml": yaml.safe_dump(VALID_PERMISSIONS).encode(),
        "dependencies.yaml": yaml.safe_dump(VALID_DEPENDENCIES).encode(),
    }
    return {path: base64.b64encode(content).decode("ascii") for path, content in raw.items()}


def _link_headers_and_body(
    client,
    *,
    tag="v1.2.3",
    repo_url="https://github.com/acme/tool-x",
    release_branches=(),
    release_branch=None,
):
    admin_token = make_token(subject="usr_admin", tenant="tnt_acme", scopes=("skills:write",))
    # No sign-in/tenant-creation flow needed here: repo_link_store is
    # seeded directly, same shortcut test_draft_routes.py's guardrail
    # tests use for the guardrails_client. Membership/authz checks that
    # matter for /release live in the auth branch, not repo-link storage.
    client.app.state.repo_link_store.create(
        tenant_id="tnt_acme",
        skill_id=VALID_MANIFEST["id"],
        repo_url=repo_url,
        created_by="usr_admin",
        release_branches=tuple(release_branches),
    )
    body = {"files": _files_b64(), "tag": tag, "repoUrl": repo_url}
    if release_branch is not None:
        body["releaseBranch"] = release_branch
    return admin_token, body


class TestPatAuthPath:
    def test_successful_release(self, client):
        token, body = _link_headers_and_body(client)

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == VALID_MANIFEST["id"]
        assert resp.json()["version"] == "1.2.3"
        # FAKE_CATALOG's default policy skips the opt-in level-3 check —
        # a git-native release still gets a certification (guardrails_client
        # is never optional here), just capped at level 2.
        assert resp.json()["guardrailCertifiedLevel"] == 2

        # Immediately visible via metadata in this same server process —
        # publish_skill() only writes the blob/tag, so the route itself
        # must re-index synchronously or this stays 404 until a restart.
        meta_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3", headers=_auth(token)
        )
        assert meta_resp.status_code == 200

    def test_owner_user_is_the_repo_links_creator_not_the_repo_url(self, client):
        """A regression test: owner_user must be a real user id (whoever
        registered the repo link), never the repo URL string used for
        `actor`/provenance — otherwise no real user would ever satisfy the
        web UI's isOwner check for a git-released skill."""
        from jaas_registry.index.ingest import parse_published_record
        from jaas_registry.storage.keys import tag_key

        token, body = _link_headers_and_body(client)

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        record = client.app.state.store.read(tag_key(VALID_MANIFEST["id"], "1.2.3"))
        entry = parse_published_record(record)
        assert entry.owner_user == "usr_admin"
        assert entry.source_repo == "https://github.com/acme/tool-x"

    def test_rejects_when_no_repo_link_registered(self, client):
        token = make_token(subject="usr_admin", tenant="tnt_acme", scopes=("skills:write",))
        body = {
            "files": _files_b64(),
            "tag": "v1.2.3",
            "repoUrl": "https://github.com/acme/tool-x",
        }

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 403
        assert resp.json()["code"] == "REPO_LINK_REQUIRED"

    def test_rejects_tag_manifest_version_mismatch(self, client):
        token, body = _link_headers_and_body(client, tag="v9.9.9")

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 400
        assert resp.json()["code"] == "RELEASE_VERSION_MISMATCH"

    def test_missing_repo_url_is_rejected(self, client):
        token = make_token(subject="usr_admin", tenant="tnt_acme", scopes=("skills:write",))
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 400

    def test_re_releasing_the_same_tag_is_idempotent(self, client):
        token, body = _link_headers_and_body(client)

        first = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        second = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["digest"] == second.json()["digest"]

    def test_mandatory_guardrail_block_rejects_the_release(self, client):
        token, body = _link_headers_and_body(client)
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

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 400
        assert resp.json()["code"] == "GUARDRAIL_VIOLATION"

    def test_guardrails_client_is_always_invoked_never_skippable(self, client):
        token, body = _link_headers_and_body(client)
        fake = client.app.state.guardrails_client

        client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert fake.last_scan_kwargs is not None

    def test_release_branch_matching_the_allow_list_succeeds(self, client):
        token, body = _link_headers_and_body(
            client, release_branches=("main", "staging"), release_branch="staging"
        )

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 200, resp.text

    def test_release_branch_not_in_the_allow_list_is_rejected(self, client):
        token, body = _link_headers_and_body(
            client, release_branches=("main",), release_branch="staging"
        )

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 403
        assert resp.json()["code"] == "RELEASE_LINE_NOT_ALLOWED"

    def test_missing_release_branch_against_a_restricted_link_is_rejected(self, client):
        token, body = _link_headers_and_body(client, release_branches=("main",))

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 403
        assert resp.json()["code"] == "RELEASE_LINE_NOT_ALLOWED"

    def test_unrestricted_link_ignores_release_branch_entirely(self, client):
        """release_branches=() (the default) is 'no restriction' — every
        pre-existing link, and every tenant that never opted in, must keep
        working with no releaseBranch at all."""
        token, body = _link_headers_and_body(client)

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))

        assert resp.status_code == 200, resp.text


class TestSourceFilesBrowsing:
    """GET .../source-files{,/<path>} — the "browse the full repo tree at
    the release tag" feature, separate from /files (the narrow packaged
    archive). Uses its own `client` fixture so it can inject a
    FakeGitHubApiClient and control what the "unauthenticated public
    GitHub" surface returns."""

    @pytest.fixture
    def client(self, tmp_path, rsa_keypair):
        _, public_key = rsa_keypair
        index = InMemoryIndex()
        store = LocalFilesystemStore(tmp_path / "storage")
        settings = Settings(
            storage_root=tmp_path / "storage",
            policy_dir=tmp_path / "policy",
            release_oidc_audience=AUDIENCE,
        )
        authorizer = JwtAuthorizer(
            secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
        )
        github_api_client = FakeGitHubApiClient()
        app = create_app(
            index=index,
            store=store,
            settings=settings,
            authorizer=authorizer,
            guardrails_client=FakeGuardrailsClient(),
            oidc_verifier=GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key)),
            github_api_client=github_api_client,
        )
        test_client = TestClient(app)
        test_client.github_api_client = github_api_client
        return test_client

    def test_full_repo_tree_is_available_when_the_tag_is_public(self, client):
        token, body = _link_headers_and_body(client)
        client.github_api_client.seed_public_source(
            "v1.2.3",
            {
                "manifest.yaml": b"id: acme.tool.x\n",
                "README.md": b"# hi\n",
                "tests/test_x.py": b"def test(): pass\n",
            },
        )

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        tree_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3/source-files",
            headers=_auth(token),
        )
        assert tree_resp.status_code == 200
        data = tree_resp.json()
        assert data["available"] is True
        assert data["ref"] == "v1.2.3"
        assert data["repoUrl"] == "https://github.com/acme/tool-x"
        assert set(data["files"]) == {"manifest.yaml", "README.md", "tests/test_x.py"}

        content_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3/source-files/README.md",
            headers=_auth(token),
        )
        assert content_resp.status_code == 200
        assert content_resp.json() == {"path": "README.md", "content": "# hi\n"}

    def test_tree_is_scoped_to_source_path_and_relativized(self, client):
        """Regression test: a repo hosting several skills (design.md's
        "Per-Skill Git Directories") must not leak a sibling skill's files
        into this one's source-files listing, and returned paths must
        match the Package tab's skill-relative paths, not the repo-root-
        relative paths GitHub's tree API actually returns."""
        token, body = _link_headers_and_body(client)
        body["sourcePath"] = "acme.tool.x"
        client.github_api_client.seed_public_source(
            "v1.2.3",
            {
                "acme.tool.x/manifest.yaml": b"id: acme.tool.x\n",
                "acme.tool.x/README.md": b"# hi\n",
                "acme.tool.x/tests/test_x.py": b"def test(): pass\n",
                "other-skill/manifest.yaml": b"id: other-skill\n",
            },
        )

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        tree_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3/source-files",
            headers=_auth(token),
        )
        assert tree_resp.status_code == 200
        data = tree_resp.json()
        assert data["available"] is True
        assert set(data["files"]) == {"manifest.yaml", "README.md", "tests/test_x.py"}
        assert "other-skill/manifest.yaml" not in data["files"]

        content_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3/source-files/README.md",
            headers=_auth(token),
        )
        assert content_resp.status_code == 200
        assert content_resp.json() == {"path": "README.md", "content": "# hi\n"}

    def test_unavailable_when_source_path_matches_nothing_at_this_ref(self, client):
        """A recorded source_path that doesn't exist at the release ref
        (stale/renamed directory) must degrade to unavailable, not a
        misleadingly empty-but-successful listing."""
        token, body = _link_headers_and_body(client)
        body["sourcePath"] = "acme.tool.x"
        client.github_api_client.seed_public_source(
            "v1.2.3", {"some-other-dir/manifest.yaml": b"id: x\n"}
        )

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        tree_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3/source-files",
            headers=_auth(token),
        )
        data = tree_resp.json()
        assert data["available"] is False
        assert "acme.tool.x" in data["reason"]

    def test_unavailable_when_repo_is_private_or_unreachable(self, client):
        """Never seeded in the fake -> looks exactly like a private repo or
        a GitHub outage from get_public_tree's point of view. Must degrade
        to available=False, not a 500 or a leaked archive."""
        token, body = _link_headers_and_body(client)

        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        tree_resp = client.get(
            f"/api/v1/skills/{VALID_MANIFEST['id']}/versions/1.2.3/source-files",
            headers=_auth(token),
        )
        assert tree_resp.status_code == 200
        data = tree_resp.json()
        assert data["available"] is False
        assert data["files"] == []
        assert data["reason"]


class TestOidcAuthPath:
    def _headers(self, token: str, private_key, **claim_overrides) -> dict:
        return {"X-Jaas-OIDC-Token": _oidc_token(private_key, **claim_overrides)}

    def test_successful_release_via_oidc(self, client, rsa_keypair):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
        )
        body = {"files": _files_b64(), "tag": "v1.2.3", "ciRunUrl": "https://github.com/run/1"}

        resp = client.post(
            "/api/v1/skills/release", json=body, headers=self._headers("", private_key)
        )

        assert resp.status_code == 200, resp.text

    def test_rejects_when_skill_id_has_no_link_at_all(self, client, rsa_keypair):
        private_key, _ = rsa_keypair
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post(
            "/api/v1/skills/release", json=body, headers=self._headers("", private_key)
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "REPO_LINK_REQUIRED"

    def test_rejects_when_link_points_at_a_different_repo(self, client, rsa_keypair):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/a-different-repo",
            created_by="usr_admin",
        )
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post(
            "/api/v1/skills/release", json=body, headers=self._headers("", private_key)
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "REPO_LINK_REQUIRED"

    def test_rejects_request_tag_not_matching_oidc_token_tag(self, client, rsa_keypair):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
        )
        body = {"files": _files_b64(), "tag": "v9.9.9"}

        resp = client.post(
            "/api/v1/skills/release", json=body, headers=self._headers("", private_key)
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == "RELEASE_VERSION_MISMATCH"

    def test_environment_claim_matching_the_allow_list_succeeds(self, client, rsa_keypair):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
            release_branches=("main", "staging"),
        )
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post(
            "/api/v1/skills/release",
            json=body,
            headers=self._headers("", private_key, environment="staging"),
        )

        assert resp.status_code == 200, resp.text

    def test_environment_claim_not_in_the_allow_list_is_rejected(self, client, rsa_keypair):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
            release_branches=("main",),
        )
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post(
            "/api/v1/skills/release",
            json=body,
            headers=self._headers("", private_key, environment="staging"),
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "RELEASE_LINE_NOT_ALLOWED"

    def test_missing_environment_claim_against_a_restricted_link_is_rejected(
        self, client, rsa_keypair
    ):
        """No `environment:` declared in the workflow job at all — we can't
        verify the branch, so a restricted link must reject, not silently
        allow."""
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
            release_branches=("main",),
        )
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post(
            "/api/v1/skills/release", json=body, headers=self._headers("", private_key)
        )

        assert resp.status_code == 403
        assert resp.json()["code"] == "RELEASE_LINE_NOT_ALLOWED"

    def test_provenance_is_recorded(self, client, rsa_keypair, capsys):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
        )
        body = {"files": _files_b64(), "tag": "v1.2.3", "ciRunUrl": "https://github.com/run/1"}

        resp = client.post(
            "/api/v1/skills/release", json=body, headers=self._headers("", private_key)
        )
        assert resp.status_code == 200

        logged = capsys.readouterr().out
        assert '"source_repo": "acme/tool-x"' in logged
        assert '"source_commit": "abc123"' in logged
        assert '"source_tag": "v1.2.3"' in logged

    def test_source_branch_is_recorded_when_environment_claim_present(
        self, client, rsa_keypair, capsys
    ):
        private_key, _ = rsa_keypair
        client.app.state.repo_link_store.create(
            tenant_id="tnt_acme",
            skill_id=VALID_MANIFEST["id"],
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_admin",
            release_branches=("staging",),
        )
        body = {"files": _files_b64(), "tag": "v1.2.3"}

        resp = client.post(
            "/api/v1/skills/release",
            json=body,
            headers=self._headers("", private_key, environment="staging"),
        )
        assert resp.status_code == 200, resp.text

        logged = capsys.readouterr().out
        assert '"source_branch": "staging"' in logged


@pytest.fixture
def client_requiring_sigstore(tmp_path, rsa_keypair):
    """IMPLEMENTATION_PLAN.md Phase 1.2: same rig as `client`, but with
    Settings.feature_flags.sigstore_signing_required=True — a deployment
    that has opted into requiring a Sigstore-signed release."""
    _, public_key = rsa_keypair
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(
        storage_root=tmp_path / "storage",
        policy_dir=tmp_path / "policy",
        release_oidc_audience=AUDIENCE,
        feature_flags=FeatureFlags(sigstore_signing_required=True),
    )
    authorizer = JwtAuthorizer(
        secret=DEFAULT_SECRET, issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )
    app = create_app(
        index=index,
        store=store,
        settings=settings,
        authorizer=authorizer,
        guardrails_client=FakeGuardrailsClient(),
        oidc_verifier=GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key)),
    )
    return TestClient(app)


class TestSigstoreSigningRequired:
    def test_default_deployment_still_dev_rsa_signs_and_records_the_kind(self, client):
        """The flag defaults off — an unmodified deployment (and every CI
        caller on an older jaasctl that never sends a bundle) keeps
        working exactly as before this feature existed."""
        from jaas_registry.index.ingest import parse_published_record
        from jaas_registry.storage.keys import tag_key

        token, body = _link_headers_and_body(client)
        resp = client.post("/api/v1/skills/release", json=body, headers=_auth(token))
        assert resp.status_code == 200, resp.text

        record = client.app.state.store.read(tag_key(VALID_MANIFEST["id"], "1.2.3"))
        entry = parse_published_record(record)
        assert entry.signature_kind == "dev-rsa"

    def test_a_release_with_no_bundle_is_rejected_when_required(self, client_requiring_sigstore):
        token, body = _link_headers_and_body(client_requiring_sigstore)

        resp = client_requiring_sigstore.post(
            "/api/v1/skills/release", json=body, headers=_auth(token)
        )

        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "SIGSTORE_SIGNATURE_REQUIRED"
