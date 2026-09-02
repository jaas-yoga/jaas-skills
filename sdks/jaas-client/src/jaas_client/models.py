"""Response types returned by JaasRegistryClient. Deliberately independent,
lightweight dataclasses -- not imports of jaas_registry.api.schemas -- so
this client has no runtime dependency on the backend package. Field names
match the registry's real JSON response shapes (see
jaas_registry.api.schemas.SearchResultItem / SkillMetadataResponse)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSummary:
    id: str
    name: str
    version: str
    category: str
    tags: tuple[str, ...]
    runtime: tuple[str, ...]
    score: float
    visibility: str
    status: str

    @classmethod
    def _from_json(cls, data: dict) -> SkillSummary:
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            category=data["category"],
            tags=tuple(data["tags"]),
            runtime=tuple(data["runtime"]),
            score=data["score"],
            visibility=data["visibility"],
            status=data["status"],
        )


@dataclass(frozen=True)
class SkillMetadata:
    id: str
    name: str
    version: str
    description: str
    category: str
    tags: tuple[str, ...]
    owner_team: str
    visibility: str
    status: str

    @classmethod
    def _from_json(cls, data: dict) -> SkillMetadata:
        return cls(
            id=data["id"],
            name=data["name"],
            version=data["version"],
            description=data["description"],
            category=data["category"],
            tags=tuple(data["tags"]),
            owner_team=data["owner"]["team"],
            visibility=data["visibility"],
            status=data["status"],
        )
