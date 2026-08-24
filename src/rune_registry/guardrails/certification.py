"""Guardrail certification: a per-level attestation of what a publish
actually passed, derived once at publish time from a `GuardrailScanResult`
and the catalog — never fetched from or computed by the standalone
rune-guardrails service itself (it deliberately never persists scan
history; see that repo's README). Everything here is pure/offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from rune_registry.guardrails.models import GuardrailDefinition, GuardrailScanResult

ALL_LEVELS: tuple[int, ...] = (1, 2, 3, 4)


class CertificationStatus(StrEnum):
    CERTIFIED = "certified"
    ATTEMPTED_WITH_FINDINGS = "attempted_with_findings"
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True)
class GuardrailCertification:
    # Highest N such that levels 1..N are ALL certified — contiguous from
    # the bottom, so a certified level sitting above a not-attempted one
    # never counts (that would misrepresent an untested lower bar as
    # implicitly passed). None only when there was no scan at all.
    highest_certified_level: int | None
    # Always all 4 levels, in order — never sparse, so a caller can render
    # a complete 1-4 breakdown without guessing about missing entries.
    level_statuses: tuple[tuple[int, CertificationStatus], ...]
    # The specific check ids that produced a WARN finding, across every
    # level — the persisted counterpart of the audit-only
    # PublishAuditEvent.guardrail_warning_ids, so a caller can explain
    # *why* a level shows attempted_with_findings.
    warning_check_ids: tuple[str, ...]


def compute_certification(
    *,
    scan: GuardrailScanResult | None,
    enabled_check_ids: frozenset[str],
    catalog: list[GuardrailDefinition],
) -> GuardrailCertification | None:
    """`None` when `scan` is `None` — no guardrails service was reached for
    this publish, same "`None` is itself meaningful" convention as
    IndexEntry.source_repo. A BLOCK finding can never reach this function
    with data to certify around, since publish_skill() already raises
    GUARDRAIL_VIOLATION and aborts before persisting anything — so any
    `scan` handed in here already has zero blocking findings in practice,
    but this only reads `scan.blocking`/`scan.warnings` uniformly rather
    than assuming that invariant, so it stays correct if ever called
    earlier in a future caller."""
    if scan is None:
        return None

    mandatory_ids = {d.id for d in catalog if d.mandatory}
    attempted_ids = enabled_check_ids | mandatory_ids
    finding_ids = {f.check_id for f in (*scan.blocking, *scan.warnings)}
    warning_check_ids = tuple(sorted({f.check_id for f in scan.warnings}))

    level_statuses: list[tuple[int, CertificationStatus]] = []
    for level in ALL_LEVELS:
        level_ids = {d.id for d in catalog if d.level == level}
        if not level_ids <= attempted_ids:
            level_statuses.append((level, CertificationStatus.NOT_ATTEMPTED))
        elif level_ids & finding_ids:
            level_statuses.append((level, CertificationStatus.ATTEMPTED_WITH_FINDINGS))
        else:
            level_statuses.append((level, CertificationStatus.CERTIFIED))

    highest_certified_level = 0
    for level, status in level_statuses:
        if status != CertificationStatus.CERTIFIED:
            break
        highest_certified_level = level

    return GuardrailCertification(
        highest_certified_level=highest_certified_level,
        level_statuses=tuple(level_statuses),
        warning_check_ids=warning_check_ids,
    )


def flatten_certification(
    certification: GuardrailCertification | None,
) -> tuple[int | None, list[tuple[int, str]], list[str]]:
    """The (level, statuses, warningIds) triple every response schema that
    carries certification data needs (DraftPublishResponse, ReleaseResponse,
    serialize_published_record) — `None` flattens to the same empty/None
    defaults uniformly, so callers don't each re-derive this ternary."""
    if certification is None:
        return None, [], []
    return (
        certification.highest_certified_level,
        [(level, status.value) for level, status in certification.level_statuses],
        list(certification.warning_check_ids),
    )
