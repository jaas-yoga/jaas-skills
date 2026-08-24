"""Draft data model. ui-design.md §7, §11.

A draft is mutable scratch space for an in-progress, unpublished skill
package — explicitly separate from the immutable blobs/tags storage
(design.md §2.1.1), never indexed or searchable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Draft:
    id: str
    owner_user: str
    owner_tenant: str
    created_at: str
    forked_from_id: str | None = None
    forked_from_version: str | None = None
    # Optional git-backed persistence (drafts/git_sync.py) — all None means
    # "local disk only," today's default and the only state prior to this
    # field's introduction. provider is validated against a fixed set
    # ("github" today) at the API boundary, not here.
    provider: str | None = None
    repo_url: str | None = None
    git_owner: str | None = None
    git_repo: str | None = None
    target_branch: str | None = None
    working_branch: str | None = None
    last_synced_sha: str | None = None
    git_sync_error: str | None = None
    # The folder (under the repo root) this draft's files are committed
    # under, letting one repo host several skills without their files
    # colliding at the root — see drafts/git_sync.py's skill_directory_name.
    # None means "not yet using a directory": every draft connected before
    # this field existed, until an explicit move-to-directory migrates it.
    git_subdirectory: str | None = None
