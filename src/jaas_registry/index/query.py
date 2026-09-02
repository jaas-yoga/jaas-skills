"""Query planner: text query, structured filters, pagination, weighted ranking.

Design ref: design.md §6.3 (Ranking Model), implementation-plan.md Phase 3 task 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from jaas_registry.index.models import IndexEntry, Visibility
from jaas_registry.index.runtime_filter import runtime_matches
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.index.usage import usage_score
from jaas_registry.sharing.access import (
    ANONYMOUS,
    CallerContext,
    can_view,
    visible_skill_ids_via_grants,
)
from jaas_registry.sharing.grants import GrantStore

# Weights mirror design.md §6.3, kept in sync with §3.2.3's weighted-field list.
WEIGHT_EXACT_ID = 1.0
WEIGHT_NAME = 0.6
WEIGHT_OWNER = 0.5
WEIGHT_TAG = 0.4
WEIGHT_CATEGORY = 0.3
WEIGHT_DESCRIPTION = 0.2
# IMPLEMENTATION_PLAN.md Phase 3.1: a supporting signal, not a dominant
# one — comparable in magnitude to WEIGHT_CATEGORY, deliberately well
# below WEIGHT_EXACT_ID/WEIGHT_NAME, so popularity nudges ranking rather
# than overriding actual query relevance. A starting point, not tuned
# against real usage data (none exists yet).
WEIGHT_USAGE = 0.3


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
    usage_counts: dict[str, int] | None = None,
) -> SearchPage:
    """`caller`/`grants` apply ui-design.md §5.4's visibility filter — an
    anonymous caller (the default) only ever sees PUBLIC entries, matching
    this endpoint's pre-existing no-auth-required behavior exactly for
    every entry that predates the visibility model (defaults to PUBLIC,
    see index/models.py).

    `usage_counts` (IMPLEMENTATION_PLAN.md Phase 3.1) is None by default —
    every existing caller that doesn't pass it gets byte-identical
    behavior to before this feature existed. `api/routes.py::search_skills`
    only passes a real dict when `feature_flags.usage_ranking_enabled` is
    on; a missing skill_id in the dict scores as zero usage, never an
    error. Applied unconditionally (including to a query-less browse,
    where every candidate's text score is 0.0 and today's fallback is
    purely alphabetical-by-id) — deliberate, not just a tiebreak within
    query matches, since query-less browsing is exactly where a
    popularity signal is most valuable and today has no relevance signal
    at all."""
    candidates: list[ScoredEntry] = []
    # IMPLEMENTATION_PLAN.md Phase 3.2: computed at most once per search()
    # call, lazily (only if a non-public candidate is actually hit) — the
    # request-scoped mitigation ui-implementation-plan.md's risk register
    # specified, replacing what would otherwise be one
    # grants.list_for_skill() file read per non-public candidate with two
    # fixed-cost grants.list_for_grantee() calls for the whole request.
    visible_skill_ids: set[str] | None = None
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
        if entry.visibility != Visibility.PUBLIC:
            if visible_skill_ids is None and grants is not None:
                visible_skill_ids = visible_skill_ids_via_grants(caller, grants)
            if not can_view(
                entry, caller=caller, grants=grants, _visible_skill_ids=visible_skill_ids
            ):
                continue

        text_score = score_entry(entry, query) if query else 0.0
        if query and text_score == 0.0:
            continue

        score = text_score
        if usage_counts is not None:
            # Added after the query-match filter above, on purpose — a
            # popular-but-irrelevant skill must never leak into a
            # specific-query search just because of its usage count.
            score += WEIGHT_USAGE * usage_score(usage_counts.get(entry.id, 0))

        candidates.append(ScoredEntry(entry=entry, score=score))

    # Deterministic Resolution (design.md §2.1.3): score desc, then id asc as a stable tiebreak.
    candidates.sort(key=lambda c: (-c.score, c.entry.id))

    total = len(candidates)
    start = (page - 1) * page_size
    page_items = candidates[start : start + page_size]
    next_page_token = str(page + 1) if start + page_size < total else None

    return SearchPage(items=page_items, total=total, next_page_token=next_page_token)
