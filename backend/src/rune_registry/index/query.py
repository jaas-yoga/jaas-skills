"""Query planner: text query, structured filters, pagination, weighted ranking.

Design ref: design.md §6.3 (Ranking Model), implementation-plan.md Phase 3 task 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from rune_registry.index.models import IndexEntry, Visibility
from rune_registry.index.runtime_filter import runtime_matches
from rune_registry.index.store import InMemoryIndex
from rune_registry.sharing.access import ANONYMOUS, CallerContext, can_view
from rune_registry.sharing.grants import GrantStore

# Weights mirror design.md §6.3, kept in sync with §3.2.3's weighted-field list.
WEIGHT_EXACT_ID = 1.0
WEIGHT_NAME = 0.6
WEIGHT_OWNER = 0.5
WEIGHT_TAG = 0.4
WEIGHT_CATEGORY = 0.3
WEIGHT_DESCRIPTION = 0.2


@dataclass(frozen=True)
class ScoredEntry:
    entry: IndexEntry
    score: float


@dataclass(frozen=True)
class SearchPage:
    items: list[ScoredEntry]
    total: int
    next_page_token: str | None


def score_entry(entry: IndexEntry, query: str) -> float:
    q = query.strip().lower()
    if not q:
        return 0.0
    tokens = q.split()
    score = 0.0
    if q == entry.id.lower():
        score += WEIGHT_EXACT_ID
    if q in entry.name.lower() or any(t in entry.name.lower().split() for t in tokens):
        score += WEIGHT_NAME
    if q in entry.owner_team.lower():
        score += WEIGHT_OWNER
    if any(t in (tag.lower() for tag in entry.tags) for t in tokens):
        score += WEIGHT_TAG
    if q in entry.category.lower():
        score += WEIGHT_CATEGORY
    if q in entry.description.lower():
        score += WEIGHT_DESCRIPTION
    return score


def search(
    index: InMemoryIndex,
    *,
    query: str | None = None,
    tags: list[str] | None = None,
    category: str | None = None,
    runtime: str | None = None,
    version_constraint: str | None = None,
    page: int = 1,
    page_size: int = 20,
    caller: CallerContext = ANONYMOUS,
    grants: GrantStore | None = None,
) -> SearchPage:
    """`caller`/`grants` apply ui-design.md §5.4's visibility filter — an
    anonymous caller (the default) only ever sees PUBLIC entries, matching
    this endpoint's pre-existing no-auth-required behavior exactly for
    every entry that predates the visibility model (defaults to PUBLIC,
    see index/models.py)."""
    candidates: list[ScoredEntry] = []
    for skill_id in index.all_ids():
        entry = index.get_resolved(skill_id, version_constraint)
        if entry is None:
            continue
        if runtime and not runtime_matches(entry, runtime):
            continue
        if category and entry.category != category:
            continue
        if tags and not set(tags).issubset(entry.tags):
            continue
        # Cheap inline check for the overwhelmingly common case (public)
        # avoids a full can_view() call+grant-store dispatch per candidate;
        # ordered after the category/tags/runtime filters above so it only
        # runs against whatever already survived those (typically a small
        # fraction of the corpus), not every entry in the index.
        if entry.visibility != Visibility.PUBLIC and not can_view(
            entry, caller=caller, grants=grants
        ):
            continue

        score = score_entry(entry, query) if query else 0.0
        if query and score == 0.0:
            continue

        candidates.append(ScoredEntry(entry=entry, score=score))

    # Deterministic Resolution (design.md §2.1.3): score desc, then id asc as a stable tiebreak.
    candidates.sort(key=lambda c: (-c.score, c.entry.id))

    total = len(candidates)
    start = (page - 1) * page_size
    page_items = candidates[start : start + page_size]
    next_page_token = str(page + 1) if start + page_size < total else None

    return SearchPage(items=page_items, total=total, next_page_token=next_page_token)
