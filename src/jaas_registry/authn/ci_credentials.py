"""Verifies CI-presented OIDC credentials for the git-native release
endpoint (api/release_routes.py) and resolves them against
authn/repo_links.py's registry to find which tenant is authorized to
release a given skill id.

This is GitHub Actions' "trusted publishing" model — the CI job presents
a short-lived OIDC ID token, minted fresh per workflow run, with no
secret stored anywhere (https://docs.github.com/en/actions/deployment/
security-hardening-your-deployments/about-security-hardening-with-
openid-connect). It's the same direction npm and PyPI both moved
publishing auth after repeated incidents involving leaked long-lived
publish tokens ("npm/PyPI Trusted Publishers"). A caller that isn't on
GitHub Actions falls back to a normal PAT (authn/pat.py) — see
api/release_routes.py for that branch; this module only covers OIDC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import jwt as pyjwt

from jaas_registry.authn.repo_links import RepoLinkStore
from jaas_registry.common.errors import ErrorCode, JaasError

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"

# "repo:<owner>/<repo>:ref:refs/tags/<tag>" — GitHub's documented subject
# claim shape for a workflow triggered by a tag push. Deliberately only
# accepts a tag ref: a release is a deliberate, versioned act, not
# something every push to a branch should be able to trigger.
_TAG_SUBJECT_RE = re.compile(r"^repo:(?P<repo>[^:]+):ref:refs/tags/(?P<tag>.+)$")


@dataclass(frozen=True)
class CiIdentity:
    repo: str  # "owner/name"
    tag: str
    sha: str | None = None  # GitHub's "sha" claim, when present
    # GitHub's "environment" claim, present only when the workflow job
    # declares `environment: <name>` — the trust boundary this platform
    # relies on for restricting which branch may release (see
    # resolve_release_tenant's caller in api/release_routes.py): GitHub
    # itself enforces, via that environment's deployment branch policy,
    # which branches may run a job targeting it. We never try to derive
    # "which branch is this tag on" ourselves — git has no single answer
    # to that anyway.
    environment: str | None = None


class JwkClient(Protocol):
    def get_signing_key_from_jwt(self, token: str): ...


class GitHubOidcVerifier:
    def __init__(self, *, jwk_client: JwkClient | None = None):
        self._jwk_client = jwk_client or pyjwt.PyJWKClient(GITHUB_OIDC_JWKS_URL)

    def verify(self, id_token: str, *, audience: str) -> CiIdentity:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(id_token)
            payload = pyjwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                issuer=GITHUB_OIDC_ISSUER,
                audience=audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except pyjwt.PyJWTError as exc:
            raise JaasError(
                ErrorCode.INVALID_CI_CREDENTIAL, f"invalid OIDC token: {exc}"
            ) from exc

        subject = payload.get("sub", "")
        match = _TAG_SUBJECT_RE.match(subject)
        if match is None:
            raise JaasError(
                ErrorCode.INVALID_CI_CREDENTIAL,
                f"OIDC token subject '{subject}' is not a tag-triggered GitHub Actions "
                f"run (expected 'repo:<owner>/<repo>:ref:refs/tags/<tag>')",
            )
        return CiIdentity(
            repo=match.group("repo"),
            tag=match.group("tag"),
            sha=payload.get("sha"),
            environment=payload.get("environment"),
        )


def _repo_matches(repo_url: str, oidc_repo: str) -> bool:
    """repo_url is a full URL (https://github.com/acme/tool-x, optionally
    with a trailing .git); oidc_repo is GitHub's own bare 'owner/repo'
    form from the OIDC subject claim."""
    normalized = repo_url.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    return normalized == oidc_repo or normalized.endswith(f"/{oidc_repo}")


def resolve_release_tenant(
    *, identity: CiIdentity, skill_id: str, repo_link_store: RepoLinkStore
) -> str:
    """The core anti-squatting check for the OIDC path: a workflow run can
    only release a skill id if *some* tenant has registered a repo link
    for that id, and the link's repo matches the repo the OIDC token
    actually came from — not just any repo the presenter happens to
    control."""
    link = repo_link_store.find_any(skill_id)
    if link is None:
        raise JaasError(
            ErrorCode.REPO_LINK_REQUIRED,
            f"skill id '{skill_id}' has no registered repo link — a tenant admin must "
            f"register one (POST /api/v1/tenants/{{id}}/repo-links) before CI can release it",
        )
    if not _repo_matches(link.repo_url, identity.repo):
        raise JaasError(
            ErrorCode.REPO_LINK_REQUIRED,
            f"skill id '{skill_id}' is linked to a different repository than this "
            f"workflow run came from",
        )
    return link.tenant_id
