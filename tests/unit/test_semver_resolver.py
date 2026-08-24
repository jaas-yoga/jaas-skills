from jaas_registry.index.semver_resolver import resolve_version


def test_resolve_stable_by_default_picks_highest_non_prerelease():
    assert resolve_version(["1.0.0", "1.2.0", "2.0.0-beta.1"], None) == "1.2.0"


def test_resolve_stable_alias_same_as_default():
    assert resolve_version(["1.0.0", "1.2.0", "2.0.0-beta.1"], "stable") == "1.2.0"


def test_resolve_latest_alias_includes_prerelease():
    assert resolve_version(["1.0.0", "1.2.0", "2.0.0-beta.1"], "latest") == "2.0.0-beta.1"


def test_resolve_falls_back_to_prerelease_if_no_stable_exists():
    assert resolve_version(["1.0.0-alpha.1", "1.0.0-beta.1"], None) == "1.0.0-beta.1"


def test_resolve_range_constraint():
    assert resolve_version(["1.0.0", "1.5.0", "2.0.0"], ">=1.0.0,<2.0.0") == "1.5.0"


def test_resolve_range_constraint_no_match_returns_none():
    assert resolve_version(["1.0.0", "1.5.0"], ">=2.0.0") is None


def test_resolve_empty_versions_returns_none():
    assert resolve_version([], None) is None
