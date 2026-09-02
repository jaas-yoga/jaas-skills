"""Git-native release endpoint: CI calls this once a version tag is
pushed. Two credential paths, mutually exclusive:

- `X-Jaas-OIDC-Token`: a GitHub Actions OIDC ID token (see
  authn/ci_credentials.py). Recommended — nothing long-lived to leak.
- `Authorization: Bearer <PAT>`: the same personal-access-token auth every
  other endpoint here already accepts, for CI systems that aren't GitHub
  Actions.

Either way, the resolved tenant must have a repo-links.py registration
for the skill id being released, and the underlying pipeline is exactly
`artifact/publish.py::publish_skill()` — the same one `jaasctl publish`
and the web UI's draft-publish already go through. `guardrails_client` is
never optional here (unlike the CLI's local-dev-only opt-out): every
git-triggered release is scanned, no exceptions.
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jaas_registry.api.deps import (
    AuthorizerDep,
    CustomGuardrailRuleStoreDep,
    GuardrailCatalogDep,
    GuardrailPolicyStoreDep,
    GuardrailsClientDep,
    IndexDep,
    OidcVerifierDep,
    RepoLinkStoreDep,
    SettingsDep,
    StoreDep,
)
from jaas_registry.api.schemas import ReleaseRequest, ReleaseResponse
from jaas_registry.artifact.packaging import build_normalized_archive, compute_digest
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import load_or_create_keypair
from jaas_registry.artifact.sigstore_trust import load_sigstore_trust_policy
from jaas_registry.artifact.trust import ensure_key_registered, load_trust_policy
from jaas_registry.authn.ci_credentials import GitHubOidcVerifier, resolve_release_tenant
from jaas_registry.authn.repo_links import RepoLinkStore
from jaas_registry.common.audit import StructuredLogAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.guardrails.certification import flatten_certification
from jaas_registry.guardrails.policy import GuardrailPolicy
from jaas_registry.guardrails.skill_config import (
    GUARDRAILS_CONFIG_PATH,
    parse_skill_guardrail_config,
    resolve_guardrails_for_skill,
)
from jaas_registry.index.ingest import parse_published_record
from jaas_registry.sharing.access import resolve_caller_context
from jaas_registry.storage.keys import tag_key as make_tag_key

router = APIRouter(prefix="/api/v1/skills")
_bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_tenant(
    *,
    body: ReleaseRequest,
    skill_id: str,
    settings: Settings,
    authorizer,
    repo_link_store: RepoLinkStore,
    oidc_verifier: GitHubOidcVerifier,
    oidc_token: str | None,
    credentials: HTTPAuthorizationCredentials | None,
) -> tuple[str, str, dict]:
    """Returns (tenant_id, owner_user, provenance dict). Exactly one of the
    two auth paths is used, chosen by which credential the caller
    presented. `owner_user` is the repo link's `created_by` — the admin
    who registered this skill id — not a git identity (CI has none); it's
    what the web UI's ownership checks (e.g. "New Version"/Share buttons)
    key off, so it must be a real user id, never the repo URL string used
    for `actor`/provenance below."""
    if oidc_token is not None:
        identity = oidc_verifier.verify(oidc_token, audience=settings.release_oidc_audience)
        if identity.tag != body.tag:
            raise JaasError(
                ErrorCode.RELEASE_VERSION_MISMATCH,
                f"request tag '{body.tag}' does not match the OIDC token's tag "
                f"'{identity.tag}' — refusing to release under a mismatched claim",
            )
        tenant_id = resolve_release_tenant(
            identity=identity, skill_id=skill_id, repo_link_store=repo_link_store
        )
        link = repo_link_store.get(tenant_id=tenant_id, skill_id=skill_id)
        assert link is not None  # resolve_release_tenant() just proved this link exists
        _check_release_branch_allowed(
            link, source_branch=identity.environment, hint="declare a matching `environment:`"
        )
        provenance = {
            "source_repo": identity.repo,
            "source_commit": identity.sha,
            "source_tag": identity.tag,
            "source_branch": identity.environment,
            "source_path": body.sourcePath,
            "ci_run_url": body.ciRunUrl,
        }
        return tenant_id, link.created_by, provenance

    # PAT fallback: identical bearer-token auth every other endpoint uses.
    # A PAT already carries a `tenant` claim from the same JWT machinery
    # session tokens use (see authn/pat.py), so no new scope is needed —
    # the repo-link check below is what actually authorizes the release.
    authorizer.check(
        token=credentials.credentials if credentials else None,
        tenant_header=None,
        required_permissions=("skills:write",),
    )
    caller = resolve_caller_context(
        credentials.credentials if credentials else None, settings=settings
    )
    tenant_id = caller.tenant_id or ""
    if not body.repoUrl:
        raise JaasError(
            ErrorCode.SCHEMA_VALIDATION_FAILED,
            "repoUrl is required when releasing with a personal access token",
        )
    link = repo_link_store.get(tenant_id=tenant_id, skill_id=skill_id)
    if link is None or link.repo_url.rstrip("/") != body.repoUrl.rstrip("/"):
        raise JaasError(
            ErrorCode.REPO_LINK_REQUIRED,
            f"skill id '{skill_id}' has no repo link registered for this tenant matching "
            f"the given repoUrl",
        )
    _check_release_branch_allowed(
        link, source_branch=body.releaseBranch, hint="pass `releaseBranch` in the request body"
    )
    provenance = {
        "source_repo": body.repoUrl,
        "source_commit": None,
        "source_tag": body.tag,
        "source_branch": body.releaseBranch,
        "source_path": body.sourcePath,
        "ci_run_url": body.ciRunUrl,
    }
    return tenant_id, link.created_by, provenance


def _check_release_branch_allowed(link, *, source_branch: str | None, hint: str) -> None:
    """Empty `release_branches` (the default) means no restriction — every
    repo link created before this feature existed, and every tenant that
    doesn't need multiple release lines, is unaffected. Once a tenant
    opts in, an unresolvable branch (missing entirely, or not in the
    allow-list) is rejected rather than silently accepted, since we can't
    fall back to "no restriction" without defeating the point of opting
    in."""
    if not link.release_branches:
        return
    if source_branch is None or source_branch not in link.release_branches:
        raise JaasError(
            ErrorCode.RELEASE_LINE_NOT_ALLOWED,
            f"skill id '{link.skill_id}' only allows releases from "
            f"{sorted(link.release_branches)}, but this release did not resolve to one of "
            f"them — {hint}",
        )


@router.post("/release", response_model=ReleaseResponse)
def release_skill(
    body: ReleaseRequest,
    settings: SettingsDep,
    authorizer: AuthorizerDep,
    store: StoreDep,
    index: IndexDep,
    repo_link_store: RepoLinkStoreDep,
    guardrail_policy_store: GuardrailPolicyStoreDep,
    guardrail_catalog: GuardrailCatalogDep,
    guardrails_client: GuardrailsClientDep,
    custom_rule_store: CustomGuardrailRuleStoreDep,
    oidc_verifier: OidcVerifierDep,
    oidc_token: Annotated[str | None, Header(alias="X-Jaas-OIDC-Token")] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> ReleaseResponse:
    files = {path: base64.b64decode(content) for path, content in body.files.items()}
    manifest_bytes = files.get("manifest.yaml")
    if manifest_bytes is None:
        raise JaasError(ErrorCode.MISSING_REQUIRED_FILE, "release is missing manifest.yaml")
    manifest_peek = yaml.safe_load(manifest_bytes)
    skill_id = manifest_peek.get("id", "") if isinstance(manifest_peek, dict) else ""
    manifest_version = manifest_peek.get("version", "") if isinstance(manifest_peek, dict) else ""
    if not skill_id:
        raise JaasError(ErrorCode.MISSING_REQUIRED_FILE, "manifest.yaml is missing an id")

    # A tag must name the exact version it releases — the same discipline
    # `npm publish`/`cargo publish` implicitly rely on package metadata
    # for, checked explicitly here rather than trusting CI got it right.
    if body.tag.removeprefix("v") != manifest_version:
        raise JaasError(
            ErrorCode.RELEASE_VERSION_MISMATCH,
            f"tag '{body.tag}' does not match manifest.yaml version '{manifest_version}'",
        )

    tenant_id, owner_user, provenance = _resolve_tenant(
        body=body,
        skill_id=skill_id,
        settings=settings,
        authorizer=authorizer,
        repo_link_store=repo_link_store,
        oidc_verifier=oidc_verifier,
        oidc_token=oidc_token,
        credentials=credentials,
    )

    policy = guardrail_policy_store.get(tenant_id, guardrail_catalog)
    skill_config = parse_skill_guardrail_config(files.get(GUARDRAILS_CONFIG_PATH))
    enabled_ids, custom_rules = resolve_guardrails_for_skill(
        tenant_id=tenant_id,
        skill_id=skill_id,
        policy=policy,
        catalog_ids=frozenset(d.id for d in guardrail_catalog),
        skill_config=skill_config,
        custom_rule_store=custom_rule_store,
    )
    resolved_policy = GuardrailPolicy(tenant_id=tenant_id, enabled_check_ids=enabled_ids)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for name, content in files.items():
            dest = tmp_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        # release_routes.py's callers never send io_schema/permissions/
        # dependencies as separate top-level fields the way drafts do —
        # everything travels as files, so make sure the four required
        # documents collect_package_files() expects are present as real
        # files (schema.json etc. must exist even if empty-shaped).
        if not (tmp_dir / "schema.json").exists():
            (tmp_dir / "schema.json").write_text(json.dumps({"inputs": {}, "outputs": {}}))
        if not (tmp_dir / "permissions.yaml").exists():
            (tmp_dir / "permissions.yaml").write_text("[]\n")
        if not (tmp_dir / "dependencies.yaml").exists():
            (tmp_dir / "dependencies.yaml").write_text("[]\n")

        # IMPLEMENTATION_PLAN.md Phase 1.2: a caller that already signed
        # client-side with Sigstore (jaasctl release on the OIDC path)
        # skips server-side dev-RSA signing entirely — the registry only
        # ever verifies that signature, never produces its own. A caller
        # with no bundle falls back to dev-RSA, unless this deployment has
        # opted into requiring Sigstore for every release. publish_skill()
        # itself enforces "exactly one of signing_key/external_signature";
        # both pairs are passed explicitly (rather than a **kwargs dict)
        # so that invariant stays type-checked here too.
        keypair = None
        trust_policy = None
        sigstore_trust_policy = None
        if body.sigstoreBundle is not None:
            sigstore_trust_policy = load_sigstore_trust_policy(
                identity_issuer=settings.sigstore_identity_issuer
            )
        elif settings.feature_flags.sigstore_signing_required:
            raise JaasError(
                ErrorCode.SIGSTORE_SIGNATURE_REQUIRED,
                "this deployment requires a Sigstore signature for releases — upgrade "
                "jaasctl and release via the OIDC auth path, which signs automatically",
            )
        else:
            keypair = load_or_create_keypair(settings.policy_dir / "signing_key.pem")
            ensure_key_registered(settings.policy_dir, keypair.public_key_pem())
            trust_policy = load_trust_policy(settings.policy_dir)

        try:
            result = publish_skill(
                source_dir=tmp_dir,
                store=store,
                signing_key=keypair,
                trust_policy=trust_policy,
                external_signature=body.sigstoreBundle,
                sigstore_trust_policy=sigstore_trust_policy,
                actor=provenance["source_repo"] or "ci",
                audit_sink=StructuredLogAuditSink(),
                owner_user=owner_user,
                owner_tenant=tenant_id,
                guardrails_client=guardrails_client,
                guardrail_policy=resolved_policy,
                custom_rules=custom_rules,
                source_repo=provenance["source_repo"],
                source_commit=provenance["source_commit"],
                source_tag=provenance["source_tag"],
                source_branch=provenance["source_branch"],
                source_path=provenance["source_path"],
                ci_run_url=provenance["ci_run_url"],
            )
        except FileNotFoundError as exc:
            raise JaasError(ErrorCode.MISSING_REQUIRED_FILE, str(exc)) from exc
        except JaasError as exc:
            if exc.code is not ErrorCode.DUPLICATE_PUBLISH:
                raise
            # A CI re-run of the same tag (retry after a transient
            # failure, or the workflow simply ran twice) must succeed, not
            # fail the pipeline — the version is already published,
            # byte-for-byte identical, and immutable either way. Recompute
            # the digest the same way publish_skill() would have, purely
            # to answer the caller; nothing is written again. Still worth
            # re-indexing: this retry may be landing in a fresh process
            # (after a restart) whose in-memory index never saw the
            # original publish.
            digest = compute_digest(build_normalized_archive(files))
            index.put(parse_published_record(store.read(make_tag_key(skill_id, manifest_version))))
            return ReleaseResponse(id=skill_id, version=manifest_version, digest=digest)

    # publish_skill() only writes the blob/tag — this app's index is a
    # single in-process InMemoryIndex with no background consumer wired to
    # it (index/consumer.py's IndexEventConsumer exists for a future multi-
    # replica deployment, not this one), so without this a release would be
    # invisible to search/metadata lookups until the next process restart.
    index.put(parse_published_record(store.read(result.tag_key)))

    certified_level, level_statuses, warning_ids = flatten_certification(result.certification)
    return ReleaseResponse(
        id=result.manifest.id,
        version=result.manifest.version,
        digest=result.manifest.digest,
        guardrailCertifiedLevel=certified_level,
        guardrailLevelStatuses=level_statuses,
        guardrailWarningCheckIds=warning_ids,
    )
