"""Index entry: the denormalized, indexed view of one published skill version.

Design ref: design.md §6.1 (Indexed Fields).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Visibility(StrEnum):
    """ui-design.md §5.1: a property of the skill id, not each version —
    every version of a given id shares one visibility value. PUBLIC is
    discoverable/readable by any authenticated user; PRIVATE is visible only
    to the owning user/tenant and anyone it's been explicitly shared with
    (sharing/grants.py) — sharing is additive metadata on top of PRIVATE,
    never a third enum value (ui-design.md §5.1 note 3)."""

    PUBLIC = "public"
    PRIVATE = "private"


class ArtifactStatus(StrEnum):
    """A post-publish status overlay (artifact/yank.py), layered on top of an
    otherwise-immutable published record via a sidecar file that lives
    alongside the tag manifest — never inside it, and never part of
    index/ingest.py's (de)serialization of the manifest record itself.
    index/bootstrap.py and index/consumer.py are the two places that read
    the sidecar and apply it to an IndexEntry built from the tag."""

    ACTIVE = "active"
    YANKED = "yanked"


@dataclass(frozen=True)
class IndexEntry:
    id: str
    name: str
    description: str
    category: str
    owner_team: str
    version: str
    digest: str
    signature: str
    publish_timestamp: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    runtime_families: tuple[str, ...] = field(default_factory=tuple)
    runtime_ranges: dict[str, str] = field(default_factory=dict)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    # each item is (dependency id, version constraint)
    dependencies: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # ui-design.md §5.3. Defaults preserve every pre-existing call site
    # (tests, fixtures, jaasctl publish) as fully public/unowned, matching
    # this registry's behavior before the visibility model existed — the
    # *API's* publish path (once it requires auth) is what should actually
    # default new skills to PRIVATE, not this dataclass.
    owner_user: str = ""
    owner_tenant: str = ""
    visibility: Visibility = Visibility.PUBLIC
    # Populated only for a version released via api/release_routes.py (the
    # git-native CI path) — None for anything published via the web UI's
    # drafts flow or a local `jaasctl publish`, which is itself meaningful
    # provenance ("not traceable to a CI run").
    source_repo: str | None = None
    source_commit: str | None = None
    source_tag: str | None = None
    source_branch: str | None = None
    ci_run_url: str | None = None
    # The skill's own directory relative to source_repo's root, e.g.
    # "jira.create_ticket" for a repo hosting several skills — None means
    # the repo root *is* the skill (the reference CI workflow's
    # documented "one repo per skill" convention). Best-effort, derived
    # client-side via `git rev-parse --show-prefix` (cli.py's cmd_release)
    # — used only to scope the "browse full source at this tag" feature
    # (api/routes.py's source-files endpoints) to this skill's own files
    # instead of the whole repo; never affects what's packaged/signed.
    source_path: str | None = None
    # A point-in-time guardrail attestation, computed once at publish
    # (guardrails/certification.py) and never recomputed — a later tenant
    # policy change or catalog update does not retroactively change an
    # already-published version's certification. None for anything
    # published without a guardrails_client reachable at publish time
    # (see GuardrailCertification's own None case), or for a record written
    # before this field existed — both read the same way: "not available",
    # never "failed".
    guardrail_certified_level: int | None = None
    # (level, status) for all 4 levels, status one of "certified" |
    # "attempted_with_findings" | "not_attempted".
    guardrail_level_statuses: tuple[tuple[int, str], ...] = ()
    guardrail_warning_check_ids: tuple[str, ...] = ()
    # "dev-rsa" | "sigstore" (artifact/signing.py vs. artifact/sigstore_sign.py) —
    # default preserves every record published before this field existed,
    # matching validation/models.py::ManifestDocument's None->"dev-rsa"
    # handling in index_entry_from_manifest below.
    signature_kind: str = "dev-rsa"
    # Overlaid post-hoc from the status.json sidecar (artifact/yank.py) —
    # never read from or written into the manifest record itself. Default
    # preserves every pre-existing call site (tests, fixtures, a tag
    # written before this field existed) as ACTIVE.
    status: ArtifactStatus = ArtifactStatus.ACTIVE
