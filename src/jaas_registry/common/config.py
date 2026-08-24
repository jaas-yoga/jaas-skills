"""Configuration model: environment variables, policy files, and feature flags.

Design ref: implementation-plan.md Phase 0, task 2.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FeatureFlags(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JAAS_FEATURE_")

    high_assurance_signature_recheck: bool = False
    tenant_boundary_enforcement: bool = False


class Settings(BaseSettings):
    """Process-wide configuration, sourced from environment variables (12-factor style).

    Local-prototype scope: `storage_root` stands in for the S3/OCI-backed object
    store described in design.md; see storage/local_filesystem.py.
    """

    model_config = SettingsConfigDict(env_prefix="JAAS_", env_file=".env", extra="ignore")

    environment: str = "dev"

    storage_root: Path = Path(".local_registry/artifacts")
    policy_dir: Path = Path(".local_registry/policy")

    jwt_issuer: str = "jaas-registry-dev"
    jwt_audience: str = "jaas-registry"
    # >= 32 bytes: RFC 7518 §3.2 minimum recommended HMAC key length for HS256.
    jwt_secret: str = "dev-only-shared-secret-not-for-prod!!"

    # ui-design.md §4/§6.3: authn/ (Google sign-in) is a distinct concern from
    # authz/ (validating the tokens authn/ mints). No default is provided for
    # google_client_id — an unset value means Google sign-in is not configured
    # for this deployment and authn/google.py must fail closed, not silently
    # accept unverifiable tokens.
    google_client_id: str | None = None

    # Local-dev-only alternative to Google sign-in: a single shared password
    # for a fixed pair of seeded accounts (authn/service.py's
    # _DEV_LOGIN_USERS), for environments where wiring up a real Google
    # OAuth client isn't worth it. Same fail-closed posture as
    # google_client_id — unset means POST /api/v1/auth/login is disabled,
    # never a silently-guessable default password.
    dev_login_password: str | None = None

    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30  # 30 days

    artifact_url_ttl_seconds: int = 120

    index_cold_start_timeout_seconds: int = 120

    # design.md §4.5: the standalone jaas-guardrails service — a separate
    # codebase/process (see the jaas-guardrails-catalog repo), never
    # imported in-process. JAAS_GUARDRAILS_SERVICE_URL overrides for
    # non-local deployments.
    guardrails_service_url: str = "http://127.0.0.1:8028"

    # The `aud` claim a GitHub Actions OIDC token must carry to be accepted
    # by the release endpoint (api/release_routes.py) — a workflow requests
    # this explicitly via `core.getIDToken(audience)` / the `audience:`
    # input to actions/github-script, so it must match exactly on both
    # sides. Distinct from jwt_audience (this app's own session tokens);
    # unrelated token spaces that happen to both need an audience value.
    release_oidc_audience: str = "jaas-registry"

    # authn/github_oauth.py: the "Connect GitHub" flow that powers the live
    # repo/branch picker in Connect-a-repo (tenant_routes.py's repo-links
    # UI). Unlike google_client_id, there is no deployment-wide client id/
    # secret here — each tenant registers its own GitHub OAuth App
    # (authn/github_oauth_apps.py, configured via the Repositories tab), so
    # "not configured" is a per-tenant state, not a global setting. Only
    # the fixed callback URL every tenant's own OAuth App must point at
    # stays deployment-level, since GitHub only allows one redirect URI.
    github_oauth_redirect_uri: str = "http://127.0.0.1:8027/api/v1/github/callback"
    # Where api/github_routes.py::github_callback bounces the browser back
    # to after completing the OAuth exchange — the one place this backend
    # needs to know the frontend's own origin.
    web_app_url: str = "http://localhost:3027"

    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)


def load_settings() -> Settings:
    return Settings()
