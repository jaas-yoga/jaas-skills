"""Skill packaging: collect files, build a normalized archive, compute its digest.

Design ref: design.md §4.1 (Package Layout), implementation-plan.md Phase 2 task 1.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

# manifest.yaml has no sensible default — id/name/version/owner are the
# skill's own identity, and there's nothing to invent in their place.
REQUIRED_PACKAGE_FILES = ("manifest.yaml",)

# The other three documents *do* have an unambiguous empty default (no
# permissions requested, no dependencies, an open/untyped I/O contract), so
# a skill that doesn't need one of these doesn't have to carry a
# placeholder file just to say so — absence means exactly this.
DEFAULT_PACKAGE_FILE_CONTENTS: dict[str, bytes] = {
    "schema.json": b'{"inputs": {"type": "object", "properties": {}}, '
    b'"outputs": {"type": "object", "properties": {}}}',
    "permissions.yaml": b"[]\n",
    "dependencies.yaml": b"[]\n",
}


def collect_package_files(source_dir: Path) -> dict[str, bytes]:
    """Read the canonical package layout from a skill source directory.
    `manifest.yaml` must exist; the other three documents fall back to
    `DEFAULT_PACKAGE_FILE_CONTENTS` when absent rather than failing."""
    files: dict[str, bytes] = {}
    for name in REQUIRED_PACKAGE_FILES:
        path = source_dir / name
        if not path.is_file():
            raise FileNotFoundError(
                f"skill package at {source_dir} is missing required file '{name}'"
            )
        files[name] = path.read_bytes()
    for name, default_content in DEFAULT_PACKAGE_FILE_CONTENTS.items():
        path = source_dir / name
        files[name] = path.read_bytes() if path.is_file() else default_content
    return files


def build_normalized_archive(files: dict[str, bytes]) -> bytes:
    """Build a deterministic tar archive: sorted names, zeroed metadata, so identical
    logical content always produces identical bytes — required for stable digesting."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def compute_digest(archive_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(archive_bytes).hexdigest()


def extract_archive(archive_bytes: bytes) -> dict[str, bytes]:
    """Inverse of build_normalized_archive — used by drafts/store.py to fork a
    published version's files into a new draft (ui-design.md §11.4), and by
    the skill-files API (api/routes.py) to serve a published version's read-
    only file viewer. Recovers whatever publish_skill actually packaged: the
    four package documents (manifest.yaml plus whatever real-or-defaulted
    schema.json/permissions.yaml/dependencies.yaml collect_package_files
    produced) *and* the entrypoint file manifest.yaml pointed at, if one
    existed on disk at publish time (see artifact/publish.py's
    load_source_documents) — not the full canonical layout in design.md
    §4.1 (README.md, changelog.md, tests/, examples/ are still never
    archived, only the one file entrypoint names)."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            if extracted is not None:
                files[member.name] = extracted.read()
    return files
