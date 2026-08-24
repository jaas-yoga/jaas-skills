"""Cold-start bootstrap timing against design.md §9.1.4 (<= 120s rebuild).

implementation-plan.md Phase 7 task 1. Building the full 50,000-skill capacity
assumption (§9.2.1) on disk just to time one bootstrap would make this test
itself slow to set up; instead this builds a representative sample directly
via serialize_published_record (skipping the RSA signing/packaging overhead
that `publish_skill` would add per skill, which is a CI-time cost unrelated to
what bootstrap itself does) and checks the observed per-skill cost, extrapolated
linearly, stays inside budget at 50,000 — bootstrap is a single sequential
scan with no per-skill fan-out, so linear scaling is the right model here.
"""

from __future__ import annotations

import time

from jaas_registry.index.bootstrap import bootstrap_index
from jaas_registry.index.ingest import serialize_published_record
from jaas_registry.storage.keys import tag_key
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from jaas_registry.validation.models import DependenciesDocument, PermissionsDocument
from jaas_registry.validation.rules import validate_manifest
from tests.fixtures.manifests import VALID_MANIFEST

SAMPLE_SIZE = 5000
TARGET_CORPUS_SIZE = 50_000  # design.md §9.2.1
COLD_START_BUDGET_SECONDS = 120  # design.md §9.1.4


def _seed_published_records(store: LocalFilesystemStore, count: int) -> None:
    permissions = PermissionsDocument.model_validate([])
    dependencies = DependenciesDocument.model_validate([])
    for i in range(count):
        manifest_data = dict(VALID_MANIFEST, id=f"acme.load.skill{i:06d}")
        manifest = validate_manifest(manifest_data).model_copy(
            update={"digest": f"sha256:{i:064x}", "signature": "sig"}
        )
        record = serialize_published_record(
            manifest=manifest,
            permissions=permissions,
            dependencies=dependencies,
            publish_timestamp="2026-01-01T00:00:00+00:00",
        )
        store.write_tag_if_absent(tag_key(manifest.id, manifest.version), record)


def test_bootstrap_cold_start_extrapolates_within_slo_at_target_corpus_size(tmp_path):
    store = LocalFilesystemStore(tmp_path)
    _seed_published_records(store, SAMPLE_SIZE)

    start = time.perf_counter()
    index = bootstrap_index(store)
    elapsed = time.perf_counter() - start

    assert len(index.all_ids()) == SAMPLE_SIZE

    seconds_per_skill = elapsed / SAMPLE_SIZE
    projected_seconds_at_target = seconds_per_skill * TARGET_CORPUS_SIZE
    assert projected_seconds_at_target < COLD_START_BUDGET_SECONDS, (
        f"bootstrap measured {elapsed:.2f}s for {SAMPLE_SIZE} skills "
        f"({seconds_per_skill * 1000:.3f}ms/skill); projected "
        f"{projected_seconds_at_target:.1f}s at {TARGET_CORPUS_SIZE} exceeds "
        f"the {COLD_START_BUDGET_SECONDS}s SLO"
    )
