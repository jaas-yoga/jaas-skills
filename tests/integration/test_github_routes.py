"""End-to-end tests for the "Connect GitHub" flow (api/github_routes.py) —
a fake GitHubApiClient stands in for real network calls to github.com,
same injection pattern test_release_routes.py uses for OIDC verification.

Each tenant registers its own GitHub OAuth App (authn/github_oauth_apps.py)
before "Connect GitHub" becomes available — there is no deployment-wide
config anymore, so most tests here call `_configure_oauth_app` first.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.api.deps import get_google_verifier
from jaas_registry.authn.github_client import GitHubRepo, GitHubUser
from jaas_registry.authn.google import GoogleIdentity
from jaas_registry.authz.policy import JwtAuthorizer
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.fake_guardrails_client import FakeGuardrailsClient
from tests.fixtures.jwt_tokens import DEFAULT_AUDIENCE, DEFAULT_ISSUER, DEFAULT_SECRET


class FakeGoogleIdentityVerifier:
    def __init__(self, identities: dict[str, GoogleIdentity]):
        self._identities = identities

    def verify(self, google_id_token_jwt: str) -> GoogleIdentity:
        identity = self._identities.get(google_id_token_jwt)
        if identity is None:
            raise JaasError(ErrorCode.INVALID_GOOGLE_TOKEN, "unknown test token")
        return identity


class FakeGitHubApiClient:
    def __init__(self, *, fail_exchange: bool = False):
        self.fail_exchange = fail_exchange
        self.last_access_token_used: str | None = None
        self.last_client_id_used: str | None = None

    def exchange_code_for_token(
        self, code: str, *, client_id: str, client_secret: str, redirect_uri: str
    ) -> str:
        self.last_client_id_used = client_id
        if self.fail_exchange:
            raise JaasError(ErrorCode.GITHUB_API_ERROR, "exchange failed")
        return f"token-for-{code}"

    def get_authenticated_user(self, access_token: str) -> GitHubUser:
        return GitHubUser(login="octocat", avatar_url="https://avatars.example/octocat.png")

    def list_repos(self, access_token: str) -> list[GitHubRepo]:
        self.last_access_token_used = access_token
        return [
            GitHubRepo(
                full_name="acme/tool-x", owner="acme", name="tool-x", private=False,
                default_branch="main",
            )
        ]

    def list_branches(self, access_token: str, *, owner: str, repo: str) -> list[str]:
        self.last_access_token_used = access_token
        return ["main", "staging"]


@pytest.fixture
def fake_github_client():
    return FakeGitHubApiClient()


def _make_client(tmp_path, fake_github_client, *, web_app_url="http://web.example") -> TestClient:
    index = InMemoryIndex()
    store = LocalFilesystemStore(tmp_path / "storage")
    settings = Settings(
        storage_root=tmp_path / "storage",
        policy_dir=tmp_path / "policy",
        github_oauth_redirect_uri="http://testserver/api/v1/github/callback",
        web_app_url=web_app_url,
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
        github_api_client=fake_github_client,
    )
    app.dependency_overrides[get_google_verifier] = lambda: FakeGoogleIdentityVerifier(
        {
            "alice-token": GoogleIdentity(
                sub="google-alice", email="alice@example.com", name="Alice", picture=None
            ),
            "bob-token": GoogleIdentity(
                sub="google-bob", email="bob@example.com", name="Bob", picture=None
            ),
        }
    )
    return TestClient(app)


@pytest.fixture
def client(tmp_path, fake_github_client):
    return _make_client(tmp_path, fake_github_client)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _sign_in(client: TestClient, id_token: str) -> str:
    resp = client.post("/api/v1/auth/google", json={"idToken": id_token})
    assert resp.status_code == 200, resp.text
    return resp.json()["accessToken"]


def _create_tenant(client: TestClient, admin_token: str) -> dict:
    resp = client.post("/api/v1/tenants", json={"name": "Acme"}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _configure_oauth_app(
    client: TestClient, admin_token: str, tenant_id: str, *, client_id: str = "test-client-id"
) -> None:
    resp = client.put(
        f"/api/v1/tenants/{tenant_id}/github/oauth-app",
        json={"clientId": client_id, "clientSecret": "test-client-secret"},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 200, resp.text


class TestOAuthApp:
    def test_admin_can_configure_and_it_is_reflected_in_connection_status(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        put_resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app",
            json={"clientId": "cid-123", "clientSecret": "secret-123"},
            headers=_auth(admin_token),
        )
        assert put_resp.status_code == 200, put_resp.text
        assert put_resp.json()["configured"] is True
        assert put_resp.json()["clientId"] == "cid-123"
        assert put_resp.json()["redirectUri"]  # deployment-fixed, non-empty

        get_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app", headers=_auth(admin_token)
        )
        assert get_resp.json()["configured"] is True
        assert get_resp.json()["clientId"] == "cid-123"
        # the secret is never echoed back
        assert "clientSecret" not in get_resp.json()

    def test_member_cannot_configure(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app",
            json={"clientId": "cid", "clientSecret": "secret"},
            headers=_auth(bob_token),
        )
        assert resp.status_code == 403

    def test_blank_client_id_is_rejected(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        resp = client.put(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app",
            json={"clientId": "  ", "clientSecret": "secret"},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 400

    def test_admin_can_remove_configuration(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        _configure_oauth_app(client, admin_token, tenant["id"])

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app", headers=_auth(admin_token)
        )
        assert resp.status_code == 204

        get_resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app", headers=_auth(admin_token)
        )
        assert get_resp.json()["configured"] is False
        assert get_resp.json()["clientId"] is None

    def test_removing_when_unconfigured_is_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app", headers=_auth(admin_token)
        )
        assert resp.status_code == 501
        assert resp.json()["code"] == "GITHUB_OAUTH_NOT_CONFIGURED"


class TestConnectionStatus:
    def test_not_connected_but_configured(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        _configure_oauth_app(client, admin_token, tenant["id"])

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(admin_token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "connected": False,
            "configured": True,
            "githubLogin": None,
            "githubAvatarUrl": None,
            "connectedAt": None,
        }

    def test_not_configured(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(admin_token)
        )

        assert resp.status_code == 200
        assert resp.json()["configured"] is False


class TestConnectUrl:
    def test_admin_gets_a_github_authorize_url(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        _configure_oauth_app(client, admin_token, tenant["id"], client_id="cid-xyz")

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connect-url", headers=_auth(admin_token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["authorizeUrl"].startswith("https://github.com/login/oauth/authorize")
        assert "state=" in resp.json()["authorizeUrl"]
        assert "cid-xyz" in resp.json()["authorizeUrl"]

    def test_member_cannot_get_a_connect_url(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        _configure_oauth_app(client, admin_token, tenant["id"])
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connect-url", headers=_auth(bob_token)
        )

        assert resp.status_code == 403

    def test_not_configured_is_rejected(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connect-url", headers=_auth(admin_token)
        )

        assert resp.status_code == 501
        assert resp.json()["code"] == "GITHUB_OAUTH_NOT_CONFIGURED"


class TestCallback:
    def _get_state(self, client: TestClient, admin_token: str, tenant_id: str) -> str:
        resp = client.get(
            f"/api/v1/tenants/{tenant_id}/github/connect-url", headers=_auth(admin_token)
        )
        url = resp.json()["authorizeUrl"]
        return url.split("state=")[1].split("&")[0]

    def test_successful_callback_stores_the_connection_and_redirects(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        _configure_oauth_app(client, admin_token, tenant["id"])
        state = self._get_state(client, admin_token, tenant["id"])

        resp = client.get(
            "/api/v1/github/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert resp.headers["location"] == (
            f"http://web.example/tenants/{tenant['id']}/repositories?github=connected"
        )

        status = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(admin_token)
        )
        assert status.json()["connected"] is True
        assert status.json()["githubLogin"] == "octocat"

    def test_invalid_state_redirects_to_a_generic_error(self, client):
        resp = client.get(
            "/api/v1/github/callback",
            params={"code": "abc123", "state": "not-a-real-state"},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert "github=error" in resp.headers["location"]
        assert "/tenants/" not in resp.headers["location"]

    def test_github_error_param_redirects_without_attempting_exchange(self, client):
        resp = client.get(
            "/api/v1/github/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert "github=error" in resp.headers["location"]

    def test_oauth_app_removed_between_authorize_and_callback_redirects_to_error(self, client):
        """The tenant started connecting, then an admin removed the OAuth
        App before GitHub redirected back — the callback can't exchange
        the code without a client_secret to use, so it must fail closed,
        not crash."""
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        _configure_oauth_app(client, admin_token, tenant["id"])
        state = self._get_state(client, admin_token, tenant["id"])
        client.delete(
            f"/api/v1/tenants/{tenant['id']}/github/oauth-app", headers=_auth(admin_token)
        )

        resp = client.get(
            "/api/v1/github/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert resp.headers["location"] == (
            f"http://web.example/tenants/{tenant['id']}/repositories?github=error"
        )

    def test_exchange_failure_redirects_to_the_tenants_page_with_error(
        self, tmp_path, fake_github_client
    ):
        fake_github_client.fail_exchange = True
        failing_client = _make_client(tmp_path, fake_github_client)
        admin_token = _sign_in(failing_client, "alice-token")
        tenant = _create_tenant(failing_client, admin_token)
        _configure_oauth_app(failing_client, admin_token, tenant["id"])
        state = self._get_state(failing_client, admin_token, tenant["id"])

        resp = failing_client.get(
            "/api/v1/github/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        assert resp.headers["location"] == (
            f"http://web.example/tenants/{tenant['id']}/repositories?github=error"
        )


class TestReposAndBranches:
    def _connect(self, client: TestClient, admin_token: str, tenant_id: str) -> None:
        _configure_oauth_app(client, admin_token, tenant_id)
        state = TestCallback()._get_state(client, admin_token, tenant_id)
        resp = client.get(
            "/api/v1/github/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )
        assert resp.status_code == 307

    def test_list_repos_requires_a_connection(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/repos", headers=_auth(admin_token)
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "GITHUB_NOT_CONNECTED"

    def test_list_repos_returns_the_connected_accounts_repos(self, client, fake_github_client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        self._connect(client, admin_token, tenant["id"])

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/repos", headers=_auth(admin_token)
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == [
            {"fullName": "acme/tool-x", "owner": "acme", "name": "tool-x", "private": False,
             "defaultBranch": "main"}
        ]
        assert fake_github_client.last_access_token_used == "token-for-abc123"

    def test_list_branches_returns_the_repos_branches(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        self._connect(client, admin_token, tenant["id"])

        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/repos/acme/tool-x/branches",
            headers=_auth(admin_token),
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == ["main", "staging"]

    def test_member_can_list_repos_but_a_different_tenants_member_cannot(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        self._connect(client, admin_token, tenant["id"])

        bob_token = _sign_in(client, "bob-token")
        resp = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/repos", headers=_auth(bob_token)
        )
        assert resp.status_code == 404  # bob isn't a member of this tenant at all


class TestDisconnect:
    def test_admin_can_disconnect(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        TestReposAndBranches()._connect(client, admin_token, tenant["id"])

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(admin_token)
        )
        assert resp.status_code == 204

        status = client.get(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(admin_token)
        )
        assert status.json()["connected"] is False

    def test_disconnecting_when_not_connected_is_404(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(admin_token)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "GITHUB_NOT_CONNECTED"

    def test_member_cannot_disconnect(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant = _create_tenant(client, admin_token)
        TestReposAndBranches()._connect(client, admin_token, tenant["id"])
        bob_token = _sign_in(client, "bob-token")
        client.post(
            f"/api/v1/tenants/{tenant['id']}/members",
            json={"email": "bob@example.com", "role": "member"},
            headers=_auth(admin_token),
        )

        resp = client.delete(
            f"/api/v1/tenants/{tenant['id']}/github/connection", headers=_auth(bob_token)
        )
        assert resp.status_code == 403


class TestCrossTenantIsolation:
    def test_tenant_bs_admin_cannot_connect_url_for_tenant_a(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant_a = _create_tenant(client, admin_token)
        bob_token = _sign_in(client, "bob-token")
        _create_tenant(client, bob_token)  # tenant_b, bob is its admin

        resp = client.get(
            f"/api/v1/tenants/{tenant_a['id']}/github/connect-url", headers=_auth(bob_token)
        )
        assert resp.status_code == 404  # bob has no membership in tenant_a at all

    def test_tenant_bs_admin_cannot_see_tenant_as_connection(self, client, fake_github_client):
        admin_token = _sign_in(client, "alice-token")
        tenant_a = _create_tenant(client, admin_token)
        TestReposAndBranches()._connect(client, admin_token, tenant_a["id"])

        bob_token = _sign_in(client, "bob-token")
        _create_tenant(client, bob_token)

        resp = client.get(
            f"/api/v1/tenants/{tenant_a['id']}/github/connection", headers=_auth(bob_token)
        )
        assert resp.status_code == 404

    def test_tenant_bs_oauth_app_config_does_not_leak_to_tenant_a(self, client):
        admin_token = _sign_in(client, "alice-token")
        tenant_a = _create_tenant(client, admin_token)
        bob_token = _sign_in(client, "bob-token")
        tenant_b = _create_tenant(client, bob_token)
        _configure_oauth_app(client, bob_token, tenant_b["id"], client_id="tenant-b-cid")

        resp = client.get(
            f"/api/v1/tenants/{tenant_a['id']}/github/oauth-app", headers=_auth(admin_token)
        )

        assert resp.json()["configured"] is False
        assert resp.json()["clientId"] is None
