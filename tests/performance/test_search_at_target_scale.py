"""IMPLEMENTATION_PLAN.md Phase 4.4: does the design.md §9.1 search p95 SLO
(160ms, see test_load.py) still hold at design.md §9.2.1's stated 50,000-
package 12-month capacity target, or only at test_load.py's 2,000-entry
corpus?

Calls `query.py::search()` directly rather than routing through a real ASGI
HTTP client/concurrency harness like test_load.py does: test_load.py already
covers concurrent-request overhead (tracing, header parsing, etc.) at 2,000
entries, so what's new and unproven here is specifically whether the
per-request O(n) candidate scan in search() itself (no inverted index, no
secondary lookups by tag/category -- see index/store.py, index/query.py)
still fits the SLO once n is 25x larger. Isolating that from HTTP/concurrency
overhead keeps this test fast to run and honest about what it's measuring.

Same absolute-wall-clock-budget caveat as test_load.py's own p95 tests
applies here, more so for the query-less browse case below: run in
isolation this reliably has real headroom (~85-130ms vs the 160ms budget,
measured directly during Phase 4.4's investigation), but run at the tail
of the full suite on shared/loaded dev hardware it can occasionally tip
over -- machine noise, not evidence the 50k-entry corpus itself is the
problem (test_load.py's pre-existing 2,000-entry HTTP-path p95 test shows
the identical pattern, unrelated to corpus size).
"""

from __future__ import annotations

import time

from jaas_registry.index.query import search
from jaas_registry.index.store import InMemoryIndex
from tests.fixtures.index_entries import make_entry

TARGET_CORPUS_SIZE = 50_000  # design.md §9.2.1
SEARCH_P95_BUDGET_SECONDS = 0.160  # design.md §9.1, test_load.py
SAMPLE_QUERIES = 20


def _build_target_scale_index() -> InMemoryIndex:
    index = InMemoryIndex()
    categories = ["nlp", "vision", "audio", "nlp-utils", "search"]
    for i in range(TARGET_CORPUS_SIZE):
        index.put(
            make_entry(
                id=f"acme.scale.skill{i:06d}",
                name=f"Skill {i}",
                category=categories[i % len(categories)],
                tags=(f"tag{i % 20}", "shared"),
                version="1.0.0",
            )
        )
    return index


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    idx = int(round(0.95 * (len(ordered) - 1)))
    return ordered[idx]


def test_search_p95_latency_within_slo_at_50k_corpus():
    index = _build_target_scale_index()

    latencies = []
    for _ in range(SAMPLE_QUERIES):
        start = time.perf_counter()
        search(index, query="Skill", category="nlp", tags=["shared"], page_size=20)
        latencies.append(time.perf_counter() - start)

    p95 = _p95(latencies)
    assert p95 < SEARCH_P95_BUDGET_SECONDS, (
        f"search() p95 {p95 * 1000:.1f}ms at a {TARGET_CORPUS_SIZE}-entry "
        f"corpus exceeds the {SEARCH_P95_BUDGET_SECONDS * 1000:.0f}ms SLO "
        "(design.md §9.1) validated at test_load.py's 2,000-entry corpus -- "
        "the O(n) unindexed candidate scan in query.py::search() does not "
        "hold at design.md §9.2.1's 50,000-package target."
    )


def test_browse_p95_latency_within_slo_at_50k_corpus():
    """Query-less browse still scans and sorts the full corpus (index/query.py
    `search()` has no early-exit for an empty query) -- worth its own
    assertion since it's the default landing-page path, not just the
    query-match path above."""
    index = _build_target_scale_index()

    latencies = []
    for _ in range(SAMPLE_QUERIES):
        start = time.perf_counter()
        search(index, page_size=20)
        latencies.append(time.perf_counter() - start)

    p95 = _p95(latencies)
    assert p95 < SEARCH_P95_BUDGET_SECONDS, (
        f"query-less browse p95 {p95 * 1000:.1f}ms at a {TARGET_CORPUS_SIZE}-"
        f"entry corpus exceeds the {SEARCH_P95_BUDGET_SECONDS * 1000:.0f}ms "
        "SLO (design.md §9.1)."
    )
