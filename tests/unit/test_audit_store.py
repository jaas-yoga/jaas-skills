import json

from jaas_registry.common.audit import (
    new_custom_guardrail_rule_event,
    new_github_connection_event,
    new_publish_event,
    new_share_grant_event,
    new_yank_event,
)
from jaas_registry.common.audit_store import FileAuditSink


def test_emit_publish_appends_one_json_line_to_the_audit_file(tmp_path, capsys):
    sink = FileAuditSink(tmp_path / "audit")
    sink.emit(new_publish_event(actor="alice", skill_id="s", version="1.0.0", digest="sha256:a"))

    lines = (tmp_path / "audit" / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "publish"
    assert record["skill_id"] == "s"

    # Still prints, same JSON shape as StructuredLogAuditSink — nothing that
    # tails process logs today should lose that output.
    assert "\"event_type\": \"publish\"" in capsys.readouterr().out


def test_emit_yank_and_share_grant_change_are_persisted_too(tmp_path):
    sink = FileAuditSink(tmp_path / "audit")
    sink.emit_yank(
        new_yank_event(actor="a", skill_id="s", version="1.0.0", action="yanked", reason=None)
    )
    sink.emit_share_grant_change(
        new_share_grant_event(
            actor="a", skill_id="s", grant_id="g1", grantee_type="user",
            grantee_id="bob", permission="view", action="granted",
        )
    )

    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "audit" / "audit.jsonl").read_text().splitlines()
    ]
    assert event_types == ["yank", "share_grant_change"]


def test_read_all_returns_every_persisted_event_across_all_event_types(tmp_path):
    sink = FileAuditSink(tmp_path / "audit")
    sink.emit(new_publish_event(actor="a", skill_id="s1", version="1.0.0", digest="sha256:a"))
    sink.emit_custom_guardrail_change(
        new_custom_guardrail_rule_event(actor="a", tenant_id="t1", rule_id="r1", action="created")
    )
    sink.emit_github_connection_change(
        new_github_connection_event(
            actor="a", tenant_id="t1", github_login="alice", action="connected"
        )
    )
    sink.emit_yank(
        new_yank_event(actor="a", skill_id="s1", version="1.0.0", action="yanked", reason=None)
    )
    sink.emit_share_grant_change(
        new_share_grant_event(
            actor="a", skill_id="s1", grant_id="g1", grantee_type="user",
            grantee_id="bob", permission="view", action="granted",
        )
    )

    records = sink.read_all()

    assert len(records) == 5
    assert [r["event_type"] for r in records] == [
        "publish", "custom_guardrail_change", "github_connection_change", "yank",
        "share_grant_change",
    ]


def test_read_all_on_a_fresh_store_with_no_events_yet_is_empty(tmp_path):
    sink = FileAuditSink(tmp_path / "audit")
    assert sink.read_all() == []


def test_two_sink_instances_over_the_same_directory_share_the_persisted_log(tmp_path):
    """Mirrors how routes.py constructs a fresh sink instance per request
    (same convention as tenant_routes.py's existing StructuredLogAuditSink()
    calls) -- persistence must not depend on reusing one Python object."""
    FileAuditSink(tmp_path / "audit").emit(
        new_publish_event(actor="a", skill_id="s1", version="1.0.0", digest="sha256:a")
    )
    FileAuditSink(tmp_path / "audit").emit(
        new_publish_event(actor="a", skill_id="s2", version="1.0.0", digest="sha256:b")
    )

    records = FileAuditSink(tmp_path / "audit").read_all()
    assert len(records) == 2
