"""Scope mapping: token scopes -> policy permission checks.

Design ref: design.md §3.4.2 ("Map claims to policy scopes"), §3.4 design note 2
("Permission matching allows exact and hierarchical scope patterns"),
implementation-plan.md Phase 4 task 2.

Granted scopes may be exact ("fs:read") or a hierarchical wildcard ("fs:*",
matching any "fs:..." requirement). Required permissions (declared per skill in
permissions.yaml) are always exact strings.
"""

from __future__ import annotations


def scope_covers(granted: str, required: str) -> bool:
    if granted == required:
        return True
    if granted.endswith(":*"):
        prefix = granted[: -len("*")]  # "fs:*" -> "fs:"
        return required.startswith(prefix)
    return False


def has_all_required_scopes(
    granted_scopes: tuple[str, ...], required_permissions: tuple[str, ...]
) -> bool:
    return all(
        any(scope_covers(granted, required) for granted in granted_scopes)
        for required in required_permissions
    )
