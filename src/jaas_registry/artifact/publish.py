"""Publish pipeline: validate, package, sign, verify, write immutably, audit.

Design ref: implementation-plan.md Phase 2. Exit criteria: tampered packages
rejected, duplicate publishes return 409, and a publish audit event carries
actor + digest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from jaas_registry.artifact.packaging import (
    build_normalized_archive,
    collect_package_files,
    compute_digest,
)
from jaas_registry.artifact.signing import DevKeypair, sign_digest
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.artifact.verify import verify_artifact
from jaas_registry.common.audit import AuditSink, PublishAuditEvent, new_publish_event
from jaas_registry.common.errors import ErrorCode, JaasError
from jaas_registry.guardrails.certification import GuardrailCertification, compute_certification
from jaas_registry.guardrails.client import CustomRuleInput, GuardrailsClient
from jaas_registry.guardrails.policy import GuardrailPolicy, default_policy
from jaas_registry.index.events import EventBus, new_index_update_event
from jaas_registry.index.ingest import serialize_published_record
from jaas_registry.index.models import Visibility
from jaas_registry.observability.tracing import annotate_current_span_error
from jaas_registry.storage.base import ObjectStore
from jaas_registry.storage.keys import blob_key as make_blob_key
from jaas_registry.storage.keys import tag_key as make_tag_key
from jaas_registry.validation.graph import validate_no_cycles
from jaas_registry.validation.models import ManifestDocument
from jaas_registry.validation.package import validate_skill_package


@dataclass(frozen=True)
class PublishResult:
    manifest: ManifestDocument
    blob_key: str
    tag_key: str
    audit_event: PublishAuditEvent
    certification: GuardrailCertification | None = None


def load_source_documents(source_dir: Path) -> tuple[dict[str, bytes], dict, dict, list, list]:
    """Read and parse the four package documents (design.md §4.1) from a skill
    source directory. Shared with jaasctl's `validate` command."""
    files = collect_package_files(source_dir)
    manifest_data = yaml.safe_load(files["manifest.yaml"])
    io_schema_data = json.loads(files["schema.json"])
    permissions_data = yaml.safe_load(files["permissions.yaml"]) or []
    dependencies_data = yaml.safe_load(files["dependencies.yaml"]) or []

    # Archive the entrypoint file too (prompt.md/SKILL.md/executor.py/...) —
    # previously only the four metadata documents were ever packaged, so a
    # published skill's own actual content was never downloadable/viewable.
    # `entrypoint` is attacker/user-controlled content straight out of
    # manifest.yaml, so it gets the same path-traversal guard as
    # drafts/store.py's _safe_file_path: no absolute paths, no "..".
    entrypoint = manifest_data.get("entrypoint") if isinstance(manifest_data, dict) else None
    if isinstance(entrypoint, str) and entrypoint:
        candidate = Path(entrypoint)
        if not candidate.is_absolute() and ".." not in candidate.parts:
            entrypoint_path = source_dir / candidate
            if entrypoint_path.is_file():
                files[entrypoint] = entrypoint_path.read_bytes()

    return files, manifest_data, io_schema_data, permissions_data, dependencies_data


def publish_skill(
    *,
    source_dir: Path,
    store: ObjectStore,
    signing_key: DevKeypair,
    trust_policy: TrustPolicy,
    actor: str,
    audit_sink: AuditSink,
    existing_dependency_graph: dict[str, list[str]] | None = None,
    event_bus: EventBus | None = None,
    owner_user: str | None = None,
    owner_tenant: str | None = None,
    visibility: Visibility = Visibility.PUBLIC,
    guardrails_client: GuardrailsClient | None = None,
    guardrail_policy: GuardrailPolicy | None = None,
    custom_rules: tuple[CustomRuleInput, ...] = (),
    source_repo: str | None = None,
    source_commit: str | None = None,
    source_tag: str | None = None,
    source_branch: str | None = None,
    source_path: str | None = None,
    ci_run_url: str | None = None,
) -> PublishResult:
    files, manifest_data, io_schema_data, permissions_data, dependencies_data = (
        load_source_documents(source_dir)
    )
    guardrail_warning_ids: tuple[str, ...] = ()
    certification: GuardrailCertification | None = None
    try:
        docs = validate_skill_package(
            manifest=manifest_data,
            io_schema=io_schema_data,
            permissions=permissions_data,
            dependencies=dependencies_data,
        )

        # design.md §4.5: content-risk gate, independent of and after
        # structural validation, delegated entirely to the standalone
        # jaas-guardrails service over HTTP. Runs before any archive/store
        # write, same "reject before persisting anything" posture as the
        # checks below. Same opt-in-via-None shape as `existing_dependency_graph`
        # above: real callers (cli.py, draft_routes.py) always pass a real
        # client, so production publishes are always scanned; a caller that
        # only cares about signing/storage/index behavior can omit it and
        # skip the scan entirely, rather than needing a live guardrails
        # service just to exercise unrelated code paths.
        if guardrails_client is not None:
            catalog = guardrails_client.fetch_catalog()
            resolved_policy = (
                guardrail_policy
                if guardrail_policy is not None
                else default_policy(owner_tenant or "local", catalog)
            )
            scan = guardrails_client.scan(
                files=files,
                manifest=docs.manifest,
                permissions=docs.permissions.root,
                dependencies=docs.dependencies.root,
                enabled_check_ids=resolved_policy.enabled_check_ids,
                existing_skill_ids=frozenset(existing_dependency_graph or {}),
                custom_rules=custom_rules,
            )
        else:
            scan = None
        if scan is not None and scan.blocking:
            raise JaasError(
                ErrorCode.GUARDRAIL_VIOLATION,
                f"{len(scan.blocking)} guardrail check(s) failed",
                details={"findings": [asdict(f) for f in scan.blocking]},
            )
        if scan is not None:
            guardrail_warning_ids = tuple(f.check_id for f in scan.warnings)
            # design.md §4.5 follow-on: a persisted, queryable attestation
            # of what this exact version passed and at what level — unlike
            # guardrail_warning_ids above (log-only, for trend auditing),
            # this survives on the published record itself (see
            # serialize_published_record below).
            certification = compute_certification(
                scan=scan,
                enabled_check_ids=resolved_policy.enabled_check_ids,
                catalog=catalog,
            )

        if existing_dependency_graph is not None:
            graph = dict(existing_dependency_graph)
            dep_ids = [dep.id for dep in docs.dependencies.root]
            graph[docs.manifest.id] = dep_ids
            for dep_id in dep_ids:
                if dep_id not in graph:
                    raise JaasError(
                        ErrorCode.MISSING_DEPENDENCY,
                        f"dependency '{dep_id}' is not resolvable against published skills",
                    )
            validate_no_cycles(graph)
    except JaasError as exc:
        # design.md §10.3.2: annotate the current span with the validation outcome.
        annotate_current_span_error(exc)
        raise

    archive = build_normalized_archive(files)
    digest = compute_digest(archive)
    signature = sign_digest(digest, signing_key)

    # Ingest verification: re-check our own output before it becomes immutable,
    # guarding against signer/config bugs (design.md §3.3.1).
    verify_artifact(
        archive_bytes=archive, digest=digest, signature=signature, trust_policy=trust_policy
    )

    manifest = docs.manifest.model_copy(update={"digest": digest, "signature": signature})

    blob_key = make_blob_key(digest)
    tag_key = make_tag_key(manifest.id, manifest.version)

    record = serialize_published_record(
        manifest=manifest,
        permissions=docs.permissions,
        dependencies=docs.dependencies,
        publish_timestamp=datetime.now(UTC).isoformat(),
        # ui-design.md §7: a real (web UI) publish call always supplies both
        # explicitly from the caller's session. jaasctl publish has no
        # session/tenant concept, so it defaults to the CLI actor as owner
        # and a fixed "local" tenant, publishing PUBLIC by default — this
        # preserves jaasctl's pre-existing no-auth-needed behavior exactly.
        owner_user=owner_user if owner_user is not None else actor,
        owner_tenant=owner_tenant if owner_tenant is not None else "local",
        visibility=visibility,
        source_repo=source_repo,
        source_commit=source_commit,
        source_tag=source_tag,
        source_branch=source_branch,
        source_path=source_path,
        ci_run_url=ci_run_url,
        certification=certification,
    )

    store.write_blob_if_absent(blob_key, archive)
    store.write_tag_if_absent(tag_key, record)

    if event_bus is not None:
        event_bus.publish(
            new_index_update_event(skill_id=manifest.id, version=manifest.version, tag_key=tag_key)
        )

    event = new_publish_event(
        actor=actor,
        skill_id=manifest.id,
        version=manifest.version,
        digest=digest,
        guardrail_warning_ids=guardrail_warning_ids,
        source_repo=source_repo,
        source_commit=source_commit,
        source_tag=source_tag,
        source_branch=source_branch,
        ci_run_url=ci_run_url,
    )
    audit_sink.emit(event)

    return PublishResult(
        manifest=manifest,
        blob_key=blob_key,
        tag_key=tag_key,
        audit_event=event,
        certification=certification,
    )
