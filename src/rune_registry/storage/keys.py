"""Storage key layout, shared by every module that writes or reads them.

blob_key: content-addressed, keyed by digest (see storage/base.py write_blob_if_absent).
tag_key: the mutable-name "tag" for one id+version (write_tag_if_absent enforces
immutability here — this is the artifact registry's analogue of an OCI tag).
"""

from __future__ import annotations

TAG_PREFIX = "tags/"
TAG_MANIFEST_SUFFIX = "manifest.json"


def blob_key(digest: str) -> str:
    algo, hex_digest = digest.split(":", 1)
    return f"blobs/{algo}/{hex_digest}"


def tag_key(skill_id: str, version: str) -> str:
    return f"{TAG_PREFIX}{skill_id}/{version}/{TAG_MANIFEST_SUFFIX}"
