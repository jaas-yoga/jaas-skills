"""Share grant data model. ui-design.md §5.1 item 4, §5.4.

A share grant is additive ACL metadata layered on top of a PRIVATE skill —
it never changes a skill's own visibility value, and is looked up
per-request (never baked into the index), so revoking one takes effect
immediately without any index rebuild (ui-implementation-plan.md Phase 2
exit criteria 3-4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GranteeType(StrEnum):
    USER = "user"
    TENANT = "tenant"


class SharePermission(StrEnum):
    READ = "read"
    READ_WRITE = "read_write"


@dataclass(frozen=True)
class ShareGrant:
    id: str
    skill_id: str
    grantee_type: GranteeType
    grantee_id: str
    permission: SharePermission
    granted_by: str
    granted_at: str
