"""Crosstalk: parallel sessions announce themselves in GitHub Discussions.

This module is the only place that talks to GitHub, and the only place that
decides what may leave the machine. The hook handlers in ``events.py`` call
it; they contain no transport and no redaction of their own.

Two rules govern everything here:

* **Fail-open.** This is a display surface, not a trust boundary. A GitHub
  outage must cost a note in the injected text, never a refused tool call.
  Fail-closed here would mean that an unreachable github.com makes the
  checkout unusable, which is a worse failure than the one it prevents.
* **Redaction is a net, not a habit.** :func:`render` sanitizes every body on
  the way out, so a careless builder cannot leak. Suppressed paths are
  COUNTED in the body: a report that quietly shrank is indistinguishable from
  a tree that got cleaner, and this repository's standing orders forbid the
  silent kind.

The channel is OFF unless ``DAEDALUS_CROSSTALK=on``, and refuses to post to a
non-private repository unless ``DAEDALUS_CROSSTALK_PUBLIC=1``. Neither switch
is ceremony: several sessions run in this checkout at once, and a hook that
starts publishing to the internet on its next start is exactly the surprise an
egress switch exists to prevent.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from ._common import git

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

ENV_ENABLE = "DAEDALUS_CROSSTALK"
ENV_PUBLIC = "DAEDALUS_CROSSTALK_PUBLIC"
ENV_CATEGORY = "DAEDALUS_CROSSTALK_CATEGORY"
ENV_REPO = "GH_REPO"

GLOBAL_THREAD = "crew-channel"
DEFAULT_CATEGORY = "General"

#: Wall clock for the SessionStart/SessionEnd network work. The hook itself is
#: given 15 s by ``.claude/settings.json``; the rest of the handler needs the
#: remainder.
CROSSTALK_BUDGET_S = 6.0
#: The turn handler runs on a 10 s hook budget and competes with the shift
#: clock and the architecture delta, both of which have burned turns before.
TURN_BUDGET_S = 3.0
#: One gh invocation.
GH_TIMEOUT_S = 6.0
#: Comments pulled per thread, and the cap on what gets injected.
READ_COMMENTS = 6
#: How stale the turn handler's view may get before it spends another call.
POLL_TTL_S = 300.0

# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

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
    """Split ``paths`` into the ones that may be named and a count of the ones
    that may not. The count is returned rather than dropped so the caller can
    SAY that something was withheld."""
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
    if "," in line:
        head, _, rest = line.partition(":")
        prefix = head + ":" if rest else ""
        body = rest if rest else line
        keep: list[str] = []
        for part in (p.strip() for p in body.split(",")):
            if not part:
                continue
            if SECRET_PAT.search(part):
                withheld += 1
            else:
                keep.append(part)
        line = (prefix + " " if prefix else "") + ", ".join(keep)
        if not keep:
            line = ""
    elif SECRET_PAT.search(line):
        return "", 1
    return line, withheld


def render(note: Note) -> str:
    """The body posted to GitHub. Every line this module publishes goes
    through here, including lines the model wrote itself."""
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


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

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
    """gh could not answer: missing binary, no login, timeout, or API error.
    One exception type, so every caller has exactly one thing to catch."""


def enabled(env: Mapping[str, str] | None = None) -> bool:
    source: Mapping[str, str] = os.environ if env is None else env
    return (source.get(ENV_ENABLE) or "").strip().lower() == "on"


def gh_graphql(query: str, variables: dict) -> dict:
    """One ``gh api graphql`` call.

    The credential never enters this process: gh holds it, which is why this
    entrypoint needs no ``Effect.SECRETS``. Strings go through ``-f`` (raw)
    and numbers through ``-F`` (typed); ``-F`` on a string would read a
    leading ``@`` as a file name.
    """
    args = ["gh", "api", "graphql", "-f", "query=" + query]
    for key, value in variables.items():
        flag = "-F" if isinstance(value, (int, float)) and not isinstance(value, bool) else "-f"
        args += [flag, f"{key}={value}"]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GH_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise TransportError("gh nicht installiert") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise TransportError("gh timeout") from exc
    if proc.returncode != 0:
        detail = [l for l in (proc.stderr or "").strip().splitlines() if l.strip()]
        raise TransportError((detail[0] if detail else f"gh exit {proc.returncode}")[:120])
    try:
        parsed = json.loads(proc.stdout)
    except ValueError as exc:
        raise TransportError("gh antwortete kein JSON") from exc
    if parsed.get("errors"):
        raise TransportError(str(parsed["errors"][0].get("message", "graphql error"))[:120])
    return parsed.get("data") or {}


class Channel:
    """A repository's Discussions, as far as the hooks care.

    Never raises. Every refusal or failure leaves a readable sentence in
    :attr:`reason`, which the handlers inject verbatim -- a channel that went
    quiet for an unstated reason is the failure mode this attribute exists to
    prevent.
    """

    def __init__(self, root: Path, transport=None, env: Mapping[str, str] | None = None):
        self.root = root
        self.env: Mapping[str, str] = os.environ if env is None else env
        self.transport = transport or gh_graphql
        self.reason = ""
        self._repo: dict | None = None
        self._dead = False

    # -- repository facts ------------------------------------------------
    def _slug(self) -> tuple[str, str] | None:
        override = self.env.get(ENV_REPO) or ""
        if "/" in override:
            owner, _, name = override.partition("/")
            return owner.strip(), name.strip()
        url = str(git(self.root, "remote", "get-url", "origin")).strip()
        match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", url)
        if not match:
            self.reason = "crosstalk: kein origin-remote erkannt"
            return None
        return match.group(1), match.group(2)

    def _repo_facts(self) -> dict | None:
        if self._repo is not None:
            return self._repo
        if self._dead:
            return None
        slug = self._slug()
        if slug is None:
            self._dead = True
            return None
        try:
            data = self.transport(_Q_REPO, {"owner": slug[0], "name": slug[1]})
        except TransportError as exc:
            self.reason = f"crosstalk: GitHub nicht erreichbar ({exc})"
            self._dead = True
            return None
        except Exception as exc:  # noqa: BLE001 - a transport bug must not cost the turn
            self.reason = f"crosstalk: Transportfehler ({type(exc).__name__})"
            self._dead = True
            return None
        repo = (data or {}).get("repository")
        if not repo:
            self.reason = "crosstalk: Repository nicht lesbar"
            self._dead = True
            return None
        if not repo.get("hasDiscussionsEnabled"):
            self.reason = "crosstalk: Discussions sind fuer dieses Repo nicht aktiviert"
            self._dead = True
            return None
        self._repo = repo
        return repo

    def _may_post(self, repo: dict) -> bool:
        if repo.get("visibility") == "PRIVATE":
            return True
        if (self.env.get(ENV_PUBLIC) or "").strip() == "1":
            return True
        self.reason = (
            "crosstalk: Repo ist oeffentlich -- kein Post ohne DAEDALUS_CROSSTALK_PUBLIC=1"
        )
        return False

    def _call(self, query: str, variables: dict, what: str) -> dict | None:
        try:
            return self.transport(query, variables)
        except TransportError as exc:
            self.reason = f"crosstalk: {what} fehlgeschlagen ({exc})"
        except Exception as exc:  # noqa: BLE001
            self.reason = f"crosstalk: {what} fehlgeschlagen ({type(exc).__name__})"
        return None

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
        data = self._call(
            _M_CREATE,
            {
                "repo": repo["id"],
                "cat": cat["id"],
                "title": title,
                "body": "Automatischer Crosstalk-Thread der parallelen Claude-Sessions.",
            },
            "Thread anlegen",
        )
        if data is None:
            return None
        new_id = ((data.get("createDiscussion") or {}).get("discussion") or {}).get("id")
        if new_id:
            # keep the local view consistent, so a second post in the same
            # process reuses the thread instead of creating it twice
            nodes = (repo.setdefault("discussions", {"nodes": []})).setdefault("nodes", [])
            nodes.append({"id": new_id, "title": title})
        return new_id

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
        return self._call(_M_COMMENT, {"id": thread, "body": render(note)}, "Post") is not None

    def read(self, thread_title: str, count: int = READ_COMMENTS) -> list[str]:
        if not enabled(self.env):
            self.reason = "crosstalk: aus (DAEDALUS_CROSSTALK != on)"
            return []
        repo = self._repo_facts()
        if repo is None:
            return []
        thread = self._thread_id(repo, thread_title, create=False)
        if thread is None:
            return []
        data = self._call(_Q_READ, {"id": thread, "n": int(count)}, "Lesen")
        if data is None:
            return []
        nodes = (((data.get("node") or {}).get("comments") or {}).get("nodes")) or []
        out: list[str] = []
        for node in nodes:
            who = ((node.get("author") or {}).get("login")) or "?"
            body = [l for l in (node.get("body") or "").strip().splitlines() if l.strip()]
            out.append(f"  [{who}] {body[0] if body else ''}"[:200])
        return out


# --------------------------------------------------------------------------
# what the handlers call
# --------------------------------------------------------------------------


def short_sid(sid: str) -> str:
    return (sid or "unknown").replace("-", "")[:4] or "unknown"


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def threads_for(branch: str) -> list[str]:
    """Which discussions this session speaks in: the global one, plus its own
    branch when it has one. A detached HEAD gets no thread of its own."""
    titles = [GLOBAL_THREAD]
    if branch and branch not in ("detached", "HEAD"):
        titles.append(branch)
    return titles


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


def announce(
    root: Path,
    sid: str,
    branch: str,
    head: str,
    ts: str,
    channel: Channel,
    *,
    do_post: bool,
) -> list[str]:
    """Post the ANMELDUNG (when ``do_post``) and read both threads back.
    Returns ASCII-safe lines for injection. Never raises.

    A switched-off channel says NOTHING. The alternative -- a line reading
    "crosstalk: aus" on every single session start -- is wallpaper, and this
    hook's whole budget discipline exists because wallpaper crowds out the
    lines that matter.
    """
    if not enabled(channel.env):
        return []
    titles = threads_for(branch)
    if do_post:
        dirty = dirty_paths(root)
        lines = ("dirty: " + ", ".join(dirty),) if dirty else ()
        note = Note("ANMELDUNG", short_sid(sid), branch, head, lines, ts)
        for title in titles:
            channel.post(note, title)
    seen: list[str] = []
    for title in titles:
        seen += channel.read(title, READ_COMMENTS)
    if seen:
        return ["CROSSTALK (" + ", ".join(titles) + "):"] + seen[-READ_COMMENTS:]
    if channel.reason:
        return [channel.reason]
    return []


def report(
    root: Path,
    sid: str,
    branch: str,
    head_now: str,
    ts: str,
    state: dict,
    channel: Channel,
) -> None:
    """Post the ERGEBNIS to every thread this session spoke in."""
    head_then = str(state.get("crosstalk_head") or "")
    lines: list[str] = []
    if head_then and head_then != head_now:
        rng = f"{head_then}..{head_now}"
        subjects = git(root, "log", "--format=%s", rng)
        subs = [s for s in str(subjects).splitlines() if s] if subjects.ok else []
        if subs:
            lines.append(f"commits: {len(subs)} ({' | '.join(subs[:3])})")
        names = git(root, "diff", "--name-only", rng)
        if names.ok:
            kept, withheld = redact_paths([n for n in str(names).splitlines() if n])
            lines.append(
                f"geaendert: {len(kept)} Dateien"
                + (f" ({withheld} zurueckgehalten)" if withheld else "")
            )
    if not lines:
        lines.append("keine Commits in dieser Session")
    started = state.get("crosstalk_started")
    if isinstance(started, (int, float)):
        lines.append(f"Dauer: {int((time.time() - started) / 60)} min")
    note = Note(
        "ERGEBNIS",
        short_sid(sid),
        branch,
        f"{head_then or '?'} -> {head_now}",
        tuple(lines),
        ts,
    )
    for title in threads_for(branch):
        channel.post(note, title)


def poll(branch: str, channel: Channel, state: dict, now: float) -> list[str]:
    """New comments for the turn handler. Refetches at most every
    :data:`POLL_TTL_S`; otherwise serves the cached lines. Mutates ``state``
    in place -- call it from inside ``update_state``."""
    if not enabled(channel.env):
        return []
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


# --------------------------------------------------------------------------
# the say CLI
# --------------------------------------------------------------------------

ENTRYPOINT_ID = "daedalus.hooks.crosstalk"
USAGE = 'usage: python -m daedalus.hooks.crosstalk say "<zeile>"'


def main(argv: list[str] | None = None) -> int:
    """``python -m daedalus.hooks.crosstalk say "..."`` -- one line, written by
    the model, into this branch's threads.

    Exit code is always 0: this is a courtesy channel, and a failed post must
    not fail whatever command sequence the model was running.
    """
    argv = list(sys.argv if argv is None else argv)
    try:
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            ENTRYPOINT_ID,
            REGISTRY_BY_ID[ENTRYPOINT_ID].effects,
            (process_guard_boundary_decision(),),
        )
    except Exception as exc:  # noqa: BLE001 - a refusal is reported, never raised
        print(f"[crosstalk] effect boundary refused or unavailable: {exc}", file=sys.stderr)
        return 0
    if len(argv) < 3 or argv[1] != "say" or not str(argv[2]).strip():
        print(USAGE, file=sys.stderr)
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    branch = str(git(root, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    head = str(git(root, "rev-parse", "--short", "HEAD")).strip()
    sid = os.environ.get("CLAUDE_SESSION_ID") or "cli"
    channel = Channel(root)
    note = Note("SAGT", short_sid(sid), branch, head, (str(argv[2]).strip(),), now_iso())
    posted = False
    for title in threads_for(branch):
        posted = channel.post(note, title) or posted
    if not posted:
        print("[crosstalk] " + (channel.reason or "nicht gepostet"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
