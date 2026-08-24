"""Draft persistence. ui-design.md §7, §11.1-11.4.

Same local-prototype, no-database convention as authn/ and sharing/. Each
draft is a directory of raw files plus a `_meta.json` sidecar — deliberately
NOT the immutable blob/tag storage (storage/local_filesystem.py), since a
draft is mutable scratch space by design, not a published artifact.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

from rune_registry.artifact.packaging import extract_archive
from rune_registry.common.errors import ErrorCode, RuneError
from rune_registry.drafts.models import Draft

_META_FILENAME = "_meta.json"

# A blank (not forked) draft used to start with zero files, so the very
# first Validate/Publish attempt always failed with MISSING_REQUIRED_FILE.
# manifest.yaml is the only document with no sensible default (id/name/
# version/owner are the skill's own identity — see artifact/packaging.py's
# REQUIRED_PACKAGE_FILES), so it's the only one seeded here; schema.json/
# permissions.yaml/dependencies.yaml are optional everywhere else in the
# system now too, and fall back to DEFAULT_PACKAGE_FILE_CONTENTS on publish
# if the user never adds them. Deliberately valid against validation/
# rules.py as-is (id format, strict SemVer, a real runtime declaration) so
# a brand new draft can be Published immediately as a genuine "hello world"
# skill without editing anything.
_STARTER_FILES: dict[str, bytes] = {
    "manifest.yaml": b"""\
apiVersion: v1
id: your-team.your-domain.your-skill
name: New Skill
version: 0.1.0
description: Describe what this skill does.
owner:
  team: your-team
entrypoint: prompt.md
category: general
tags: []
runtime:
  - family: prompt
    versionRange: ">=1.0.0,<2.0.0"
""",
}


class DraftStore:
    def __init__(self, policy_dir: Path):
        self._dir = policy_dir / "drafts"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _draft_dir(self, draft_id: str) -> Path:
        return self._dir / draft_id

    def _meta_path(self, draft_id: str) -> Path:
        return self._draft_dir(draft_id) / _META_FILENAME

    def _safe_file_path(self, draft_id: str, relative_path: str) -> Path:
        """Rejects anything that could escape the draft's own directory —
        `relative_path` is caller-supplied (a request body/path param), so
        this is a real trust boundary, not defensive theater."""
        draft_dir = self._draft_dir(draft_id).resolve()
        if not relative_path or relative_path == _META_FILENAME:
            raise RuneError(ErrorCode.INVALID_FILE_PATH, f"invalid file path '{relative_path}'")
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuneError(ErrorCode.INVALID_FILE_PATH, f"invalid file path '{relative_path}'")
        resolved = (draft_dir / candidate).resolve()
        if resolved != draft_dir and draft_dir not in resolved.parents:
            raise RuneError(ErrorCode.INVALID_FILE_PATH, f"invalid file path '{relative_path}'")
        return resolved

    def create(
        self,
        *,
        owner_user: str,
        owner_tenant: str,
        fork_archive_bytes: bytes | None = None,
        forked_from_id: str | None = None,
        forked_from_version: str | None = None,
    ) -> Draft:
        draft = Draft(
            id=f"draft_{uuid.uuid4().hex[:20]}",
            owner_user=owner_user,
            owner_tenant=owner_tenant,
            created_at=datetime.now(UTC).isoformat(),
            forked_from_id=forked_from_id,
            forked_from_version=forked_from_version,
        )
        draft_dir = self._draft_dir(draft.id)
        draft_dir.mkdir(parents=True, exist_ok=True)
        self._meta_path(draft.id).write_text(json.dumps(asdict(draft)))

        seed_files = (
            extract_archive(fork_archive_bytes)
            if fork_archive_bytes is not None
            else _STARTER_FILES
        )
        for name, content in seed_files.items():
            self.write_file(draft.id, name, content)

        return draft

    def get(self, draft_id: str) -> Draft | None:
        meta_path = self._meta_path(draft_id)
        if not meta_path.exists():
            return None
        return Draft(**json.loads(meta_path.read_text()))

    def list_for_user(self, owner_user: str) -> list[Draft]:
        drafts = []
        for meta_path in self._dir.glob(f"*/{_META_FILENAME}"):
            draft = Draft(**json.loads(meta_path.read_text()))
            if draft.owner_user == owner_user:
                drafts.append(draft)
        return sorted(drafts, key=lambda d: d.created_at, reverse=True)

    def list_files(self, draft_id: str) -> list[str]:
        draft_dir = self._draft_dir(draft_id)
        return sorted(
            str(p.relative_to(draft_dir))
            for p in draft_dir.rglob("*")
            if p.is_file() and p.name != _META_FILENAME
        )

    def read_file(self, draft_id: str, relative_path: str) -> bytes | None:
        path = self._safe_file_path(draft_id, relative_path)
        if not path.is_file():
            return None
        return path.read_bytes()

    def write_file(self, draft_id: str, relative_path: str, content: bytes) -> None:
        path = self._safe_file_path(draft_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def delete_file(self, draft_id: str, relative_path: str) -> None:
        path = self._safe_file_path(draft_id, relative_path)
        path.unlink(missing_ok=True)

    def delete(self, draft_id: str) -> None:
        shutil.rmtree(self._draft_dir(draft_id), ignore_errors=True)

    def _replace(self, draft_id: str, **fields) -> Draft:
        draft = self.get(draft_id)
        if draft is None:
            raise RuneError(ErrorCode.DRAFT_NOT_FOUND, f"draft '{draft_id}' not found")
        updated = replace(draft, **fields)
        self._meta_path(draft_id).write_text(json.dumps(asdict(updated)))
        return updated

    def set_git_connection(
        self,
        draft_id: str,
        *,
        provider: str,
        repo_url: str,
        git_owner: str,
        git_repo: str,
        target_branch: str,
        working_branch: str,
        last_synced_sha: str,
        git_subdirectory: str,
    ) -> Draft:
        return self._replace(
            draft_id,
            provider=provider,
            repo_url=repo_url,
            git_owner=git_owner,
            git_repo=git_repo,
            target_branch=target_branch,
            working_branch=working_branch,
            last_synced_sha=last_synced_sha,
            git_sync_error=None,
            git_subdirectory=git_subdirectory,
        )

    def set_git_subdirectory(self, draft_id: str, subdirectory: str) -> Draft:
        """One-time migration for a draft connected before per-skill
        directories existed — see api/draft_routes.py's move_draft_to_git_
        directory, the only caller. Never called on a draft that already
        has one (that route 409s first)."""
        return self._replace(draft_id, git_subdirectory=subdirectory)

    def set_sync_status(
        self, draft_id: str, *, sha: str | None = None, error: str | None = None
    ) -> Draft:
        """Called after every write-through commit attempt. A success
        (`sha` set) always clears any previous error; a failure (`error`
        set) never touches `last_synced_sha` — the UI's "synced" state
        reflects the last commit that actually landed, not this attempt."""
        if sha is not None:
            return self._replace(draft_id, last_synced_sha=sha, git_sync_error=None)
        return self._replace(draft_id, git_sync_error=error)
