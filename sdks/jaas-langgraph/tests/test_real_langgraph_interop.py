"""IMPLEMENTATION_PLAN.md Phase 4.1: test_adapter.py proves build_jaas_tools'
own logic against a hand-rolled fake client. This file proves the *other*
half -- that its output is genuinely usable by real LangGraph/LangChain-core
machinery, and that a real JaasRegistryClient (against a real in-process
jaas_registry app, same convention as jaas-client's own
test_client_against_real_api.py) is a valid _JaasClientLike, not just
structurally similar to one.
"""

from __future__ import annotations

import pytest
import yaml
from _live_server import run_app
from jaas_client import JaasRegistryClient
from jaas_registry.api.app import create_app
from jaas_registry.artifact.publish import publish_skill
from jaas_registry.artifact.signing import generate_dev_keypair
from jaas_registry.artifact.trust import TrustPolicy
from jaas_registry.common.audit import InMemoryAuditSink
from jaas_registry.common.config import Settings
from jaas_registry.index.consumer import IndexEventConsumer
from jaas_registry.index.events import InMemoryEventBus
from jaas_registry.index.store import InMemoryIndex
from jaas_registry.observability.tracing import build_tracer
from jaas_registry.storage.local_filesystem import LocalFilesystemStore
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from jaas_langgraph import build_jaas_tools

MANIFEST = {
    "apiVersion": "v1",
    "id": "acme.text.summarizer",
    "name": "Summarizer",
    "version": "1.2.3",
    "description": "Summarizes text",
    "owner": {"team": "platform", "contact": "platform@acme.com"},
    "entrypoint": "SKILL.md",
    "category": "nlp",
    "tags": ["summarization"],
    "runtime": [{"family": "python", "versionRange": ">=3.10.0,<4.0.0"}],
}
SKILL_MD = "# Summarizer\n\nGiven a document, produce a concise summary.\n"


@pytest.fixture
def app_and_client(tmp_path):
    keypair = generate_dev_keypair()
    store = LocalFilesystemStore(tmp_path / "storage")
    trust_policy = TrustPolicy(trusted_public_keys_pem=[keypair.public_key_pem()])
    event_bus = InMemoryEventBus()

    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "manifest.yaml").write_text(yaml.safe_dump(MANIFEST))
    (pkg_dir / "SKILL.md").write_text(SKILL_MD)

    publish_skill(
        source_dir=pkg_dir,
        store=store,
        signing_key=keypair,
        trust_policy=trust_policy,
        actor="ci-pipeline",
        audit_sink=InMemoryAuditSink(),
        event_bus=event_bus,
    )

    index = InMemoryIndex()
    IndexEventConsumer(index=index, store=store, sleep_fn=lambda _: None).consume_from(event_bus)

    settings = Settings(storage_root=store.root)
    tracer = build_tracer(exporter=InMemorySpanExporter(), batch=True)
    app = create_app(
        index=index, store=store, settings=settings, trust_policy=trust_policy, tracer=tracer
    )
    with run_app(app) as base_url, JaasRegistryClient(base_url) as client:
        yield client


def test_build_jaas_tools_output_is_accepted_by_a_real_toolnode(app_and_client):
    tools = build_jaas_tools(app_and_client)

    node = ToolNode(tools)

    assert isinstance(node, ToolNode)
    assert set(node.tools_by_name) == {"search_skills", "get_skill"}


def test_search_skills_tool_against_the_real_registry(app_and_client):
    tools = {t.name: t for t in build_jaas_tools(app_and_client)}
    assert isinstance(tools["search_skills"], BaseTool)

    result = tools["search_skills"].invoke({"query": "summarizer"})

    assert "acme.text.summarizer" in result
    assert "1.2.3" in result


def test_get_skill_tool_returns_the_real_skill_md_content(app_and_client):
    tools = {t.name: t for t in build_jaas_tools(app_and_client)}

    result = tools["get_skill"].invoke({"skill_id": "acme.text.summarizer", "version": "1.2.3"})

    assert result == SKILL_MD
