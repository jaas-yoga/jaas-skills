"""Map a published, validated skill package into its index entry, and (de)serialize
the published record stored at the tag key so bootstrap/reconciliation can rebuild
that same entry later without re-reading the raw package files.

Shared by the publish-time index update (Phase 3), the event consumer, and the
Phase 5 bootstrap harvester, so none of them can disagree on field mapping.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from jaas_registry.guardrails.certification import GuardrailCertification, flatten_certification
from jaas_registry.index.models import IndexEntry, Visibility
from jaas_registry.validation.models import (
    DependenciesDocument,
    ManifestDocument,
    PermissionsDocument,
)

logger = logging.getLogger(__name__)


def index_entry_from_manifest(
    manifest: ManifestDocument,
    *,
    permissions: PermissionsDocument | None = None,
    dependencies: DependenciesDocument | None = None,
    publish_timestamp: str | None = None,
    owner_user: str = "",
    owner_tenant: str = "",
    visibility: Visibility = Visibility.PUBLIC,
    source_repo: str | None = None,
    source_commit: str | None = None,
    source_tag: str | None = None,
    source_branch: str | None = None,
    source_path: str | None = None,
    ci_run_url: str | None = None,
    guardrail_certified_level: int | None = None,
    guardrail_level_statuses: tuple[tuple[int, str], ...] = (),
    guardrail_warning_check_ids: tuple[str, ...] = (),
) -> IndexEntry:
    if manifest.digest is None or manifest.signature is None:
        raise ValueError("manifest must be published (digest and signature set) before indexing")

    return IndexEntry(
        id=manifest.id,
        name=manifest.name,
        description=manifest.description,
        category=manifest.category,
        owner_team=manifest.owner.team,
        version=manifest.version,
        digest=manifest.digest,
        signature=manifest.signature,
        signature_kind=manifest.signature_kind or "dev-rsa",
        publish_timestamp=publish_timestamp or datetime.now(UTC).isoformat(),
        tags=tuple(manifest.tags),
        runtime_families=tuple(rt.family for rt in manifest.runtime),
        runtime_ranges={rt.family: rt.version_range for rt in manifest.runtime},
        permissions=tuple(permissions.root) if permissions else (),
        dependencies=tuple((d.id, d.version_constraint) for d in dependencies.root)
        if dependencies
        else (),
        owner_user=owner_user,
        source_repo=source_repo,
        source_commit=source_commit,
        source_tag=source_tag,
        source_branch=source_branch,
        source_path=source_path,
        ci_run_url=ci_run_url,
        owner_tenant=owner_tenant,
        visibility=visibility,
        guardrail_certified_level=guardrail_certified_level,
        guardrail_level_statuses=guardrail_level_statuses,
        guardrail_warning_check_ids=guardrail_warning_check_ids,
    )


def serialize_published_record(
    *,
    manifest: ManifestDocument,
    permissions: PermissionsDocument,
    dependencies: DependenciesDocument,
    publish_timestamp: str,
    owner_user: str = "",
    owner_tenant: str = "",
    visibility: Visibility = Visibility.PUBLIC,
    source_repo: str | None = None,
    source_commit: str | None = None,
    source_tag: str | None = None,
    source_branch: str | None = None,
    source_path: str | None = None,
    ci_run_url: str | None = None,
    certification: GuardrailCertification | None = None,
) -> bytes:
    """What gets written at the tag key (design.md §4.1's four package documents,
    condensed into the one registry-facing metadata record bootstrap reads back)."""
    certified_level, level_statuses, warning_ids = flatten_certification(certification)
    return json.dumps(
        {
            "manifest": json.loads(manifest.model_dump_json(by_alias=True)),
            "permissions": permissions.root,
            "dependencies": [d.model_dump(by_alias=True) for d in dependencies.root],
            "publishTimestamp": publish_timestamp,
            "ownerUser": owner_user,
            "ownerTenant": owner_tenant,
            "visibility": visibility.value,
            "sourceRepo": source_repo,
            "sourceCommit": source_commit,
            "sourceTag": source_tag,
            "sourceBranch": source_branch,
            "sourcePath": source_path,
            "ciRunUrl": ci_run_url,
            "guardrailCertifiedLevel": certified_level,
            "guardrailLevelStatuses": [list(pair) for pair in level_statuses],
            "guardrailWarningCheckIds": warning_ids,
        }
    ).encode()


def parse_published_record(data: bytes) -> IndexEntry:
    obj = json.loads(data)
    manifest = ManifestDocument.model_validate(obj["manifest"])
    permissions = PermissionsDocument.model_validate(obj["permissions"])
    dependencies = DependenciesDocument.model_validate(obj["dependencies"])

    # ui-implementation-plan.md Phase 2 task 7: a record written before the
    # visibility model existed has no "visibility" key. Default that case to
    # PRIVATE (the safe direction — never silently grant new public exposure
    # to something already stored) rather than PUBLIC, and say so loudly.
    if "visibility" not in obj:
        logger.warning(
            "published record for %s@%s predates the visibility model; "
            "defaulting to PRIVATE with no owner",
            manifest.id,
            manifest.version,
        )
        visibility = Visibility.PRIVATE
    else:
        visibility = Visibility(obj["visibility"])

    return index_entry_from_manifest(
        manifest,
        permissions=permissions,
        dependencies=dependencies,
        publish_timestamp=obj["publishTimestamp"],
        owner_user=obj.get("ownerUser", ""),
        owner_tenant=obj.get("ownerTenant", ""),
        visibility=visibility,
        source_repo=obj.get("sourceRepo"),
        source_commit=obj.get("sourceCommit"),
        source_tag=obj.get("sourceTag"),
        source_branch=obj.get("sourceBranch"),
        source_path=obj.get("sourcePath"),
        ci_run_url=obj.get("ciRunUrl"),
        guardrail_certified_level=obj.get("guardrailCertifiedLevel"),
        guardrail_level_statuses=tuple(
            (level, status) for level, status in obj.get("guardrailLevelStatuses", [])
        ),
        guardrail_warning_check_ids=tuple(obj.get("guardrailWarningCheckIds", [])),
    )
