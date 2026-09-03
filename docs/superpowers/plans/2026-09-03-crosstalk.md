# Crosstalk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallel Claude sessions announce themselves, report their result, and read each other's notes in GitHub Discussions, so the repository owner can follow and answer from the browser.

**Architecture:** One new module `daedalus/hooks/crosstalk.py` holds transport, redaction and formatting. The existing dispatcher `python -m daedalus.hooks <event>` gains a `session_end` handler and calls crosstalk from `session_start`, `session_end` and `user_prompt`. A small CLI `python -m daedalus.hooks.crosstalk say "…"` lets the model itself write a line. Transport is `gh api graphql` as a subprocess, so no token is ever handled by this code.

**Tech Stack:** Python 3 stdlib only (`subprocess`, `json`, `re`, `os`, `time`). `gh` 2.98.0. pytest.

**Spec:** [docs/superpowers/specs/2026-09-03-crosstalk-design.md](../specs/2026-09-03-crosstalk-design.md)

## Global Constraints

- **Fail-open, always.** No handler may raise, no exit code may be non-zero, no tool call may be refused. Every failure becomes a visible note plus a ledger row.
- **Default off.** No network call happens unless `DAEDALUS_CROSSTALK` equals `on` (case-insensitive, stripped).
- **Public-repo lock.** If repository visibility is not `PRIVATE`, refuse to post unless `DAEDALUS_CROSSTALK_PUBLIC=1`.
- **Never egress:** owner prompt text, file contents, diffs, test output, absolute paths, `.env` / `.agentenv/` / secret-shaped paths.
- **Never silently withhold.** Suppressed paths are counted and the count is shown.
- **No new hook script.** Everything runs through `daedalus/hooks/__main__.py`.
- **Time budgets:** 6.0 s for the SessionStart/SessionEnd network work, 3.0 s in the turn handler, enforced with the existing `_common.with_deadline`.
- **ASCII in injected hook text.** `_tree.py` learned this against a cp1252 console; injected lines stay ASCII. Bodies POSTED to GitHub may be UTF-8.
- **Staging discipline.** `git add` names exact paths. Never `git add -A`. Do not touch `daedalus/mapping/reach.py`, `tests/test_mapping_reach_facades.py`, `.semgrep/guardian.yml` — they belong to other live sessions.

---

### Task 1: Redaction and message rendering

Pure functions, no I/O, no network. This is the safety net that every later task posts through.

**Files:**
- Create: `daedalus/hooks/crosstalk.py`
- Test: `tests/test_crosstalk.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Note` dataclass (fields `kind: str`, `session: str`, `branch: str`, `head: str`, `lines: tuple[str, ...]`, `ts: str`); `render(note: Note) -> str`; `redact_paths(paths: Iterable[str]) -> tuple[list[str], int]`; `SECRET_PAT`; `ABS_PAT`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_crosstalk.py`:

```python
"""Tests for daedalus/hooks/crosstalk.py — the GitHub Discussions crosstalk.

No test touches the network: the transport is always a fake that records
calls. Tests that assert redaction FIRST assert the input really contained
the forbidden string, because a fixture that is inert makes the guard look
green while guarding nothing.
"""
from __future__ import annotations

from pathlib import Path

from daedalus.hooks import crosstalk


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
        kind="ERGEBNIS", session="a3f2", branch="packet/x", head="abc1234",
        lines=("commits: 2",), ts="2026-09-03T09:46:02+02:00",
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daedalus.hooks.crosstalk'`

- [ ] **Step 3: Write the module's pure half**

Create `daedalus/hooks/crosstalk.py`:

```python
"""Crosstalk: parallel sessions announce themselves in GitHub Discussions.

This module is the only place that talks to GitHub, and the only place that
decides what may leave the machine. The hook handlers in ``events.py`` call
it; they contain no transport and no redaction of their own.

Two rules govern everything here:

* **Fail-open.** This is an display surface, not a trust boundary. A GitHub
  outage must cost a note in the injected text, never a refused tool call.
  Fail-closed here would mean an unreachable github.com makes the checkout
  unusable.
* **Redaction is a net, not a habit.** :func:`render` sanitizes every body on
  the way out, so a careless builder cannot leak. Suppressed paths are
  COUNTED in the body: a report that quietly shrank is indistinguishable
  from a tree that got cleaner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

#: Paths that never leave the machine. Deliberately broad: a false positive
#: costs one counted line, a false negative costs a secret.
SECRET_PAT = re.compile(
    r"(^|/)\.env|(^|/)\.agentenv/|secret|token|credential|password|\.pem$|\.key$|"
    r"(^|/)id_[a-z]+$",
    re.IGNORECASE,
)

#: Absolute paths carry the machine's user name and layout. Windows drive
#: paths, UNC paths and POSIX home paths all get replaced whole.
ABS_PAT = re.compile(
    r"([A-Za-z]:[\\/][^\s,;]*)|(\\\\[^\s,;]+)|(/(?:home|Users|root)/[^\s,;]*)"
)

WITHHELD = "<pfad entfernt>"


@dataclass(frozen=True)
class Note:
    """One message on its way to a Discussion. ``lines`` is free text written
    by a builder or by the model; :func:`render` is what makes it safe."""

    kind: str
    session: str
    branch: str
    head: str
    lines: tuple[str, ...] = ()
    ts: str = ""


def redact_paths(paths: Iterable[str]) -> tuple[list[str], int]:
    """Split ``paths`` into the ones that may be named and a count of the
    ones that may not. The count is returned rather than dropped so the
    caller can SAY that something was withheld."""
    kept: list[str] = []
    withheld = 0
    for path in paths:
        if SECRET_PAT.search(path):
            withheld += 1
        else:
            kept.append(path)
    return kept, withheld


def _sanitize(line: str) -> tuple[str, int]:
    """One body line, plus how many secret-shaped tokens were removed."""
    line = ABS_PAT.sub(WITHHELD, line)
    withheld = 0
    parts = [p.strip() for p in line.split(",")]
    if len(parts) > 1:
        keep: list[str] = []
        for part in parts:
            if SECRET_PAT.search(part):
                withheld += 1
            else:
                keep.append(part)
        line = ", ".join(keep)
    elif SECRET_PAT.search(line):
        return "", 1
    return line, withheld


def render(note: Note) -> str:
    """The body posted to GitHub. Every path this module publishes goes
    through here."""
    header = f"{note.kind} `{note.session}` {note.branch or 'detached'} @{note.head or '?'}"
    out = [header]
    withheld = 0
    for raw in note.lines:
        line, dropped = _sanitize(raw)
        withheld += dropped
        if line:
            out.append(line)
    if withheld:
        out.append(f"({withheld} zurueckgehalten: secret-verdaechtiger pfad)")
    if note.ts:
        out.append(f"_{note.ts}_")
    return "\n".join(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add daedalus/hooks/crosstalk.py tests/test_crosstalk.py
git commit -m "feat(crosstalk): redaction and message rendering for the discussions channel"
```

---

### Task 2: Transport, gating and thread resolution

**Files:**
- Modify: `daedalus/hooks/crosstalk.py`
- Test: `tests/test_crosstalk.py`

**Interfaces:**
- Consumes: `Note`, `render` from Task 1.
- Produces: `TransportError`; `enabled(env=None) -> bool`; `Channel` class with `__init__(self, root: Path, transport=None, env=None)`, `.post(note: Note, thread_title: str) -> None`, `.read(thread_title: str, count: int = 8) -> list[str]`, `.reason: str`; module constants `ENV_ENABLE`, `ENV_PUBLIC`, `ENV_CATEGORY`, `GLOBAL_THREAD`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_crosstalk.py`:

```python
class FakeTransport:
    """Stands in for ``gh api graphql``. Records every call; returns canned
    GraphQL payloads."""

    def __init__(self, visibility="PRIVATE", discussions=None, fail=None):
        self.calls: list[dict] = []
        self.visibility = visibility
        self.discussions = discussions or []
        self.fail = fail

    def __call__(self, query: str, variables: dict) -> dict:
        self.calls.append({"query": query, "variables": variables})
        if self.fail is not None:
            raise self.fail
        if "discussionCategories" in query:
            return {
                "repository": {
                    "id": "R_1",
                    "visibility": self.visibility,
                    "hasDiscussionsEnabled": True,
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
                            {"author": {"login": "KTY137"}, "createdAt": "2026-09-03T09:00:00Z",
                             "body": "ANMELDUNG `b7c1` packet/x @aaa"}
                        ]
                    },
                }
            }
        raise AssertionError("unexpected query: " + query[:60])


def _channel(tmp_path: Path, transport, **env):
    base = {"DAEDALUS_CROSSTALK": "on", "GH_REPO": "KTY137/daedalus"}
    base.update(env)
    return crosstalk.Channel(tmp_path, transport=transport, env=base)


def test_disabled_by_default_makes_no_call(tmp_path: Path):
    fake = FakeTransport()
    ch = crosstalk.Channel(tmp_path, transport=fake, env={})
    ch.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert fake.calls == []
    assert "aus" in ch.reason


def test_public_repo_is_refused_without_optin(tmp_path: Path):
    fake = FakeTransport(visibility="PUBLIC")
    ch = _channel(tmp_path, fake)
    ch.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert not any("addDiscussionComment" in c["query"] for c in fake.calls)
    assert "oeffentlich" in ch.reason


def test_public_repo_posts_with_optin(tmp_path: Path):
    fake = FakeTransport(visibility="PUBLIC")
    ch = _channel(tmp_path, fake, DAEDALUS_CROSSTALK_PUBLIC="1")
    ch.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")
    assert any("addDiscussionComment" in c["query"] for c in fake.calls)


def test_missing_thread_is_created_then_commented(tmp_path: Path):
    fake = FakeTransport(discussions=[])
    ch = _channel(tmp_path, fake)
    ch.post(crosstalk.Note("ANMELDUNG", "a3f2", "packet/x", "abc"), "packet/x")
    kinds = [c["query"] for c in fake.calls]
    assert any("createDiscussion" in q for q in kinds)
    assert any("addDiscussionComment" in q for q in kinds)


def test_existing_thread_is_reused(tmp_path: Path):
    fake = FakeTransport(discussions=[{"id": "D_7", "title": "packet/x", "number": 7}])
    ch = _channel(tmp_path, fake)
    ch.post(crosstalk.Note("ANMELDUNG", "a3f2", "packet/x", "abc"), "packet/x")
    assert not any("createDiscussion" in c["query"] for c in fake.calls)
    comment = [c for c in fake.calls if "addDiscussionComment" in c["query"]][0]
    assert comment["variables"]["id"] == "D_7"


def test_transport_failure_is_fail_open(tmp_path: Path):
    fake = FakeTransport(fail=TimeoutError("boom"))
    ch = _channel(tmp_path, fake)
    ch.post(crosstalk.Note("ANMELDUNG", "a3f2", "main", "abc"), "crew-channel")  # must not raise
    assert ch.reason
    assert ch.read("crew-channel") == []


def test_read_returns_comment_lines(tmp_path: Path):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    ch = _channel(tmp_path, fake)
    lines = ch.read("crew-channel", count=3)
    assert any("b7c1" in l for l in lines)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v`
Expected: FAIL — `AttributeError: module 'daedalus.hooks.crosstalk' has no attribute 'Channel'`

- [ ] **Step 3: Implement transport and channel**

Append to `daedalus/hooks/crosstalk.py`:

```python
import json
import os
import subprocess
from pathlib import Path

from ._common import git, hooks_dir

ENV_ENABLE = "DAEDALUS_CROSSTALK"
ENV_PUBLIC = "DAEDALUS_CROSSTALK_PUBLIC"
ENV_CATEGORY = "DAEDALUS_CROSSTALK_CATEGORY"
GLOBAL_THREAD = "crew-channel"
DEFAULT_CATEGORY = "General"
GH_TIMEOUT_S = 6.0

_Q_REPO = """
query($owner:String!,$name:String!){
  repository(owner:$owner,name:$name){
    id visibility hasDiscussionsEnabled
    discussionCategories(first:25){nodes{id name}}
    discussions(first:50, orderBy:{field:UPDATED_AT,direction:DESC}){nodes{id title number}}
  }
}
"""
_M_CREATE = """
mutation($repo:ID!,$cat:ID!,$title:String!,$body:String!){
  createDiscussion(input:{repositoryId:$repo,categoryId:$cat,title:$title,body:$body}){
    discussion{id number}
  }
}
"""
_M_COMMENT = """
mutation($id:ID!,$body:String!){
  addDiscussionComment(input:{discussionId:$id,body:$body}){comment{id}}
}
"""
_Q_READ = """
query($id:ID!,$n:Int!){
  node(id:$id){... on Discussion{title comments(last:$n){
    nodes{author{login} createdAt body}
  }}}
}
"""


class TransportError(RuntimeError):
    """gh could not answer: missing binary, no login, timeout, API error."""


def enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return (env.get(ENV_ENABLE) or "").strip().lower() == "on"


def gh_graphql(query: str, variables: dict) -> dict:
    """One ``gh api graphql`` call. Raises :class:`TransportError` for every
    failure mode so the caller has exactly one thing to catch. The token
    never enters this process: gh holds it."""
    args = ["gh", "api", "graphql", "-f", "query=" + query]
    for key, value in variables.items():
        args += ["-F", f"{key}={value}"]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=GH_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise TransportError("gh nicht installiert") from exc
    except subprocess.SubprocessError as exc:
        raise TransportError("gh timeout") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        raise TransportError((detail[0] if detail else "gh exit " + str(proc.returncode))[:120])
    try:
        parsed = json.loads(proc.stdout)
    except ValueError as exc:
        raise TransportError("gh antwortete kein JSON") from exc
    if parsed.get("errors"):
        raise TransportError(str(parsed["errors"][0].get("message", "graphql error"))[:120])
    return parsed.get("data") or {}


class Channel:
    """A repository's Discussions, as far as the hooks care.

    Never raises. Every refusal or failure leaves a human-readable German
    sentence in :attr:`reason`, which the handlers inject verbatim.
    """

    def __init__(self, root: Path, transport=None, env: dict | None = None):
        self.root = root
        self.env = os.environ if env is None else env
        self.transport = transport or gh_graphql
        self.reason = ""
        self._repo: dict | None = None

    # -- repository facts ------------------------------------------------
    def _slug(self) -> tuple[str, str] | None:
        override = self.env.get("GH_REPO") or ""
        if "/" in override:
            owner, _, name = override.partition("/")
            return owner, name
        url = str(git(self.root, "remote", "get-url", "origin"))
        match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url.strip())
        if not match:
            self.reason = "crosstalk: kein origin-remote erkannt"
            return None
        return match.group(1), match.group(2)

    def _repo_facts(self) -> dict | None:
        if self._repo is not None:
            return self._repo
        slug = self._slug()
        if slug is None:
            return None
        try:
            data = self.transport(_Q_REPO, {"owner": slug[0], "name": slug[1]})
        except TransportError as exc:
            self.reason = f"crosstalk: GitHub nicht erreichbar ({exc})"
            return None
        repo = (data or {}).get("repository")
        if not repo:
            self.reason = "crosstalk: Repository nicht lesbar"
            return None
        if not repo.get("hasDiscussionsEnabled"):
            self.reason = "crosstalk: Discussions sind fuer dieses Repo nicht aktiviert"
            return None
        self._repo = repo
        return repo

    def _may_post(self, repo: dict) -> bool:
        if repo.get("visibility") == "PRIVATE":
            return True
        if (self.env.get(ENV_PUBLIC) or "").strip() == "1":
            return True
        self.reason = (
            "crosstalk: Repo ist oeffentlich -- kein Post ohne "
            "DAEDALUS_CROSSTALK_PUBLIC=1"
        )
        return False

    def _thread_id(self, repo: dict, title: str, create: bool) -> str | None:
        for node in (repo.get("discussions") or {}).get("nodes") or []:
            if node.get("title") == title:
                return node.get("id")
        if not create:
            self.reason = f"crosstalk: Thread '{title}' existiert noch nicht"
            return None
        cats = (repo.get("discussionCategories") or {}).get("nodes") or []
        wanted = self.env.get(ENV_CATEGORY) or DEFAULT_CATEGORY
        cat = next((c for c in cats if c.get("name") == wanted), None) or (cats[0] if cats else None)
        if not cat:
            self.reason = "crosstalk: keine Discussion-Kategorie im Repo"
            return None
        try:
            data = self.transport(
                _M_CREATE,
                {"repo": repo["id"], "cat": cat["id"], "title": title,
                 "body": "Automatischer Crosstalk-Thread der Claude-Sessions."},
            )
        except TransportError as exc:
            self.reason = f"crosstalk: Thread anlegen fehlgeschlagen ({exc})"
            return None
        return ((data.get("createDiscussion") or {}).get("discussion") or {}).get("id")

    # -- public surface --------------------------------------------------
    def post(self, note: Note, thread_title: str) -> bool:
        if not enabled(self.env):
            self.reason = "crosstalk: aus (DAEDALUS_CROSSTALK != on)"
            return False
        repo = self._repo_facts()
        if repo is None or not self._may_post(repo):
            return False
        thread = self._thread_id(repo, thread_title, create=True)
        if thread is None:
            return False
        try:
            self.transport(_M_COMMENT, {"id": thread, "body": render(note)})
        except TransportError as exc:
            self.reason = f"crosstalk: Post fehlgeschlagen ({exc})"
            return False
        return True

    def read(self, thread_title: str, count: int = 8) -> list[str]:
        if not enabled(self.env):
            self.reason = "crosstalk: aus (DAEDALUS_CROSSTALK != on)"
            return []
        repo = self._repo_facts()
        if repo is None:
            return []
        thread = self._thread_id(repo, thread_title, create=False)
        if thread is None:
            return []
        try:
            data = self.transport(_Q_READ, {"id": thread, "n": count})
        except TransportError as exc:
            self.reason = f"crosstalk: Lesen fehlgeschlagen ({exc})"
            return []
        nodes = (((data.get("node") or {}).get("comments") or {}).get("nodes")) or []
        out: list[str] = []
        for node in nodes:
            who = ((node.get("author") or {}).get("login")) or "?"
            first = (node.get("body") or "").strip().splitlines()
            out.append(f"  [{who}] {first[0] if first else ''}"[:200])
        return out
```

Move the `import re` from Task 1 to the top of the file with the others; there must be exactly one import block.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add daedalus/hooks/crosstalk.py tests/test_crosstalk.py
git commit -m "feat(crosstalk): gh transport, public-repo lock and thread resolution"
```

---

### Task 3: SessionStart announces and reads back

**Files:**
- Modify: `daedalus/hooks/crosstalk.py`
- Modify: `daedalus/hooks/events.py:79-105`
- Test: `tests/test_crosstalk.py`

**Interfaces:**
- Consumes: `Channel`, `Note`, `render` from Task 2.
- Produces: `dirty_paths(root: Path) -> list[str]`; `short_sid(sid: str) -> str`; `announce(root, sid, facts, state, channel) -> list[str]` returning ASCII lines for injection; state key `crosstalk_announced`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_crosstalk.py`:

```python
import io

from daedalus.hooks import __main__ as entry
from daedalus.hooks import _common

RECEIPT = entry.start_effect()


def _run(event: str, data: dict):
    out = io.StringIO()
    result = entry.dispatch(event, data, RECEIPT, stdout=out)
    return result, out.getvalue()


def test_session_start_does_not_egress_the_prompt(repo, monkeypatch):
    fake = FakeTransport()
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    data = {
        "session_id": "sess-1", "cwd": str(repo), "hook_event_name": "SessionStart",
        "source": "startup", "prompt": "GEHEIMER-PROMPT-TEXT",
    }
    assert "GEHEIMER-PROMPT-TEXT" in json.dumps(data)  # the fixture is not inert
    _run("session", data)
    posted = json.dumps(fake.calls)
    assert "GEHEIMER-PROMPT-TEXT" not in posted


def test_session_start_announces_once_across_compaction(repo, monkeypatch):
    fake = FakeTransport()
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    base = {"session_id": "sess-2", "cwd": str(repo), "hook_event_name": "SessionStart"}
    _run("session", dict(base, source="startup"))
    first = sum("addDiscussionComment" in c["query"] for c in fake.calls)
    _run("session", dict(base, source="compact"))
    second = sum("addDiscussionComment" in c["query"] for c in fake.calls)
    assert first == 1
    assert second == 1  # compaction re-reads, it does not re-announce


def test_session_start_injects_the_thread(repo, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    _, text = _run("session", {
        "session_id": "sess-3", "cwd": str(repo),
        "hook_event_name": "SessionStart", "source": "startup",
    })
    assert "CROSSTALK" in text
    assert "b7c1" in text


def test_session_start_survives_a_dead_transport(repo, monkeypatch):
    fake = FakeTransport(fail=TimeoutError("boom"))
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    result, text = _run("session", {
        "session_id": "sess-4", "cwd": str(repo),
        "hook_event_name": "SessionStart", "source": "startup",
    })
    assert "TREE:" in text            # the rest of the hook still answered
    assert "nicht erreichbar" in text  # and it says why
```

The `repo` fixture is the one in `tests/test_hooks_v2.py`. Copy it verbatim into `tests/test_crosstalk.py` (with its `_git` helper) rather than importing across test modules — the plan deliberately keeps the two files independent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v -k session_start`
Expected: FAIL — no CROSSTALK line in the output, no transport call recorded.

- [ ] **Step 3: Add the announce helper to crosstalk.py**

```python
CROSSTALK_BUDGET_S = 6.0
READ_COMMENTS = 6


def short_sid(sid: str) -> str:
    return (sid or "unknown").replace("-", "")[:4] or "unknown"


def dirty_paths(root: Path, limit: int = 8) -> list[str]:
    """Repo-relative paths of modified/untracked files, redacted and capped."""
    out = git(root, "status", "--porcelain")
    if not out.ok:
        return []
    paths = [line[3:].strip() for line in str(out).splitlines() if len(line) > 3]
    kept, withheld = redact_paths(paths)
    shown = kept[:limit]
    if len(kept) > limit:
        shown.append(f"(+{len(kept) - limit} weitere)")
    if withheld:
        shown.append(f"({withheld} zurueckgehalten)")
    return shown


def threads_for(branch: str) -> list[str]:
    """Which discussions this session speaks in: the global one, plus its
    own branch when it has one."""
    titles = [GLOBAL_THREAD]
    if branch and branch != "detached":
        titles.append(branch)
    return titles


def announce(root: Path, sid: str, branch: str, head: str, ts: str,
             channel: "Channel", *, do_post: bool) -> list[str]:
    """Post the ANMELDUNG (when ``do_post``) and read both threads back.
    Returns ASCII lines for injection -- never raises."""
    lines: list[str] = []
    titles = threads_for(branch)
    if do_post:
        note = Note("ANMELDUNG", short_sid(sid), branch, head,
                    tuple(["dirty: " + ", ".join(dirty_paths(root))] if dirty_paths(root) else []),
                    ts)
        for title in titles:
            channel.post(note, title)
    seen: list[str] = []
    for title in titles:
        for line in channel.read(title, READ_COMMENTS):
            seen.append(line)
    if seen:
        lines.append("CROSSTALK (" + ", ".join(titles) + "):")
        lines += seen[-READ_COMMENTS:]
    elif channel.reason:
        lines.append(channel.reason)
    return lines
```

- [ ] **Step 4: Wire it into `session_start`**

In `daedalus/hooks/events.py`, add `from . import crosstalk` to the imports, then insert before `base_fp = source_fingerprint(root)`:

```python
    already = bool(_common.load_state(root, sid).get("crosstalk_announced"))
    cross = with_deadline(
        lambda: crosstalk.announce(
            root, sid, facts.branch, facts.head, now_iso(),
            crosstalk.Channel(root), do_post=not already,
        ),
        crosstalk.CROSSTALK_BUDGET_S,
        ["crosstalk: Zeitbudget ueberschritten"],
    )
    lines += cross
```

Add `load_state` and `now_iso` to the `._common` import list, and set the state flag inside the existing `mutate`:

```python
        state["crosstalk_announced"] = True
```

- [ ] **Step 5: Run the tests**

Run: `uv run --frozen pytest tests/test_crosstalk.py tests/test_hooks_v2.py -v`
Expected: all pass — the four new SessionStart tests plus the whole existing hooks suite unchanged.

- [ ] **Step 6: Commit**

```bash
git add daedalus/hooks/crosstalk.py daedalus/hooks/events.py tests/test_crosstalk.py
git commit -m "feat(crosstalk): SessionStart announces once and injects both threads"
```

---

### Task 4: SessionEnd reports the result

**Files:**
- Modify: `daedalus/hooks/crosstalk.py`
- Modify: `daedalus/hooks/events.py`
- Modify: `daedalus/hooks/__main__.py:41-51`
- Modify: `.claude/settings.json`
- Test: `tests/test_crosstalk.py`

**Interfaces:**
- Consumes: `Channel`, `Note`, `short_sid`, `threads_for`, `dirty_paths`.
- Produces: `events.session_end(payload, root, sid) -> HookResult`; dispatcher key `"session_end"`.

- [ ] **Step 1: Write the failing test**

```python
def test_session_end_reports_commits_and_files(repo, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    base = {"session_id": "sess-5", "cwd": str(repo), "hook_event_name": "SessionStart"}
    _run("session", dict(base, source="startup"))
    (repo / "daedalus" / "b.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", "daedalus/b.py")
    _git(repo, "commit", "-q", "-m", "feat: add b")
    _run("session_end", dict(base, hook_event_name="SessionEnd", reason="clear"))
    bodies = [c["variables"].get("body", "") for c in fake.calls
              if "addDiscussionComment" in c["query"]]
    assert any(b.startswith("ERGEBNIS") for b in bodies)
    assert any("feat: add b" in b for b in bodies)


def test_session_end_without_a_start_is_silent(repo, monkeypatch):
    fake = FakeTransport()
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    _run("session_end", {"session_id": "sess-6", "cwd": str(repo),
                         "hook_event_name": "SessionEnd", "reason": "clear"})
    assert not any("addDiscussionComment" in c["query"] for c in fake.calls)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v -k session_end`
Expected: FAIL — `unknown-event:session_end`, no comment recorded.

- [ ] **Step 3: Add the result builder to crosstalk.py**

```python
def report(root: Path, sid: str, branch: str, head_now: str, ts: str,
           state: dict, channel: "Channel") -> None:
    """Post the ERGEBNIS to every thread this session spoke in."""
    head_then = str(state.get("crosstalk_head") or "")
    lines: list[str] = []
    if head_then and head_then != head_now:
        rng = f"{head_then}..{head_now}"
        subjects = git(root, "log", "--format=%s", rng)
        if subjects.ok:
            subs = [s for s in str(subjects).splitlines() if s]
            if subs:
                lines.append(f"commits: {len(subs)} ({' | '.join(subs[:3])})")
        names = git(root, "diff", "--name-only", rng)
        if names.ok:
            kept, withheld = redact_paths([n for n in str(names).splitlines() if n])
            lines.append(f"geaendert: {len(kept)} Dateien"
                         + (f" ({withheld} zurueckgehalten)" if withheld else ""))
    else:
        lines.append("keine Commits in dieser Session")
    started = state.get("crosstalk_started")
    if isinstance(started, (int, float)):
        lines.append(f"Dauer: {int((time.time() - started) / 60)} min")
    note = Note("ERGEBNIS", short_sid(sid), branch,
                f"{head_then or '?'} -> {head_now}", tuple(lines), ts)
    for title in threads_for(branch):
        channel.post(note, title)
```

Add `import time` to the module imports. In `announce`, record the start facts by having the caller store them — see Step 4.

- [ ] **Step 4: Add the handler and record the start facts**

In `events.py`'s `session_start` `mutate`, alongside `state["crosstalk_announced"] = True`:

```python
        state.setdefault("crosstalk_head", facts.head)
        state.setdefault("crosstalk_started", time.time())
```

Then add the new handler after `user_prompt`:

```python
def session_end(payload: dict, root: Path, sid: str) -> HookResult:
    """SessionEnd: post the result. A session that never announced stays
    silent -- there is nothing to close, and a stray ERGEBNIS without an
    ANMELDUNG reads as a session that vanished."""
    state = load_state(root, sid)
    if not state.get("crosstalk_announced"):
        return HookResult(note="crosstalk:no-announce")
    facts = tree_facts(root)
    with_deadline(
        lambda: crosstalk.report(
            root, sid, facts.branch, facts.head, now_iso(), state, crosstalk.Channel(root)
        ),
        crosstalk.CROSSTALK_BUDGET_S,
        None,
    )
    return HookResult(note="crosstalk:reported")
```

- [ ] **Step 5: Register the handler**

In `daedalus/hooks/__main__.py`, add to `HANDLERS`:

```python
    "session_end": events.session_end,
```

Update the module docstring's event list to name `session_end`.

- [ ] **Step 6: Add the settings entry**

In `.claude/settings.json`, inside `"hooks"`, add:

```json
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PROJECT_DIR}/daedalus/hooks/__main__.py\" session_end",
            "timeout": 15
          }
        ]
      }
    ],
```

- [ ] **Step 7: Run the tests**

Run: `uv run --frozen pytest tests/test_crosstalk.py tests/test_hooks_v2.py tests/test_hooks_precompact.py -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add daedalus/hooks/crosstalk.py daedalus/hooks/events.py daedalus/hooks/__main__.py .claude/settings.json tests/test_crosstalk.py
git commit -m "feat(crosstalk): SessionEnd posts the result through the one dispatcher"
```

---

### Task 5: The turn handler re-reads, cached

**Files:**
- Modify: `daedalus/hooks/crosstalk.py`
- Modify: `daedalus/hooks/events.py:198-258`
- Test: `tests/test_crosstalk.py`

**Interfaces:**
- Consumes: `Channel`, `threads_for`.
- Produces: `poll(root, branch, channel, state, now) -> list[str]`; `POLL_TTL_S`; state keys `crosstalk_polled_at`, `crosstalk_cache`.

- [ ] **Step 1: Write the failing test**

```python
def test_turn_poll_is_cached(repo, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    base = {"session_id": "sess-7", "cwd": str(repo)}
    _run("session", dict(base, hook_event_name="SessionStart", source="startup"))
    fake.calls.clear()
    _run("turn", dict(base, hook_event_name="UserPromptSubmit", prompt="a"))
    after_first = len([c for c in fake.calls if "comments(last" in c["query"]])
    _run("turn", dict(base, hook_event_name="UserPromptSubmit", prompt="b"))
    after_second = len([c for c in fake.calls if "comments(last" in c["query"]])
    assert after_first == 1
    assert after_second == 1  # inside the TTL: served from cache
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v -k turn_poll`
Expected: FAIL — `after_second == 2` (or 0 if no poll exists yet).

- [ ] **Step 3: Implement the cached poll**

```python
POLL_TTL_S = 300.0
TURN_BUDGET_S = 3.0


def poll(root: Path, branch: str, channel: "Channel", state: dict, now: float) -> list[str]:
    """New comments for the turn handler. Refetches at most every
    :data:`POLL_TTL_S`; otherwise serves the cached lines. Mutates ``state``
    in place -- call it from inside ``update_state``."""
    last = state.get("crosstalk_polled_at")
    cached = state.get("crosstalk_cache") or []
    if isinstance(last, (int, float)) and now - last < POLL_TTL_S:
        return list(cached)
    lines: list[str] = []
    for title in threads_for(branch):
        lines += channel.read(title, READ_COMMENTS)
    state["crosstalk_polled_at"] = now
    state["crosstalk_cache"] = lines
    return lines
```

- [ ] **Step 4: Wire it into `user_prompt`**

Inside the existing `mutate` in `user_prompt`, after the watchdog block:

```python
        if state.get("crosstalk_announced"):
            fresh = with_deadline(
                lambda: crosstalk.poll(
                    root, tree_facts(root).branch, crosstalk.Channel(root),
                    state, time.time(),
                ),
                crosstalk.TURN_BUDGET_S,
                [],
            )
            previous = collected.get("_crosstalk_prev") or state.get("crosstalk_shown") or []
            new = [l for l in fresh if l not in previous]
            if new:
                state["crosstalk_shown"] = fresh
                collected["crosstalk"] = ["CROSSTALK neu:"] + new[-3:]
```

And in the priority order block, immediately after the watchdog line (alarms first, chatter after):

```python
    if collected.get("crosstalk"):
        lines += collected["crosstalk"]
```

- [ ] **Step 5: Run the tests**

Run: `uv run --frozen pytest tests/test_crosstalk.py tests/test_hooks_v2.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add daedalus/hooks/crosstalk.py daedalus/hooks/events.py tests/test_crosstalk.py
git commit -m "feat(crosstalk): cached re-read in the turn handler so browser replies land"
```

---

### Task 6: The `say` CLI and the effect-boundary registration

**Files:**
- Modify: `daedalus/hooks/crosstalk.py`
- Modify: `daedalus/spine/effect_boundary.py:1734-1749`
- Test: `tests/test_crosstalk.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `crosstalk.main(argv: list[str] | None = None) -> int`; registry row `daedalus.hooks.crosstalk`.

- [ ] **Step 1: Write the failing tests**

```python
def test_say_posts_a_model_written_line(repo, monkeypatch):
    fake = FakeTransport(discussions=[{"id": "D_1", "title": "crew-channel", "number": 1}])
    monkeypatch.setenv("DAEDALUS_CROSSTALK", "on")
    monkeypatch.setenv("GH_REPO", "KTY137/daedalus")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr(crosstalk, "gh_graphql", fake)
    rc = crosstalk.main(["crosstalk", "say", "nehme reach.py, fasst sie nicht an"])
    assert rc == 0
    bodies = [c["variables"].get("body", "") for c in fake.calls
              if "addDiscussionComment" in c["query"]]
    assert any("fasst sie nicht an" in b for b in bodies)


def test_say_never_raises_without_arguments(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert crosstalk.main(["crosstalk", "say"]) == 0


def test_crosstalk_entrypoint_is_registered():
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    row = REGISTRY_BY_ID["daedalus.hooks.crosstalk"]
    assert "network_egress" in [e.value for e in row.effects]
    assert "process_spawn" in [e.value for e in row.effects]


def test_hooks_entrypoint_notes_mention_github():
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    notes = " ".join(REGISTRY_BY_ID["daedalus.hooks"].notes)
    assert "github.com" in notes  # the loopback-only justification is no longer true
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --frozen pytest tests/test_crosstalk.py -v -k "say or registered or notes"`
Expected: FAIL — `AttributeError: main`, `KeyError: 'daedalus.hooks.crosstalk'`.

- [ ] **Step 3: Add the CLI**

```python
def main(argv: list[str] | None = None) -> int:
    """``python -m daedalus.hooks.crosstalk say "..."`` -- one line, written by
    the model, into this branch's threads. Exit code is always 0: this is a
    courtesy channel, and a failed post must not fail a command."""
    import sys

    argv = list(sys.argv if argv is None else argv)
    try:
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "daedalus.hooks.crosstalk",
            REGISTRY_BY_ID["daedalus.hooks.crosstalk"].effects,
            (process_guard_boundary_decision(),),
        )
    except Exception as exc:  # noqa: BLE001 - a refusal is reported, never raised
        print(f"[crosstalk] effect boundary refused or unavailable: {exc}", file=sys.stderr)
        return 0
    if len(argv) < 3 or argv[1] != "say" or not argv[2].strip():
        print("usage: python -m daedalus.hooks.crosstalk say \"<zeile>\"", file=sys.stderr)
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    facts_branch = str(git(root, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    facts_head = str(git(root, "rev-parse", "--short", "HEAD")).strip()
    sid = os.environ.get("CLAUDE_SESSION_ID") or "cli"
    channel = Channel(root)
    note = Note("SAGT", short_sid(sid), facts_branch, facts_head,
                (argv[2].strip(),), _now_iso())
    ok = False
    for title in threads_for(facts_branch):
        ok = channel.post(note, title) or ok
    if not ok:
        print("[crosstalk] " + (channel.reason or "nicht gepostet"), file=sys.stderr)
    return 0


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Register the entrypoint and correct the notes**

In `daedalus/spine/effect_boundary.py`, change the `daedalus.hooks` row's `notes` to:

```python
        notes=(
            "Claude Code hooks dispatcher (python -m daedalus.hooks <event>): "
            "writes runs/hooks/ state and ledger, spawns git for tree facts, "
            "probes Serena's loopback dashboard port, and -- when "
            "DAEDALUS_CROSSTALK=on -- spawns gh to reach github.com for the "
            "Discussions crosstalk. Starts centrally; a boundary refusal "
            "prints to stderr and exits 0 (hook protocol)."
        ),
```

and add a new row directly after it:

```python
    EntrypointSpec(
        id="daedalus.hooks.crosstalk",
        surface=Surface.CLI,
        target="daedalus.hooks.crosstalk:main",
        effects=(Effect.NETWORK_EGRESS, Effect.PROCESS_SPAWN),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        anchors=(GuardAnchor("daedalus.hooks.crosstalk:main", "begin_effect"),),
        notes=(
            "python -m daedalus.hooks.crosstalk say \"...\": posts one "
            "model-written line into the branch's GitHub Discussions via gh. "
            "No token is handled here -- gh holds the credential. Off unless "
            "DAEDALUS_CROSSTALK=on; refuses on a public repo without "
            "DAEDALUS_CROSSTALK_PUBLIC=1; exits 0 on every failure."
        ),
        migration="complete for the daedalus.hooks.crosstalk entrypoint (2026-09-03)",
    ),
```

- [ ] **Step 5: Run the full affected suite**

Run: `uv run --frozen pytest tests/test_crosstalk.py tests/test_hooks_v2.py tests/test_hooks_precompact.py tests/test_hooks_review_20260825.py tests/test_effect_boundary.py tests/test_cli_effect_boundary.py -v`
Expected: all pass. Any pre-existing failure is named separately as a baseline failure, not attributed to this work.

- [ ] **Step 6: Commit**

```bash
git add daedalus/hooks/crosstalk.py daedalus/spine/effect_boundary.py tests/test_crosstalk.py
git commit -m "feat(crosstalk): say CLI, registered entrypoint, honest egress notes"
```

---

### Task 7: Live verification and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-crosstalk-design.md` (status line only)
- Modify: `.claude/AGENT_PROTOCOL.md` (one paragraph naming the channel)

- [ ] **Step 1: Check whether the owner actions happened**

Run: `gh auth status && gh repo view KTY137/daedalus --json visibility,hasDiscussionsEnabled`
Expected: either a login plus the two flags, or "not logged into any GitHub hosts".

- [ ] **Step 2: If logged in, do one real round trip**

```bash
DAEDALUS_CROSSTALK=on python -m daedalus.hooks.crosstalk say "crosstalk live check"
gh api graphql -f query='{repository(owner:"KTY137",name:"daedalus"){discussions(first:3){nodes{title}}}}'
```
Expected: the comment appears in `crew-channel`. Record the discussion number.

- [ ] **Step 3: If NOT logged in, record it honestly**

Set the spec's `Status:` line to `implemented; live path UNVERIFIED (no gh login as of <date>)`. Do not write "works".

- [ ] **Step 4: Document the channel for the crew**

Add to `.claude/AGENT_PROTOCOL.md` under "Standing orders":

```markdown
- **Crosstalk.** Parallel sessions announce themselves in GitHub Discussions
  (`crew-channel` plus one thread per branch). SessionStart injects the last
  few lines; say something back with
  `python -m daedalus.hooks.crosstalk say "..."` when you take a file another
  session may want. The channel informs; it never blocks, and it is off unless
  `DAEDALUS_CROSSTALK=on`.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-09-03-crosstalk-design.md .claude/AGENT_PROTOCOL.md
git commit -m "docs(crosstalk): name the channel in the crew protocol, record live status"
```

---

## Self-review

**Spec coverage.** Redaction → Task 1. Transport, default-off, public lock, fail-open, thread resolution → Task 2. SessionStart announce + read-back + the compact-dedupe → Task 3. SessionEnd → Task 4. Cached turn poll → Task 5. `say` CLI, entrypoint registration, corrected notes → Task 6. Live verification and the honest UNVERIFIED status → Task 7. The spec's six named thermometer tests map to: redaction (T1), fail-open (T2/T3), dedupe (T3), default-off (T2), public lock (T2), turn cache (T5).

**Type consistency.** `Note(kind, session, branch, head, lines, ts)` is constructed identically in Tasks 3, 4 and 6. `Channel.post` returns `bool`, `Channel.read` returns `list[str]`, both used that way throughout. `threads_for(branch)` is the single source of which threads get written.

**Known rough edge, deliberately left.** `announce` calls `dirty_paths` twice in the code as written; the implementer should hoist it to a local. It is left visible here rather than silently smoothed, because the plan is what gets reviewed.
