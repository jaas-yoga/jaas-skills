"""AutoGen tool adapter for jaas-client.

IMPLEMENTATION_PLAN.md Phase 4.1. Targets the current `autogen-core`/
`autogen-agentchat` packages (the post-2024 rearchitecture), not the
legacy `pyautogen`/AG2 fork -- see this package's README. Same two-tool
shape as jaas-langgraph/jaas-crewai: search the registry, and fetch a
skill's instructions (its packaged entrypoint file) for an agent to read
and follow -- see jaas_langgraph's __init__.py docstring for the product
reasoning behind these two capabilities specifically.

`autogen_core.tools.FunctionTool` accepts a plain sync function directly
(confirmed by introspection during this investigation -- it wraps calling
it under `run_json`'s async interface itself), so the tool functions below
stay plain sync, matching jaas_client's own sync API.
"""

from __future__ import annotations

from typing import Protocol

from autogen_core.tools import FunctionTool


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


def build_jaas_tools(client: _JaasClientLike) -> list[FunctionTool]:
    """Returns [search_skills, get_skill] -- real
    autogen_core.tools.FunctionTool instances bound to `client`, ready to
    pass into an AutoGen agent's `tools` list."""

    def search_skills(query: str) -> str:
        """Search the JaaS skill registry. Returns each match's id@version,
        name, and category, one per line, so a model can pick one to load
        with get_skill."""
        return _format_results(client.search(query=query))

    def get_skill(skill_id: str, version: str = "latest") -> str:
        """Fetch a skill's instructions from the JaaS registry, given its id
        (from search_skills) and an optional version (defaults to the
        latest published version). Returns the skill's own instructions
        for you to read and follow."""
        return client.get_entrypoint_content(skill_id, version)

    return [
        FunctionTool(
            search_skills,
            description=search_skills.__doc__ or "",
            name="search_skills",
        ),
        FunctionTool(
            get_skill,
            description=get_skill.__doc__ or "",
            name="get_skill",
        ),
    ]
