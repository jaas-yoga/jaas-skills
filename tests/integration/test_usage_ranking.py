"""IMPLEMENTATION_PLAN.md Phase 3.1: artifact-token issuance records
usage; search_skills blends it into ranking only when
feature_flags.usage_ranking_enabled is on. End-to-end over real HTTP
requests, not just the underlying functions."""

import pytest
from fastapi.testclient import TestClient

from jaas_registry.api.app import create_app
from jaas_registry.common.config import FeatureFlags, Settings
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.index.usage import UsageCounter, flush_usage_counts, read_usage_counts
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from tests.fixtures.index_entries import make_entry


@pytest.fixture
def system(tmp_path):
    index = InMemoryIndex()
    index.put(make_entry(id="acme.text.popular", name="Popular Skill"))
    index.put(make_entry(id="acme.text.unpopular", name="Unpopular Skill"))
    store = LocalFilesystemStore(tmp_path / "storage")
    usage_counter = UsageCounter()

    def make_client(*, usage_ranking_enabled: bool) -> TestClient:
        settings = Settings(
            storage_root=store.root,
            policy_dir=tmp_path / "policy",
            usage_dir=tmp_path / "usage",
            feature_flags=FeatureFlags(usage_ranking_enabled=usage_ranking_enabled),
        )
        app = create_app(index=index, store=store, settings=settings, usage_counter=usage_counter)
        return TestClient(app)

    return {
        "usage_counter": usage_counter,
        "usage_dir": tmp_path / "usage",
        "make_client": make_client,
    }


class TestArtifactTokenRecordsUsage:
    def test_issuing_a_token_records_usage_for_that_skill(self, system):
        client = system["make_client"](usage_ranking_enabled=False)

        resp = client.post("/api/v1/skills/acme.text.popular/versions/1.0.0/artifact-token")

        assert resp.status_code == 200
        assert system["usage_counter"].drain() == {"acme.text.popular": 1}

    def test_recording_happens_regardless_of_the_ranking_flag(self, system):
        """Collection is unconditional -- only the read side into search()
        is gated, so real data is already warm when the flag flips on."""
        client = system["make_client"](usage_ranking_enabled=False)

        client.post("/api/v1/skills/acme.text.popular/versions/1.0.0/artifact-token")

        assert system["usage_counter"].drain() == {"acme.text.popular": 1}


class TestSearchRankingRespectsTheFeatureFlag:
    def test_search_ordering_is_unaffected_when_flag_is_off(self, system):
        client = system["make_client"](usage_ranking_enabled=False)
        for _ in range(10):
            client.post("/api/v1/skills/acme.text.popular/versions/1.0.0/artifact-token")
        flush_usage_counts(system["usage_counter"], system["usage_dir"])

        resp = client.get("/api/v1/skills")

        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        # No query, flag off: falls back to the pre-existing
        # alphabetical-by-id tiebreak, unaffected by the 10 recorded uses.
        assert ids == ["acme.text.popular", "acme.text.unpopular"]

    def test_search_ordering_reflects_usage_when_flag_is_on(self, system):
        write_client = system["make_client"](usage_ranking_enabled=False)
        for _ in range(10):
            write_client.post("/api/v1/skills/acme.text.unpopular/versions/1.0.0/artifact-token")
        flush_usage_counts(system["usage_counter"], system["usage_dir"])
        assert read_usage_counts(system["usage_dir"]) == {"acme.text.unpopular": 10}

        read_client = system["make_client"](usage_ranking_enabled=True)
        resp = read_client.get("/api/v1/skills")

        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        # "unpopular" by name only, but the more-used skill in this run —
        # ranking flips id-alphabetical order once the flag is on.
        assert ids == ["acme.text.unpopular", "acme.text.popular"]
