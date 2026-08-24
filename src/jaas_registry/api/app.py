"""API gateway app factory. Design ref: design.md §3.1."""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry.trace import Tracer

from jaas_registry.api import observability_routes
from jaas_registry.api.account_routes import router as account_router
from jaas_registry.api.auth_routes import router as auth_router
from jaas_registry.api.draft_routes import router as draft_router
from jaas_registry.api.errors import register_error_handlers
from jaas_registry.api.github_routes import router as github_router
from jaas_registry.api.guardrail_routes import router as guardrail_router
from jaas_registry.api.middleware import ObservabilityMiddleware
from jaas_registry.api.release_routes import router as release_router
from jaas_registry.api.routes import router
from jaas_registry.api.tenant_routes import router as tenant_router
from jaas_registry.artifact.tokens import ArtifactTokenIssuer
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.authn.ci_credentials import GitHubOidcVerifier
from jaas_registry.authn.github_client import GitHubApiClient, HttpGitHubApiClient
from jaas_registry.authn.github_connections import GitHubConnectionStore
from jaas_registry.authn.github_oauth_apps import GitHubOAuthAppStore
from jaas_registry.authn.invites import InviteStore
from jaas_registry.authn.pat import PatStore
from jaas_registry.authn.repo_links import RepoLinkStore
from jaas_registry.authn.tenants import MembershipStore, TenantStore
from jaas_registry.authn.tokens import RefreshTokenStore
from jaas_registry.authn.users import UserStore
from jaas_registry.authz.base import AllowAllAuthorizer, Authorizer
from jaas_registry.common.config import Settings
from jaas_registry.drafts.store import DraftStore
from jaas_registry.guardrails.client import GuardrailsClient, HttpGuardrailsClient
from jaas_registry.guardrails.custom_rules import CustomGuardrailRuleStore
from jaas_registry.guardrails.policy import GuardrailPolicyStore
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.observability.tracing import build_tracer
from jaas_registry.sharing.grants import GrantStore
from jaas_registry.storage.base import ObjectStore


def create_app(
    *,
    index: InMemoryIndex,
    store: ObjectStore,
    settings: Settings,
    authorizer: Authorizer | None = None,
    token_issuer: ArtifactTokenIssuer | None = None,
    trust_policy: TrustPolicy | None = None,
    user_store: UserStore | None = None,
    tenant_store: TenantStore | None = None,
    membership_store: MembershipStore | None = None,
    refresh_token_store: RefreshTokenStore | None = None,
    grant_store: GrantStore | None = None,
    draft_store: DraftStore | None = None,
    invite_store: InviteStore | None = None,
    pat_store: PatStore | None = None,
    guardrail_policy_store: GuardrailPolicyStore | None = None,
    custom_guardrail_rule_store: CustomGuardrailRuleStore | None = None,
    repo_link_store: RepoLinkStore | None = None,
    github_connection_store: GitHubConnectionStore | None = None,
    github_oauth_app_store: GitHubOAuthAppStore | None = None,
    github_api_client: GitHubApiClient | None = None,
    oidc_verifier: GitHubOidcVerifier | None = None,
    guardrails_client: GuardrailsClient | None = None,
    tracer: Tracer | None = None,
) -> FastAPI:
    app = FastAPI(title="JaaS Skills", version="0.1.0")
    app.state.index = index
    app.state.store = store
    app.state.settings = settings
    app.state.authorizer = authorizer or AllowAllAuthorizer()
    app.state.token_issuer = token_issuer or ArtifactTokenIssuer(
        ttl_seconds=settings.artifact_url_ttl_seconds
    )
    # Only consulted when feature_flags.high_assurance_signature_recheck is on;
    # empty by default so redemption fails closed if that's enabled without
    # a configured trust policy, rather than silently skipping verification.
    app.state.trust_policy = trust_policy or TrustPolicy()

    # ui-design.md §6.3: authn/'s file-backed stores, same policy_dir as the
    # existing trust-key store.
    app.state.user_store = user_store or UserStore(settings.policy_dir)
    app.state.tenant_store = tenant_store or TenantStore(settings.policy_dir)
    app.state.membership_store = membership_store or MembershipStore(settings.policy_dir)
    app.state.refresh_token_store = refresh_token_store or RefreshTokenStore(settings.policy_dir)
    app.state.grant_store = grant_store or GrantStore(settings.policy_dir)
    app.state.draft_store = draft_store or DraftStore(settings.policy_dir)
    app.state.invite_store = invite_store or InviteStore(settings.policy_dir)
    app.state.pat_store = pat_store or PatStore(settings.policy_dir)
    app.state.guardrail_policy_store = guardrail_policy_store or GuardrailPolicyStore(
        settings.policy_dir
    )
    app.state.custom_guardrail_rule_store = custom_guardrail_rule_store or (
        CustomGuardrailRuleStore(settings.policy_dir)
    )
    app.state.repo_link_store = repo_link_store or RepoLinkStore(settings.policy_dir)
    app.state.github_connection_store = github_connection_store or GitHubConnectionStore(
        settings.policy_dir
    )
    app.state.github_oauth_app_store = github_oauth_app_store or GitHubOAuthAppStore(
        settings.policy_dir
    )
    # Always a real client now — client_id/client_secret are per-tenant
    # (authn/github_oauth_apps.py), passed per-call rather than bound here,
    # so there's nothing deployment-wide left to gate construction on.
    app.state.github_api_client = github_api_client or HttpGitHubApiClient()
    # Constructing this never touches the network — jwt.PyJWKClient fetches
    # GitHub's JWKS lazily, only on the first token it actually needs to
    # verify (and caches it for 5 minutes after that). Tests override this
    # with a fake to verify tokens signed by a throwaway keypair instead.
    app.state.oidc_verifier = oidc_verifier or GitHubOidcVerifier()
    # design.md §4.5: the standalone jaas-guardrails service — a separate
    # codebase/process, reached only over HTTP (guardrails/client.py). Never
    # fetched here at construction time: most routes never touch it, and a
    # temporary blip in that service shouldn't take this whole app down at
    # startup. `api/deps.py::get_guardrail_catalog` fetches on demand, only
    # for the specific requests that actually need it.
    app.state.guardrails_client = guardrails_client or HttpGuardrailsClient(
        settings.guardrails_service_url
    )

    app.add_middleware(ObservabilityMiddleware, tracer=tracer or build_tracer(batch=True))

    register_error_handlers(app)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(draft_router)
    app.include_router(tenant_router)
    app.include_router(guardrail_router)
    app.include_router(release_router)
    app.include_router(github_router)
    app.include_router(account_router)
    app.include_router(observability_routes.router)
    return app
