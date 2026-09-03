"""Tests for ``daedalus/hooks/crosstalk.py`` -- the GitHub Discussions channel
between parallel Claude sessions (2026-09-03).

No test touches the network: the transport is always a fake that records every
call. Each redaction test FIRST asserts that its input really contained the
forbidden string, because a fixture that is inert makes the guard look green
while guarding nothing -- a standing rule of this repository.

Every test builds its own throwaway git repository, so no assertion depends on
this checkout's state.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from daedalus.hooks import __main__ as entry
from daedalus.hooks import crosstalk


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "daedalus").mkdir()
    (r / "daedalus" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "init")
    return r


class FakeTransport:
    """Stands in for ``gh api graphql``. Records every call and returns canned
    GraphQL payloads."""

    def __init__(self, visibility="PRIVATE", discussions=None, fail=None, discussions_enabled=True):
        self.calls: list[dict] = []
        self.visibility = visibility
        self.discussions = list(discussions or [])
        self.fail = fail
        self.discussions_enabled = discussions_enabled

    def comments(self) -> list[str]:
        return [
            c["variables"]["body"] for c in self.calls if "addDiscussionComment" in c["query"]
        ]

    def count(self, needle: str) -> int:
        return sum(needle in c["query"] for c in self.calls)

    def __call__(self, query: str, variables: dict) -> dict:
        self.calls.append({"query": query, "variables": variables})
        if self.fail is not None:
            raise self.fail
        if "discussionCategories" in query:
            return {
                "repository": {
                    "id": "R_1",
                    "visibility": self.visibility,
                    "hasDiscussionsEnabled": self.discussions_enabled,
                    "discussionCategories": {"nodes": [{"id": "C_1", "name": "General"}]},
                    "discussions": {"nodes": list(self.discussions)},
                }
            }
        if "createDiscussion" in query:
            return {"createDiscussion": {"discussion": {"id": "D_new", "number": 9}}}
        if "addDiscussionComment" in query:
            return {"addDiscussionComment": {"comment": {"id": "DC_1"}}}
        if "comments(last" in query:
            return {
                "node": {
                    "title": "crew-channel",
                    "comments": {
                        "nodes": [
                            {
                                "author": {"login": "KTY137"},
                                "createdAt": "2026-09-03T09:00:00Z",
                                "body": "ANMELDUNG `b7c1` packet/x @aaa",
                            }
                        ]
                    },
                }
            }
        raise AssertionError("unexpected query: " + query[:60])


def _channel(root: Path, transport, **env):
    base = {"DAEDALUS_CROSSTALK": "on", "GH_REPO": "KTY137/daedalus"}
    base.update(env)
    return crosstalk.Channel(root, transport=transport, env=base)


def _live(monkeypatch, transport) -> None:
    """Arm the channel for a dispatcher-level test."""
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", transport)


RECEIPT = entry.start_effect()


def _run(event: str, data: dict):
    out = io.StringIO()
    result = entry.dispatch(event, data, RECEIPT, stdout=out)
    return result, out.getvalue()


# --------------------------------------------------------------------------
# redaction and rendering
# --------------------------------------------------------------------------


def test_render_drops_secret_paths_and_counts_them():
    note = crosstalk.Note(
        kind="ANMELDUNG",
        session="a3f2",
        branch="packet/g1-map-01",
        head="b9321abd",
        lines=("dirty: daedalus/mapping/reach.py, .agentenv/tool-allowances.json, .env",),
        ts="2026-09-03T09:05:11+02:00",
    )
    assert ".agentenv" in note.lines[0]  # the fixture is not inert
    body = crosstalk.render(note)
    assert ".agentenv" not in body
    assert ".env" not in body
    assert "daedalus/mapping/reach.py" in body
    assert "2 zurueckgehalten" in body


def test_render_strips_absolute_paths():
    note = crosstalk.Note(
        kind="SAGT",
        session="a3f2",
        branch="main",
        head="deadbeef",
        lines=(r"schaue in C:\Users\Administrator\Desktop\projects\daedalus\x.py",),
        ts="2026-09-03T09:05:11+02:00",
    )
    assert "Administrator" in note.lines[0]  # the fixture is not inert
    body = crosstalk.render(note)
    assert "Administrator" not in body
    assert "<pfad entfernt>" in body


def test_render_keeps_the_header_fields():
    note = crosstalk.Note(
        kind="ERGEBNIS",
        session="a3f2",
        branch="packet/x",
        head="abc1234",
        lines=("commits: 2",),
        ts="2026-09-03T09:46:02+02:00",
    )
    body = crosstalk.render(note)
    assert body.startswith("ERGEBNIS `a3f2` packet/x @abc1234")
    assert "commits: 2" in body


def test_redact_paths_counts_withheld():
    kept, withheld = crosstalk.redact_paths(
        ["daedalus/a.py", ".env", "keys/id_rsa.pem", "docs/b.md"]
    )
    assert kept == ["daedalus/a.py", "docs/b.md"]
    assert withheld == 2


# --------------------------------------------------------------------------
# gating and transport
# --------------------------------------------------------------------------


def test_disabled_by_default_makes_no_call(tmp_path: Path):
    fake = FakeTransport()
    channel = crosstalk.Channel(tmp_path, transport=fake, env={})
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert fake.calls == []
    assert "aus" in channel.reason


def test_public_repo_is_refused_without_optin(tmp_path: Path):
    fake = FakeTransport(visibility="PUBLIC")
    channel = _channel(tmp_path, fake)
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert fake.count("addDiscussionComment") == 0
    assert "oeffentlich" in channel.reason


def test_public_repo_posts_with_optin(tmp_path: Path):
    fake = FakeTransport(visibility="PUBLIC")
    channel = _channel(tmp_path, fake, DAEDALUS_CROSSTALK_PUBLIC="1")
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert fake.count("addDiscussionComment") == 1


def test_disabled_discussions_are_named_not_swallowed(tmp_path: Path):
    fake = FakeTransport(discussions_enabled=False)
    channel = _channel(tmp_path, fake)
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert fake.count("addDiscussionComment") == 0
    assert "nicht aktiviert" in channel.reason


def test_missing_thread_is_created_then_commented(tmp_path: Path):
    fake = FakeTransport(discussions=[])
    channel = _channel(tmp_path, fake)
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "packet/x", "abc"), "packet/x")
    assert fake.count("createDiscussion") == 1
    assert fake.count("addDiscussionComment") == 1


def test_existing_thread_is_reused(tmp_path: Path):
    fake = FakeTransport(discussions=[{"id": "D_7", "title": "packet/x", "number": 7}])
    channel = _channel(tmp_path, fake)
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "packet/x", "abc"), "packet/x")
    assert fake.count("createDiscussion") == 0
    comment = [c for c in fake.calls if "addDiscussionComment" in c["query"]][0]
    assert comment["variables"]["id"] == "D_7"


def test_transport_failure_is_fail_open(tmp_path: Path):
    fake = FakeTransport(fail=crosstalk.TransportError("gh timeout"))
    channel = _channel(tmp_path, fake)
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert "nicht erreichbar" in channel.reason
    assert channel.read("crew-channel") == []


def test_an_unexpected_transport_bug_is_also_fail_open(tmp_path: Path):
    """Not every failure arrives as a TransportError. A bug in the transport
    itself must still cost a sentence, never the turn."""
    fake = FakeTransport(fail=ValueError("kaputt"))
    channel = _channel(tmp_path, fake)
    channel.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert "ValueError" in channel.reason


def test_read_returns_comment_lines(tmp_path: Path):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    channel = _channel(tmp_path, fake)
    lines = channel.read("crew-channel", count=3)
    assert any("b7c1" in line for line in lines)


# --------------------------------------------------------------------------
# SessionStart
# --------------------------------------------------------------------------


def test_session_start_does_not_egress_the_prompt(repo: Path, monkeypatch):
    fake = FakeTransport()
    _live(monkeypatch, fake)
    data = {
        "session_id": "sess-1",
        "cwd": str(repo),
        "hook_event_name": "SessionStart",
        "source": "startup",
        "prompt": "GEHEIMER-PROMPT-TEXT",
    }
    assert "GEHEIMER-PROMPT-TEXT" in json.dumps(data)  # the fixture is not inert
    _run("session", data)
    assert fake.count("addDiscussionComment") > 0  # it really did post
    assert "GEHEIMER-PROMPT-TEXT" not in json.dumps(fake.calls)


def test_session_start_announces_once_across_compaction(repo: Path, monkeypatch):
    fake = FakeTransport()
    _live(monkeypatch, fake)
    base = {"session_id": "sess-2", "cwd": str(repo), "hook_event_name": "SessionStart"}
    _run("session", dict(base, source="startup"))
    after_start = fake.count("addDiscussionComment")
    _run("session", dict(base, source="compact"))
    after_compact = fake.count("addDiscussionComment")
    assert after_start > 0
    assert after_compact == after_start  # compaction re-reads, it does not re-announce


def test_session_start_injects_the_thread(repo: Path, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    _live(monkeypatch, fake)
    _, text = _run(
        "session",
        {
            "session_id": "sess-3",
            "cwd": str(repo),
            "hook_event_name": "SessionStart",
            "source": "startup",
        },
    )
    assert "CROSSTALK" in text
    assert "b7c1" in text


def test_session_start_survives_a_dead_transport(repo: Path, monkeypatch):
    fake = FakeTransport(fail=crosstalk.TransportError("gh nicht installiert"))
    _live(monkeypatch, fake)
    _, text = _run(
        "session",
        {
            "session_id": "sess-4",
            "cwd": str(repo),
            "hook_event_name": "SessionStart",
            "source": "startup",
        },
    )
    assert "TREE:" in text  # the rest of the hook still answered
    assert "nicht erreichbar" in text  # and it says why


def test_session_start_is_silent_when_switched_off(repo: Path, monkeypatch):
    fake = FakeTransport()
    monkeypatch.delenv("DAEDALUS_CROSSTALK", raising=False)
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    _, text = _run(
        "session",
        {
            "session_id": "sess-8",
            "cwd": str(repo),
            "hook_event_name": "SessionStart",
            "source": "startup",
        },
    )
    assert fake.calls == []
    assert "TREE:" in text
    # A switched-off channel is SILENT, not chatty about being off: that line
    # would appear on every session start and crowd out the ones that matter.
    assert "crosstalk" not in text.lower()


# --------------------------------------------------------------------------
# SessionEnd
# --------------------------------------------------------------------------


def test_session_end_reports_commits(repo: Path, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    _live(monkeypatch, fake)
    base = {"session_id": "sess-5", "cwd": str(repo)}
    _run("session", dict(base, hook_event_name="SessionStart", source="startup"))
    (repo / "daedalus" / "b.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "daedalus/b.py")
    _git(repo, "commit", "-q", "-m", "feat: add b")
    _run("session_end", dict(base, hook_event_name="SessionEnd", reason="clear"))
    bodies = fake.comments()
    assert any(b.startswith("ERGEBNIS") for b in bodies)
    assert any("feat: add b" in b for b in bodies)


def test_session_end_without_a_start_is_silent(repo: Path, monkeypatch):
    fake = FakeTransport()
    _live(monkeypatch, fake)
    result, _ = _run(
        "session_end",
        {
            "session_id": "sess-6",
            "cwd": str(repo),
            "hook_event_name": "SessionEnd",
            "reason": "clear",
        },
    )
    assert fake.count("addDiscussionComment") == 0
    assert result.note == "crosstalk:no-announce"


# --------------------------------------------------------------------------
# UserPromptSubmit
# --------------------------------------------------------------------------


def test_turn_poll_is_cached(repo: Path, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    _live(monkeypatch, fake)
    base = {"session_id": "sess-7", "cwd": str(repo)}
    _run("session", dict(base, hook_event_name="SessionStart", source="startup"))
    fake.calls.clear()
    _run("turn", dict(base, hook_event_name="UserPromptSubmit", prompt="a"))
    after_first = fake.count("comments(last")
    _run("turn", dict(base, hook_event_name="UserPromptSubmit", prompt="b"))
    after_second = fake.count("comments(last")
    assert after_first == 1
    assert after_second == 1  # inside the TTL: served from cache


# --------------------------------------------------------------------------
# the say CLI and the registry
# --------------------------------------------------------------------------


def test_say_posts_a_model_written_line(repo: Path, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    _live(monkeypatch, fake)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert crosstalk.main(["crosstalk", "say", "nehme reach.py, fasst sie nicht an"]) == 0
    assert any("fasst sie nicht an" in b for b in fake.comments())


def test_say_never_raises_without_arguments(repo: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert crosstalk.main(["crosstalk", "say"]) == 0
    assert crosstalk.main(["crosstalk"]) == 0


def test_crosstalk_entrypoint_is_registered():
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    row = REGISTRY_BY_ID["daedalus.hooks.crosstalk"]
    effects = [e.value for e in row.effects]
    assert "network_egress" in effects
    assert "process_spawn" in effects
    assert "secrets" not in effects  # gh holds the credential, not this code


def test_hooks_entrypoint_notes_admit_the_github_egress():
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    notes = REGISTRY_BY_ID["daedalus.hooks"].notes
    assert "loopback" in notes  # the old justification is still there ...
    assert "github.com" in notes  # ... and no longer the whole truth on its own
