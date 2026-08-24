"""Test double for guardrails.client.GuardrailsClient.

This app's tests never execute the real jaas-guardrails service's code —
that service has its own, separate test suite in its own repo. This fake
only verifies *wiring*: does a blocking finding stop a publish, does a
warning get recorded on the audit event, does the tenant policy's enabled
ids reach the client correctly. Each test supplies exactly the
GuardrailScanResult it wants back.
"""

from __future__ import annotations

from jaas_registry.guardrails.models import (
    GuardrailDefinition,
    GuardrailLevel,
    GuardrailScanResult,
    GuardrailSeverity,
)

FAKE_CATALOG = [
    GuardrailDefinition(
        id="secret-scan",
        name="Secret Scan",
        description="fake",
        category="SECRET",
        level=GuardrailLevel.BASELINE,
        mandatory=True,
        default_enabled=True,
        severity=GuardrailSeverity.BLOCK,
        standard_ref="test",
    ),
    GuardrailDefinition(
        id="package-size-limit",
        name="Package Size Limit",
        description="fake",
        category="SIZE",
        level=GuardrailLevel.BASELINE,
        mandatory=True,
        default_enabled=True,
        severity=GuardrailSeverity.BLOCK,
        standard_ref="test",
    ),
    GuardrailDefinition(
        id="unpinned-dependency-range",
        name="Unpinned Dependency Range",
        description="fake",
        category="SUPPLY_CHAIN",
        level=GuardrailLevel.STANDARD,
        mandatory=False,
        default_enabled=True,
        severity=GuardrailSeverity.WARN,
        standard_ref="test",
    ),
    GuardrailDefinition(
        id="pii-pattern-scan",
        name="PII Pattern Scan",
        description="fake",
        category="PRIVACY",
        level=GuardrailLevel.ADVANCED,
        mandatory=False,
        default_enabled=False,
        severity=GuardrailSeverity.WARN,
        standard_ref="test",
    ),
]

CLEAN_SCAN = GuardrailScanResult(blocking=(), warnings=())


class FakeGuardrailsClient:
    def __init__(
        self,
        *,
        catalog: list[GuardrailDefinition] | None = None,
        scan_result: GuardrailScanResult | None = None,
        validate_error: str | None = None,
    ):
        self._catalog = catalog if catalog is not None else FAKE_CATALOG
        self._scan_result = scan_result if scan_result is not None else CLEAN_SCAN
        self._validate_error = validate_error
        self.last_scan_kwargs: dict | None = None
        self.last_validate_kwargs: dict | None = None

    def fetch_catalog(self) -> list[GuardrailDefinition]:
        return list(self._catalog)

    def scan(self, **kwargs) -> GuardrailScanResult:
        self.last_scan_kwargs = kwargs
        return self._scan_result

    def validate_rule(self, **kwargs) -> str | None:
        self.last_validate_kwargs = kwargs
        return self._validate_error
