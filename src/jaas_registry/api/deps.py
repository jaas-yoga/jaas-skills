"""FastAPI dependency accessors, backed by app.state set up in app.py's create_app()."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from jaas_registry.artifact.tokens import ArtifactTokenIssuer
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.authn.ci_credentials import GitHubOidcVerifier
from jaas_registry.authn.github_client import GitHubApiClient
from jaas_registry.authn.github_connections import GitHubConnectionStore
from jaas_registry.authn.github_oauth_apps import GitHubOAuthAppStore
from jaas_registry.authn.google import GoogleIdentityVerifier, RealGoogleIdentityVerifier
from jaas_registry.authn.invites import InviteStore
from jaas_registry.authn.pat import PatStore
from jaas_registry.authn.repo_links import RepoLinkStore
from jaas_registry.authn.tenants import MembershipStore, TenantStore
from jaas_registry.authn.tokens import RefreshTokenStore
from jaas_registry.authn.users import UserStore
from jaas_registry.authz.base import Authorizer
from jaas_registry.common.config import Settings
from jaas_registry.drafts.store import DraftStore
from jaas_registry.guardrails.client import GuardrailsClient
from jaas_registry.guardrails.custom_rules import CustomGuardrailRuleStore
from jaas_registry.guardrails.models import GuardrailDefinition
from jaas_registry.guardrails.policy import GuardrailPolicyStore
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.index.usage import UsageCounter
from jaas_registry.sharing.grants import GrantStore
from jaas_registry.storage.base import ObjectStore


def get_index(request: Request) -> InMemoryIndex:
    return request.app.state.index


def get_store(request: Request) -> ObjectStore:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_authorizer(request: Request) -> Authorizer:
    return request.app.state.authorizer


def get_token_issuer(request: Request) -> ArtifactTokenIssuer:
    return request.app.state.token_issuer


def get_trust_policy(request: Request) -> TrustPolicy:
    return request.app.state.trust_policy


def get_user_store(request: Request) -> UserStore:
    return request.app.state.user_store


def get_tenant_store(request: Request) -> TenantStore:
    return request.app.state.tenant_store


def get_membership_store(request: Request) -> MembershipStore:
    return request.app.state.membership_store


def get_refresh_token_store(request: Request) -> RefreshTokenStore:
    return request.app.state.refresh_token_store


def get_grant_store(request: Request) -> GrantStore:
    return request.app.state.grant_store


def get_usage_counter(request: Request) -> UsageCounter:
    return request.app.state.usage_counter


def get_draft_store(request: Request) -> DraftStore:
    return request.app.state.draft_store


def get_invite_store(request: Request) -> InviteStore:
    return request.app.state.invite_store


def get_pat_store(request: Request) -> PatStore:
    return request.app.state.pat_store


def get_guardrail_policy_store(request: Request) -> GuardrailPolicyStore:
    return request.app.state.guardrail_policy_store


def get_custom_guardrail_rule_store(request: Request) -> CustomGuardrailRuleStore:
    return request.app.state.custom_guardrail_rule_store


def get_repo_link_store(request: Request) -> RepoLinkStore:
    return request.app.state.repo_link_store


def get_github_connection_store(request: Request) -> GitHubConnectionStore:
    return request.app.state.github_connection_store


def get_github_oauth_app_store(request: Request) -> GitHubOAuthAppStore:
    return request.app.state.github_oauth_app_store


def get_github_api_client(request: Request) -> GitHubApiClient:
    """Always a real, usable client now — client_id/client_secret are
    per-tenant (authn/github_oauth_apps.py) and passed per-call, not bound
    here, so there's no deployment-wide "unconfigured" state for this
    object itself. api/github_routes.py fails closed with
    GITHUB_OAUTH_NOT_CONFIGURED when *a given tenant* hasn't registered an
    OAuth App, which this dependency has no way to know in advance."""
    return request.app.state.github_api_client


def get_oidc_verifier(request: Request) -> GitHubOidcVerifier:
    return request.app.state.oidc_verifier


def get_guardrails_client(request: Request) -> GuardrailsClient:
    return request.app.state.guardrails_client


def get_guardrail_catalog(request: Request) -> list[GuardrailDefinition]:
    """Fetched fresh from the standalone guardrails service for whichever
    request actually needs it (raises JaasError(GUARDRAILS_SERVICE_UNAVAILABLE)
    if that service is unreachable) — most routes never call this at all."""
    guardrails_client: GuardrailsClient = request.app.state.guardrails_client
    return guardrails_client.fetch_catalog()


def get_google_verifier(request: Request) -> GoogleIdentityVerifier | None:
    """Fail-closed by construction: only a configured `google_client_id`
    produces a real verifier; AuthService.sign_in_with_google rejects
    outright when this is None rather than skipping verification
    (ui-design.md §6.3). Overridden in tests via FastAPI's
    `app.dependency_overrides` to inject a fake verifier without needing a
    real Google account."""
    settings: Settings = request.app.state.settings
    if not settings.google_client_id:
        return None
    return RealGoogleIdentityVerifier(client_id=settings.google_client_id)


IndexDep = Annotated[InMemoryIndex, Depends(get_index)]
StoreDep = Annotated[ObjectStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
AuthorizerDep = Annotated[Authorizer, Depends(get_authorizer)]
TokenIssuerDep = Annotated[ArtifactTokenIssuer, Depends(get_token_issuer)]
TrustPolicyDep = Annotated[TrustPolicy, Depends(get_trust_policy)]
UserStoreDep = Annotated[UserStore, Depends(get_user_store)]
TenantStoreDep = Annotated[TenantStore, Depends(get_tenant_store)]
MembershipStoreDep = Annotated[MembershipStore, Depends(get_membership_store)]
RefreshTokenStoreDep = Annotated[RefreshTokenStore, Depends(get_refresh_token_store)]
GoogleVerifierDep = Annotated[GoogleIdentityVerifier | None, Depends(get_google_verifier)]
GrantStoreDep = Annotated[GrantStore, Depends(get_grant_store)]
UsageCounterDep = Annotated[UsageCounter, Depends(get_usage_counter)]
DraftStoreDep = Annotated[DraftStore, Depends(get_draft_store)]
InviteStoreDep = Annotated[InviteStore, Depends(get_invite_store)]
PatStoreDep = Annotated[PatStore, Depends(get_pat_store)]
GuardrailPolicyStoreDep = Annotated[GuardrailPolicyStore, Depends(get_guardrail_policy_store)]
CustomGuardrailRuleStoreDep = Annotated[
    CustomGuardrailRuleStore, Depends(get_custom_guardrail_rule_store)
]
RepoLinkStoreDep = Annotated[RepoLinkStore, Depends(get_repo_link_store)]
GitHubConnectionStoreDep = Annotated[GitHubConnectionStore, Depends(get_github_connection_store)]
GitHubOAuthAppStoreDep = Annotated[GitHubOAuthAppStore, Depends(get_github_oauth_app_store)]
GitHubApiClientDep = Annotated[GitHubApiClient, Depends(get_github_api_client)]
OidcVerifierDep = Annotated[GitHubOidcVerifier, Depends(get_oidc_verifier)]
GuardrailsClientDep = Annotated[GuardrailsClient, Depends(get_guardrails_client)]
GuardrailCatalogDep = Annotated[list[GuardrailDefinition], Depends(get_guardrail_catalog)]
