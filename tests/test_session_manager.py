from __future__ import annotations

from duedatehq.core.session_manager import InMemoryInteractionSessionManager


def test_in_memory_session_manager_starts_and_returns_session():
    manager = InMemoryInteractionSessionManager()

    session = manager.start("tenant-1", today="2025-05-10", session_id="session-1")

    assert session["session_id"] == "session-1"
    assert session["tenant_id"] == "tenant-1"
    assert session["today"] == "2025-05-10"
    assert session["selectable_items"] == []
    assert session["current_workspace"] is None
    assert session["previous_workspace"] is None
    assert session["breadcrumb"] == []
    assert session["operation_log"] == []
    assert session["prefetch_pool"] == {}
    assert manager.get("session-1") is session


def test_in_memory_session_manager_saves_existing_session():
    manager = InMemoryInteractionSessionManager()
    session = manager.start("tenant-1", session_id="session-1")
    session["state_summary"] = "showing today"

    manager.save(session)

    assert manager.get("session-1")["state_summary"] == "showing today"
