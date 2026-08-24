from rune_registry.authz.scopes import has_all_required_scopes, scope_covers


def test_exact_scope_match():
    assert scope_covers("fs:read", "fs:read") is True


def test_exact_scope_mismatch():
    assert scope_covers("fs:read", "fs:write") is False


def test_wildcard_covers_child_scope():
    assert scope_covers("fs:*", "fs:read") is True
    assert scope_covers("fs:*", "fs:write") is True


def test_wildcard_does_not_cover_different_top_level():
    assert scope_covers("fs:*", "network:egress") is False


def test_no_required_permissions_trivially_satisfied():
    assert has_all_required_scopes((), ()) is True
    assert has_all_required_scopes((), ("fs:read",)) is False


def test_all_required_present_exactly():
    granted = ("fs:read", "network:egress")
    required = ("fs:read", "network:egress")
    assert has_all_required_scopes(granted, required) is True


def test_missing_one_required_scope_fails():
    assert has_all_required_scopes(("fs:read",), ("fs:read", "network:egress")) is False


def test_wildcard_grant_satisfies_multiple_specific_requirements():
    assert has_all_required_scopes(("fs:*",), ("fs:read", "fs:write")) is True


def test_extra_unrelated_granted_scopes_do_not_break_match():
    granted = ("fs:read", "unrelated:scope")
    assert has_all_required_scopes(granted, ("fs:read",)) is True
