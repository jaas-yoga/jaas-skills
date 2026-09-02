from jaas_registry.common.audit import (
    InMemoryAuditSink,
    new_share_grant_event,
    new_yank_event,
)


def test_new_yank_event_has_actor_skill_version_action_reason_timestamp():
    event = new_yank_event(
        actor="alice", skill_id="acme.text.summarizer", version="1.2.3",
        action="yanked", reason="security issue",
    )
    assert event.actor == "alice"
    assert event.skill_id == "acme.text.summarizer"
    assert event.version == "1.2.3"
    assert event.action == "yanked"
    assert event.reason == "security issue"
    assert event.timestamp


def test_new_share_grant_event_has_grant_details():
    event = new_share_grant_event(
        actor="alice", skill_id="acme.text.summarizer", grant_id="grant_abc",
        grantee_type="user", grantee_id="bob@acme.com", permission="view",
        action="granted",
    )
    assert event.grant_id == "grant_abc"
    assert event.grantee_type == "user"
    assert event.grantee_id == "bob@acme.com"
    assert event.permission == "view"
    assert event.action == "granted"


def test_in_memory_sink_records_yank_and_share_grant_events():
    sink = InMemoryAuditSink()
    sink.emit_yank(
        new_yank_event(
            actor="alice", skill_id="s", version="1.0.0", action="yanked", reason=None
        )
    )
    sink.emit_share_grant_change(
        new_share_grant_event(
            actor="alice", skill_id="s", grant_id="g1", grantee_type="user",
            grantee_id="bob", permission="view", action="granted",
        )
    )
    assert len(sink.yank_events) == 1
    assert len(sink.share_grant_events) == 1
