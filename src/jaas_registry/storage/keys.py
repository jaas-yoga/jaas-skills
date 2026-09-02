"""Storage key layout, shared by every module that writes or reads them.

blob_key: content-addressed, keyed by digest (see storage/base.py write_blob_if_absent).
tag_key: the mutable-name "tag" for one id+version (write_tag_if_absent enforces
immutability here — this is the artifact registry's analogue of an OCI tag).
"""

from __future__ import annotations

TAG_PREFIX = "tags/"
TAG_MANIFEST_SUFFIX = "manifest.json"
STATUS_SUFFIX = "status.json"
GOVERNANCE_PREFIX = "governance/"
GOVERNANCE_SUFFIX = "governance.json"


def blob_key(digest: str) -> str:
    algo, hex_digest = digest.split(":", 1)
    return f"blobs/{algo}/{hex_digest}"


def tag_key(skill_id: str, version: str) -> str:
    return f"{TAG_PREFIX}{skill_id}/{version}/{TAG_MANIFEST_SUFFIX}"


def status_key(skill_id: str, version: str) -> str:
    """The yank/unyank sidecar (artifact/yank.py) — same directory as
    tag_key's manifest, but written via write_object rather than
    write_tag_if_absent, since this one file is meant to be overwritten."""
    return f"{TAG_PREFIX}{skill_id}/{version}/{STATUS_SUFFIX}"


def governance_key(skill_id: str) -> str:
    """The governance-record sidecar (artifact/governance.py, Phase 3.3) —
    keyed by skill_id only, not skill_id+version like status_key: a
    skill's business purpose/systems-accessed/review-date doesn't vary
    per version, so it lives under its own top-level prefix rather than
    inside any one version's tags/ directory."""
    return f"{GOVERNANCE_PREFIX}{skill_id}/{GOVERNANCE_SUFFIX}"
