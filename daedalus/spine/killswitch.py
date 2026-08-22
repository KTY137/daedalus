"""KILL SWITCH for the unattended loop. A loop you cannot stop is one you may not start.

ADR-013's precondition list, and ADR-007 line 19, name this as unmet:
*"Acceptance requires ... a kill switch that the candidate process cannot
modify."* This module is that switch, and every claim it makes below is a
claim someone measured, not a claim someone hoped.

THE MECHANISM, AND WHY THIS ONE
-------------------------------
A **permit file**, not a stop file. The loop runs only while a file on disk
holds the exact token ``RUN`` on its first non-empty line. A human in another
terminal halts the loop with::

    python -m daedalus.spine.killswitch stop

which is a rename-over of that file plus a sticky ``.stopped`` marker beside
it. ``del`` on the permit works just as well, which matters at 3am.

Presence-means-stop (the obvious design) was rejected because it fails OPEN on
every interesting failure. ``Path.exists()`` returns ``False`` for "the file is
not there" AND for "the volume is gone", "the ACL denies you", "the name is too
long", "the handle table is exhausted" -- so a switch built on it silently
answers *continue* exactly when the machine is least trustworthy. Absence-means-
stop inverts every one of those: any question this module cannot answer becomes
STOP. That is requirement 4, and it is structural rather than promised, because
there is no code path in :meth:`KillSwitch.read_state` that returns "running"
without having positively read the token.

THE LATENCY CONTRACT, WHICH IS THE WHOLE DELIVERABLE
----------------------------------------------------
A bound nobody measured is a promise. Three bounds, three different things,
stated separately because they are NOT the same number:

1. **OBSERVATION** -- the switch latches within ONE poll interval of the permit
   changing on disk (default 0.25 s). MEASURED at a 0.1 s poll, across a
   *process boundary* because the operator is in another terminal and not in
   this interpreter: **215 / 222 / 225 / 233 / 239 ms** over five runs, against
   a 600 ms budget (``test_latency_latch_within_one_poll_interval``). The
   stamp is taken BEFORE the stop is written, so every figure over-reports.
2. **CHILD DEATH** -- the whole process TREE is dead, and the gate has given
   up, within the same window. MEASURED on the real
   :func:`daedalus.spine.attempt.pytest_gate` path against a child that ignores
   ``CTRL_BREAK_EVENT`` and has spawned a grandchild: **257 / 258 / 262 / 268 /
   425 ms** (cold first run last), against a 3.0 s budget
   (``test_latency_gate_child_tree_dies``). Both pids are asserted dead, not
   merely "cancelled".
3. **NO NEW SPEND** -- no attempt and no provider call is *started* after the
   latch, because :meth:`checkpoint` raises. An HTTP request already in flight
   is NOT aborted. That is a real hole and it is named here rather than papered
   over: the bound is *before the next* billable call, not *during* this one.

MONOTONIC BY CONSTRUCTION
-------------------------
Once :meth:`should_stop` has answered True it answers True forever, in memory,
for the life of the object. Restoring the permit file does not un-latch it.
This is what turns "a candidate might win a race against the poller" from a
defeat into a 0.25 s window that must ALSO get past the kernel (below).

WHAT A CANDIDATE CAN AND CANNOT DO -- MEASURED ON THIS BOX
----------------------------------------------------------
The permit lives in ``%USERPROFILE%/.daedalus/control/<repo-digest>/``, an
entirely different tree from ``%LOCALAPPDATA%/daedalus/worktrees/`` where
candidate worktrees go. That is deliberate:
:func:`daedalus.spine.containment.label_low_integrity` stamps ``(OI)(CI)Low``
on a worktree, and inheritance flows DOWN a tree, never sideways -- so no
amount of labelling in ``worktrees/`` can ever reach ``control/``.

IT USED TO LIVE UNDER ``%LOCALAPPDATA%``, AND THAT MADE THE SWITCH A NO-OP
--------------------------------------------------------------------------
MEASURED on this box, with the repo's own ``python`` (the Microsoft-Store
shim ``…/WindowsApps/PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0``):
that interpreter runs under the Store's filesystem virtualisation, so a write
to ``C:\\Users\\<u>\\AppData\\Local\\daedalus\\control\\<digest>\\killswitch``
lands in
``…\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.10_qbz5n2kfra8p0\\LocalCache\\Local\\daedalus\\control\\<digest>\\killswitch``
instead -- and reads are redirected to match, so the lie is invisible from
inside the interpreter. ``arm()`` reported ``running=True``; ``cmd /c type``
on the literal path answered *"Das System kann den angegebenen Pfad nicht
finden."*; an operator's ``echo STOP>`` to the literal path failed with rc=1
and the loop went on reading ``RUN``. The permit, the lease ledger
(``effect-leases.sqlite3``) and the issuer key were none of them where
``receipt.killswitch_path`` said they were, and **the stop did not stop
anything**.

Two changes, because the placement alone would only move the next such bug:

* the root is derived from ``%USERPROFILE%`` (not ``%LOCALAPPDATA%``), which
  the Store shim does not virtualise, and :func:`control_root` is the single
  source of it -- :mod:`daedalus.kernel.offload_lease` and
  :mod:`daedalus.kernel.promotion_trust_root` both derive theirs from here so
  the three cannot drift apart again;
* :func:`verify_control_root` FAILS CLOSED on the symptom rather than on the
  known cause: it refuses when ``realpath`` disagrees with the literal path,
  and it refuses when a write in this process is not readable by a second
  process reading that literal path. A future virtualisation this module has
  never heard of trips the same wire.

A pre-migration root that still holds state is a REFUSAL, not a silent fresh
start: a fresh ledger beside a populated old one is a replay window.

  * A candidate under :func:`daedalus.spine.containment.spawn_contained`
    (Low integrity) is refused by the KERNEL when it tries to delete the
    permit, overwrite it with ``RUN``, delete the ``.stopped`` marker, or
    create either. Measured in ``test_contained_candidate_cannot_defeat_it``,
    which also asserts the same candidate CAN write its own worktree -- without
    that half, the test would pass just as happily against a candidate that
    never ran.
  * A candidate NOT under containment, running at the operator's own integrity
    level, CAN rewrite both files. It still cannot un-latch a switch that has
    already read STOP (``test_uncontained_forgery_cannot_unlatch``). So the
    residual exposure is a sub-poll-interval race, not a defeat -- and it
    closes entirely when the loop uses containment, which is why ADR-007's
    wording ("cannot modify") is only satisfied in the contained configuration.

THE SWEEP IS PROCESS-WIDE, SO THE LOOP MUST OWN ITS INTERPRETER
---------------------------------------------------------------
:meth:`KillSwitch.stop_children` calls
:func:`daedalus.spine.cancel.cancel_all_managed`, which cancels EVERY live
``ManagedProcess`` in this interpreter -- not merely the ones handed to
:meth:`KillSwitch.track`. That breadth is deliberate: the backstop exists
precisely for the child whose loop driver forgot to thread ``cancel=`` through,
and a registry that only reaps what it was told about would not have caught it.

The cost is that a kill switch in a process that hosts more than the loop (a
web API, a REPL) will also kill that other work. For an unattended loop driver
that is correct and is the point; for anything else, construct the switch with
``sweep_managed=False`` and rely on :meth:`track` plus the cancel token. Do not
run the loop inside a long-lived multi-purpose process and expect the sweep to
be discriminating -- it is not, and it is not trying to be.

WHY THERE IS NO LOCK HERE
-------------------------
``runs/council/room.py::_RoomLock`` is this repo's cross-process locking idiom
and it is the right one for the room -- it degrades to a no-op when the lock
cannot be taken, on the reasoning that losing serialisation beats losing a
human's message. That trade is exactly inverted here: a kill switch that
degrades is not a kill switch. So rather than reuse a fail-open lock or invent
a third mechanism, this module needs no lock at all: writes go through
``os.replace`` (atomic on both platforms), so a reader sees the old bytes or
the new bytes and never a torn file, and a read that fails for ANY reason --
including a Windows sharing violation -- is already STOP.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..atomic import write_text_atomic
from typing import Any, Iterable

from daedalus.spine.cancel import cancel_all_managed

__all__ = [
    "CONTROL_PROBE_TIMEOUT_S",
    "ControlRootCheck",
    "DEFAULT_POLL_S",
    "ENV_SWITCH_PATH",
    "KillSwitch",
    "LEGACY_CONTROL_ARTIFACTS",
    "LoopHalted",
    "MAX_PERMIT_BYTES",
    "OS_PROFILE_DIR",
    "OS_PROFILE_SOURCE",
    "REPLACE_RETRY_S",
    "RUN_TOKEN",
    "STOP_TOKEN",
    "SwitchState",
    "control_root",
    "default_switch_path",
    "legacy_control_root",
    "os_control_root",
    "profile_root_disagreement",
    "repo_control_digest",
    "verify_control_root",
]

#: The only token that means "keep going". Anything else means stop.
RUN_TOKEN = "RUN"
STOP_TOKEN = "STOP"

#: Poll interval for :meth:`KillSwitch.watch`, and the unit of the OBSERVATION
#: bound. 0.25 s matches the poll in :func:`daedalus.spine.attempt.pytest_gate`,
#: so the two loops cannot disagree about how stale a verdict may be.
DEFAULT_POLL_S = 0.25

#: A permit larger than this is refused unread. Candidate code cannot be
#: allowed to make the switch's own read slow (or memory-hungry) by growing the
#: file it is being watched by.
MAX_PERMIT_BYTES = 64 * 1024

#: How long an atomic replace may retry a sharing conflict. See
#: :meth:`KillSwitch._atomic_write` -- a poller reading the permit can block the
#: operator's own write on win32, and that raced in practice.
REPLACE_RETRY_S = 2.0

ENV_SWITCH_PATH = "DAEDALUS_KILLSWITCH"

#: Repo root, mirroring the convention in :mod:`daedalus.spine.attempt`.
ROOT = Path(__file__).resolve().parents[2]

_MARKER_SUFFIX = ".stopped"


class LoopHalted(RuntimeError):
    """Raised by :meth:`KillSwitch.checkpoint` when the loop must not proceed.

    An exception rather than a return value on purpose: a checkpoint placed
    before a billable call must be impossible to ignore by forgetting to look
    at a bool.
    """


@dataclass(frozen=True)
class SwitchState:
    """One reading of the permit. ``running`` is never true by default."""

    running: bool
    reason: str
    path: str
    token: str | None = None

    @property
    def stopped(self) -> bool:
        return not self.running

    def to_dict(self) -> dict:
        return {
            "running": self.running,
            "reason": self.reason,
            "path": self.path,
            "token": self.token,
        }


def repo_control_digest(repo_root: str | Path | None = None) -> str:
    """The 12-hex namespace of one checkout. Unchanged by the move off
    ``%LOCALAPPDATA%`` on purpose: the digest is how an operator correlates a
    control root with a worktree root, and renaming it would orphan both."""
    repo = Path(repo_root).resolve() if repo_root else ROOT
    return hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:12]


#: What :data:`OS_PROFILE_DIR` was derived from. ``"environment"`` is the one
#: value that means "this process could not ask the operating system", and it
#: is the only value for which :func:`profile_root_disagreement` stays silent:
#: there is nothing to compare against, and refusing every box whose ctypes
#: call fails would be a fail-closed that closes on the wrong thing.
_PROFILE_SOURCE_ENV = "environment"

#: ``FOLDERID_Profile`` -- {5E6C858F-0E22-4760-9AFE-EA3317B67173}.
_FOLDERID_PROFILE_FIELDS = (
    0x5E6C858F, 0x0E22, 0x4760,
    (0x9A, 0xFE, 0xEA, 0x33, 0x17, 0xB6, 0x71, 0x73),
)

#: ``CSIDL_PROFILE`` for the ``SHGetFolderPathW`` fallback.
_CSIDL_PROFILE = 0x28


def _win_profile_dir() -> str | None:
    """The profile directory from the Windows shell, never from the block.

    ``SHGetKnownFolderPath(FOLDERID_Profile)`` first, ``SHGetFolderPathW``
    (``CSIDL_PROFILE``) second. Both read the token/registry, so neither is
    movable by an in-process ``os.environ`` write -- which is the entire point:
    ``%USERPROFILE%`` is an ordinary environment variable and any library, test
    harness, or "sandboxed environment" layer can set it before this module's
    first use.
    """
    try:
        import ctypes
    except Exception:                                        # pragma: no cover
        return None
    try:
        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        d1, d2, d3, d4 = _FOLDERID_PROFILE_FIELDS
        guid = _GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))
        shell32 = ctypes.windll.shell32                      # type: ignore[attr-defined]
        ptr = ctypes.c_void_p()
        hresult = shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(ptr))
        try:
            if hresult == 0 and ptr.value:
                return ctypes.wstring_at(ptr.value)
        finally:
            if ptr.value:
                ctypes.windll.ole32.CoTaskMemFree(ptr)       # type: ignore[attr-defined]
    except Exception:                                        # pragma: no cover
        pass
    try:
        shell32 = ctypes.windll.shell32                      # type: ignore[attr-defined]
        buf = ctypes.create_unicode_buffer(1024)
        if shell32.SHGetFolderPathW(None, _CSIDL_PROFILE, None, 0, buf) == 0:
            return buf.value or None
    except Exception:                                        # pragma: no cover
        pass
    return None


def _posix_profile_dir() -> str | None:
    """The passwd entry for this uid. ``$HOME`` is environment, ``pwd`` is not."""
    try:
        import pwd

        entry = pwd.getpwuid(os.getuid())                    # type: ignore[attr-defined]
    except Exception:                                        # pragma: no cover
        return None
    return entry.pw_dir or None


def _resolve_os_profile_dir() -> tuple[Path, str]:
    """``(directory, source)``. Called exactly once, at import."""
    raw = _win_profile_dir() if os.name == "nt" else _posix_profile_dir()
    if raw:
        return Path(raw), (
            "shell32.SHGetKnownFolderPath/SHGetFolderPathW"
            if os.name == "nt" else "pwd.getpwuid")
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    if not home:
        expanded = os.path.expanduser("~")
        home = expanded if expanded and expanded != "~" else ""
    return (Path(home) if home else Path(tempfile.gettempdir())), _PROFILE_SOURCE_ENV


#: The profile directory as the OPERATING SYSTEM reports it, frozen at import
#: so that nothing which runs later can move it. THIS is the base of the
#: control root. See :func:`profile_root_disagreement` for why an environment
#: that disagrees with it is a refusal rather than a preference.
OS_PROFILE_DIR: Path
OS_PROFILE_SOURCE: str
OS_PROFILE_DIR, OS_PROFILE_SOURCE = _resolve_os_profile_dir()


def _same_directory(left: Path | str, right: Path | str) -> bool:
    """Two spellings of one directory. Compares the literal AND the resolved
    form, so neither a trailing separator nor a junction reads as a difference.
    """
    def spellings(value: Path | str) -> set[str]:
        text = os.path.abspath(str(value))
        out = {os.path.normcase(os.path.normpath(text))}
        try:
            out.add(os.path.normcase(os.path.normpath(os.path.realpath(text))))
        except OSError:                                      # pragma: no cover
            pass
        return out

    return bool(spellings(left) & spellings(right))


def _env_profile_dir() -> str | None:
    """What the ENVIRONMENT claims the profile directory is, or ``None``."""
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or ""
    return home or None


def profile_root_disagreement() -> str | None:
    """``None`` when the environment agrees with the OS, else WHY it must stop.

    THE SEAM THIS CLOSES. ``control_root`` used to read ``%USERPROFILE%`` out
    of the environment of the very process it protects. Anything that writes
    ``os.environ["USERPROFILE"]`` in-process -- a test harness, an SDK that
    "sandboxes the environment", a library that normalises a home directory --
    relocates the control root, and it does so silently:

    MEASURED on this box (2026-08-22), with ``%USERPROFILE%`` and
    ``%LOCALAPPDATA%`` both redirected to fresh temp directories before the
    first :class:`KillSwitch` construction::

        control_root()      -> ...\\Temp\\heracles-seams2-home-qqhk94xi\\.daedalus\\control\\2ea46e496ce4
        legacy_control_root -> ...\\Temp\\heracles-seams2-la-mk7hjrdi\\daedalus\\control\\2ea46e496ce4
        arm(force=True)     -> running=True          <-- ARMED SOMEWHERE ELSE
        control_check.ok    -> True

    Two failures at once. The operator's ``C:\\Users\\<u>\\.daedalus\\control``
    is not the file being watched, so a stop written there is never read; and
    the pre-migration refusal inspected a temp directory instead of the real
    ``%LOCALAPPDATA%`` root, which on this box genuinely holds ``killswitch``,
    ``effect-leases.sqlite3`` and ``effect-lease-issuer.key`` -- so the replay
    window that refusal exists to catch was waved through.

    The fix is deliberately a REFUSAL and not a silent correction. Silently
    using :data:`OS_PROFILE_DIR` while the rest of the process believes in its
    own ``%USERPROFILE%`` would put the permit somewhere the caller does not
    expect, which is the same class of lie one directory further along.
    """
    if OS_PROFILE_SOURCE == _PROFILE_SOURCE_ENV:
        return None
    env_home = _env_profile_dir()
    if env_home is None or _same_directory(env_home, OS_PROFILE_DIR):
        return None
    return (
        f"the profile directory in this process's environment ({env_home}) is "
        f"not the one the operating system reports ({OS_PROFILE_DIR}, via "
        f"{OS_PROFILE_SOURCE}). The control root is derived from the profile "
        "directory, so an in-process environment edit moves the permit, the "
        "lease ledger and the promotion ledger somewhere no operator can "
        "find, and makes the pre-migration check inspect the wrong tree. "
        "Refusing to treat a relocated control root as this machine's.")


def os_control_root(repo_root: str | Path | None = None) -> Path:
    """The control root as derived from the OS, ignoring the environment."""
    return OS_PROFILE_DIR / ".daedalus" / "control" / repo_control_digest(repo_root)


def control_root(repo_root: str | Path | None = None) -> Path:
    """THE control root for ``repo_root``. One function, three consumers.

    :mod:`daedalus.kernel.offload_lease` (lease ledger + issuer key) and
    :mod:`daedalus.kernel.promotion_trust_root` (single-use approval ledger)
    both derive theirs from this, so the permit, the ledger and the key cannot
    end up on three different volumes -- which is exactly the shape the
    ``%LOCALAPPDATA%`` bug took, one file at a time.

    ``%USERPROFILE%`` rather than ``%LOCALAPPDATA%``: the latter is virtualised
    for Microsoft-Store Python (see the module docstring; MEASURED), the former
    is not. There is deliberately NO environment override for the ROOT. Only
    the permit FILE has one (``DAEDALUS_KILLSWITCH``), for tests and for an
    operator with an unusual layout; an overridable control root would be an
    overridable uniqueness store, which is the A12 finding one layer up.

    The environment is still what this function READS, because a caller that
    moved it deserves a truthful answer about where its own derivation lands.
    It is not what a switch is allowed to USE: a derived
    :class:`KillSwitch` folds :func:`profile_root_disagreement` into its
    control check, so an environment that disagrees with :data:`OS_PROFILE_DIR`
    produces a refusal, never a permit at the moved address. When the two
    agree -- every unmodified process -- this returns exactly
    :func:`os_control_root`.

    The empty-environment fall-back is :data:`OS_PROFILE_DIR` rather than the
    temp directory it used to be: a control root under ``%TEMP%`` is a control
    root that a cleaner may delete between two polls.
    """
    home = _env_profile_dir()
    base_dir = Path(home) if home else OS_PROFILE_DIR
    return base_dir / ".daedalus" / "control" / repo_control_digest(repo_root)


#: Names whose presence under the pre-migration root means real state is there.
LEGACY_CONTROL_ARTIFACTS: tuple[str, ...] = (
    "killswitch",
    "killswitch.stopped",
    "effect-leases.sqlite3",
    "effect-lease-issuer.key",
    "promotion",
)


def legacy_control_root(repo_root: str | Path | None = None) -> Path | None:
    """Where the control root used to be, or ``None`` when it never applied."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    return Path(local_appdata) / "daedalus" / "control" / repo_control_digest(repo_root)


def default_switch_path(repo_root: str | Path | None = None) -> Path:
    """Where the permit lives for ``repo_root``: :func:`control_root` plus a name.

    ``DAEDALUS_KILLSWITCH`` overrides it, which is how tests and an operator
    with an unusual layout point at another file. The override changes the
    FILE, never the verification: an overridden path is checked for redirection
    and cross-process visibility exactly like a derived one.
    """
    override = os.environ.get(ENV_SWITCH_PATH)
    if override:
        return Path(os.path.abspath(override))
    return control_root(repo_root) / "killswitch"


#: A second process that cannot answer in this long is treated as "cannot see
#: it". Generous: the probe is one `type`/`cat` of a 32-byte file.
CONTROL_PROBE_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class ControlRootCheck:
    """Whether the control root is the directory this process thinks it is.

    ``ok`` is the only field to branch on; ``reason`` is written to be pasted
    into a receipt and read by a human at 3am, so it names both paths.
    """

    ok: bool
    reason: str
    path: str
    realpath: str
    legacy_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "control_root_ok": self.ok,
            "control_root_reason": self.reason,
            "control_root_path": self.path,
            "control_root_realpath": self.realpath,
            "control_root_legacy_path": self.legacy_path,
        }


_CONTROL_CHECK_CACHE: dict[str, ControlRootCheck] = {}
_CONTROL_CHECK_LOCK = threading.Lock()


def _cross_process_visible(root: Path) -> tuple[bool, str]:
    """Write a token here, read it back from ANOTHER process. ``(ok, why_not)``.

    This is the test that would have caught the Store-shim redirection without
    anybody knowing that Store shims exist. The reader is deliberately not
    Python: an interpreter under the same virtualisation would see the same
    lie, so the probe uses the shell an operator would use.
    """
    token = uuid.uuid4().hex
    probe = root / f".control-probe-{token}"
    cmd = ["cmd", "/c", "type", str(probe)] if os.name == "nt" else ["cat", str(probe)]
    try:
        try:
            probe.write_bytes(token.encode("ascii"))
        except OSError as e:
            return False, (
                f"the control root {root} is not writable "
                f"({type(e).__name__}: {e})")
        # bytes, not text: the shell answers in the OEM codepage and a decode
        # error here would masquerade as an invisible control root.
        proc = subprocess.run(cmd, capture_output=True,
                              timeout=CONTROL_PROBE_TIMEOUT_S)
        if token.encode("ascii") in (proc.stdout or b""):
            return True, ""
        detail = (proc.stderr or b"")[:200].decode("utf-8", "replace").strip()
        return False, (
            f"a second process cannot see the control root: `{' '.join(cmd)}` "
            f"did not return the {len(token)} bytes this process just wrote to "
            f"{probe} ({detail or f'rc={proc.returncode}'}). The permit is not "
            "where this process says it is, so an operator's stop written to "
            "that path would never reach this loop.")
    except Exception as e:                                       # noqa: BLE001
        return False, (
            f"the cross-process visibility probe failed "
            f"({type(e).__name__}: {e}); an unverifiable control root is STOP")
    finally:
        try:
            os.unlink(probe)
        except OSError:
            pass


def _legacy_state(repo_root: str | Path | None) -> tuple[Path, list[str]] | None:
    legacy = legacy_control_root(repo_root)
    if legacy is None:
        return None
    found: list[str] = []
    for name in LEGACY_CONTROL_ARTIFACTS:
        try:
            os.stat(legacy / name)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            found.append(f"{name} (unreadable)")
        else:
            found.append(name)
    return (legacy, found) if found else None


def _verify_control_root_uncached(root: Path, repo_root: str | Path | None,
                                  check_legacy: bool) -> ControlRootCheck:
    literal = str(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return ControlRootCheck(
            False,
            f"the control root {literal} could not be created "
            f"({type(e).__name__}: {e}); a loop whose permit has nowhere to "
            "live may not start",
            literal, literal)
    try:
        real = os.path.realpath(literal)
    except OSError as e:                                    # pragma: no cover
        return ControlRootCheck(
            False, f"the control root {literal} could not be resolved "
                   f"({type(e).__name__}: {e})", literal, literal)
    if os.path.normcase(real) != os.path.normcase(literal):
        return ControlRootCheck(
            False,
            f"the control root is REDIRECTED: this process writes {literal} "
            f"but the bytes land in {real}. An operator stopping the loop from "
            "another shell writes the literal path, which this process would "
            "never read. Refusing to arm.",
            literal, real)
    ok, why = _cross_process_visible(root)
    if not ok:
        return ControlRootCheck(False, why, literal, real)
    if check_legacy:
        legacy = _legacy_state(repo_root)
        if legacy is not None:
            legacy_root, found = legacy
            try:
                legacy_real = os.path.realpath(str(legacy_root))
            except OSError:                                 # pragma: no cover
                legacy_real = str(legacy_root)
            return ControlRootCheck(
                False,
                "a pre-migration control root still holds "
                f"{', '.join(found)} at {legacy_root} (which resolves to "
                f"{legacy_real}). Starting fresh at {literal} would leave that "
                "state unspent and unwatched -- a replay window and a stop "
                "nobody reads -- so this refuses instead. Move or delete the "
                "old root deliberately, then start again.",
                literal, real, str(legacy_root))
    return ControlRootCheck(
        True,
        f"the control root {literal} is literal and visible to another process",
        literal, real)


def verify_control_root(root: str | Path, *,
                        repo_root: str | Path | None = None,
                        check_legacy: bool = True,
                        use_cache: bool = True) -> ControlRootCheck:
    """Fail-closed startup check on the control root. NEVER raises.

    Three refusals, in cost order: the root cannot be created; ``realpath``
    disagrees with the literal path (a redirection, junction, or virtualised
    store); a second process cannot read what this one just wrote. Then one
    migration refusal: pre-migration state still exists.

    Cached per resolved root per interpreter, because the third check costs a
    subprocess and the poller asks 4x/second. ``use_cache=False`` is for the
    tests that need to see a changed filesystem.
    """
    root_path = Path(os.path.abspath(str(root)))
    key = f"{os.path.normcase(str(root_path))}|{bool(check_legacy)}|{repo_root}"
    if use_cache:
        with _CONTROL_CHECK_LOCK:
            hit = _CONTROL_CHECK_CACHE.get(key)
        if hit is not None:
            return hit
    try:
        check = _verify_control_root_uncached(root_path, repo_root, check_legacy)
    except BaseException as e:                                   # noqa: BLE001
        check = ControlRootCheck(
            False,
            f"the control-root check itself failed ({type(e).__name__}: {e}); "
            "an unverifiable control root is STOP",
            str(root_path), str(root_path))
    with _CONTROL_CHECK_LOCK:
        _CONTROL_CHECK_CACHE[key] = check
    return check


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KillSwitch:
    """A latching, fail-closed permit that a human can revoke from anywhere.

    Usage in a loop driver::

        switch = KillSwitch()
        with switch.watch():                 # background poller + child reaper
            while True:
                switch.checkpoint()          # raises LoopHalted; no new spend
                run_attempt(task, cancel=switch, ...)

    ``cancel=switch`` works unmodified because
    :func:`daedalus.spine.attempt._as_predicate` accepts any callable, and this
    object is callable. It also exposes ``is_set()`` so it can stand in for a
    ``threading.Event`` anywhere one is expected.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        poll_s: float = DEFAULT_POLL_S,
        repo_root: str | Path | None = None,
        kill_grace_s: float = 0.0,
        cooperative_grace_s: float = DEFAULT_POLL_S,
        sweep_managed: bool = True,
    ) -> None:
        # RESOLVED ONCE. Re-reading the environment on every check would let
        # anything that can set an env var in this process move the switch out
        # from under a running loop; the path a loop was started with is the
        # path it is stopped by.
        self._path = Path(path) if path is not None else default_switch_path(repo_root)
        self._path = Path(os.path.abspath(str(self._path)))
        self._marker = self._path.with_name(self._path.name + _MARKER_SUFFIX)
        # The pre-migration refusal applies only to the DERIVED root. A caller
        # who named a path (a test, or `--path`) is not the caller whose old
        # state we are protecting, and refusing them would be a false alarm.
        self._derived_path = path is None and not os.environ.get(ENV_SWITCH_PATH)
        self._repo_root = repo_root
        self._control_check: ControlRootCheck | None = None
        self.poll_s = max(0.01, float(poll_s))
        self.kill_grace_s = max(0.0, float(kill_grace_s))
        self.cooperative_grace_s = max(0.0, float(cooperative_grace_s))
        self._sweep_managed = bool(sweep_managed)

        self._lock = threading.Lock()
        self._tripped = False
        self._reason: str | None = None
        self._event = threading.Event()
        self._tracked: list[Any] = []
        self._watcher: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self._children_stopped = False

    # -- identity ---------------------------------------------------------- #

    @property
    def path(self) -> Path:
        """The permit path, frozen at construction."""
        return self._path

    @property
    def marker_path(self) -> Path:
        return self._marker

    @property
    def reason(self) -> str | None:
        """Why the switch latched, or ``None`` while it has not."""
        return self._reason

    @property
    def control_check(self) -> ControlRootCheck:
        """The fail-closed verdict on this switch's control root. Never raises.

        Resolved on first use rather than in ``__init__`` so that constructing
        a switch stays free (the operator CLI builds one just to call
        :meth:`stop`) and so a test that moves the filesystem underneath a
        constructed switch still gets a truthful answer on first read.
        """
        check = self._control_check
        if check is None:
            # FIRST, AND BEFORE `verify_control_root`. Two reasons, both
            # load-bearing:
            #
            # * it is the CAUSE, and the pre-migration check is one of its
            #   symptoms. `legacy_control_root` reads `%LOCALAPPDATA%` from the
            #   same relocated environment, so once the profile has moved that
            #   check is inspecting the wrong tree -- reporting it as the
            #   headline would send an operator to clean a directory that was
            #   never the problem.
            # * `_CONTROL_CHECK_CACHE` is keyed by the root PATH, so a process
            #   that relocated the profile could otherwise seed an ok=True
            #   verdict for the moved root and have every later switch read it
            #   back: first-writer-wins. This check is per switch and never
            #   consults that cache.
            #
            # Only for a DERIVED root: a caller who named a path, or set
            # `DAEDALUS_KILLSWITCH`, chose that file deliberately and is not
            # the caller this refusal protects -- the same reasoning that
            # scopes the pre-migration check to `_derived_path`.
            disagreement = (
                profile_root_disagreement() if self._derived_path else None)
            if disagreement is not None:
                literal = str(self._path.parent)
                check = ControlRootCheck(False, disagreement, literal, literal)
            else:
                check = verify_control_root(
                    self._path.parent,
                    repo_root=self._repo_root,
                    check_legacy=self._derived_path)
            self._control_check = check
        return check

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<KillSwitch path={self._path} tripped={self._tripped}>"

    # -- reading ----------------------------------------------------------- #

    def _marker_present(self) -> tuple[bool, str | None]:
        """``(present, unreadable_reason)``.

        NOT ``Path.exists()``. ``exists()`` swallows every OSError and answers
        False, so an ACL that denies us the marker would read as "no stop was
        requested" -- the precise fail-open this module exists to avoid. Only
        ``FileNotFoundError``/``NotADirectoryError`` mean absent; anything else
        means we could not tell, and could-not-tell is STOP.
        """
        try:
            os.stat(self._marker)
        except (FileNotFoundError, NotADirectoryError):
            return False, None
        except OSError as e:
            return True, f"the stop marker could not be examined ({e})"
        return True, None

    def read_state(self) -> SwitchState:
        """Read the permit from disk. Never raises; defaults to stopped.

        Every early return below is a STOP. There is exactly one ``running``
        exit, and it is reached only after the token was positively read and no
        stop marker was found.
        """
        p = self._path

        def halt(reason: str, token: str | None = None) -> SwitchState:
            return SwitchState(False, reason, str(p), token)

        # FIRST, BEFORE THE PERMIT IS EVEN LOOKED AT. A permit read out of a
        # directory that is not the directory an operator can write is not
        # evidence of anything; answering "armed" from it is the whole F1 bug.
        check = self.control_check
        if not check.ok:
            return halt(f"the control root is not usable: {check.reason}")

        try:
            st = os.stat(p)
        except (FileNotFoundError, NotADirectoryError):
            return halt("no permit file: the loop is not armed")
        except OSError as e:
            return halt(f"the permit could not be examined ({e})")
        except Exception as e:  # noqa: BLE001 - a switch may not raise, ever
            return halt(f"the permit could not be examined ({type(e).__name__}: {e})")

        if not stat.S_ISREG(st.st_mode):
            return halt("the permit path is not a regular file")
        if st.st_size > MAX_PERMIT_BYTES:
            return halt(f"the permit is implausibly large ({st.st_size} bytes)")

        try:
            data = p.read_bytes()
        except OSError as e:
            return halt(f"the permit could not be read ({e})")
        except Exception as e:  # noqa: BLE001
            return halt(f"the permit could not be read ({type(e).__name__}: {e})")

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return halt("the permit is not valid UTF-8")

        token: str | None = None
        for line in text.splitlines():
            if line.strip():
                token = line.strip()
                break
        if token is None:
            return halt("the permit is empty")
        if token != RUN_TOKEN:
            if token == STOP_TOKEN:
                return halt("stop was requested", token)
            return halt(f"the permit holds an unrecognised token {token!r}", token)

        present, unreadable = self._marker_present()
        if unreadable is not None:
            return halt(unreadable, token)
        if present:
            return halt("a stop marker is present beside the permit", token)

        return SwitchState(True, "armed", str(p), token)

    # -- latching ---------------------------------------------------------- #

    def should_stop(self) -> bool:
        """True once, then True forever. NEVER raises, and NEVER returns False
        because something went wrong.

        The never-raises property is not politeness. ``_as_predicate`` in
        :mod:`daedalus.spine.attempt` wraps a cancel token in
        ``try/except -> False``, i.e. a token that raises is treated as *not
        cancelled*. That is fail-open, it lives in a file this module may not
        edit, and the only defence available from this side is to make raising
        impossible: any internal failure here latches STOP instead of escaping.
        """
        with self._lock:
            if self._tripped:
                return True
        try:
            state = self.read_state()
            stopped, reason = state.stopped, state.reason
        except BaseException as e:  # noqa: BLE001 - see docstring
            stopped, reason = True, f"the switch itself failed ({type(e).__name__}: {e})"
        if not stopped:
            return False
        with self._lock:
            if not self._tripped:
                self._tripped = True
                self._reason = reason
            self._event.set()
        return True

    # Interchangeable with a callable token and with a threading.Event, so it
    # drops into `cancel=` (attempt.TaskAttempt) either way.
    def __call__(self) -> bool:
        return self.should_stop()

    def is_set(self) -> bool:
        return self.should_stop()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the watcher latches. Only meaningful under :meth:`watch`."""
        return self._event.wait(timeout)

    def checkpoint(self) -> None:
        """Raise :class:`LoopHalted` if the loop must not proceed.

        Call this immediately before anything that costs money or writes: it is
        the enforcement point for the "no new spend after the latch" bound.
        """
        if self.should_stop():
            raise LoopHalted(f"kill switch engaged: {self._reason} [{self._path}]")

    # -- children ---------------------------------------------------------- #

    def track(self, managed: Any) -> Any:
        """Register a :class:`~daedalus.spine.cancel.ManagedProcess` to reap.

        Returns its argument so it can wrap a constructor inline. Tracking is
        belt-and-braces: :func:`~daedalus.spine.cancel.cancel_all_managed`
        already sweeps every live ``ManagedProcess`` in this interpreter, which
        is what stops a gate child whose loop driver forgot to thread the
        cancel token through.
        """
        with self._lock:
            self._tracked.append(managed)
        return managed

    def stop_children(self) -> list:
        """Cancel every tracked tree, and (by default) every live managed tree.

        Returns the cancel results. Idempotent per trip; a second call after
        everything is already dead is cheap and harmless.
        """
        results = []
        with self._lock:
            tracked = list(self._tracked)
            self._children_stopped = True
        for proc in tracked:
            try:
                results.append(proc.cancel(grace_s=self.kill_grace_s))
            except Exception:  # noqa: BLE001 - one stuck child may not block the rest
                pass
        if self._sweep_managed:
            try:
                results.extend(cancel_all_managed(grace_s=self.kill_grace_s))
            except Exception:  # noqa: BLE001
                pass
        return results

    @property
    def children_stopped(self) -> bool:
        return self._children_stopped

    # -- the watcher ------------------------------------------------------- #

    def start_watch(self) -> None:
        """Start the background poller. Idempotent.

        A DAEMON thread that exits on the first trip: a watcher that outlives
        its trip is the "stale watcher still running old code" failure this
        repo has already paid for once.
        """
        with self._lock:
            if self._watcher is not None and self._watcher.is_alive():
                return
            self._watch_stop.clear()
            self._watcher = threading.Thread(
                target=self._watch_loop, name="daedalus-killswitch", daemon=True)
            watcher = self._watcher
        watcher.start()

    def stop_watch(self, timeout: float = 5.0) -> None:
        """Stop the poller and join it. Idempotent; safe after a trip."""
        self._watch_stop.set()
        with self._lock:
            watcher = self._watcher
            self._watcher = None
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=timeout)

    def _watch_loop(self) -> None:
        while True:
            if self.should_stop():
                # THE LATCH IS ALREADY SET at this point, so every cooperative
                # poller (pytest_gate's loop over ctx.is_cancelled(), and any
                # `cancel=switch` checkpoint) can already see it. Wait one gate
                # poll before the sweep of last resort fires.
                #
                # WHY, and this cost a measured bug: the sweep and the gate's
                # own poll race for the same child. When the sweep won, the
                # gate saw `proc.poll()` return non-None, left its loop by the
                # ordinary exit, and reported `cancelled=False, returncode=1`
                # -- which attempt.py then records as `gates_failed` rather
                # than `cancelled`. That is a FABRICATED VERDICT about a
                # candidate whose tests were never judged, and it would feed
                # the picker as if the candidate had been measured and lost.
                # Observed flapping ~50/50 across runs before this wait.
                #
                # The sweep is not weakened by yielding: the gate's own
                # `proc.cancel()` blocks for its DEFAULT 3 s grace against a
                # child that ignores CTRL_BREAK, and the sweep's grace-0
                # kill_tree cuts that wait short the moment it fires. So the
                # cooperative path gets the correct ATTRIBUTION and the sweep
                # still supplies the SPEED.
                if self.cooperative_grace_s > 0:
                    self._watch_stop.wait(self.cooperative_grace_s)
                # Unconditional: we have tripped, so children die even if the
                # watcher was also asked to shut down during the grace.
                self.stop_children()
                return
            # wait() returns True only when asked to shut down, so an armed
            # switch costs one syscall per poll and no busy loop.
            if self._watch_stop.wait(self.poll_s):
                return

    def watch(self) -> "_WatchScope":
        """Context manager wrapping :meth:`start_watch`/:meth:`stop_watch`."""
        return _WatchScope(self)

    def __enter__(self) -> "KillSwitch":
        self.start_watch()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop_watch()

    # -- operator side ----------------------------------------------------- #

    def _atomic_write(self, target: Path, text: str,
                      retry_s: float = REPLACE_RETRY_S) -> None:
        """Replace ``target`` atomically, retrying a Windows sharing conflict.

        MEASURED, and the reason this retry exists: on win32 a poller reading
        the permit holds it open WITHOUT ``FILE_SHARE_DELETE`` (CPython's
        ``open()`` offers no way to ask for it), so ``MoveFileEx`` over it
        returns ERROR_ACCESS_DENIED. With a 50 ms poll that raced often enough
        to break the operator's own stop command -- i.e. the kill switch could
        fail to engage precisely because something was watching it. The window
        is one ``read_bytes`` of a <1 KiB file, so a bounded retry closes it;
        the caller decides what an exhausted retry means.

        This is where that retry was first measured and written. It now
        delegates to :mod:`daedalus.atomic`, which is this same loop lifted so
        the four other publishers that documented themselves as atomic and
        omitted it (``arch_memory.save``, ``shift._write_atomic``,
        ``file_bridge._write_json_atomic``, ``loop.LoopLedger.save``) share one
        implementation instead of four divergent copies. Behaviour here is
        unchanged: same temp-sibling scheme, same bounded retry, same raise on
        an exhausted deadline.
        """
        write_text_atomic(target, text, retry_s=retry_s)

    def arm(self, *, force: bool = False, note: str = "") -> SwitchState:
        """Write the permit so work may proceed.

        REFUSES if a stop marker is present unless ``force=True``. That refusal
        is the guard against the most likely way an unattended system undoes a
        human decision: the loop crashes, a supervisor restarts it, its startup
        path calls ``arm()``, and the 3am stop evaporates. Re-arming after a
        deliberate stop has to be a deliberate act.
        """
        check = self.control_check
        if not check.ok:
            # `force=True` deliberately does NOT override this. Forcing past a
            # stop marker is an operator overruling an operator; forcing past
            # an unusable control root is an operator arming a switch nobody
            # can reach, which is the one thing this module exists to prevent.
            raise LoopHalted(f"refusing to arm: {check.reason}")
        present, unreadable = self._marker_present()
        if (present or unreadable is not None) and not force:
            raise LoopHalted(
                f"refusing to arm: a stop marker is present at {self._marker}. "
                f"A human stopped this loop; clear it explicitly "
                f"(arm(force=True), or `python -m daedalus.spine.killswitch "
                f"clear`) rather than re-arming automatically.")
        if force:
            try:
                os.unlink(self._marker)
            except OSError:
                pass
        body = f"{RUN_TOKEN}\narmed_at={_now_iso()}\npid={os.getpid()}\n"
        if note:
            body += f"note={note.splitlines()[0][:200]}\n"
        self._atomic_write(self._path, body)
        return self.read_state()

    def stop(self, reason: str = "operator request") -> SwitchState:
        """Revoke the permit and drop a sticky marker. The operator entry point.

        MARKER FIRST, and that order is load-bearing twice over:

        * If the process dies between the two writes, the permit still says
          ``RUN`` -- but the marker alone already means stop, so the crash
          window resolves to STOPPED rather than to running.
        * :meth:`_marker_present` uses ``os.stat``, which does not open the
          file, so nothing a poller does can block the marker being written.
          The permit rewrite is the one that can lose a sharing race, and by
          then the stop has ALREADY taken effect.

        Neither write failing is swallowed and neither is allowed to abort a
        stop that did take: this raises only if, after both attempts, the
        switch still reads as running. An operator's stop command must be loud
        when it did nothing and quiet when it worked.
        """
        first = reason.splitlines()[0][:200] if reason else "operator request"
        body = f"{STOP_TOKEN}\nat={_now_iso()}\nreason={first}\n"
        errors: list[str] = []
        for target in (self._marker, self._path):
            try:
                self._atomic_write(target, body)
            except OSError as e:
                errors.append(f"{target.name}: {e}")
        # Latch THIS object too. The operator asked this switch to stop; that
        # must not depend on a subsequent read of a disk that just misbehaved.
        with self._lock:
            if not self._tripped:
                self._tripped = True
                self._reason = f"stop requested: {first}"
            self._event.set()
        state = self.read_state()
        if state.running:
            raise LoopHalted(
                f"THE STOP DID NOT TAKE: {self._path} still reads as armed "
                f"after writing both files ({'; '.join(errors) or 'no error'}). "
                f"Kill the loop process directly.")
        return state

    def clear(self) -> None:
        """Remove permit and marker. Leaves the switch STOPPED (no permit)."""
        for target in (self._marker, self._path):
            try:
                os.unlink(target)
            except OSError:
                pass


class _WatchScope:
    def __init__(self, switch: KillSwitch) -> None:
        self._switch = switch

    def __enter__(self) -> KillSwitch:
        self._switch.start_watch()
        return self._switch

    def __exit__(self, exc_type, exc, tb) -> None:
        self._switch.stop_watch()


# --------------------------------------------------------------------------- #
# operator CLI -- `python -m daedalus.spine.killswitch <verb>`                  #
# --------------------------------------------------------------------------- #
def _main(argv: Iterable[str]) -> int:
    args = list(argv)
    verb = args[0] if args else "status"
    path: str | None = None
    rest: list[str] = []
    i = 1
    while i < len(args):
        if args[i] == "--path" and i + 1 < len(args):
            path = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1

    switch = KillSwitch(path)
    if verb == "stop":
        state = switch.stop(" ".join(rest) or "operator request")
        print(f"STOPPED {switch.path}: {state.reason}")
        return 0
    if verb == "arm":
        force = "--force" in rest
        try:
            state = switch.arm(force=force, note=" ".join(w for w in rest if w != "--force"))
        except LoopHalted as e:
            print(str(e))
            return 4
        print(f"{'ARMED' if state.running else 'NOT ARMED'} {switch.path}: {state.reason}")
        return 0 if state.running else 3
    if verb == "clear":
        switch.clear()
        print(f"CLEARED {switch.path} (loop remains stopped: no permit)")
        return 0
    if verb == "status":
        state = switch.read_state()
        print(f"{'RUNNING' if state.running else 'STOPPED'} {switch.path}: {state.reason}")
        return 0 if state.running else 3
    print(f"usage: python -m daedalus.spine.killswitch "
          f"{{status|arm|stop|clear}} [--path P] [--force] [reason...]")
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(_main(sys.argv[1:]))
