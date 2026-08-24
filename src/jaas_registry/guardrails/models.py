"""Hand-kept mirror of the standalone jaas-guardrails service's response
shapes (https://github.com/balakrishna-maduru/jaas-guardrails-catalog).

This module intentionally contains no scanning logic — that lives entirely
in the separate service. `client.py` is the only thing that talks to it;
everything else in this app only ever sees these types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class GuardrailSeverity(StrEnum):
    BLOCK = "BLOCK"
    WARN = "WARN"


class GuardrailLevel(IntEnum):
    BASELINE = 1
    STANDARD = 2
    ADVANCED = 3
    REGULATORY = 4


@dataclass(frozen=True)
class GuardrailDefinition:
    """Mirrors the service's GET /catalog entry shape."""

    id: str
    name: str
    description: str
    category: str
    level: GuardrailLevel
    mandatory: bool
    default_enabled: bool
    severity: GuardrailSeverity
    standard_ref: str


@dataclass(frozen=True)
class GuardrailFinding:
    """Mirrors one entry of the service's POST /scan response."""

    check_id: str
    file: str
    message: str
    severity: GuardrailSeverity


@dataclass(frozen=True)
class GuardrailScanResult:
    blocking: tuple[GuardrailFinding, ...]
    warnings: tuple[GuardrailFinding, ...]
