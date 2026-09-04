"""Seeds a fixed set of example skills (../../examples/skills/) into a
fresh registry, so a brand-new local checkout always has something to look
at in /skills instead of an empty "No skills match" page — two public,
one private (user-owned), one private (tenant-owned), matching the four
visibility/ownership combinations the "My Skills" / "My Tenant" / "Public"
filters in visibility-filter.ts distinguish between.

Idempotent by skill id: does nothing once every id below is already in the
index (bumping a seeded package's own manifest.yaml version does NOT
trigger a re-seed of the new version — republish it yourself, the same way
you would any other skill, if you want that).

Never raises — a broken example package or bug in this module must not
prevent the API from starting; each package is attempted independently and
a failure is logged and skipped, not fatal.
"""

from __future__ import annotations

import logging
from pathlib import Path

from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import DevKeypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.authn.tenants import personal_tenant_id
from jaas_registry.authn.users import derive_user_id
from jaas_registry.common.audit import StructuredLogAuditSink
from jaas_registry.index.ingest import parse_published_record
from jaas_registry.index.models import Visibility
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.storage.base import ObjectStore

logger = logging.getLogger(__name__)

# repo root: src/jaas_registry/index/demo_seed.py -> src/jaas_registry ->
# src -> repo root.
_EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples" / "skills"
_SEED_ACTOR = "jaas-registry-examples"

# The dev-login account (authn/service.py's _DEV_LOGIN_USERS) the
# user-owned/tenant-owned demo skills below are seeded under — id
# computed the same deterministic way authn/service.py does, so ownership
# lines up correctly once someone actually signs in as owner@jaas.local,
# even though seeding runs at API startup, before any sign-in has ever
# happened and before a real User/Tenant record for that account exists.
_OWNER_GOOGLE_SUB = "local:owner@jaas.local"
_OWNER_USER_ID = derive_user_id(_OWNER_GOOGLE_SUB)
_OWNER_TENANT_ID = personal_tenant_id(_OWNER_USER_ID)

# (example dir name, skill id, owner_user, owner_tenant). Visibility is
# derived from ownership below: PUBLIC when neither is set, PRIVATE
# otherwise. sharing/access.py's can_view() (design.md §5.4) only ever
# grants private visibility via an owner_tenant match (or an explicit share
# grant) — never owner_user alone — so a private skill with no
# owner_tenant would be visible to literally no one, not even its nominal
# "owner". personal-notes therefore sets *both*: owner_tenant is what
# actually makes it visible to owner@jaas.local, owner_user is what then
# narrows it into "My Skills" specifically (vs. team-runbook below, which
# has no owner_user and so only ever shows under "My Tenant").
_SEED_PACKAGES: tuple[tuple[str, str, str, str], ...] = (
    ("github/git-fundamentals", "jaas.devtools.git-fundamentals", "", ""),
    ("github/github-workflow-assistant", "jaas.devtools.github-assistant", "", ""),
    ("personal-notes", "jaas.demo.personal-notes", _OWNER_USER_ID, _OWNER_TENANT_ID),
    ("team-runbook", "jaas.demo.team-runbook", "", _OWNER_TENANT_ID),
    # The rest of the developer-tools category (EXAMPLE_SKILLS.md's "additional"
    # table) — same public, unowned shape as git-fundamentals/github-workflow-
    # assistant above. ci-failure-triage declares a dependency on
    # jaas.devtools.github-assistant in its dependencies.yaml, but publish_skill()
    # never validates dependency existence when existing_dependency_graph is
    # None (seed_demo_skills below doesn't pass one), so seed order here doesn't
    # matter functionally — kept after github-workflow-assistant anyway for
    # readability.
    (
        "developer-tools/code-review-checklist",
        "jaas.devtools.code-review-checklist",
        "",
        "",
    ),
    (
        "developer-tools/dependency-upgrade-assistant",
        "jaas.devtools.dependency-upgrade-assistant",
        "",
        "",
    ),
    (
        "developer-tools/debugging-methodology",
        "jaas.devtools.debugging-methodology",
        "",
        "",
    ),
    (
        "developer-tools/api-client-generator",
        "jaas.devtools.api-client-generator",
        "",
        "",
    ),
    (
        "developer-tools/database-migration-safety",
        "jaas.devtools.database-migration-safety",
        "",
        "",
    ),
    (
        "developer-tools/monorepo-navigation",
        "jaas.devtools.monorepo-navigation",
        "",
        "",
    ),
    ("developer-tools/ci-failure-triage", "jaas.devtools.ci-failure-triage", "", ""),
    (
        "developer-tools/refactoring-safety-net",
        "jaas.devtools.refactoring-safety-net",
        "",
        "",
    ),
)


def seed_demo_skills(
    *,
    index: InMemoryIndex,
    store: ObjectStore,
    signing_key: DevKeypair,
    trust_policy: TrustPolicy,
) -> None:
    existing_ids = set(index.all_ids())
    for dir_name, skill_id, owner_user, owner_tenant in _SEED_PACKAGES:
        if skill_id in existing_ids:
            continue
        visibility = Visibility.PRIVATE if (owner_user or owner_tenant) else Visibility.PUBLIC
        try:
            result = publish_skill(
                source_dir=_EXAMPLES_DIR / dir_name,
                store=store,
                signing_key=signing_key,
                trust_policy=trust_policy,
                actor=_SEED_ACTOR,
                # Deliberately NOT FileAuditSink (common/audit_store.py) —
                # this seed data is synthetic and runs on every fresh
                # checkout/restart; persisting it into the durable audit
                # trail would pollute a real Phase 3.3 audit export with
                # fake "who did what" records. print-only is correct here.
                audit_sink=StructuredLogAuditSink(),
                owner_user=owner_user,
                owner_tenant=owner_tenant,
                visibility=visibility,
                # No guardrails scan for seed data: this runs at API
                # startup, before there's any guarantee the standalone
                # guardrails service is reachable yet, and these packages
                # are fixed, already-reviewed example content, not
                # arbitrary user input. Shows as "not attempted"
                # certification, same as any other unscanned publish —
                # never a fabricated "certified" badge.
                guardrails_client=None,
            )
        except Exception:
            logger.warning("demo_seed: failed to seed %r, skipping", skill_id, exc_info=True)
            continue
        # publish_skill() only writes the blob/tag; same index.put() +
        # read-back-and-parse pattern api/draft_routes.py uses after its
        # own publish_skill() call, so this new version is actually
        # visible to search immediately rather than only after the next
        # bootstrap_index() (see that call site's comment for why).
        index.put(parse_published_record(store.read(result.tag_key)))
        existing_ids.add(skill_id)
        logger.info("demo_seed: seeded %s@%s", skill_id, result.manifest.version)
