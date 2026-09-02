"""CrewAI tool adapter for jaas-client.

IMPLEMENTATION_PLAN.md Phase 4.1. Same two-tool shape as jaas-langgraph:
search the registry, and fetch a skill's instructions (its packaged
entrypoint file) for an agent to read and follow -- see that package's
__init__.py docstring for the product reasoning behind these two
capabilities specifically.
"""

from __future__ import annotations

from typing import Protocol

from crewai.tools import BaseTool, tool


class _SkillSummaryLike(Protocol):
    id: str
    name: str
    version: str
    category: str


class _JaasClientLike(Protocol):
    def search(self, query: str | None = None, **kwargs: object) -> list[_SkillSummaryLike]: ...

    def get_entrypoint_content(self, skill_id: str, version: str = "latest") -> str: ...


def _format_results(results: list[_SkillSummaryLike]) -> str:
    if not results:
        return "No skills found."
    return "\n".join(f"{r.id}@{r.version} - {r.name} ({r.category})" for r in results)


def build_jaas_tools(client: _JaasClientLike) -> list[BaseTool]:
    """Returns [search_skills, get_skill] -- real crewai.tools.BaseTool
    instances bound to `client`, ready to pass into a CrewAI Agent's
    `tools` list."""

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
