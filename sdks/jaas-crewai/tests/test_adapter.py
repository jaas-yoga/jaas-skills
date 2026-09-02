"""IMPLEMENTATION_PLAN.md Phase 4.1. Same pattern as jaas-langgraph's own
test_adapter.py: unit-level against a hand-rolled fake client. See
test_real_crewai_interop.py for real crewai.tools.BaseTool interop.
"""

from __future__ import annotations

from dataclasses import dataclass

from crewai.tools import BaseTool

from jaas_crewai import build_jaas_tools


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


def _tools_by_name(client) -> dict[str, BaseTool]:
    return {t.name: t for t in build_jaas_tools(client)}


def test_returns_two_real_crewai_tools():
    tools = build_jaas_tools(_FakeClient())
    assert len(tools) == 2
    assert all(isinstance(t, BaseTool) for t in tools)
    assert {t.name for t in tools} == {"search_skills", "get_skill"}


class TestSearchSkillsTool:
    def test_run_forwards_the_query_and_summarizes_results(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        result = tools["search_skills"].run(query="summarizer")

        assert client.search_calls == ["summarizer"]
        assert "acme.text.summarizer" in result
        assert "1.2.3" in result

    def test_no_results_returns_a_readable_message_not_an_empty_string(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        result = tools["search_skills"].run(query="nothing-matches-this")

        assert result
        assert "no" in result.lower()


class TestGetSkillTool:
    def test_run_returns_the_entrypoint_content(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        result = tools["get_skill"].run(skill_id="acme.text.summarizer")

        assert result == client._entrypoint_content
        assert client.entrypoint_calls == [("acme.text.summarizer", "latest")]

    def test_run_forwards_an_explicit_version(self):
        client = _FakeClient()
        tools = _tools_by_name(client)

        tools["get_skill"].run(skill_id="acme.text.summarizer", version="1.2.3")

        assert client.entrypoint_calls == [("acme.text.summarizer", "1.2.3")]
