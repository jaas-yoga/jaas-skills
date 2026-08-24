"""Guardrail catalog endpoint. Design ref: design.md §4.5, ui-design.md §7.

No auth required — a static, non-tenant-scoped list of what checks exist,
same "reachable without auth" posture as search/metadata.
"""

from __future__ import annotations

from fastapi import APIRouter

from jaas_registry.api.deps import GuardrailCatalogDep
from jaas_registry.api.schemas import GuardrailDefinitionResponse

router = APIRouter(prefix="/api/v1/guardrails")


@router.get("", response_model=list[GuardrailDefinitionResponse])
def list_guardrail_catalog(catalog: GuardrailCatalogDep) -> list[GuardrailDefinitionResponse]:
    return [
        GuardrailDefinitionResponse(
            id=d.id,
            name=d.name,
            description=d.description,
            category=d.category,
            level=int(d.level),
            mandatory=d.mandatory,
            defaultEnabled=d.default_enabled,
            defaultSeverity=d.severity.value,
            standardRef=d.standard_ref,
        )
        for d in catalog
    ]
