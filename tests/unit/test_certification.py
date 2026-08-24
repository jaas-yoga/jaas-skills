"""Unit tests for guardrails/certification.py's pure compute_certification()
— no HTTP, no fixtures beyond hand-built GuardrailDefinition/ScanResult
values, one per catalog level so every branch (certified/findings/not-
attempted) is independently exercisable."""

from __future__ import annotations

from jaas_registry.guardrails.certification import CertificationStatus, compute_certification
from jaas_registry.guardrails.models import (
    GuardrailDefinition,
    GuardrailFinding,
    GuardrailLevel,
    GuardrailScanResult,
    GuardrailSeverity,
)


def _check(id_: str, level: GuardrailLevel, *, mandatory: bool = False) -> GuardrailDefinition:
    return GuardrailDefinition(
        id=id_,
        name=id_,
        description="fake",
        category="TEST",
        level=level,
        mandatory=mandatory,
        default_enabled=mandatory,
        severity=GuardrailSeverity.BLOCK if mandatory else GuardrailSeverity.WARN,
        standard_ref="test",
    )


CATALOG = [
    _check("l1-mandatory", GuardrailLevel.BASELINE, mandatory=True),
    _check("l2-check", GuardrailLevel.STANDARD),
    _check("l3-check", GuardrailLevel.ADVANCED),
    _check("l4-check", GuardrailLevel.REGULATORY),
]


def test_returns_none_when_there_was_no_scan():
    assert compute_certification(scan=None, enabled_check_ids=frozenset(), catalog=CATALOG) is None


def test_everything_attempted_and_clean_certifies_every_level():
    scan = GuardrailScanResult(blocking=(), warnings=())
    cert = compute_certification(
        scan=scan,
        enabled_check_ids=frozenset({"l2-check", "l3-check", "l4-check"}),
        catalog=CATALOG,
    )

    assert cert.highest_certified_level == 4
    assert cert.level_statuses == (
        (1, CertificationStatus.CERTIFIED),
        (2, CertificationStatus.CERTIFIED),
        (3, CertificationStatus.CERTIFIED),
        (4, CertificationStatus.CERTIFIED),
    )
    assert cert.warning_check_ids == ()


def test_a_warning_at_level_2_caps_certification_below_it():
    scan = GuardrailScanResult(
        blocking=(),
        warnings=(GuardrailFinding("l2-check", "manifest.yaml", "warn", GuardrailSeverity.WARN),),
    )
    cert = compute_certification(
        scan=scan,
        enabled_check_ids=frozenset({"l2-check", "l3-check", "l4-check"}),
        catalog=CATALOG,
    )

    assert cert.highest_certified_level == 1
    assert cert.level_statuses[0] == (1, CertificationStatus.CERTIFIED)
    assert cert.level_statuses[1] == (2, CertificationStatus.ATTEMPTED_WITH_FINDINGS)
    # levels above a non-certified one are still reported on their own
    # merits, not forced to "not attempted" — 3/4 were attempted and clean.
    assert cert.level_statuses[2] == (3, CertificationStatus.CERTIFIED)
    assert cert.level_statuses[3] == (4, CertificationStatus.CERTIFIED)
    assert cert.warning_check_ids == ("l2-check",)


def test_a_disabled_level_is_not_attempted_not_failed():
    scan = GuardrailScanResult(blocking=(), warnings=())
    cert = compute_certification(
        scan=scan,
        enabled_check_ids=frozenset({"l3-check", "l4-check"}),  # l2-check left off
        catalog=CATALOG,
    )

    assert cert.level_statuses[1] == (2, CertificationStatus.NOT_ATTEMPTED)
    # a certified level *above* a gap doesn't count toward the headline
    # number — an untested lower bar must never look implicitly passed.
    assert cert.highest_certified_level == 1


def test_mandatory_checks_count_as_attempted_even_if_not_in_enabled_ids():
    """policy.py strips mandatory ids from what it persists (they're
    force-run regardless) — enabled_check_ids alone must not be trusted to
    reflect what actually ran."""
    scan = GuardrailScanResult(blocking=(), warnings=())
    cert = compute_certification(scan=scan, enabled_check_ids=frozenset(), catalog=CATALOG)

    assert cert.level_statuses[0] == (1, CertificationStatus.CERTIFIED)
