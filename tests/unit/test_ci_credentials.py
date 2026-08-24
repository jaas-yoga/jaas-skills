import time
from dataclasses import dataclass

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from jaas_registry.authn.ci_credentials import (
    GITHUB_OIDC_ISSUER,
    CiIdentity,
    GitHubOidcVerifier,
    resolve_release_tenant,
)
from jaas_registry.authn.repo_links import RepoLinkStore
from jaas_registry.common.errors import JaasError

AUDIENCE = "jaas-registry"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@dataclass
class _FakeSigningKey:
    key: object


class _FakeJwkClient:
    """Stands in for jwt.PyJWKClient — returns a fixed public key instead
    of fetching GitHub's real JWKS over the network."""

    def __init__(self, public_key):
        self._public_key = public_key

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(key=self._public_key)


def _make_token(private_key, **claim_overrides) -> str:
    claims = {
        "iss": GITHUB_OIDC_ISSUER,
        "aud": AUDIENCE,
        "sub": "repo:acme/tool-x:ref:refs/tags/v1.2.3",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
    }
    claims.update(claim_overrides)
    return pyjwt.encode(claims, private_key, algorithm="RS256")


class TestGitHubOidcVerifier:
    def test_verifies_a_valid_tag_triggered_token(self, rsa_keypair):
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key)

        identity = verifier.verify(token, audience=AUDIENCE)

        assert identity == CiIdentity(repo="acme/tool-x", tag="v1.2.3")

    def test_rejects_wrong_audience(self, rsa_keypair):
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key, aud="some-other-service")

        with pytest.raises(JaasError, match="invalid OIDC token"):
            verifier.verify(token, audience=AUDIENCE)

    def test_rejects_wrong_issuer(self, rsa_keypair):
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key, iss="https://not-github.example.com")

        with pytest.raises(JaasError, match="invalid OIDC token"):
            verifier.verify(token, audience=AUDIENCE)

    def test_rejects_expired_token(self, rsa_keypair):
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key, exp=int(time.time()) - 10)

        with pytest.raises(JaasError, match="invalid OIDC token"):
            verifier.verify(token, audience=AUDIENCE)

    def test_rejects_branch_ref_not_tag_ref(self, rsa_keypair):
        """A release is a deliberate, versioned act — only a tag-triggered
        run may release, never an arbitrary branch push."""
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key, sub="repo:acme/tool-x:ref:refs/heads/main")

        with pytest.raises(JaasError, match="not a tag-triggered"):
            verifier.verify(token, audience=AUDIENCE)

    def test_captures_the_environment_claim_when_present(self, rsa_keypair):
        """The `environment` claim is the trust boundary release_routes.py
        uses to restrict which branch may release — see repo_links.py's
        `release_branches`. It's only present when the workflow job
        declares `environment:`, so it must be optional here."""
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key, environment="staging")

        identity = verifier.verify(token, audience=AUDIENCE)

        assert identity.environment == "staging"

    def test_environment_defaults_to_none_when_absent(self, rsa_keypair):
        private_key, public_key = rsa_keypair
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(private_key)

        identity = verifier.verify(token, audience=AUDIENCE)

        assert identity.environment is None

    def test_rejects_signature_from_a_different_key(self, rsa_keypair):
        """Proves this actually verifies the signature, not just parses
        claims — a token signed by a different key must be rejected even
        though every claim is otherwise well-formed."""
        _, public_key = rsa_keypair
        other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = GitHubOidcVerifier(jwk_client=_FakeJwkClient(public_key))
        token = _make_token(other_private_key)

        with pytest.raises(JaasError, match="invalid OIDC token"):
            verifier.verify(token, audience=AUDIENCE)


class TestResolveReleaseTenant:
    def test_resolves_the_linked_tenant(self, tmp_path):
        store = RepoLinkStore(tmp_path)
        store.create(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            repo_url="https://github.com/acme/tool-x",
            created_by="usr_1",
        )
        tenant_id = resolve_release_tenant(
            identity=CiIdentity(repo="acme/tool-x", tag="v1.2.3"),
            skill_id="acme.tool.x",
            repo_link_store=store,
        )
        assert tenant_id == "tnt_1"

    def test_matches_a_repo_url_with_a_trailing_git_suffix(self, tmp_path):
        store = RepoLinkStore(tmp_path)
        store.create(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            repo_url="https://github.com/acme/tool-x.git",
            created_by="usr_1",
        )
        tenant_id = resolve_release_tenant(
            identity=CiIdentity(repo="acme/tool-x", tag="v1.2.3"),
            skill_id="acme.tool.x",
            repo_link_store=store,
        )
        assert tenant_id == "tnt_1"

    def test_raises_repo_link_required_when_no_link_exists(self, tmp_path):
        store = RepoLinkStore(tmp_path)
        with pytest.raises(JaasError, match="no registered repo link"):
            resolve_release_tenant(
                identity=CiIdentity(repo="acme/tool-x", tag="v1.2.3"),
                skill_id="acme.tool.x",
                repo_link_store=store,
            )

    def test_raises_when_link_points_at_a_different_repo(self, tmp_path):
        store = RepoLinkStore(tmp_path)
        store.create(
            tenant_id="tnt_1",
            skill_id="acme.tool.x",
            repo_url="https://github.com/acme/a-different-repo",
            created_by="usr_1",
        )
        with pytest.raises(JaasError, match="different repository"):
            resolve_release_tenant(
                identity=CiIdentity(repo="acme/tool-x", tag="v1.2.3"),
                skill_id="acme.tool.x",
                repo_link_store=store,
            )
