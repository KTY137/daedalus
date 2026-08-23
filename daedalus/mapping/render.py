"""mapping/render.py -- ``daedalus map``: the architecture artifact itself.

WHY THIS COMMAND EXISTS
-----------------------
A hand-written feature inventory listed 136 features, 8 islands and 2 dark
switches. Six hours later a nine-agent deep read of the same tree found 827, 55
and 51. The hand-written artifact was not wrong when it was written. It went
stale immediately, and nobody could tell -- which is the part that matters,
because ``daedalus/spine/picker.py`` reads that file as the two highest-priority
bands of the self-improvement work queue.

So the artifact is split in half and only one half is ever hand-maintained:

  * The MECHANICAL half is REGENERATED WHOLESALE on every run -- what exists,
    what reaches it, what is dark, what is an island, and the counts. It comes
    from :mod:`daedalus.mapping.reach`, :mod:`daedalus.mapping.switches` and
    :mod:`daedalus.mapping.drift`. A derived number cannot go stale; at worst
    the page is old, and the staleness stamp says exactly how old.
  * The NARRATIVE half is hand-written and lives in
    ``docs/architecture-narrative.md``: the invariants, the reversals, the
    kitchen-hierarchy mapping, the per-area prose. No scanner derives WHY
    ``reap_branches`` must not delete inside a ``finally`` block, and a
    generator that pretended to would simply be inventing.

REGENERATION MUST NOT EAT THE PROSE. That is the whole design point of reading
the narrative from a separate file rather than from the previous HTML: the
generator never parses its own output, so it can never lose what a human wrote
into it. If the narrative file is missing, every narrative section renders with
an explicit ABSENT marker rather than silently vanishing -- a section that
quietly disappears is indistinguishable from a section nobody ever wrote.

ONE WALK
--------
:func:`analyse_once` runs the reachability engine and the switch engine exactly
once per invocation, and the SAME two reports are handed to the page, to the
gate and to the re-baseline. This is a correctness property, not tidiness:
while they were separate calls the gate ran its own scanners and reported
eleven islands where the page reported six, sharing not one member -- and this
file printed prose "explaining" the gap with a reason that predicted the gate's
number would be the smaller one. Where the two halves still report different
numbers (:func:`_reconciliation`) the difference is now a subtraction over one
list, computed and displayed, never asserted in prose that can go stale.

THE STALENESS STAMP, AND WHAT IT IS ALLOWED TO CLAIM
----------------------------------------------------
Generated-at, git revision, branch, whether the tree was dirty, and HOW MANY OF
THE FILES THE SCANNER ACTUALLY READ ARE TRACKED BY GIT. The last one is not
decoration. ``git status`` answers "what changed among the things git watches";
a file hidden by ``.git/info/exclude``, a global excludesfile or
``assume-unchanged`` is invisible to it and completely visible to a filesystem
walk, so the page could count a module and a switch that are in no revision
while stamping itself "tree clean". The stamp therefore says what it verified:
it claims to describe a revision only when the tree is clean AND every scanned
module is tracked, and otherwise says it describes what was on disk.

The revision is read straight out of ``.git`` (HEAD, refs, packed-refs) with no
subprocess, so it works in a bare checkout and in tests; only the dirty and
tracked probes shell out, and both degrade to "unknown" rather than failing.

MODES
-----
``daedalus map``            render the HTML and re-baseline the snapshot. The
                            drift against the PREVIOUS snapshot is printed
                            first: re-baselining is Tier 2 acceptance from
                            :mod:`~daedalus.mapping.drift`, and Tier 2 only
                            works if a human sees the number move.
``daedalus map --json``     the same payload, machine-readable, writes nothing.
``daedalus map --check``    gate mode. Compares, prints, exits non-zero on
                            unaccepted drift, writes nothing.
``daedalus map --accept``   record a dated acceptance in the snapshot. It
                            INHERITS the mechanical lists rather than
                            rescanning, so it verifies the digest covering them
                            first and refuses on a mismatch -- re-signing
                            hand-edited bytes would launder them into a valid
                            baseline, which is worse than having no verb.

COST: THIS IS A CI GATE, NOT A PRE-COMMIT HOOK. A run rebuilds the structural
index and parses every Python file in the tree twice, which is tens of seconds
on this repo -- the index rebuild alone is most of it. Wired into pre-commit it
would be bypassed with ``--no-verify`` inside a week, and a gate people route
around is worse than no gate, because it also carries a claim of safety.

A MISSING SNAPSHOT FAILS, EVERYWHERE. Gate mode writes nothing, so it cannot
establish the baseline it is missing, and a gate that reports OK while
comparing against nothing is the failure this whole subsystem exists to
prevent. ``--check`` exits non-zero and says which command to run;
``python -m daedalus.mapping.drift`` now does the same, so ``rm
docs/architecture-state.json`` is not a green run through either door.

EVERYTHING RENDERED IS ESCAPED. Module docstrings, acceptance prose and the
narrative file are all agent-authored text, and an architecture page that
executes what an agent wrote into a docstring is a worse problem than a stale
inventory.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "daedalus.mapping.render/1"

MAP_REL = "docs/architecture-map.html"
NARRATIVE_REL = "docs/architecture-narrative.md"

# The status vocabulary, carried over VERBATIM from the hand-built page so the
# generated map and anything still written by hand cannot drift into two
# dialects for the same nine words. (slug, label, meaning).
STATUS_VOCAB: tuple[tuple[str, str, str], ...] = (
    ("wired", "wired",
     "Reachable from a CLI, a route, the UI, or another running module."),
    ("dark", "dark",
     "Built and wired, but OFF by default -- a flag or an env variable holds "
     "it shut."),
    ("island", "island",
     "Built, usually tested, and nothing calls it."),
    ("shim", "shim",
     "A backwards-compatible forward to the real location."),
    ("baseline", "baseline",
     "A placeholder that is honest about being one."),
    ("stale", "stale",
     "Superseded, dead, or a build artifact that outlived its build."),
    ("planned", "spec only",
     "Specification, zero code."),
    ("broken", "broken",
     "Exists, gets called, does not work."),
    ("unknown", "unknown",
     "Status not determinable -- listed here so it is not forgotten."),
)

# How the reachability engine's seven classes are painted in that vocabulary.
# ``orphan`` and ``test`` have no hand-written counterpart, so they borrow a
# colour and keep their own name rather than being flattened into "island":
# an orphan imports nothing AND is imported by nothing AND has no test, which
# is a strictly different remedy from an island's.
CLASS_STATUS: dict[str, str] = {
    "entry": "wired",
    "reachable": "wired",
    "island": "island",
    "orphan": "island",
    "shim": "shim",
    "unknown": "unknown",
    "test": "baseline",
}

CLASS_MEANING: dict[str, str] = {
    "entry": "a way in: a console script, a __main__, a main guard, a CLI "
             "branch, an HTTP route, or a bus handler",
    "reachable": "reached from an entry point through the import graph",
    "island": "nothing reaches it except its own tests",
    "orphan": "imports nothing, imported by nothing, no test names it",
    "shim": "a re-export forwarding to the real module",
    "unknown": "unreached, but named as a string literal somewhere that could "
               "load it -- evidence recorded, verdict withheld",
    "test": "a test module; reached by pytest, not by the import graph",
}

# Narrative sections the page has a place for. A key that is absent from the
# file is rendered as ABSENT rather than skipped.
NARRATIVE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("state", "The one-paragraph state"),
    ("reading", "How to read this map"),
    ("kitchen", "The kitchen -- roles and their real counterparts"),
    ("areas", "The areas"),
    ("reversals", "The reversals"),
    ("drift", "Drift, evidenced by hand"),
    ("blockers", "What is blocking right now"),
    ("invariants", "The invariants"),
)

_SECTION_KEY_RE = re.compile(r"\{#([A-Za-z0-9_-]+)\}\s*$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", str(text).lower()).strip("-") or "x"


# --------------------------------------------------------------------------
# staleness stamp
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Stamp:
    """When, from what, and how clean. Every field degrades to a string that
    says it does not know, because a stamp that raises stops the map from being
    written at all -- and no map is worse than an honestly-unsure one."""

    generated_at: str
    revision: str = "unknown"
    branch: str = "unknown"
    dirty: str = "unknown"          # clean | dirty | unknown
    dirty_paths: int = -1           # -1 => not determined
    # Modules the SCANNER read that git does not track. `git status` reports
    # what git knows about; a file hidden by .git/info/exclude, a global
    # excludesfile or assume-unchanged is invisible to it and fully visible to
    # a filesystem walk. -1 => not determined.
    untracked_scanned: int = -1
    untracked_sample: tuple[str, ...] = ()

    @property
    def short(self) -> str:
        return self.revision[:12] if self.revision != "unknown" else "unknown"

    @property
    def describes_revision(self) -> bool:
        """May this page be read as "the architecture at ``revision``"?

        Only when git says the tree is clean AND every module the scanner
        actually read is tracked. Both halves are needed: the first was the
        whole claim before, and it is checkable in a way that says nothing
        about the files git was told to ignore."""
        return self.dirty == "clean" and self.untracked_scanned == 0

    def to_dict(self) -> dict:
        return {"generated_at": self.generated_at, "revision": self.revision,
                "revision_short": self.short, "branch": self.branch,
                "dirty": self.dirty, "dirty_paths": self.dirty_paths,
                "untracked_scanned": self.untracked_scanned,
                "untracked_sample": list(self.untracked_sample),
                "describes_revision": self.describes_revision}

    def one_line(self) -> str:
        n = f" ({self.dirty_paths} paths)" if self.dirty == "dirty" and self.dirty_paths >= 0 else ""
        u = ""
        if self.untracked_scanned > 0:
            u = f" - {self.untracked_scanned} scanned modules untracked"
        elif self.untracked_scanned < 0:
            u = " - tracked-ness of the scanned files unverified"
        return (f"generated {self.generated_at} - rev {self.short} on "
                f"{self.branch} - working tree {self.dirty}{n}{u}")


def _git_dir(repo_root: Path) -> Path | None:
    """``.git`` is a directory in a normal checkout and a FILE holding
    ``gitdir: <path>`` inside a linked worktree, which this repo creates on
    every ``daedalus improve`` attempt."""
    candidate = repo_root / ".git"
    if candidate.is_dir():
        return candidate
    if candidate.is_file():
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        for line in text.splitlines():
            if line.startswith("gitdir:"):
                p = Path(line.split(":", 1)[1].strip())
                if not p.is_absolute():
                    p = (repo_root / p).resolve()
                return p if p.is_dir() else None
    return None


def _common_dir(git_dir: Path) -> Path | None:
    """The directory shared refs live in. Inside a LINKED worktree ``git_dir``
    is ``<main>/.git/worktrees/<name>``, which holds only HEAD, the index and
    worktree-local state; ``refs/heads/*`` and ``packed-refs`` live in the main
    repository, named by the ``commondir`` file (relative to ``git_dir``).
    MEASURED 2026-08-23: every inventory regenerated from the agent_env_g0
    worktree recorded ``head: unknown`` because this was read from the wrong
    directory, and the committed artifact could not say which tree it scanned.
    """
    try:
        text = (git_dir / "commondir").read_text(encoding="utf-8",
                                                 errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    common = Path(text)
    if not common.is_absolute():
        common = (git_dir / common).resolve()
    return common if common.is_dir() else None


def _resolve_ref(git_dir: Path, ref: str) -> str:
    places = [git_dir]
    common = _common_dir(git_dir)
    if common is not None and common != git_dir:
        places.append(common)
    for place in places:
        loose = place / ref
        try:
            if loose.is_file():
                return loose.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            pass
    for place in places:
        try:
            packed = (place / "packed-refs").read_text(encoding="utf-8",
                                                       errors="replace")
        except OSError:
            continue
        for line in packed.splitlines():
            if line.startswith(("#", "^")):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0].strip()
    return "unknown"


def _head(repo_root: Path) -> tuple[str, str]:
    git_dir = _git_dir(repo_root)
    if git_dir is None:
        return "unknown", "unknown"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8",
                                            errors="replace").strip()
    except OSError:
        return "unknown", "unknown"
    if head.startswith("ref:"):
        ref = head[4:].strip()
        branch = ref.split("refs/heads/", 1)[-1] if "refs/heads/" in ref else ref
        return _resolve_ref(git_dir, ref), branch
    if re.fullmatch(r"[0-9a-f]{7,40}", head):
        return head, "(detached)"
    return "unknown", "unknown"


def _dirty(repo_root: Path) -> tuple[str, int]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(repo_root),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown", -1
    if proc.returncode != 0:
        return "unknown", -1
    lines = [l for l in proc.stdout.decode("utf-8", "replace").splitlines() if l.strip()]
    return ("dirty" if lines else "clean"), len(lines)


def _untracked(repo_root: Path, scanned: Sequence[str]) -> tuple[int, tuple[str, ...]]:
    """How many of the files the SCANNER read are unknown to git.

    ``git status --porcelain`` answers "what changed among the things git is
    watching". It is silent about a file excluded via ``.git/info/exclude``, a
    global ``core.excludesfile`` or ``assume-unchanged`` -- and the scanner
    reads the filesystem, so such a file is fully present in every count on
    this page while the stamp says "clean". Asking ``ls-files`` what is
    TRACKED, and subtracting, is the only version of this claim that is
    verified rather than assumed.
    """
    if not scanned:
        return -1, ()
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"], cwd=str(repo_root),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return -1, ()
    if proc.returncode != 0:
        return -1, ()
    tracked = {p.replace("\\", "/") for p in
               proc.stdout.decode("utf-8", "replace").split("\0") if p}
    if not tracked:
        return -1, ()
    missing = sorted(m for m in scanned if m not in tracked)
    return len(missing), tuple(missing[:8])


def git_stamp(repo_root, *, now: datetime | None = None,
              probe_dirty: bool = True,
              scanned: Sequence[str] | None = None) -> Stamp:
    root = Path(repo_root)
    moment = now or datetime.now(timezone.utc)
    revision, branch = _head(root)
    dirty, count = _dirty(root) if probe_dirty else ("unknown", -1)
    untracked, sample = (_untracked(root, scanned) if probe_dirty and scanned
                         else (-1, ()))
    return Stamp(generated_at=moment.strftime("%Y-%m-%d %H:%M:%SZ"),
                 revision=revision, branch=branch, dirty=dirty,
                 dirty_paths=count, untracked_scanned=untracked,
                 untracked_sample=sample)


# --------------------------------------------------------------------------
# the narrative half
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class NarrativeSection:
    key: str
    title: str
    body: str


@dataclass(frozen=True)
class Narrative:
    path: str
    present: bool
    sections: tuple[NarrativeSection, ...] = ()
    problem: str = ""

    def get(self, key: str) -> NarrativeSection | None:
        for s in self.sections:
            if s.key == key:
                return s
        return None

    @property
    def missing(self) -> tuple[str, ...]:
        have = {s.key for s in self.sections}
        return tuple(k for k, _ in NARRATIVE_SECTIONS if k not in have)

    @property
    def extra(self) -> tuple[NarrativeSection, ...]:
        known = {k for k, _ in NARRATIVE_SECTIONS}
        return tuple(s for s in self.sections if s.key not in known)

    def to_dict(self) -> dict:
        return {"path": self.path, "present": self.present,
                "problem": self.problem,
                "sections": [{"key": s.key, "title": s.title,
                              "chars": len(s.body)} for s in self.sections],
                "missing": list(self.missing)}


def parse_narrative(text: str, path: str = NARRATIVE_REL) -> Narrative:
    """Split the hand-written file on ``## `` headings.

    A section is addressed by an explicit ``{#key}`` suffix on its heading
    rather than by matching its wording, so the prose can be retitled, rewritten
    or translated without silently detaching itself from the slot it renders
    into. A heading with no key still renders -- under "further narrative" --
    because dropping a section somebody wrote is the one behaviour this file
    must never have.
    """
    sections: list[NarrativeSection] = []
    key = title = None
    buf: list[str] = []

    def flush() -> None:
        if key is None:
            return
        sections.append(NarrativeSection(key=key, title=title or key,
                                         body="\n".join(buf).strip()))

    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("###"):
            flush()
            buf = []
            heading = line[3:].strip()
            m = _SECTION_KEY_RE.search(heading)
            if m:
                key = m.group(1)
                title = heading[:m.start()].strip()
            else:
                key = "extra-" + _slug(heading)
                title = heading
        elif key is not None:
            buf.append(line)
    flush()
    return Narrative(path=path, present=True, sections=tuple(sections))


def load_narrative(path) -> Narrative:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Narrative(path=str(p), present=False,
                         problem="file does not exist")
    except OSError as exc:
        return Narrative(path=str(p), present=False, problem=str(exc))
    return parse_narrative(text, path=str(p))


# --------------------------------------------------------------------------
# a very small markdown subset, rendered safely
# --------------------------------------------------------------------------

_INLINE_CODE = re.compile(r"`([^`]+)`")
_INLINE_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _inline(text: str) -> str:
    """Escape FIRST, then apply inline markup.

    Order is the whole safety argument: after escaping there is no ``<`` left in
    the string, so every tag in the result is one this function put there. The
    narrative file is hand-written but the prose inside it was gathered by
    agents, and agent-authored text is untrusted input.
    """
    out = esc(text)
    out = _INLINE_CODE.sub(lambda m: "<code>" + m.group(1) + "</code>", out)
    out = _INLINE_BOLD.sub(lambda m: "<strong>" + m.group(1) + "</strong>", out)
    return out


def _md_blocks(body: str) -> list[tuple[str, Any]]:
    blocks: list[tuple[str, Any]] = []
    lines = body.splitlines()
    i = 0
    para: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(("p", " ".join(para).strip()))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_para()
            i += 1
            continue
        if stripped.startswith("#### "):
            flush_para()
            blocks.append(("h4", stripped[5:].strip()))
            i += 1
            continue
        if stripped.startswith("### "):
            flush_para()
            blocks.append(("h3", stripped[4:].strip()))
            i += 1
            continue
        if stripped.startswith("> "):
            flush_para()
            quote = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                quote.append(lines[i].strip()[2:])
                i += 1
            blocks.append(("quote", " ".join(quote)))
            continue
        if stripped.startswith("| "):
            flush_para()
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set("-: ") and c for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", (rows[0], rows[1:])))
            continue
        if stripped.startswith(("- ", "* ")):
            flush_para()
            items: list[str] = []
            while i < len(lines):
                cur = lines[i].strip()
                if cur.startswith(("- ", "* ")):
                    items.append(cur[2:].strip())
                elif cur and items and lines[i].startswith(("  ", "\t")):
                    items[-1] += " " + cur
                else:
                    break
                i += 1
            blocks.append(("ul", items))
            continue
        para.append(stripped)
        i += 1
    flush_para()
    return blocks


def _render_md(body: str) -> str:
    out: list[str] = []
    for kind, payload in _md_blocks(body):
        if kind == "p":
            out.append(f"<p>{_inline(payload)}</p>")
        elif kind == "h3":
            out.append(f"<h3>{_inline(payload)}</h3>")
        elif kind == "h4":
            out.append(f"<h4>{_inline(payload)}</h4>")
        elif kind == "quote":
            out.append(f'<p class="lede">{_inline(payload)}</p>')
        elif kind == "ul":
            items = "".join(f"<li>{_inline(x)}</li>" for x in payload)
            out.append(f'<ul class="plain">{items}</ul>')
        elif kind == "table":
            head, rows = payload
            th = "".join(f"<th>{_inline(c)}</th>" for c in head)
            body_rows = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                for r in rows)
            out.append(f'<div class="tw"><table class="feat"><thead><tr>{th}'
                       f"</tr></thead><tbody>{body_rows}</tbody></table></div>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# the mechanical half
# --------------------------------------------------------------------------

def analyse_once(repo_root, index=None):
    """The single walk of the tree. Returns ``(reach report, switch report)``.

    Extracted so that ONE analysis can serve the page, the gate and the
    re-baseline inside a single ``daedalus map`` run. When they were three
    calls they were also three chances to disagree, and they took them: the
    page reported six islands while the gate on the same page reported eleven,
    with not one member in common.
    """
    from . import reach as reach_mod
    from . import switches as switches_mod

    root = Path(repo_root).resolve()
    if index is None:
        try:
            from daedalus.structcore import cached_index
            # refresh=True on purpose. ``cached_index`` memoises per process,
            # and this map's whole value is that it describes the tree NOW --
            # a map served from an index some earlier caller in this process
            # warmed would be exactly the silently-stale artifact the command
            # exists to replace. The on-disk cache is content-keyed, so the
            # rebuild is still cheap.
            index = cached_index(str(root), refresh=True)
        except Exception:
            index = None
    return reach_mod.analyse(root, index=index), switches_mod.analyse(root)


def build(repo_root, *, index=None, narrative_path=None, snapshot_path=None,
          today: date | None = None, stamp: Stamp | None = None,
          probe_dirty: bool = True, reports=None) -> dict:
    """Derive the whole payload. PURE with respect to the repository: it reads
    the tree, the snapshot and the narrative, and writes nothing."""
    from . import drift as drift_mod
    from .reach import CLASSES as reach_classes

    root = Path(repo_root).resolve()
    narr_path = Path(narrative_path) if narrative_path else root / NARRATIVE_REL
    snap_path = Path(snapshot_path) if snapshot_path else root / drift_mod.SNAPSHOT_REL

    reach_report, switch_report = reports or analyse_once(root, index)
    drift_report = drift_mod.check(root, snap_path, today=today, index=index,
                                   write_missing=False,
                                   reach_report=reach_report,
                                   switch_report=switch_report,
                                   probe_dirty=probe_dirty)
    narrative = load_narrative(narr_path)
    scanned = [m.module for m in reach_report.modules]
    the_stamp = stamp or git_stamp(root, probe_dirty=probe_dirty, scanned=scanned)

    return {
        "schema": SCHEMA,
        "root": str(root),
        "stamp": the_stamp.to_dict(),
        "counts": {
            "modules": len(reach_report.modules),
            **{k: int(reach_report.counts.get(k, 0)) for k in reach_classes},
            "entry_points": len(reach_report.entry_points),
            "broken_entries": len(reach_report.broken_entries),
            "env_switches": switch_report.counts.env_switches,
            "dark_env_switches": switch_report.counts.dark_env,
            "param_switches": switch_report.counts.param_switches,
            "dark_params": switch_report.counts.dark_params,
            "doc_drift": switch_report.counts.drift,
            # The gate's own view, so --json carries both numbers and the
            # difference between them is arithmetic rather than an assertion.
            "gate_islands": len(drift_report.state.get("islands", [])),
            "gate_unknown": len(drift_report.state.get("unknown", [])),
            "gate_shims": len(drift_report.state.get("shims", [])),
            # The honest total. islands alone is a SUBSET of the modules
            # nothing reaches, and printing only that subset is what let an
            # unwired module sit on disk behind a green gate.
            "gate_unreached": (len(drift_report.state.get("islands", []))
                               + len(drift_report.state.get("unknown", []))
                               + len(drift_report.state.get("shims", []))),
            "gate_test_only": len(drift_report.state.get("test_only", [])),
            "gate_dark_switches": len(drift_report.state.get("dark_switches", [])),
            "gate_index_extra_edges": len(
                drift_report.state.get("index_extra_edges", [])),
        },
        "reach": reach_report.to_dict(),
        "switches": switch_report.to_dict(),
        "gate": {
            "ok": drift_report.ok,
            "first_run": drift_report.first_run,
            "snapshot_path": drift_report.snapshot_path,
            "snapshot_exists": snap_path.is_file(),
            "state": drift_report.state,
            "counts": drift_report.counts,
            "items": [i.as_dict() for i in drift_report.items],
            "blocking": len(drift_report.blocking),
            "text": drift_report.render(),
        },
        "narrative": narrative.to_dict(),
    }


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------

_THEME_VARS_LIGHT = """
  --ground:#f6f4ef; --surface:#fffefb; --sunk:#efece5;
  --ink:#171c22; --ink-2:#454e58; --muted:#6d7681;
  --rule:#ddd8ce; --rule-2:#c9c3b6;
  --accent:#2f7565; --accent-soft:#e2efeb;
  --wired:#2f7565; --dark:#8a6d1f; --island:#a8571f; --stale:#8a8175;
  --shim:#6b7480; --baseline:#6b7480; --planned:#5b5091; --broken:#a52f28;
  --unknown:#7a6f5f;
"""

_THEME_VARS_DARK = """
  --ground:#0e1216; --surface:#151b21; --sunk:#111820;
  --ink:#e6e4de; --ink-2:#b3bac2; --muted:#8a939d;
  --rule:#242d36; --rule-2:#33404b;
  --accent:#63b39d; --accent-soft:#15302a;
  --wired:#63b39d; --dark:#d0a53f; --island:#e08a4a; --stale:#8a8175;
  --shim:#8794a1; --baseline:#8794a1; --planned:#9b90d4; --broken:#e2685e;
  --unknown:#a9998a;
"""

# The theme toggle stamps data-theme on <html>, and BOTH data-theme rules are
# emitted so the toggle wins in either direction: a viewer whose OS says dark
# must be able to force light, which a bare prefers-color-scheme block cannot do.
_CSS = """
:root {__LIGHT__
  --mono:ui-monospace,"Cascadia Mono","SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
@media (prefers-color-scheme:dark) { :root {__DARK__} }
:root[data-theme="dark"] {__DARK__}
:root[data-theme="light"] {__LIGHT__}
* { box-sizing:border-box; }
body { margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:16px; line-height:1.65;
  -webkit-font-smoothing:antialiased; }
.wrap { max-width:1180px; margin:0 auto; padding:0 24px 96px; }
.prose { max-width:74ch; }
h1,h2,h3,h4 { text-wrap:balance; line-height:1.2; margin:0; }
h1 { font-size:clamp(28px,4.4vw,44px); letter-spacing:-.02em; font-weight:650; }
h2 { font-size:22px; letter-spacing:-.01em; margin:64px 0 6px; font-weight:650; }
h3 { font-size:15px; font-weight:650; margin:22px 0 6px; }
h4 { font-size:12px; text-transform:uppercase; letter-spacing:.09em;
     color:var(--muted); font-weight:600; margin:20px 0 8px; }
p { margin:0 0 14px; }
code { font-family:var(--mono); font-size:.86em; overflow-wrap:anywhere; }
header { border-bottom:1px solid var(--rule); padding:56px 0 32px; }
.eyebrow { font-family:var(--mono); font-size:11.5px; letter-spacing:.16em;
  text-transform:uppercase; color:var(--accent); margin:0 0 14px; }
.lede { font-size:19px; line-height:1.5; color:var(--ink-2);
  border-left:2px solid var(--accent); padding-left:18px; margin:24px 0 0;
  max-width:74ch; }
.stampbar { font-family:var(--mono); font-size:12px; color:var(--muted);
  margin-top:22px; display:flex; flex-wrap:wrap; gap:6px 18px;
  align-items:center; }
.stampbar b { color:var(--ink-2); font-weight:600; }
.warnbar { border-left:2px solid var(--broken); background:var(--surface);
  padding:10px 14px; margin-top:14px; font-size:13px; color:var(--ink-2);
  max-width:80ch; }
.counts { display:flex; flex-wrap:wrap; gap:8px; margin:26px 0 0; }
.ct { background:var(--surface); border:1px solid var(--rule);
  border-top:2px solid currentColor; border-radius:2px; padding:9px 13px;
  display:flex; align-items:baseline; gap:7px; }
.ct b { font-size:19px; font-variant-numeric:tabular-nums; color:var(--ink); }
.ct span { font-size:11.5px; color:var(--muted); }
.legend { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr));
  gap:2px 26px; margin:14px 0 0; }
.lg { display:flex; gap:11px; align-items:baseline; padding:5px 0;
  font-size:13.5px; color:var(--ink-2); }
.lg .chip { flex:0 0 auto; }
.chip { font-family:var(--mono); font-size:10.5px; letter-spacing:.05em;
  text-transform:uppercase; padding:2px 7px; border-radius:2px;
  border:1px solid currentColor; white-space:nowrap; font-weight:600; }
.s-wired { color:var(--wired); } .s-dark { color:var(--dark); }
.s-island { color:var(--island); } .s-stale { color:var(--stale); }
.s-shim { color:var(--shim); } .s-baseline { color:var(--baseline); }
.s-planned { color:var(--planned); } .s-broken { color:var(--broken); }
.s-unknown { color:var(--unknown); }
.chip.s-broken, .chip.s-planned { background:var(--accent-soft); }
.tw { overflow-x:auto; max-width:100%; }
table.feat { width:100%; border-collapse:collapse; font-size:14px; }
table.feat th { text-align:left; font-size:11px; font-weight:600;
  text-transform:uppercase; letter-spacing:.09em; color:var(--muted);
  border-bottom:1px solid var(--rule-2); padding:0 12px 7px 0;
  white-space:nowrap; }
table.feat td { border-bottom:1px solid var(--rule);
  padding:11px 12px 11px 0; vertical-align:top; }
table.feat td.mono { font-family:var(--mono); font-size:12px; }
.reach { font-size:11.5px; color:var(--muted); margin-top:3px;
  font-family:var(--mono); overflow-wrap:anywhere; }
.note { font-size:12.5px; color:var(--muted); margin-top:3px; line-height:1.5; }
details.area { border:1px solid var(--rule); border-radius:2px;
  background:var(--surface); margin-bottom:8px; }
details.area summary { cursor:pointer; padding:15px 20px; display:flex;
  align-items:center; gap:14px; flex-wrap:wrap; list-style:none; }
details.area summary::-webkit-details-marker { display:none; }
details.area summary::before { content:"+"; font-family:var(--mono);
  color:var(--accent); font-size:15px; width:12px; flex:0 0 auto; }
details.area[open] summary::before { content:"\\2212"; }
details.area[open] summary { border-bottom:1px solid var(--rule); }
.a-name { font-weight:600; font-size:14.5px; flex:1 1 300px; }
.a-count { font-family:var(--mono); font-size:12px; color:var(--muted);
  font-variant-numeric:tabular-nums; }
details.area .tw, details.area .sub { padding:0 20px 18px; }
.sub { padding:0 20px 18px; font-size:13.5px; color:var(--ink-2); }
ul.plain { padding-left:20px; margin:0 0 14px; }
ul.plain li { margin-bottom:9px; }
.absent { border-left:2px solid var(--planned); background:var(--surface);
  padding:14px 18px; margin:14px 0; font-size:13.5px; color:var(--ink-2);
  max-width:80ch; }
.gate-ok { color:var(--wired); } .gate-bad { color:var(--broken); }
pre.gate { background:var(--surface); border:1px solid var(--rule);
  border-left:2px solid var(--rule-2); border-radius:2px; padding:16px 18px;
  font-family:var(--mono); font-size:12px; line-height:1.6; color:var(--ink-2);
  overflow-x:auto; max-width:100%; white-space:pre; }
nav.toc { display:flex; flex-wrap:wrap; gap:6px 16px; font-family:var(--mono);
  font-size:11.5px; margin-top:18px; }
nav.toc a { color:var(--muted); text-decoration:none;
  border-bottom:1px solid var(--rule); }
nav.toc a:hover { color:var(--accent); }
#themetoggle { font-family:var(--mono); font-size:11px; cursor:pointer;
  background:var(--surface); color:var(--muted); border:1px solid var(--rule);
  border-radius:2px; padding:3px 9px; }
.foot { margin-top:72px; padding-top:22px; border-top:1px solid var(--rule);
  font-size:12.5px; color:var(--muted); max-width:80ch; }
summary:focus-visible, details:focus-visible, #themetoggle:focus-visible {
  outline:2px solid var(--accent); outline-offset:2px; }
@media (prefers-reduced-motion:reduce) { * { transition:none !important; } }
""".replace("__LIGHT__", _THEME_VARS_LIGHT).replace("__DARK__", _THEME_VARS_DARK)

_TOGGLE_JS = """
(function () {
  var root = document.documentElement;
  var btn = document.createElement("button");
  btn.id = "themetoggle";
  btn.type = "button";
  btn.textContent = "theme";
  btn.setAttribute("aria-label", "toggle light and dark theme");
  btn.addEventListener("click", function () {
    var dark = root.getAttribute("data-theme") === "dark"
      || (!root.getAttribute("data-theme")
          && window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.setAttribute("data-theme", dark ? "light" : "dark");
  });
  var bar = document.getElementById("stampbar");
  if (bar) { bar.appendChild(btn); }
})();
"""


def _chip(status: str, label: str, title: str = "") -> str:
    t = f' title="{esc(title)}"' if title else ""
    return f'<span class="chip s-{esc(status)}"{t}>{esc(label)}</span>'


def _section(key: str, title: str, body: str) -> str:
    return (f'<section id="{esc(key)}">\n<h2>{esc(title)}</h2>\n{body}\n</section>')


def _narrative_section(narrative: Narrative, key: str, title: str) -> str:
    got = narrative.get(key)
    if got is not None and got.body.strip():
        head = esc(got.title or title)
        return (f'<section id="n-{esc(key)}">\n<h2>{head}</h2>\n'
                f'<div class="prose">{_render_md(got.body)}</div>\n</section>')
    if not narrative.present:
        why = (f"the narrative file {esc(narrative.path)} does not exist"
               if not narrative.problem
               else f"the narrative file could not be read: {esc(narrative.problem)}")
    else:
        why = (f"no section carrying <code>{{#{esc(key)}}}</code> in "
               f"{esc(narrative.path)}")
    return (f'<section id="n-{esc(key)}">\n<h2>{esc(title)}</h2>\n'
            f'<p class="absent"><strong>ABSENT</strong> &mdash; {why}. '
            f"This half of the map is hand-written on purpose: no scanner "
            f"derives it, so nothing was generated in its place. It is missing, "
            f"not empty.</p>\n</section>")


def _counts_bar(data: dict) -> str:
    counts = data["counts"]
    cells = [
        ("wired", counts.get("entry", 0), "entry"),
        ("wired", counts.get("reachable", 0), "reachable"),
        ("island", counts.get("island", 0), "island"),
        ("island", counts.get("orphan", 0), "orphan"),
        ("island", counts.get("gate_test_only", 0), "reached only by tests"),
        ("shim", counts.get("shim", 0), "shim"),
        ("unknown", counts.get("unknown", 0), "unknown"),
        ("baseline", counts.get("test", 0), "test"),
        ("dark", counts.get("dark_env_switches", 0), "dark env switches"),
        ("dark", counts.get("dark_params", 0), "dark param gates"),
        ("stale", counts.get("doc_drift", 0), "doc/code drift"),
    ]
    out = [f'<div class="ct s-wired"><b>{counts.get("modules", 0)}</b>'
           f"<span>python modules</span></div>",
           # The headline the page owes the reader: not "islands", which is one
           # of three unreached classes, but every module no entry point gets
           # to. island + orphan + unknown + shim, and the tiles beside it add
           # up to exactly this.
           f'<div class="ct s-island"><b>{esc(counts.get("gate_unreached", 0))}</b>'
           f"<span>unreached (nothing gets here)</span></div>"]
    for status, value, label in cells:
        out.append(f'<div class="ct s-{status}"><b>{esc(value)}</b>'
                   f"<span>{esc(label)}</span></div>")
    return '<div class="counts">' + "".join(out) + "</div>"


def _legend() -> str:
    rows = "".join(
        f'<div class="lg">{_chip(slug, label)}<span>{esc(meaning)}</span></div>'
        for slug, label, meaning in STATUS_VOCAB)
    return f'<div class="legend">{rows}</div>'


def _class_legend() -> str:
    from .reach import CLASSES
    rows = "".join(
        f'<div class="lg">{_chip(CLASS_STATUS.get(c, "unknown"), c)}'
        f'<span>{esc(CLASS_MEANING.get(c, ""))}</span></div>' for c in CLASSES)
    return f'<div class="legend">{rows}</div>'


def _entry_table(data: dict) -> str:
    from .reach import ENTRY_KINDS
    entries = data["reach"]["entry_points"]
    by_kind: dict[str, list[dict]] = {}
    for e in entries:
        by_kind.setdefault(e["kind"], []).append(e)
    out: list[str] = []
    for kind in ENTRY_KINDS:
        rows = by_kind.get(kind, [])
        if not rows:
            continue
        body = "".join(
            f'<tr><td class="mono">{esc(e["name"])}</td>'
            f'<td class="mono">{esc(e["module"])}'
            + (f'<span class="reach">{esc(e["function"])}()</span>'
               if e.get("function") else "")
            + "</td>"
            f'<td class="mono">{esc(", ".join(e["targets"])) or "&mdash;"}</td></tr>'
            for e in rows)
        out.append(
            f'<details class="area"><summary><span class="a-name">{esc(kind)}'
            f'</span><span class="a-count">{len(rows)}</span></summary>'
            f'<div class="tw"><table class="feat"><thead><tr><th>name</th>'
            f"<th>module</th><th>reaches directly</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div></details>")
    return "".join(out)


def _module_table(data: dict) -> str:
    from .reach import CLASSES
    mods = data["reach"]["modules"]
    by_class: dict[str, list[dict]] = {}
    for m in mods:
        by_class.setdefault(m["classification"], []).append(m)
    # The alarms open by default; "reachable" and "test" are the long tail and
    # stay folded, because a page that dumps 88 test files first is a page
    # whose reader never scrolls to the seven islands.
    order = ("island", "orphan", "unknown", "shim", "entry", "reachable", "test")
    out: list[str] = []
    for cls in [c for c in order if c in by_class] + \
               [c for c in CLASSES if c in by_class and c not in order]:
        rows = by_class[cls]
        open_attr = " open" if cls in ("island", "orphan", "unknown", "shim") else ""
        body = []
        for m in rows:
            path = " -> ".join(m["path"]) if m["path"] else ""
            detail = []
            if m.get("entry"):
                detail.append(f'entry {esc(m["entry"])}'
                              + (f' at depth {esc(m["depth"])}'
                                 if m.get("depth") is not None else ""))
            if path:
                detail.append(esc(path))
            if m.get("tested_by"):
                detail.append(f'tested by {esc(", ".join(m["tested_by"]))}')
            if m.get("evidence"):
                detail.append(f'evidence: {esc("; ".join(m["evidence"]))}')
            body.append(
                f'<tr><td class="mono">{esc(m["module"])}</td>'
                f'<td>{_chip(CLASS_STATUS.get(cls, "unknown"), cls)}</td>'
                f'<td>{esc(m.get("reason") or "")}'
                + ("".join(f'<div class="reach">{d}</div>' for d in detail))
                + "</td></tr>")
        out.append(
            f'<details class="area"{open_attr}><summary><span class="a-name">'
            f'{esc(cls)}</span>{_chip(CLASS_STATUS.get(cls, "unknown"), cls)}'
            f'<span class="a-count">{len(rows)}</span></summary>'
            f'<div class="tw"><table class="feat"><thead><tr><th>module</th>'
            f"<th>class</th><th>why / how it is reached</th></tr></thead>"
            f'<tbody>{"".join(body)}</tbody></table></div></details>')
    return "".join(out)


def _test_only_table(data: dict) -> str:
    """Modules whose only importer is a test, as their own class.

    This is the population that used to be silently green. The rule that a
    test counts as intent is kept -- these do not fail the gate -- but the
    consequence of the rule is now a list with a number on it, because "wired
    to nothing but a test" is precisely the state that grew to 55 unnoticed
    the last time it was invisible.
    """
    mods = list(data["gate"]["state"].get("test_only", []))
    facts = {m["module"]: m for m in data["reach"]["modules"]}
    rows = "".join(
        f'<tr><td class="mono">{esc(m)}</td>'
        f'<td class="mono">{esc(", ".join(facts.get(m, {}).get("tested_by", [])))}'
        f"</td></tr>" for m in mods)
    return (
        f'<details class="area"{" open" if mods else ""}>'
        f'<summary><span class="a-name">reached only by their own tests</span>'
        f'{_chip("island", "island")}'
        f'<span class="a-count">{len(mods)}</span></summary>'
        f'<p class="sub">Nothing reaches these from any entry point; a test '
        f'imports them. The gate reports them under <code>TEST ONLY</code> and '
        f'does NOT block on them &mdash; landing a test is evidence somebody '
        f'means to wire the thing, and a gate that fails over that gets turned '
        f'off. It is a count that has to keep moving toward zero, not an '
        f'alarm.</p>'
        f'<div class="tw"><table class="feat"><thead><tr><th>module</th>'
        f"<th>tested by</th></tr></thead><tbody>{rows}</tbody></table></div>"
        f"</details>")


def _broken_entry_table(data: dict) -> str:
    broken = data["reach"]["broken_entries"]
    if not broken:
        return ""
    items = "".join(f"<li><code>{esc(b)}</code></li>" for b in broken)
    return (
        f'<details class="area" open><summary><span class="a-name">'
        f'declared entry points that cannot be taken</span>'
        f'{_chip("broken", "broken")}'
        f'<span class="a-count">{len(broken)}</span></summary>'
        f'<p class="sub">A <code>[project.scripts]</code> target naming a '
        f'module or a function that does not exist. It raises on invocation, '
        f'so it is not a way in and nothing behind it is reached through '
        f'it.</p><div class="sub"><ul class="plain">{items}</ul></div></details>')


def _switch_tables(data: dict) -> str:
    sw = data["switches"]
    out: list[str] = []

    dark = [s for s in sw["env_switches"] if s["dark"]]
    rows = "".join(
        f'<tr><td class="mono">{esc(s["name"])}</td>'
        f'<td>{_chip("dark", s["kind"])}</td>'
        f'<td class="mono">{esc(s["default"])}</td>'
        f'<td class="mono">{esc(", ".join(x["module"] + ":" + str(x["line"]) for x in s["sites"]))}'
        f'</td></tr>' for s in dark)
    out.append(
        f'<details class="area" open><summary><span class="a-name">'
        f'dark environment switches</span>{_chip("dark", "dark")}'
        f'<span class="a-count">{len(dark)}</span></summary>'
        f'<p class="sub">Default off, and no read site falls back to a usable '
        f'value: the code path does not run in normal operation.</p>'
        f'<div class="tw"><table class="feat"><thead><tr><th>name</th>'
        f"<th>kind</th><th>default</th><th>read at</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></details>")

    conflicting = [s for s in sw["env_switches"] if s["conflicting_defaults"]]
    if conflicting:
        rows = "".join(
            f'<tr><td class="mono">{esc(s["name"])}</td>'
            f'<td class="mono">{esc(" vs ".join(s["conflicting_defaults"]))}</td>'
            f'<td class="mono">{esc(", ".join(x["module"] + ":" + str(x["line"]) for x in s["sites"]))}'
            f"</td></tr>" for s in conflicting)
        out.append(
            f'<details class="area" open><summary><span class="a-name">'
            f'conflicting defaults</span>{_chip("broken", "broken")}'
            f'<span class="a-count">{len(conflicting)}</span></summary>'
            f'<p class="sub">The same variable resolves to different values in '
            f'different modules. A status screen can report a setting the '
            f'harness does not run.</p>'
            f'<div class="tw"><table class="feat"><thead><tr><th>name</th>'
            f"<th>defaults</th><th>read at</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></details>")

    dark_params = [p for p in sw["param_switches"] if p["dark"]]
    if dark_params:
        rows = "".join(
            f'<tr><td class="mono">{esc(p["qualname"])}({esc(p["param"])})</td>'
            f'<td class="mono">{esc(p["default"])}</td>'
            f'<td class="mono">{esc(p["module"])}:{esc(p["line"])}</td></tr>'
            for p in dark_params)
        out.append(
            f'<details class="area"><summary><span class="a-name">'
            f'off-by-default parameter gates</span>{_chip("dark", "dark")}'
            f'<span class="a-count">{len(dark_params)}</span></summary>'
            f'<p class="sub">Gate vocabulary only. Safety postures '
            f'(<code>dry_run</code>, <code>force</code>, <code>overwrite</code>) '
            f'are deliberately not counted: <code>force=False</code> is a '
            f'default, not a hidden feature.</p>'
            f'<div class="tw"><table class="feat"><thead><tr><th>callable</th>'
            f"<th>default</th><th>at</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></details>")

    drift_rows = sw["drift"]
    if drift_rows:
        rows = "".join(
            f'<tr><td>{_chip("stale", d["kind"].replace("_", " "))}</td>'
            f'<td class="mono">{esc(d["documented"] or d["read"])}</td>'
            f'<td>{esc(d["detail"])}'
            f'<div class="reach">{esc(", ".join(d["doc_sites"] + d["code_sites"]))}</div>'
            f"</td></tr>" for d in drift_rows)
        out.append(
            f'<details class="area"><summary><span class="a-name">'
            f'doc / code drift</span>{_chip("stale", "stale")}'
            f'<span class="a-count">{len(drift_rows)}</span></summary>'
            f'<div class="tw"><table class="feat"><thead><tr><th>kind</th>'
            f"<th>name</th><th>detail</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div></details>")

    dyn = sw["dynamic_reads"]
    if dyn:
        items = "".join(f"<li><code>{esc(d)}</code></li>" for d in dyn)
        out.append(
            f'<details class="area"><summary><span class="a-name">'
            f'reads the scanner refuses to guess at</span>'
            f'{_chip("unknown", "unknown")}'
            f'<span class="a-count">{len(dyn)}</span></summary>'
            f'<div class="sub"><ul class="plain">{items}</ul></div></details>')
    return "".join(out)


def _reconciliation(data: dict) -> str:
    """The gate's numbers against the table's, computed rather than asserted.

    This block used to be prose explaining why the two halves of the page
    disagreed -- and the explanation predicted the gate's island count would be
    SMALLER than the table's when it was in fact nearly twice as large, because
    the two halves ran different scanners. There is one scanner now, so every
    number below is a subtraction over the same walk and any inconsistency
    here is arithmetic, not interpretation.
    """
    counts = data["counts"]
    gate_state = data["gate"]["state"]
    island_n = counts.get("island", 0)
    orphan_n = counts.get("orphan", 0)
    unknown_n = counts.get("unknown", 0)
    shim_n = counts.get("shim", 0)
    gate_islands = len(gate_state.get("islands", []))
    gate_unknown = len(gate_state.get("unknown", []))
    gate_shims = len(gate_state.get("shims", []))
    gate_unreached = gate_islands + gate_unknown + gate_shims
    gate_edges = len(gate_state.get("index_extra_edges", []))
    test_only = len(gate_state.get("test_only", []))
    dark = counts.get("dark_env_switches", 0)
    gate_dark = len(gate_state.get("dark_switches", []))
    # Broken out rather than lumped together: "the gate drops N" invites the
    # reader to assume one reason, and there are two with different arguments.
    secrets = sum(1 for s in data["switches"]["env_switches"]
                  if s["dark"] and s["kind"] == "secret")
    documented = dark - secrets - gate_dark
    rows = [
        ("UNREACHED, the honest total",
         f"island ({island_n}) + orphan ({orphan_n}) + unknown ({unknown_n}) "
         f"+ shim ({shim_n})",
         f"{gate_unreached}",
         "every module no entry point gets to. The gate used to count only the "
         "first two, so an <code>if False:</code> import, a swallowed "
         "ImportError, a bare string literal naming a module and a new "
         "re-export each left a genuinely unwired file on disk behind a green "
         "run. All four are counted here now, each under its own kind"),
        ("islands",
         f"island ({island_n}) + orphan ({orphan_n})",
         f"{gate_islands}",
         "the gate does not split them: the remedy for both is wire it or "
         "delete it"),
        ("unknown",
         f"{unknown_n}",
         f"{gate_unknown}",
         "nothing reaches it and the scanner refuses to guess. NOT an island: "
         "the remedy is to resolve the ambiguity, not to assume it is dead"),
        ("shims nothing reaches",
         f"{shim_n}",
         f"{gate_shims}",
         "a re-export that forwards for nobody. NOT an island either: the "
         "usual remedy is deleting the forward"),
        ("import edges the two engines disagree about",
         f'{len(data["reach"]["index_extra_edges"])}',
         f"{gate_edges}",
         "the structural index has the edge and the reachability walk refused "
         "it. Reported by both halves, merged into neither: merging them is "
         "how a dead-branch import used to paint its target "
         "<code>reachable</code>"),
        ("of the unreached, reached only by their own tests",
         f"{test_only} of {gate_unreached}",
         f"{test_only}",
         "reported under its own kind and does NOT block &mdash; a test is "
         "evidence somebody means to wire it, and a gate that fails over one "
         "gets switched off"),
        ("dark environment switches",
         f"{dark} dark by the code",
         f"{gate_dark}",
         f"the gate drops {secrets} classified <code>secret</code> (an absent "
         f"API key is an unconfigured feature, not a hidden one) and "
         f"{documented} that a document introduces the way an operator would "
         "set it, with a description, outside a code fence and outside the "
         "file this page generates"),
    ]
    body = "".join(
        f"<tr><td>{esc(label)}</td><td class=\"mono\">{table}</td>"
        f"<td class=\"mono\">{gate}</td><td>{why}</td></tr>"
        for label, table, gate, why in rows)
    return ('<div class="tw"><table class="feat"><thead><tr><th>quantity</th>'
            "<th>this page</th><th>the gate</th><th>why they differ</th>"
            f"</tr></thead><tbody>{body}</tbody></table></div>")


def _limits(data: dict) -> str:
    reach = data["reach"]
    sw = data["switches"]
    bits = [
        "ONE ENGINE. The gate above and the tables on this page are derived "
        "from the SAME reachability walk and the SAME switch scan, computed "
        "once per run. Where a number differs it is a stated subtraction over "
        "one list, shown in the table under &ldquo;the gate against this "
        "page&rdquo;, not two scanners that happen to be close.",
        f'{len(reach["broken_entries"])} declared entry points cannot actually '
        "be taken (a <code>[project.scripts]</code> target naming a module or "
        "function that does not exist). They are listed, never counted as "
        "entry points: <code>entry</code> is the strongest claim here and it is "
        "verified, not believed.",
        f'{len(reach["weak_edges"])} imports exist in the source but are not '
        "evidence that anything runs them (a dead <code>if False:</code> "
        "branch, or a <code>try:</code> whose ImportError is swallowed). They "
        "are excluded from the graph, and nothing puts them back: a module "
        "whose only importers are these is <code>unknown</code> &mdash; never "
        "<code>reachable</code> &mdash; including on runs where a structural "
        "index is supplied, which is every run of <code>daedalus map</code>. "
        "That sentence was false for as long as this page carried it: the "
        "index&rsquo;s edges were unioned into the walk, so a module imported "
        "only under <code>if False:</code> printed <code>reachable</code> on "
        "this very page.",
        "This page maps MODULES, not features. A module holding one live "
        "function and four dead ones is reachable here by construction; "
        "feature-level darkness needs a symbol-level pass this engine does "
        "not do. Any comparison against a feature-level count is comparing "
        "different denominators.",
        f'{len(reach["unparsable"])} python files could not be parsed; '
        f'{len(sw["unparsable"])} could not be parsed by the switch scanner.',
        f'{len(reach["dynamic_surfaces"])} non-literal dynamic-import surfaces '
        f'are recorded rather than resolved.',
        f'{len(reach["index_extra_edges"])} import edges are known to the '
        "structural index and are NOT in this walk &mdash; they are recorded "
        "as a disagreement between two engines and are not counted as "
        "reachability by either half of this page. structcore resolves imports "
        "without branch context, so its edge set includes the ones the walk "
        "withheld on purpose; the gate reports a new one under "
        "<code>ENGINE DISAGREEMENT</code>.",
        "The single largest judgement call is the <code>main_guard</code> "
        "entry kind: a module with a <code>__main__</code> guard is runnable "
        "as <code>python -m</code> and counts as a way in. Drop that rule and "
        "materially more modules go dark. The kind is recorded on every "
        "module so the call can be re-litigated without re-running anything.",
    ]
    return '<ul class="plain">' + "".join(f"<li>{b}</li>" for b in bits) + "</ul>"


def render_html(data: dict, narrative: Narrative) -> str:
    stamp = data["stamp"]
    gate = data["gate"]
    # The stamp says WHEN this ran and WHAT WAS ON DISK. It is allowed to claim
    # "and that is revision X" only when both halves of that claim were checked.
    notes: list[str] = []
    if stamp["dirty"] == "dirty":
        notes.append(
            "The working tree was DIRTY when this page was generated "
            f'({esc(stamp["dirty_paths"])} paths).')
    elif stamp["dirty"] == "unknown":
        notes.append("Whether the working tree was clean could not be determined.")
    if stamp.get("untracked_scanned", -1) > 0:
        sample = ", ".join(stamp.get("untracked_sample") or ())
        notes.append(
            f'{esc(stamp["untracked_scanned"])} of the python files counted on '
            "this page are NOT TRACKED by git, so they are in no revision and "
            "the dirty probe above cannot see them"
            + (f" ({esc(sample)})" if sample else "") + ".")
    elif stamp.get("untracked_scanned", -1) < 0:
        notes.append("Whether the scanned files are tracked by git could not be "
                     "determined.")
    dirty_note = ""
    if notes:
        dirty_note = (
            '<p class="warnbar">' + " ".join(notes) +
            " This page describes WHAT WAS ON DISK when it ran; it is not a "
            f'description of revision {esc(stamp["revision_short"])}.</p>')
    elif stamp.get("describes_revision"):
        dirty_note = (
            '<p class="warnbar">Working tree clean and every scanned file '
            f'tracked: what this page describes is revision '
            f'{esc(stamp["revision_short"])}.</p>')

    gate_line = (
        f'<span class="gate-ok">gate OK</span>' if gate["ok"] and not gate["first_run"]
        else '<span class="gate-bad">no baseline yet</span>' if gate["first_run"]
        else f'<span class="gate-bad">gate FAILING &mdash; {esc(gate["blocking"])} blocking</span>')

    toc_keys = [("generated-half", "generated"), ("entries", "entry points"),
                ("modules", "modules"), ("switches", "switches"),
                ("gate", "gate"), ("limits", "limits")]
    toc_keys += [("n-" + k, t) for k, t in NARRATIVE_SECTIONS]
    toc = "".join(f'<a href="#{esc(k)}">{esc(t)}</a>' for k, t in toc_keys)

    parts: list[str] = []
    parts.append('<title>Daedalus &mdash; architecture map</title>')
    parts.append(f"<style>{_CSS}</style>")
    parts.append('<div class="wrap">')
    parts.append("<header>")
    parts.append('<p class="eyebrow">architecture map &middot; generated</p>')
    parts.append("<h1>Daedalus</h1>")
    parts.append(
        '<p class="lede">The mechanical half of this page is regenerated on '
        "every run and is never hand-maintained; the narrative half is "
        "hand-written in "
        f"<code>{esc(narrative.path)}</code> and survives regeneration "
        "untouched. Numbers below are derived from the tree as it was at the "
        "moment stamped here.</p>")
    parts.append(f'<div class="stampbar" id="stampbar">'
                 f'<span><b>generated</b> {esc(stamp["generated_at"])}</span>'
                 f'<span><b>rev</b> {esc(stamp["revision_short"])}</span>'
                 f'<span><b>branch</b> {esc(stamp["branch"])}</span>'
                 f'<span><b>tree</b> {esc(stamp["dirty"])}</span>'
                 f"<span>{gate_line}</span></div>")
    parts.append(dirty_note)
    parts.append(_counts_bar(data))
    parts.append(f'<nav class="toc">{toc}</nav>')
    parts.append("</header>")

    # --- narrative: the state and the reading guide sit above the tables ----
    parts.append(_narrative_section(narrative, "state", "The one-paragraph state"))
    parts.append(_narrative_section(narrative, "reading", "How to read this map"))

    parts.append(_section(
        "generated-half", "The status vocabulary",
        '<div class="prose"><p>Nine words, carried over unchanged from the '
        "hand-built map so the generated page and anything still written by "
        "hand cannot drift into two dialects.</p></div>" + _legend() +
        '<h4>and the seven classes the reachability engine assigns</h4>' +
        _class_legend()))

    parts.append(_section(
        "entries", "Entry points",
        '<div class="prose"><p>Every way in, DISCOVERED rather than listed: '
        "console scripts from <code>[project.scripts]</code>, "
        "<code>__main__.py</code>, <code>__name__ == \"__main__\"</code> "
        "guards, then the dispatch chains and poll loops found inside modules "
        "that are already runnable. A command table inside a module nothing "
        "can run is not a way in.</p></div>" + _broken_entry_table(data)
        + _entry_table(data)))

    parts.append(_section(
        "modules", "Every module, and what reaches it",
        '<div class="prose"><p>Islands, orphans, unknowns and shims are open; '
        "the reached majority is folded. <em>Unknown</em> means unreached by "
        "the import graph but named as a string literal somewhere that could "
        "load it, or imported only where the import is no proof anything runs "
        "it &mdash; evidence recorded, verdict withheld.</p></div>" +
        _test_only_table(data) + _module_table(data)))

    parts.append(_section(
        "switches", "Switches",
        '<div class="prose"><p>A switch is dark when every read site defaults '
        "it off AND at least one site has no fallback to a usable value. A "
        "variable that is off in one module and defaulted in another is not "
        "dark &mdash; the feature is reachable and the defaults merely "
        "disagree, which is reported separately.</p></div>" +
        _switch_tables(data)))

    parts.append(_section(
        "gate", "The gate",
        '<div class="prose"><p>Compared against the committed snapshot at '
        f'<code>{esc(gate["snapshot_path"])}</code>. This is what '
        "<code>daedalus map --check</code> prints and exits on. The gate reads "
        "the same walk this page does; where a count differs it is the stated "
        "subtraction below, not a second opinion.</p></div>"
        f'<pre class="gate">{esc(gate["text"])}</pre>'
        "<h4>the gate against this page</h4>" + _reconciliation(data)))

    for key, title in NARRATIVE_SECTIONS:
        if key in ("state", "reading"):
            continue
        parts.append(_narrative_section(narrative, key, title))

    for extra in narrative.extra:
        parts.append(
            f'<section id="n-{esc(extra.key)}"><h2>{esc(extra.title)}</h2>'
            f'<div class="prose">{_render_md(extra.body)}</div></section>')

    parts.append(_section("limits", "What this page does not know", _limits(data)))

    parts.append(
        '<p class="foot">Generated by <code>daedalus map</code> '
        f"(<code>{esc(SCHEMA)}</code>). Do not hand-edit this file: the next "
        f"run overwrites it. Prose belongs in <code>{esc(narrative.path)}</code>, "
        "which this generator reads and never writes. The counts, the entry "
        "points, the classes and the switch tables are derived; the "
        "invariants, reversals, kitchen and area prose are not, and no scanner "
        "claims to derive them.</p>")
    parts.append("</div>")
    parts.append(f"<script>{_TOGGLE_JS}</script>")
    return "\n".join(p for p in parts if p) + "\n"


def write_map(path, data: dict, narrative: Narrative) -> str:
    text = render_html(data, narrative)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return text


# --------------------------------------------------------------------------
# acceptance
# --------------------------------------------------------------------------

def accept(repo_root, item: str, why: str, *, until: str = "", since: str = "",
           who: str = "", snapshot_path=None, today: date | None = None) -> tuple[bool, str]:
    """Add one dated acceptance to the snapshot. Returns (ok, message).

    The mechanical lists are carried over from the EXISTING snapshot rather than
    rescanned, so recording an acceptance can never quietly bank unrelated drift
    that happened since the baseline was taken.

    THE INHERITED BYTES ARE VERIFIED BEFORE THEY ARE RE-SIGNED. Inheriting and
    then calling ``write_snapshot`` re-signs whatever it was handed, so this
    verb was a laundry: hand-edit ``islands`` (``--check`` says INVALID
    SNAPSHOT), then run ``--accept`` on any unrelated item, and the hand-edited
    lists come back out under a freshly computed, perfectly valid digest with
    the real finding erased -- three shipped commands, no Python, exit 0. A
    snapshot whose digest does not verify is not something to build on, so this
    refuses and writes nothing. :func:`~daedalus.mapping.drift.refresh` needs no
    such check because it rescans the tree instead of inheriting.
    """
    from . import drift as drift_mod

    root = Path(repo_root).resolve()
    snap_path = Path(snapshot_path) if snapshot_path else root / drift_mod.SNAPSHOT_REL
    today = today or date.today()

    snapshot = drift_mod.load_snapshot(snap_path)
    if snapshot is None:
        return False, (f"no snapshot at {snap_path} -- run `daedalus map` once "
                       f"to record the baseline before accepting anything")
    if snapshot.get("__error__"):
        return False, f"snapshot at {snap_path} is unreadable: {snapshot['__error__']}"
    stored_schema = snapshot.get("schema")
    if stored_schema != drift_mod.SCHEMA_VERSION:
        return False, (
            f"refused: {snap_path} is schema {stored_schema!r} and this build "
            f"writes schema {drift_mod.SCHEMA_VERSION}. Its lists were derived "
            f"by a different engine and do not mean the same thing, so they "
            f"must not be carried forward under a new digest -- re-baseline "
            f"with `daedalus map` first.")
    if not drift_mod.digest_ok(snapshot):
        return False, (
            f"refused: the mechanical lists in {snap_path} do not match the "
            f"digest written with them -- something was hand-edited. Accepting "
            f"an item carries those lists forward VERBATIM and re-signs them, "
            f"which would turn an INVALID SNAPSHOT into a valid one and erase "
            f"whatever the edit was hiding. Nothing was written. Re-baseline "
            f"(`daedalus map`) after checking what changed, then accept.")

    d_since = since or today.isoformat()
    if not until:
        from datetime import timedelta
        try:
            base = date.fromisoformat(d_since)
        except ValueError:
            base = today
        until = (base + timedelta(days=14)).isoformat()

    existing = drift_mod.parse_acceptances(snapshot.get("acceptances"), today=today)
    kept = [a for a in existing if a.item != item]
    # ``today`` matters here too: --accept --since 2999-01-01 --until 2999-03-01
    # is a 59-day horizon and satisfies the cap. It has to be refused at the
    # door, not only when the gate later reads it back.
    candidate = drift_mod.parse_acceptances(
        [{"item": item, "why": why, "since": d_since, "until": until,
          "who": who}], today=today)[0]
    if not candidate.valid:
        return False, f"refused: {candidate.problem}"

    acceptances = sorted(kept + [candidate],
                         key=lambda a: (a.item, a.until, a.since))
    # Carried over from the snapshot VERBATIM, including the ignore
    # configuration it was taken under and every mechanical list, so recording
    # a reason cannot bank unrelated drift. write_snapshot re-signs the digest,
    # which is legitimate ONLY because the digest it is replacing was verified
    # above -- otherwise this is the laundry described in the docstring.
    state = {
        "ignore": snapshot.get("ignore") or {},
        "modules": snapshot.get("modules") or [],
        "islands": snapshot.get("islands") or [],
        "unknown": snapshot.get("unknown") or [],
        "shims": snapshot.get("shims") or [],
        "test_only": snapshot.get("test_only") or [],
        "dark_switches": snapshot.get("dark_switches") or [],
        "doc_drift": snapshot.get("doc_drift") or [],
        "unparsable": snapshot.get("unparsable") or [],
        "index_extra_edges": snapshot.get("index_extra_edges") or [],
    }
    drift_mod.write_snapshot(snap_path, state, acceptances)
    replaced = " (replacing the previous acceptance for it)" if len(kept) != len(existing) else ""
    return True, (f"accepted {item} until {until}{replaced}\n"
                  f"  recorded in {snap_path}; it stops suppressing on "
                  f"{until} and comes back carrying this reason.")


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _render_text_summary(data: dict, out_path: Path | None) -> str:
    counts = data["counts"]
    stamp = data["stamp"]
    lines = [f"architecture map: {data['root']}", "  " + Stamp(
        generated_at=stamp["generated_at"], revision=stamp["revision"],
        branch=stamp["branch"], dirty=stamp["dirty"],
        dirty_paths=stamp["dirty_paths"],
        untracked_scanned=stamp.get("untracked_scanned", -1),
        untracked_sample=tuple(stamp.get("untracked_sample") or ())).one_line()]
    from .reach import CLASSES
    lines.append("  modules=%d  %s" % (
        counts["modules"], "  ".join(f"{c}={counts.get(c, 0)}" for c in CLASSES)))
    lines.append("  entry_points=%d (broken %d)  env_switches=%d (dark %d)  "
                 "param_gates=%d (dark %d)  doc_drift=%d" % (
                     counts["entry_points"], counts["broken_entries"],
                     counts["env_switches"],
                     counts["dark_env_switches"], counts["param_switches"],
                     counts["dark_params"], counts["doc_drift"]))
    lines.append("  gate: unreached=%d (islands %d, unknown %d, shims %d; "
                 "test-only %d)  dark_switches=%d  engine_disagreements=%d" % (
                     counts["gate_unreached"], counts["gate_islands"],
                     counts["gate_unknown"], counts["gate_shims"],
                     counts["gate_test_only"], counts["gate_dark_switches"],
                     counts["gate_index_extra_edges"]))
    narr = data["narrative"]
    if not narr["present"]:
        lines.append(f"  narrative: ABSENT ({narr['path']}) -- every hand-written "
                     f"section renders as missing, not empty")
    elif narr["missing"]:
        lines.append("  narrative: %d sections, MISSING %s" % (
            len(narr["sections"]), ", ".join(narr["missing"])))
    else:
        lines.append("  narrative: %d sections, all present" % len(narr["sections"]))
    if out_path is not None:
        lines.append(f"  wrote {out_path}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="daedalus map",
        description="Generate the architecture artifact: the mechanical half "
                    "derived on every run, the narrative half read from "
                    "docs/architecture-narrative.md and never overwritten.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=None, help=f"default {MAP_REL}")
    ap.add_argument("--narrative", default=None, help=f"default {NARRATIVE_REL}")
    ap.add_argument("--snapshot", default=None,
                    help="default docs/architecture-state.json")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable payload to stdout; writes nothing")
    ap.add_argument("--check", action="store_true",
                    help="gate mode: compare against the snapshot, print the "
                         "drift, exit non-zero on unaccepted drift, write nothing")
    ap.add_argument("--accept", metavar="ITEM", default=None,
                    help="record a dated acceptance, e.g. island:daedalus/x.py")
    ap.add_argument("--why", default="", help="required with --accept")
    ap.add_argument("--until", default="", help="ISO date; default +14 days")
    ap.add_argument("--since", default="", help="ISO date; default today")
    ap.add_argument("--who", default="")
    ap.add_argument("--no-git", action="store_true",
                    help="skip the working-tree dirty probe")
    args = ap.parse_args(list(argv) if argv is not None else None)

    root = Path(args.repo).resolve()
    out_path = Path(args.out) if args.out else root / MAP_REL
    narr_path = Path(args.narrative) if args.narrative else root / NARRATIVE_REL
    from . import drift as drift_mod
    snap_path = Path(args.snapshot) if args.snapshot else root / drift_mod.SNAPSHOT_REL

    if not (args.json or args.check):
        # --json/--check write nothing and stay fail-open; acceptance records
        # and the map/snapshot/inventory rewrites start at the central
        # boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "cli.mapping_render",
            REGISTRY_BY_ID["cli.mapping_render"].effects,
            (process_guard_boundary_decision(),),
        )
    if args.accept:
        ok, message = accept(root, args.accept, args.why, until=args.until,
                             since=args.since, who=args.who,
                             snapshot_path=snap_path)
        print(message)
        return 0 if ok else 1

    reports = analyse_once(root)
    data = build(root, narrative_path=narr_path, snapshot_path=snap_path,
                 probe_dirty=not args.no_git, reports=reports)

    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return 0

    if args.check:
        print(data["gate"]["text"])
        if data["gate"]["first_run"]:
            # Gate mode writes nothing, so unlike drift.check it cannot create
            # the baseline it is missing -- and a gate reporting OK against
            # nothing is the exact failure this subsystem exists to prevent.
            print(f"\nNo baseline at {snap_path}: gate mode compares against "
                  f"nothing and writes nothing.\nRun `daedalus map` once and "
                  f"commit the snapshot.")
            return 1
        return 0 if data["gate"]["ok"] else 1

    # Default: print what moved BEFORE re-baselining. Re-baselining is Tier 2
    # acceptance from drift.py, and Tier 2 only has teeth if a human sees it.
    print(data["gate"]["text"])
    print()
    narrative = load_narrative(narr_path)
    write_map(out_path, data, narrative)
    # The SAME analysis the page was rendered from. Re-scanning here would
    # bank a tree that is a few seconds older than the one just published.
    drift_mod.refresh(root, snap_path, reach_report=reports[0],
                      switch_report=reports[1],
                      probe_dirty=not args.no_git)
    # The feature census, from the SAME reports, for the same reason: it used
    # to be typed by hand and it was thirty commits stale while the picker read
    # it as the top of the work queue. Generating it here is what makes "it
    # cannot be older than the run that produced it" true rather than intended.
    from . import inventory as inventory_mod
    inv_result = inventory_mod.refresh(root, root / inventory_mod.INVENTORY_REL,
                                       reports=reports,
                                       probe_dirty=not args.no_git)
    print(_render_text_summary(data, out_path))
    print(f"  re-baselined {snap_path}"
          f" -- review its git diff; that diff is the whole gate")
    print(f"  re-generated {inv_result['path']}"
          f" -- mechanical fields rewritten, annotations carried forward")
    return 0


if __name__ == "__main__":
    sys.exit(main())
