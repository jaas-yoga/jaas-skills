"""IMPLEMENTATION_PLAN.md Phase 4.1. Same pattern as jaas-langgraph/jaas-
crewai's own test_adapter.py: unit-level against a hand-rolled fake client.
See test_real_autogen_interop.py for real autogen_core.tools.FunctionTool
interop (run_json is async, hence pytest-asyncio here).
"""

from __future__ import annotations

from dataclasses import dataclass

from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool

from jaas_autogen import build_jaas_tools


@dataclass(frozen=True)
class _FakeSkillSummary:
    id: str
    name: str
    version: str
    category: str


class _FakeClient:
    def __init__(self):
        self.search_calls = []
        self.entrypoint_calls = []
        self._search_results = [
            _FakeSkillSummary(
                id="acme.text.summarizer", name="Summarizer", version="1.2.3", category="text"
            )
        ]
        self._entrypoint_content = "# Summarizer\n\nSummarize the given text.\n"

    def search(self, query=None, **kwargs):
        self.search_calls.append(query)
        if query and "summarizer" in query:
            return self._search_results
        return []

    def get_entrypoint_content(self, skill_id, version="latest"):
        self.entrypoint_calls.append((skill_id, version))
        return self._entrypoint_content


def _tools_by_name(client) -> dict[str, FunctionTool]:
    return {t.name: t for t in build_jaas_tools(client)}


def test_returns_two_real_function_tools():
    tools = build_jaas_tools(_FakeClient())
    assert len(tools) == 2
    assert all(isinstance(t, FunctionTool) for t in tools)
    assert {t.name for t in tools} == {"search_skills", "get_skill"}


class TestSearchSkillsTool:
    async def test_run_json_forwards_the_query_and_summarizes_results(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        result = await tools["search_skills"].run_json(
            {"query": "summarizer"}, CancellationToken()
        )

        assert client.search_calls == ["summarizer"]
        assert "acme.text.summarizer" in result
        assert "1.2.3" in result

    async def test_no_results_returns_a_readable_message_not_an_empty_string(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        result = await tools["search_skills"].run_json(
            {"query": "nothing-matches-this"}, CancellationToken()
        )

        assert result
        assert "no" in result.lower()


class TestGetSkillTool:
    async def test_run_json_returns_the_entrypoint_content(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        result = await tools["get_skill"].run_json(
            {"skill_id": "acme.text.summarizer"}, CancellationToken()
        )

        assert result == client._entrypoint_content
        assert client.entrypoint_calls == [("acme.text.summarizer", "latest")]

    async def test_run_json_forwards_an_explicit_version(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        await tools["get_skill"].run_json(
            {"skill_id": "acme.text.summarizer", "version": "1.2.3"}, CancellationToken()
        )

        assert client.entrypoint_calls == [("acme.text.summarizer", "1.2.3")]
