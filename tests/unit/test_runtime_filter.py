from jaas_registry.index.runtime_filter import runtime_matches
from tests.fixtures.index_entries import make_entry


def test_family_only_query_matches():
    assert runtime_matches(make_entry(), "python") is True


def test_family_mismatch_excludes():
    assert runtime_matches(make_entry(), "node") is False


def test_family_and_version_within_range_matches():
    assert runtime_matches(make_entry(), "python@3.11.2") is True


def test_family_and_version_outside_range_excludes():
    assert runtime_matches(make_entry(), "python@4.0.0") is False


def test_version_given_for_undeclared_family_excludes():
    assert runtime_matches(make_entry(), "node@20.0.0") is False


def test_family_declared_without_range_entry_excludes_when_version_given():
    entry = make_entry(runtime_families=("python",), runtime_ranges={})
    assert runtime_matches(entry, "python@3.11.2") is False
