"""LangGraph/LangChain tool adapter for jaas-client.

IMPLEMENTATION_PLAN.md Phase 4.1. Exposes two real
`langchain_core.tools.BaseTool` instances (accepted directly by LangGraph's
`ToolNode` and prebuilt agents) over a `JaasRegistryClient`: search the
registry, and fetch a skill's instructions (its packaged entrypoint file --
typically a SKILL.md) for an agent to read and follow. Deliberately thin:
no framework-specific business logic beyond formatting `search`'s results
as text a tool-calling model can read.
"""

from __future__ import annotations

from typing import Protocol

from langchain_core.tools import BaseTool, tool


class _SkillSummaryLike(Protocol):
    id: str
    name: str
    version: str
    category: str


class _JaasClientLike(Protocol):
    """Structural type for whatever client build_jaas_tools is handed --
    matches jaas_client.JaasRegistryClient's shape without importing it, so
    a caller can pass any compatible object (a real client, or a test
    fake)."""

    def search(self, query: str | None = None, **kwargs: object) -> list[_SkillSummaryLike]: ...

    def get_entrypoint_content(self, skill_id: str, version: str = "latest") -> str: ...


def _format_results(results: list[_SkillSummaryLike]) -> str:
    if not results:
        return "No skills found."
    return "\n".join(f"{r.id}@{r.version} - {r.name} ({r.category})" for r in results)


def build_jaas_tools(client: _JaasClientLike) -> list[BaseTool]:
    """Returns [search_skills, get_skill] -- real LangChain-core tools bound
    to `client`, ready to pass straight into a LangGraph ToolNode or
    prebuilt agent's tool list."""

    @tool
    def search_skills(query: str) -> str:
        """Search the JaaS skill registry. Returns each match's id@version,
        name, and category, one per line, so a model can pick one to load
        with get_skill."""
        return _format_results(client.search(query=query))

    @tool
    def get_skill(skill_id: str, version: str = "latest") -> str:
        """Fetch a skill's instructions from the JaaS registry, given its id
        (from search_skills) and an optional version (defaults to the
        latest published version). Returns the skill's own instructions
        for you to read and follow."""
        return client.get_entrypoint_content(skill_id, version)

    return [search_skills, get_skill]
