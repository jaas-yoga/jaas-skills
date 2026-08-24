from rune_registry.index.models import IndexEntry


def make_entry(**overrides) -> IndexEntry:
    defaults = dict(
        id="acme.text.summarizer",
        name="Summarizer",
        description="Summarizes long documents into short text",
        category="nlp",
        owner_team="platform",
        version="1.0.0",
        digest="sha256:" + "a" * 64,
        signature="dGVzdC1zaWduYXR1cmU=",
        publish_timestamp="2026-01-01T00:00:00+00:00",
        tags=("summarization", "nlp"),
        runtime_families=("python",),
        runtime_ranges={"python": ">=3.10.0,<4.0.0"},
        permissions=(),
        dependencies=(),
    )
    defaults.update(overrides)
    return IndexEntry(**defaults)
