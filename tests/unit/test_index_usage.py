import asyncio

import pytest

from jaas_registry.index.usage import (
    UsageCounter,
    flush_usage_counts,
    flush_usage_counts_periodically,
    read_usage_counts,
    usage_score,
)


class TestUsageCounter:
    def test_record_and_drain_returns_accumulated_counts(self):
        counter = UsageCounter()
        counter.record("acme.text.summarizer")
        counter.record("acme.text.summarizer")
        counter.record("acme.text.other")

        drained = counter.drain()

        assert drained == {"acme.text.summarizer": 2, "acme.text.other": 1}

    def test_drain_resets_the_counter(self):
        counter = UsageCounter()
        counter.record("acme.text.summarizer")
        counter.drain()

        assert counter.drain() == {}

    def test_drain_on_a_fresh_counter_is_empty(self):
        assert UsageCounter().drain() == {}


class TestReadUsageCounts:
    def test_returns_empty_dict_when_no_file_exists_yet(self, tmp_path):
        assert read_usage_counts(tmp_path / "usage") == {}


class TestFlushUsageCounts:
    def test_flush_persists_the_drained_counts(self, tmp_path):
        counter = UsageCounter()
        counter.record("acme.text.summarizer")
        counter.record("acme.text.summarizer")

        flush_usage_counts(counter, tmp_path / "usage")

        assert read_usage_counts(tmp_path / "usage") == {"acme.text.summarizer": 2}

    def test_flush_is_additive_across_multiple_flushes(self, tmp_path):
        counter = UsageCounter()
        counter.record("acme.text.summarizer")
        flush_usage_counts(counter, tmp_path / "usage")

        counter.record("acme.text.summarizer")
        counter.record("acme.text.other")
        flush_usage_counts(counter, tmp_path / "usage")

        assert read_usage_counts(tmp_path / "usage") == {
            "acme.text.summarizer": 2,
            "acme.text.other": 1,
        }

    def test_flush_with_no_recorded_events_does_not_error_or_create_a_file(self, tmp_path):
        flush_usage_counts(UsageCounter(), tmp_path / "usage")

        assert not (tmp_path / "usage" / "usage_counts.json").exists()

    def test_two_counters_flushing_the_same_directory_sum_additively(self, tmp_path):
        """Models two replicas, each with their own in-process counter,
        flushing into the same shared durable file."""
        replica_a = UsageCounter()
        replica_a.record("acme.text.summarizer")
        replica_b = UsageCounter()
        replica_b.record("acme.text.summarizer")
        replica_b.record("acme.text.summarizer")

        flush_usage_counts(replica_a, tmp_path / "usage")
        flush_usage_counts(replica_b, tmp_path / "usage")

        assert read_usage_counts(tmp_path / "usage") == {"acme.text.summarizer": 3}


class TestUsageScore:
    def test_zero_count_scores_zero(self):
        assert usage_score(0) == 0.0

    def test_score_increases_monotonically_with_count(self):
        assert usage_score(1) < usage_score(10) < usage_score(1000)

    def test_score_is_bounded_at_one(self):
        assert usage_score(10_000_000) <= 1.0

    def test_score_never_negative(self):
        assert usage_score(0) >= 0.0


class TestFlushUsageCountsPeriodically:
    @pytest.mark.asyncio
    async def test_flushes_repeatedly_until_stopped(self, tmp_path):
        counter = UsageCounter()
        counter.record("acme.text.summarizer")
        stop_event = asyncio.Event()
        flush_count = 0

        def on_flush():
            nonlocal flush_count
            flush_count += 1
            if flush_count >= 3:
                stop_event.set()

        await asyncio.wait_for(
            flush_usage_counts_periodically(
                counter,
                tmp_path / "usage",
                interval_seconds=0.01,
                stop_event=stop_event,
                on_flush=on_flush,
            ),
            timeout=5,
        )

        assert flush_count >= 3

    @pytest.mark.asyncio
    async def test_returns_immediately_when_already_stopped(self, tmp_path):
        stop_event = asyncio.Event()
        stop_event.set()

        await asyncio.wait_for(
            flush_usage_counts_periodically(
                UsageCounter(), tmp_path / "usage", interval_seconds=0.01, stop_event=stop_event
            ),
            timeout=5,
        )
