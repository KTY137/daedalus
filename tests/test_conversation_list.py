"""GET /api/conversations?project= -- a LIST over the canonical spine.

The cockpit can resume one thread per project because it remembers one id in
localStorage. It could never show the others, because the only read was
get-by-id. This packet (G1-UI-05) adds one read-only list derived from the
``conversation.turn`` facts already on the spine: no second registry, no
cache, no write.

What has to stay true, each with a test that goes red otherwise:

  1. rows are grouped by conversation, newest activity first, bounded;
  2. the project filter is the row's OWN ``project`` field -- a message that
     merely *contains* the canonical fragment ``"project":"A"`` does not leak
     project B's thread into A's list;
  3. an unknown project is an empty list, not an error;
  4. the route refuses a missing project and an out-of-range limit before it
     touches the store, and clips free text like every other loop read.
"""
from __future__ import annotations

import pytest

from daedalus import conversation as conv


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_SPINE_DB", str(tmp_path / "spine.sqlite3"))
    with conv.ConversationStore() as s:
        yield s


def _turn(store, cid, message, *, project, provider="deterministic", intent="chat"):
    return store.append_turn(
        cid, user_message=message, intent=intent, status=conv.STATUS_ANSWERED,
        assistant_text=f"re: {message}", provider_used=provider, project=project,
        envelope={"project": project, "intent": intent})


def test_rows_group_by_conversation_newest_first_and_bounded(store):
    _turn(store, "conv_a1", "erste Frage in a1", project="A")
    _turn(store, "conv_b1", "b1", project="B")
    _turn(store, "conv_a2", "a2 first", project="A", provider="claude_code_cli")
    _turn(store, "conv_a1", "zweite Frage in a1", project="A", intent="status")

    rows = store.list_conversations("A")
    assert [r["conversation_id"] for r in rows] == ["conv_a1", "conv_a2"]
    a1 = rows[0]
    assert a1["turn_count"] == 2
    assert a1["first_message"] == "erste Frage in a1"
    assert a1["last_message"] == "zweite Frage in a1"
    assert a1["last_intent"] == "status"
    assert a1["last_provider_used"] == "deterministic"
    assert a1["last_status"] == conv.STATUS_ANSWERED
    assert a1["last_ts"]
    assert rows[1]["last_provider_used"] == "claude_code_cli"

    assert [r["conversation_id"] for r in store.list_conversations("A", limit=1)] == ["conv_a1"]
    assert store.list_conversations("A", limit=0) == []


def test_project_filter_is_the_rows_own_field_not_a_substring(store):
    _turn(store, "conv_a1", "hallo", project="A")
    # Project B's turn names A in a NESTED field. The spine's LIKE test over
    # canonical JSON matches that fragment (a quoted message would not: the
    # quotes are escaped), so only the hydrated row's own ``project`` field
    # keeps this thread out of A's list. Reviewed 2026-09-02: the previous
    # fixture never reached the guard.
    store.append_turn(
        "conv_b1", user_message="b", intent="chat", status=conv.STATUS_ANSWERED,
        assistant_text="re", provider_used="deterministic", project="B",
        envelope={"project": "A"})

    assert [r["conversation_id"] for r in store.list_conversations("A")] == ["conv_a1"]
    assert [r["conversation_id"] for r in store.list_conversations("B")] == ["conv_b1"]


def test_unknown_or_blank_project_is_an_empty_list(store):
    _turn(store, "conv_a1", "hallo", project="A")
    assert store.list_conversations("nobody") == []
    assert store.list_conversations("") == []
    assert store.list_conversations("   ") == []


def test_underscore_in_a_project_name_is_literal(store):
    _turn(store, "conv_x", "x", project="agent_env")
    _turn(store, "conv_y", "y", project="agentXenv")
    assert [r["conversation_id"] for r in store.list_conversations("agent_env")] == ["conv_x"]


# --------------------------------------------------------------------------- #
# the route                                                                    #
# --------------------------------------------------------------------------- #

def _get(path: str) -> dict:
    from daedalus.web_api import DaedalusHandler

    handler = object.__new__(DaedalusHandler)
    handler.path = path
    captured: dict = {}

    def send_json(payload, status: int = 200) -> None:
        captured["payload"] = payload
        captured["status"] = status

    handler._send_json = send_json
    handler._send_static = lambda path: captured.setdefault("static", path)
    handler._handle_get()
    return captured


def test_route_refuses_before_reading_the_store(store):
    missing = _get("/api/conversations")
    assert missing["status"] == 400
    assert missing["payload"]["error"] == "project is required"

    bad_limit = _get("/api/conversations?project=A&limit=0")
    assert bad_limit["status"] == 400
    assert "limit" in bad_limit["payload"]["error"]


def test_route_lists_this_projects_threads_and_clips(store):
    from daedalus import web_api

    long = "x" * (web_api.LOOP_TEXT_CHARS + 50)
    _turn(store, "conv_a1", long, project="A")
    _turn(store, "conv_b1", "b", project="B")

    captured = _get("/api/conversations?project=A")
    assert captured["status"] == 200
    payload = captured["payload"]
    assert payload["ok"] is True
    assert payload["project"] == "A"
    rows = payload["conversations"]
    assert [r["conversation_id"] for r in rows] == ["conv_a1"]
    assert len(rows[0]["first_message"]) < len(long)
    assert rows[0]["first_message"] != long

    assert _get("/api/conversations?project=nobody")["payload"]["conversations"] == []
