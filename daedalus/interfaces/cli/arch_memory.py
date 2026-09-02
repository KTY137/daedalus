"""arch_memory.py — the compressed architecture an agent carries into every turn.

WHAT THIS IS FOR
----------------
An agent starts every conversation not knowing what this repository IS. It
rediscovers the shape by grepping, which costs tokens, takes turns, and produces
a different (usually worse) picture each time. A few hundred tokens of true,
current structure injected up front replaces all of that.

The hard part is not producing a summary. It is producing one that stays SMALL
and stays TRUE, and says so when it is neither.

WHAT GOES IN, AND WHY EACH LINE EARNS ITS PLACE
-----------------------------------------------
* **Freshness first.** A stale architecture summary is worse than none: it reads
  as authoritative and describes a tree that no longer exists. So the first line
  says which commit it was measured at and whether that is still HEAD.
* **Package roles**, because "what are the top-level parts" is the question every
  new turn actually has.
* **Hubs**, because a change to a module 40 things import behaves differently
  from a change to a leaf, and that is invisible in a file listing.
* **Islands and shims**, because dead and vestigial code is exactly what an agent
  wastes a turn reading.
* **Doc drift**, because prose that names code that does not exist is the defect
  class this repo hunts, and knowing it is outstanding changes what you trust.
* **What the index could NOT see.** Every other line is what we know; this one is
  the shape of what we do not, and it is the line that keeps the rest honest.

WHAT IS DELIBERATELY LEFT OUT
-----------------------------
File listings, function names, line counts, anything a grep answers on demand.
A summary that tries to be complete stops being a summary, and the budget it
spends is charged on EVERY turn for the rest of the session.

DERIVED, NEVER HAND-MAINTAINED
------------------------------
Built from ``docs/architecture-state.json`` (produced by ``daedalus.mapping.drift``)
plus the structcore index. Regenerate and it is true by construction. It is
regenerated on commit by ``hooks/post-commit``, because a commit is exactly the
moment the structure changed and nothing else reliably marks it.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...atomic import write_text_atomic

ARCH_MEMORY_VERSION = "1"
MEMORY_REL_PATH = "runs/arch_memory.json"
STATE_REL_PATH = "docs/architecture-state.json"

#: Hard budget. This text is charged on every turn for the whole session, so the
#: bound is a product decision, not a formatting preference.
MAX_LINES = 24
MAX_LINE_CHARS = 110


def _git(root: Path, *args) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=20)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


@dataclass
class ArchMemory:
    head: str = ""
    branch: str = ""
    dirty: bool = False
    lines: tuple = ()
    generated_at: str = ""
    version: str = ARCH_MEMORY_VERSION

    def to_dict(self) -> dict:
        return {"head": self.head, "branch": self.branch, "dirty": self.dirty,
                "lines": list(self.lines), "generated_at": self.generated_at,
                "version": self.version}


def _package_roles(root: Path) -> list[str]:
    """One line per top-level package, from its own module docstring's first
    sentence. Reading the code's own words beats inventing a description that
    then drifts from it."""
    import ast

    roles = []
    pkg_root = root / "daedalus"
    if not pkg_root.is_dir():
        return roles
    for sub in sorted(p for p in pkg_root.iterdir() if p.is_dir()
                      and (p / "__init__.py").exists() and not p.name.startswith("_")):
        try:
            doc = ast.get_docstring(ast.parse((sub / "__init__.py").read_text(encoding="utf-8")))
        except (OSError, SyntaxError, UnicodeDecodeError):
            doc = None
        if not doc:
            continue
        first = doc.strip().split("\n")[0]
        first = first.split(" — ")[-1].split(" -- ")[-1].strip().rstrip(".")
        roles.append(f"  {sub.name:<11} {first[:MAX_LINE_CHARS - 16]}")
    return roles


def build(repo_root=".") -> ArchMemory:
    root = Path(repo_root).resolve()
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain"))

    state: dict = {}
    try:
        state = json.loads((root / STATE_REL_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}

    lines: list[str] = []
    counts = state.get("counts") or {}
    snap_head = ((state.get("repo_state") or {}).get("head") or "")

    # FRESHNESS FIRST. A summary that cannot say whether it still describes the
    # tree is the one failure mode that makes every other line dangerous.
    if not state:
        lines.append("ARCHITECTURE: no snapshot (run: python -m daedalus.mapping.drift)")
    elif snap_head and head and snap_head != head:
        lines.append(f"ARCHITECTURE: STALE -- measured at {snap_head[:8]}, HEAD is {head[:8]}")
    else:
        lines.append(f"ARCHITECTURE: measured at {(snap_head or head)[:8]}"
                     + ("  (working tree dirty)" if dirty else ""))

    if counts:
        lines.append(f"  {counts.get('modules', '?')} modules | "
                     f"{counts.get('islands', 0)} islands | {counts.get('shims', 0)} shims | "
                     f"{counts.get('unreached', 0)} unreached · "
                     f"{counts.get('doc_drift', 0)} doc-drift")

    roles = _package_roles(root)
    if roles:
        lines.append("PACKAGES")
        lines.extend(roles[:9])

    islands = list(state.get("islands") or ())
    if islands:
        lines.append("ISLANDS (nothing imports these -- do not read them by accident)")
        lines.append("  " + ", ".join(Path(i).name for i in islands[:8])
                     + (f" +{len(islands) - 8} more" if len(islands) > 8 else ""))
    shims = list(state.get("shims") or ())
    if shims:
        lines.append("SHIMS (re-export only): " + ", ".join(Path(s).name for s in shims[:6]))
    drift = list(state.get("doc_drift") or ())
    if drift:
        lines.append("DOC DRIFT (prose naming code that is not there): "
                     + ", ".join(str(d) for d in drift[:4]))

    # The honest closer: what the snapshot could not resolve.
    unknown = counts.get("unknown", 0)
    unparsable = counts.get("unparsable", 0)
    if unknown or unparsable:
        lines.append(f"NOT SEEN: {unknown} unknown, {unparsable} unparsable "
                     "-- these are gaps in the map, not absences in the tree")

    lines = [l[:MAX_LINE_CHARS] for l in lines[:MAX_LINES]]
    from datetime import datetime
    return ArchMemory(head=head, branch=branch, dirty=dirty, lines=tuple(lines),
                      generated_at=datetime.now().astimezone().isoformat(timespec="seconds"))


def save(mem: ArchMemory, repo_root=".") -> Path:
    """Publish whole or not at all.

    A post-commit hook writes this while a prompt hook may be reading it. There
    is no read-modify-write here, so atomic publish is sufficient and no lock is
    needed -- a reader sees the previous snapshot or the new one, never half.

    That concurrent reader is exactly what used to break this on win32: the
    reader holds the file open without FILE_SHARE_DELETE and the bare
    ``os.replace`` failed with ERROR_ACCESS_DENIED. This function NAMED that
    scenario in the paragraph above and then did the unretried replace anyway.
    ``daedalus.atomic`` carries the measured retry; see its module docstring.

    The per-pid temp name is also gone: two hook invocations in one process
    (a post-commit hook and a prompt hook both calling save) shared one scratch
    path, so a racing pair could publish half-written bytes. ``atomic`` uses a
    random suffix instead.
    """
    p = Path(repo_root) / MEMORY_REL_PATH
    write_text_atomic(p, json.dumps(mem.to_dict(), indent=1))
    return p


def load(repo_root=".") -> ArchMemory:
    try:
        raw = json.loads((Path(repo_root) / MEMORY_REL_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ArchMemory()
    return ArchMemory(head=raw.get("head", ""), branch=raw.get("branch", ""),
                      dirty=bool(raw.get("dirty")), lines=tuple(raw.get("lines") or ()),
                      generated_at=raw.get("generated_at", ""))


def render(repo_root=".") -> str:
    """The text a hook prints. Reports staleness against the LIVE head rather
    than trusting what was stored, because the stored copy is exactly the thing
    that goes out of date."""
    mem = load(repo_root)
    if not mem.lines:
        return ""
    live = _git(Path(repo_root).resolve(), "rev-parse", "HEAD")
    out = list(mem.lines)
    if live and mem.head and live != mem.head:
        out.insert(0, f"ARCH MEMORY IS STALE: built at {mem.head[:8]}, HEAD is now "
                      f"{live[:8]} — regenerate with `python -m daedalus.interfaces.cli.arch_memory`")
    return "\n".join(out)



# --------------------------------------------------------------------------- #
# What the agent is SHOWN, as opposed to what is stored                         #
# --------------------------------------------------------------------------- #
# The full block is fourteen lines of structured fact. Printed on every turn it
# becomes wallpaper: a hook can guarantee that something is AVAILABLE, it cannot
# make it read. Repetition is what turns available into ignored -- and it is
# charged to the token budget every single turn for the whole session.
#
# So after the first showing, only the DELTA is shown. A change is news; an
# unchanged tree is one line. The full block returns whenever it actually
# changes, which is exactly when it is worth reading again.
LAST_SHOWN_REL_PATH = "runs/arch_memory.shown"
#: Named rather than inlined: this file has been edited through several
#: layers of shell quoting and a bare escape did not survive the trip.
NEWLINE = chr(10)


def _last_shown(root: Path, shown_path: Path | None = None) -> list[str]:
    try:
        return (shown_path or root / LAST_SHOWN_REL_PATH).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _remember_shown(root: Path, lines, shown_path: Path | None = None) -> None:
    write_text_atomic(shown_path or root / LAST_SHOWN_REL_PATH, NEWLINE.join(lines))


def render_delta(repo_root=".", shown_path: Path | None = None, *, silent_when_unchanged: bool = False) -> str:
    """What changed since this was last shown — or one line saying nothing did.

    The FIRST call in a session shows everything, because a fresh agent knows
    nothing. Afterwards it shows only what moved, so an unchanged repository
    costs one line instead of fourteen and a changed one is impossible to miss
    among the noise it no longer has to compete with.

    ``shown_path`` relocates the "last shown" cursor (the hooks package keeps
    one per session under ``runs/hooks/``, so two sessions on one tree do not
    share a cursor and the tracked default file stays clean).
    ``silent_when_unchanged`` returns "" instead of the one-line "unchanged"
    notice; the caller that sets it announces once that silence means
    unchanged (hooks v2, 2026-08-23), so the silence stays readable.
    """
    root = Path(repo_root).resolve()
    if shown_path is not None:
        # The cursor may be relocated, but only inside this repository: this
        # function writes it, and a caller must not turn that into a write
        # anywhere on disk (Codex round 2, 2026-08-23).
        target = Path(shown_path).resolve()
        if root not in target.parents:
            raise ValueError(f"shown_path {target} is outside the repository {root}")
        shown_path = target
    mem = load(root)
    if not mem.lines:
        return ""
    live = _git(root, "rev-parse", "HEAD")
    now = list(mem.lines)
    if live and mem.head and live != mem.head:
        now.insert(0, f"ARCH MEMORY IS STALE: built at {mem.head[:8]}, HEAD is now "
                      f"{live[:8]} -- rebuild: python -m daedalus.interfaces.cli.arch_memory")

    before = _last_shown(root, shown_path)
    if not before:
        _remember_shown(root, now, shown_path)
        return NEWLINE.join(now)
    if before == now:
        # Deliberately not silent by default: "nothing changed" is itself
        # information, and a hook that prints nothing is indistinguishable
        # from a hook that broke. A caller that has made silence readable
        # (a SessionStart legend) opts out.
        return "" if silent_when_unchanged else "ARCHITECTURE: unchanged since the last turn"

    gone = [l for l in before if l not in now]
    new = [l for l in now if l not in before]
    out = ["ARCHITECTURE CHANGED since the last turn:"]
    out += [f"  - {l.strip()}" for l in gone[:6]]
    out += [f"  + {l.strip()}" for l in new[:6]]
    if len(gone) > 6 or len(new) > 6:
        out.append(f"  ... {max(0, len(gone) - 6) + max(0, len(new) - 6)} more line(s); "
                   "full picture: python -m daedalus.interfaces.cli.arch_memory --show")
    _remember_shown(root, now, shown_path)
    return NEWLINE.join(out)


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    root = argv[0] if argv and not argv[0].startswith("-") else "."
    if "--show" in argv:
        print(render(root) or "(no memory built yet)")
        return 0
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.arch_memory",
        REGISTRY_BY_ID["cli.arch_memory"].effects,
        (process_guard_boundary_decision(),),
    )
    mem = build(root)
    save(mem, root)
    print("\n".join(mem.lines))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))
