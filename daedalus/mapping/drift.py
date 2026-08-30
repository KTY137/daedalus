# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""mapping/drift.py -- the gate that makes the generated architecture map stick.

WHY THIS EXISTS
---------------
A hand-written feature inventory listed 136 features, 8 islands and 2 dark
switches. Six hours later a deep read of the same tree found 827, 55 and 51.
The artifact was not wrong when it was written; it went stale immediately and
nobody could tell. Generating the map fixes half of that -- a derived map
cannot go stale. It does not fix the other half: a report nobody reads is
exactly how the drift got to 827 unnoticed.

So this module compares the CURRENT generated state against a COMMITTED
snapshot (``docs/architecture-state.json``) and fails when they disagree. The
snapshot is deliberately small, sorted and free of timestamps, because the
thing a human actually reviews is its ``git diff``: ``"islands": 6 -> 7`` in a
diff is a question somebody has to answer out loud.

ONE ENGINE, ONE ANSWER
----------------------
This module DERIVES NOTHING ITSELF. Islands come from :func:`reach.analyse`;
switches come from :func:`switches.analyse`; both are the same reports the page
renders, computed once and passed in. That is not a refactor, it is the
correctness property: this file used to run its own reachability scan and its
own environment scan, and the two implementations disagreed on the same tree --
the gate saw 11 islands where the page saw 6, sharing not one member, and the
gate's dark half reported 0 where the switch engine reported 15. A gate that
disagrees with the page it guards teaches the reader to believe neither.

Two derivations remain, and both are stated here so they can be argued with
rather than discovered:

  * UNREACHED = every reach class that means "no entry point gets here",
    :data:`UNREACHED_CLASSES`, split across THREE lists because the remedies
    are three different sentences:

      ``islands``  reach's ``island`` + ``orphan``. Those two are merged
                   because the remedy really is identical -- wire it or delete
                   it -- and reach splits them only for display.
      ``unknown``  reach could not tell. Something names the module (a string
                   literal, an agents/*.json entry) or imports it somewhere the
                   import is no proof anything runs it (a dead branch, a
                   swallowed ImportError). The remedy is to RESOLVE the
                   ambiguity, which is not the same instruction as "wire it".
      ``shims``    a re-export nothing reaches. A shim is deliberate, so the
                   usual remedy is "delete the forward", not "wire it".

    These three used to be one list containing only the first, and the other
    two were dropped on the floor: an ``if False:`` import, a swallowed
    ImportError, a bare string literal or a new re-export module each produced
    a genuinely unwired file on disk and EXIT 0. Every unreached module is now
    counted, in exactly one of the three lists, and
    ``counts['unreached']`` is their total -- the number the page has to add up
    to. Nothing else is added; the three lists together are a function of
    reach's classification and can only drift from it if
    :data:`UNREACHED_CLASSES` stops covering a class reach can emit.
  * DARK = switches' ``dark`` verdict, MINUS the ones it classifies ``secret``,
    MINUS the ones documented BY THIS FILE'S RULE (see DOCUMENTED, below).
    Darkness itself -- off by default, no fallback, in a boolean position -- is
    decided in exactly one place, :mod:`~daedalus.mapping.switches`; both
    subtractions are over fields that engine already computed, and the page
    prints the size of each. The secret carve-out is a judgement call worth
    arguing with: an absent API key is not a dark feature, it is a documented
    feature that is merely unconfigured, and ``daedalus doctor`` is where that
    belongs.

REACHABILITY, AND WHY IT IS NOT ``fan_in > 0``
----------------------------------------------
The naive definition -- "nothing imports it" -- calls half this repo's Python
files islands, because ``__init__.py``, ``__main__.py``, every test and every
console-script entrypoint are imported by nobody. That number is useless and
would be ignored within a day. Reachability is the transitive closure of the
import graph from DISCOVERED entry points (console scripts, ``__main__.py``,
``__main__`` guards, CLI dispatch branches, HTTP routes, poll loops).

A module reached only by its own test is STILL AN ISLAND here, and it is
reported as one -- but under its own kind, :data:`TEST_ONLY`, which does not
block. That split is the honest form of a rule that used to be silent: landing
a test is evidence that somebody intends to wire the thing, so it should not
fail a build; but "wired to nothing except a test" is exactly the state the 827
grew out of, and since every module in this repo lands with a test, treating a
test as wiring meant the loudest alarm this gate has could not physically fire.
Now it fires, in its own colour, and its count moves in the committed diff.

DARK SWITCH
-----------
An environment variable that (a) is consumed as a BOOLEAN GATE, (b) defaults
OFF with no fallback, and (c) is not documented. (a) and (b) are
:mod:`~daedalus.mapping.switches`'s judgement, verbatim.

DOCUMENTED
----------
(c) is this file's, and it is stricter than "the token appears somewhere",
because that spelling could be defeated by a markdown file containing one bare
word. A switch counts as documented when, in a doc that is not generated and
outside every fenced code block, it appears

  * in a form an operator would actually type or an author would emphasise --
    ``NAME=...``, ``export NAME``, ``set NAME``, ``$env:NAME``, "environment
    variable NAME", `` `NAME` `` or ``**NAME**`` -- and
  * beside at least :data:`MIN_DOC_DESC_CHARS` characters of other prose, on
    that line or the next non-empty one.

Both halves matter. The form rule rejects a changelog line that merely names
the variable; the description rule rejects a token dropped into a file to
silence the gate. Code fences are excluded because a fenced sample is where a
name most often appears without being explained, and :data:`GENERATED_DOCS` is
excluded because ``daedalus map`` renders that file INTO the artifact this gate
guards -- counting it would let the page document its own findings away.

This is deliberately not "one designated inventory file with a description",
which would be stronger still. It is not, because introducing that file is a
documentation change outside this module, and a gate that fails until an
unrelated file is created gets turned off rather than satisfied.

THE ACCEPTANCE MECHANISM, AND WHY IT HAS TWO TIERS
--------------------------------------------------
Some islands are legitimate: a module lands today and is wired tomorrow. A
gate that cannot be satisfied is bypassed within a week, which is strictly
worse than no gate. But ``# noqa``-style silencing never expires, so it becomes
a graveyard nobody dares delete. Both failure modes are avoided by having two
ways to make an item stop failing:

TIER 1 -- TEMPORARY, DATED, SELF-RESURFACING (``acceptances`` in the snapshot)::

    {"item": "island:daedalus/mapping/drift.py",
     "why":  "landed with the scanner; the CLI wiring is the follow-up commit",
     "since": "2026-07-28", "until": "2026-08-11", "who": "kaya"}

  * EXPLICIT AND GREPPABLE -- ``grep -n 'island:' docs/architecture-state.json``
    lists every island anyone is currently looking away from.
  * RECORDS WHY AND WHEN -- ``why`` under :data:`MIN_WHY_CHARS` characters is
    rejected, and both dates are required.
  * BOUND TO THE CALENDAR, NOT ONLY TO ITSELF. ``until`` is capped at
    :data:`MAX_HORIZON_DAYS` past ``since`` AND ``since`` may not be in the
    future. The cap alone was not enough: ``{"since": "2999-01-01", "until":
    "2999-03-01"}`` is a 59-day horizon and parsed clean, so it suppressed
    forever -- at today, and at today plus ten years. A horizon measured only
    against its own start date is not a horizon.
  * Past ``until`` the acceptance stops suppressing and the underlying item
    comes back with the acceptance's own prose attached, so it resurfaces as
    "this reason ran out on 2026-08-11", not as a fresh mystery.
  * An accepted item is NEVER written into the baseline (see
    :func:`write_snapshot`). If it were, re-running ``--refresh`` would be a
    silent third way to accept, and it would be the one everybody used.
  * An acceptance that matches nothing is a STALE ACCEPTANCE and blocks. The
    list cannot accumulate dead prose about modules that were fixed or deleted.

TIER 2 -- PERMANENT, BY REVIEWED DIFF (``--refresh``). Deleting the acceptance
and re-baselining moves the item into ``islands``/``dark_switches`` and bumps
``counts``. There is no expiry, and there does not need to be: the change is a
line in a committed file, in a diff, with the count moving next to it. That is
the escape hatch, and it is one that a reviewer sees.

WHAT THE SNAPSHOT DEFENDS AGAINST, AND WHAT IT DOES NOT
--------------------------------------------------------
Every mechanical list is covered by a :data:`DIGEST_KEY` over the canonical
bytes, so hand-editing ``islands`` or ``dark_switches`` to pre-seed a finding
into the baseline is an INVALID SNAPSHOT rather than a silent pass. The lists
are additionally required to be internally coherent (``islands``, ``unknown``
and ``shims`` are subsets of ``modules``; ``test_only`` is a subset of their
union) and grounded in reality (``dark_switches`` must name variables the code
still reads).

WHAT THAT SENTENCE IS ALLOWED TO CLAIM is exactly this: every verb in this
subsystem that READS a snapshot re-derives the digest first and refuses a
mismatch. :func:`check` reports INVALID SNAPSHOT.
:func:`~daedalus.mapping.render.accept` -- which inherits the mechanical lists
verbatim in order not to bank unrelated drift -- refuses to inherit them at all
unless the digest it is inheriting verifies, because a verb that re-signs
hand-edited bytes launders them into a valid snapshot and is worse than no
verb. :func:`refresh` does not need the check: it rescans and overwrites every
mechanical list from the tree.

It does not stop somebody who runs Python to re-compute the digest, and it is
not meant to: the control on a deliberate re-baseline is the reviewed diff,
which is Tier 2 and works exactly as designed.

THE IGNORE CONFIGURATION
------------------------
``DAEDALUS_IGNORE`` and ``.daedalusignore`` narrow the structural index. Since
the gate now reads the tree through :mod:`~daedalus.mapping.reach`, which walks
the filesystem itself, they cannot narrow what the gate sees -- but the
configuration is recorded in the snapshot and compared on every run anyway, so
that a green result taken under a narrowed configuration can never be
indistinguishable from a green result taken under a clean one.

FIRST RUN, AND WHY IT FAILS
---------------------------
A missing snapshot is NOT a pass. Both entry points refuse it: ``daedalus map
--check`` exits non-zero, and ``python -m daedalus.mapping.drift`` does too.
Writing a baseline is an explicit named action (``--init``, ``--refresh``, or a
plain ``daedalus map``), because ``rm docs/architecture-state.json`` must not be
a way to get a green run.

COST
----
This is a CI GATE, NOT A PRE-COMMIT HOOK. A full run parses every Python file
in the tree twice (reachability and switches) and takes seconds, not
milliseconds. Wired into pre-commit it would be bypassed with ``--no-verify``
within a week, and a gate people route around is worse than no gate because it
also carries a claim of safety.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Sequence

SNAPSHOT_REL = "docs/architecture-state.json"
# 2: single-engine state. Adds test_only/unparsable/ignore/digest and re-derives
# islands and dark switches from reach/switches, so a schema-1 baseline cannot
# be compared against a schema-2 run -- the lists mean different things.
# 3: the unreached half stops being one list. ``unknown`` and ``shims`` join
# ``islands`` as first-class lists with their own counts and their own gate
# kinds, ``counts['unreached']`` is their total, and ``index_extra_edges``
# records where the two engines disagree about the import graph. A schema-2
# baseline has no place to put any of that, so it is refused rather than
# read as "those lists are empty".
#
# Within 3, additively: ``repo_state`` records WHICH TREE was scanned and is
# covered by the digest. Not a version bump, because the lists still mean what
# they meant -- a schema-3 baseline without it simply cannot answer the
# freshness question, which :func:`snapshot_freshness` reports as "not fresh"
# rather than pretending otherwise.
SCHEMA_VERSION = 3

# The teeth. An acceptance may not be written further out than this, so no
# acceptance can outlive a release cycle without a human retyping the reason.
MAX_HORIZON_DAYS = 90
# "wip" is not a reason. Short enough to be typeable, long enough to be a sentence.
MIN_WHY_CHARS = 12

# reach classes the gate treats as "nothing reaches it". ``orphan`` is reach's
# strictly-worse island (imports nothing, imported by nothing, untested); the
# remedy is the same, so the gate does not split them.
ISLAND_CLASSES = ("island", "orphan")
# ``unknown`` and ``shim`` are ALSO "no entry point gets here" -- reach says so
# itself -- but they are not islands and must not be flattened into them: an
# unknown is "I could not tell" and a shim is a deliberate re-export, and the
# three carry three different remedies. Each gets its own list, its own count
# and its own gate kind. What may never happen again is a reach class that
# means unreached and appears in none of them.
UNKNOWN_CLASSES = ("unknown",)
SHIM_CLASSES = ("shim",)
UNREACHED_CLASSES = ISLAND_CLASSES + UNKNOWN_CLASSES + SHIM_CLASSES
# Everything reach can emit that is NOT unreached. Together with
# UNREACHED_CLASSES this must cover reach.CLASSES exactly; the property is
# asserted in the tests, because a new reach class silently landing outside
# both sets is precisely how two classes got dropped the first time.
REACHED_CLASSES = ("entry", "reachable", "test")

IGNORE_FILENAME = ".daedalusignore"
IGNORE_ENV = "DAEDALUS_IGNORE"

# --- documentation, the strict rule ---------------------------------------
DOC_DIRS = ("docs",)
DOC_SUFFIX = ".md"
DOC_EXTRA_FILES = (".env.example", ".env.template")

# Files this artifact GENERATES AGAINST. Counting a mention here would let the
# page document away its own findings.
GENERATED_DOCS = ("docs/architecture-narrative.md",)
_GENERATED_MARK = re.compile(r"generated by|do not hand-edit|autogenerated", re.I)
_FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")

# Prose that has to sit beside the name before a mention counts as an
# explanation. Roughly "five words": long enough that a bare token and a
# two-word label both fail, short enough that a real one-line entry passes.
MIN_DOC_DESC_CHARS = 20
_ALNUM_RUN = re.compile(r"[^A-Za-z0-9]+")

NEW_ISLAND = "NEW ISLAND"
NEW_UNKNOWN = "NEW UNKNOWN"
NEW_SHIM = "NEW UNREACHED SHIM"
ENGINE_DISAGREEMENT = "ENGINE DISAGREEMENT"
NEW_DARK_SWITCH = "NEW DARK SWITCH"
BECAME_ISLAND = "BECAME ISLAND"
NOW_REACHED = "NOW REACHED"
DOC_DRIFT = "DOC DRIFT"
VANISHED = "VANISHED"
TEST_ONLY = "TEST ONLY"
UNPARSABLE = "UNPARSABLE"
IGNORE_DRIFT = "IGNORE CONFIG CHANGED"
STALE_ACCEPTANCE = "STALE ACCEPTANCE"
INVALID_ACCEPTANCE = "INVALID ACCEPTANCE"
INVALID_SNAPSHOT = "INVALID SNAPSHOT"

# Render order: the alarm that means "somebody built something and never wired
# it" is first, the good news is last but always present -- a report that only
# ever nags is a report that gets filtered to a folder nobody opens.
KIND_ORDER = (
    INVALID_SNAPSHOT,
    IGNORE_DRIFT,
    NEW_ISLAND,
    BECAME_ISLAND,
    NEW_UNKNOWN,
    NEW_SHIM,
    ENGINE_DISAGREEMENT,
    NEW_DARK_SWITCH,
    VANISHED,
    UNPARSABLE,
    DOC_DRIFT,
    TEST_ONLY,
    INVALID_ACCEPTANCE,
    STALE_ACCEPTANCE,
    NOW_REACHED,
)
# NOW_REACHED is good news. TEST_ONLY is a real finding that deliberately does
# not block: a test is evidence of intent, and failing a build over it would
# get the gate switched off. It is loud instead -- its own kind, its own list
# in the snapshot, its own count in the diff.
NON_BLOCKING_KINDS = frozenset({NOW_REACHED, TEST_ONLY})

# What an acceptance may cover. Acceptance hygiene, a broken snapshot and a
# changed ignore configuration are deliberately NOT acceptable: "the acceptance
# list is wrong", "the snapshot contradicts itself" and "this run looked at
# less of the tree than the baseline did" have to be repaired, not waived.
ACCEPTABLE_KINDS = frozenset({
    NEW_ISLAND, BECAME_ISLAND, NEW_UNKNOWN, NEW_SHIM, ENGINE_DISAGREEMENT,
    NEW_DARK_SWITCH, VANISHED, DOC_DRIFT, UNPARSABLE})


# --------------------------------------------------------------------------
# documentation
# --------------------------------------------------------------------------

def _doc_paths(root: Path) -> list[Path]:
    paths: list[Path] = sorted(root.glob("*" + DOC_SUFFIX))
    for d in DOC_DIRS:
        paths.extend(sorted((root / d).rglob("*" + DOC_SUFFIX)))
    for name in DOC_EXTRA_FILES:
        p = root / name
        if p.is_file():
            paths.append(p)
    return paths


@dataclass(frozen=True)
class DocIndex:
    """Every prose line that could introduce an environment variable.

    Built once per run, then queried per switch name. Fenced blocks and
    generated files are dropped at BUILD time rather than at query time, so
    there is exactly one place where "does this text count" is decided."""

    lines: tuple[tuple[str, int, str, str], ...] = ()   # rel, no, line, next

    @classmethod
    def build(cls, repo_root) -> "DocIndex":
        root = Path(repo_root)
        out: list[tuple[str, int, str, str]] = []
        for path in _doc_paths(root):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:                      # pragma: no cover
                rel = path.as_posix()
            if rel in GENERATED_DOCS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            raw = text.splitlines()
            if _GENERATED_MARK.search("\n".join(raw[:5])):
                continue
            kept: list[tuple[int, str]] = []
            fenced = False
            for i, line in enumerate(raw, 1):
                if _FENCE_RE.match(line):
                    fenced = not fenced
                    continue
                if not fenced:
                    kept.append((i, line))
            for j, (no, line) in enumerate(kept):
                nxt = ""
                for _, later in kept[j + 1:j + 4]:
                    if later.strip():
                        nxt = later
                        break
                out.append((rel, no, line, nxt))
        return cls(lines=tuple(out))

    @staticmethod
    def _forms(name: str) -> tuple[re.Pattern, ...]:
        n = re.escape(name)
        return (
            re.compile(r"(?:^|[^A-Za-z0-9_])" + n + r"\s*="),
            re.compile(r"(?i:set|setx|export|\$env:)\s*:?\s*[`'\"]?" + n + r"\b"),
            re.compile(r"(?i:environment variable|env var|env-var)"
                       r"[^\n]{0,40}?" + n + r"\b"),
            re.compile(r"[`*]" + n + r"[`*]"),
        )

    @staticmethod
    def _described(name: str, line: str, nxt: str) -> bool:
        """Is there real prose beside the name, on this line or the next?

        Non-alphanumerics collapse to single spaces before counting, so
        ``PKG_TURBO=1`` scores 1, not 12: punctuation and the value are not an
        explanation of what the switch turns on."""
        for candidate in (line, line + " " + nxt):
            rest = candidate.replace(name, " ")
            if len(_ALNUM_RUN.sub(" ", rest).strip()) >= MIN_DOC_DESC_CHARS:
                return True
        return False

    def sites(self, name: str) -> tuple[str, ...]:
        forms = self._forms(name)
        hits: list[str] = []
        for rel, no, line, nxt in self.lines:
            if not any(f.search(line) for f in forms):
                continue
            if not self._described(name, line, nxt):
                continue
            hits.append(f"{rel}:{no}")
        return tuple(hits)

    def documents(self, name: str) -> bool:
        return bool(self.sites(name))


# --------------------------------------------------------------------------
# the ignore configuration
# --------------------------------------------------------------------------

def ignore_config(repo_root) -> dict:
    """What was excluded from this run, as a comparable fingerprint.

    Recorded in the snapshot so that a run narrowed by ``DAEDALUS_IGNORE`` can
    never be mistaken for a clean one. The env value is stored VERBATIM rather
    than hashed: the point is that a reviewer reading the failure can see what
    was hidden without re-running anything."""
    root = Path(repo_root)
    try:
        text = (root / IGNORE_FILENAME).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return {
        "env": os.environ.get(IGNORE_ENV, "").strip(),
        "file": (hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                 if text.strip() else ""),
    }


def _describe_ignore(cfg: dict) -> str:
    env = cfg.get("env") or ""
    fp = cfg.get("file") or ""
    parts = [f"{IGNORE_ENV}={env!r}" if env else f"{IGNORE_ENV} unset",
             f"{IGNORE_FILENAME} {fp}" if fp else f"no {IGNORE_FILENAME}"]
    return ", ".join(parts)


# --------------------------------------------------------------------------
# scanning -- which is now entirely consumption
# --------------------------------------------------------------------------

@dataclass
class ScanResult:
    """The mechanical state. ``state`` is what the snapshot stores; ``sites``
    is runtime-only detail (file:line) used to make remedies actionable, and is
    deliberately kept OUT of the snapshot so line-number churn never produces a
    diff a human has to read.

    ``reach`` and ``switches`` are the reports this state was derived FROM,
    carried out so no caller has to re-run either engine to ask a follow-up
    question -- which is how two engines got built here in the first place."""
    state: dict
    sites: dict = field(default_factory=dict)
    reach: object = None
    switches: object = None


_DRIFT_PREFIX = {
    "documented_never_read": "doc-only",
    "read_never_documented": "code-only",
    "name_mismatch": "name-mismatch",
}


def _drift_key(entry) -> str:
    if entry.kind == "name_mismatch":
        return f"name-mismatch:{entry.documented}~{entry.read}"
    prefix = _DRIFT_PREFIX.get(entry.kind, entry.kind)
    return f"{prefix}:{entry.documented or entry.read}"


# A git object name, and the shortest abbreviation that is an identifier
# rather than a coincidence. git's own floor is 7; a 1-character "prefix"
# matches roughly one HEAD in sixteen, and a check that passes by accident is
# worse than no check because it is believed.
_MIN_ABBREV = 7
_SHA_RE = re.compile(rf"[0-9a-f]{{{_MIN_ABBREV},64}}")


def repo_state(repo_root, *, probe_dirty: bool = True) -> dict:
    """WHICH TREE this scan looked at: ``head``, ``branch``, ``dirty``.

    The digest proves nobody hand-edited the snapshot. It says NOTHING about
    when the snapshot was taken -- a baseline generated thirty commits ago
    verifies its own digest perfectly, and that gap was measured doing real
    damage: the self-improvement loop suppressed the stale hand-written
    inventory (which has a freshness gate) while trusting a stale generated
    snapshot (which had none), and acted on a description of a tree that no
    longer existed.

    ``head`` is the authority and is covered by the digest (see
    :func:`_digest`). There is deliberately NO ``generated_at``: a clock
    reading answers "when did the generator run", which is the weaker question,
    and it would destroy the byte-identity this artifact is built on -- see
    :func:`snapshot_bytes`.

    ``dirty`` is probed only when there is a ``.git`` to probe, so a scan of a
    tree that is not a checkout costs no subprocess and still answers honestly:
    ``None`` means "could not tell", never "clean".
    """
    from . import render as render_mod

    root = Path(repo_root)
    head, branch = render_mod._head(root)
    dirty: bool | None = None
    if probe_dirty and head != "unknown":
        verdict, _count = render_mod._dirty(root)
        dirty = True if verdict == "dirty" else (False if verdict == "clean"
                                                 else None)
    return {"head": head, "branch": branch, "dirty": dirty}


def snapshot_freshness(snapshot, repo_root=None, *, actual_head=None) -> dict:
    """Does this snapshot describe the tree we are actually standing in?

    FAILS CLOSED on the artifact's own defects -- an absent, non-string or
    malformed ``repo_state.head`` means the snapshot cannot say what it
    scanned, and a snapshot that cannot say what it scanned is not evidence
    about this tree. That is the opposite of the map's digest rule, and
    deliberately so: the digest asks "did a human edit this", where a missing
    field is a plausible degradation; this asks "does this describe me", where
    a missing field is the whole failure.

    FAILS OPEN when the recorded head is well-formed and git cannot answer at
    all: a tarball checkout with no ``.git`` is not evidence of staleness, and
    turning "I cannot tell" into "refuse everything" is a worse failure than
    ranking. Same rule, same reasoning, as
    ``daedalus.spine.picker.inventory_freshness``.
    """
    state = snapshot.get("repo_state") if isinstance(snapshot, Mapping) else None
    recorded = state.get("head") if isinstance(state, Mapping) else None
    if not isinstance(recorded, str) or not recorded.strip():
        return {"fresh": False, "recorded_head": None, "actual_head": None,
                "reason": ("the snapshot records no repo_state.head, so it "
                           "cannot say which tree it scanned. Regenerate it "
                           "with `daedalus map`")}
    recorded = recorded.strip()
    if not _SHA_RE.fullmatch(recorded):
        return {"fresh": False, "recorded_head": recorded, "actual_head": None,
                "reason": (f"the snapshot's recorded head {recorded!r} is not a "
                           f"git object name (at least {_MIN_ABBREV} hex "
                           f"characters), so it cannot be checked against the "
                           f"tree it describes")}
    if actual_head is None and repo_root is not None:
        from . import render as render_mod

        actual_head = render_mod._head(Path(repo_root))[0]
    if not actual_head or actual_head == "unknown":
        return {"fresh": True, "recorded_head": recorded, "actual_head": None,
                "reason": "git could not report HEAD; freshness unknown, "
                          "failing open"}
    # ONE direction: the file may record an abbreviation of the full sha git
    # stores, so ``actual.startswith(recorded)`` is the containment that can be
    # true. Testing the reverse would let a shorter actual satisfy a longer
    # recorded value, which is not a relationship any git abbreviation produces.
    if actual_head.startswith(recorded):
        return {"fresh": True, "recorded_head": recorded,
                "actual_head": actual_head[:len(recorded)],
                "reason": "snapshot matches HEAD"}
    return {"fresh": False, "recorded_head": recorded,
            "actual_head": actual_head[:len(recorded)],
            "reason": (f"the snapshot was generated against {recorded[:12]} but "
                       f"HEAD is {actual_head[:12]}")}


def scan(repo_root, *, index=None, reach_report=None,
         switch_report=None, probe_dirty: bool = True) -> ScanResult:
    """Derive the current architecture state. Pure: no writes, no clock, no
    network.

    ``reach_report`` and ``switch_report`` may be injected by a caller that
    already built them (``daedalus map`` does, and that is the point: the page
    and the gate are then provably looking at the same analysis, not at two
    that happen to agree). ``index`` is only forwarded to reach for its
    structural cross-check.

    The state also records WHICH TREE it was derived from
    (:func:`repo_state`). It belongs here rather than in the writer because it
    is a property of the scan, and because a state that cannot say what it
    scanned is the exact hole this module spent a release closing on the
    hand-written side.
    """
    from . import reach as reach_mod
    from . import switches as switches_mod

    root = Path(repo_root).resolve()
    if reach_report is None:
        reach_report = reach_mod.analyse(root, index=index)
    if switch_report is None:
        switch_report = switches_mod.analyse(root)

    facts = reach_report.modules
    modules = sorted(m.module for m in facts if m.classification != "test")
    islands = sorted(m.module for m in facts
                     if m.classification in ISLAND_CLASSES)
    unknown_mods = sorted(m.module for m in facts
                          if m.classification in UNKNOWN_CLASSES)
    shims = sorted(m.module for m in facts
                   if m.classification in SHIM_CLASSES)
    # TEST ONLY is a property of an UNREACHED module, not of an island
    # specifically. Scoping it to islands meant a shim or an unknown whose only
    # importer was a test could not be described that way at all.
    unreached_facts = [m for m in facts
                       if m.classification in UNREACHED_CLASSES]
    test_only = sorted(m.module for m in unreached_facts if m.tested_by)
    # Two engines disagreeing about the import graph. reach REPORTS these and
    # refuses to merge them (see reach.analyse); the gate is where a
    # disagreement that persists across a commit becomes somebody's problem.
    index_extra_edges = sorted(reach_report.index_extra_edges)

    docs = DocIndex.build(root)
    dark: dict[str, str] = {}
    for sw in switch_report.env_switches:
        if not sw.dark:
            continue
        # An absent API key is not a dark feature. The feature it belongs to is
        # documented and merely unconfigured -- ``daedalus doctor`` already
        # reports it, and an architecture gate is a poor place to enumerate
        # which secrets a machine is missing. ``secret`` is the switch engine's
        # own classification, so this is a filter over one answer, not a
        # second opinion about what a switch is.
        if sw.kind == "secret":
            continue
        if docs.documents(sw.name):
            continue
        site = sw.sites[0] if sw.sites else None
        dark[sw.name] = f"{site.module}:{site.line}" if site else "?"

    doc_drift: dict[str, str] = {}
    for entry in switch_report.drift:
        where = (entry.doc_sites or entry.code_sites or ("?",))[0]
        doc_drift[_drift_key(entry)] = where

    # A module the scanner could not parse contributes nothing to either
    # engine's answer, which makes it a hole in the map that used to be filled
    # by a bare ``continue``. It is a finding, not a shrug.
    unparsable = set(reach_report.unparsable)
    for problem in switch_report.unparsable:
        unparsable.add(problem.split(":", 1)[0].strip())

    state = {
        "schema": SCHEMA_VERSION,
        "repo_state": repo_state(root, probe_dirty=probe_dirty),
        "counts": {
            "modules": len(modules),
            # The honest total: every module on disk that no entry point
            # reaches, whatever reach called it. It is the number the page has
            # to add up to, and it is what "islands=7" used to hide.
            "unreached": len(islands) + len(unknown_mods) + len(shims),
            "islands": len(islands),
            "unknown": len(unknown_mods),
            "shims": len(shims),
            "test_only": len(test_only),
            "dark_switches": len(dark),
            "doc_drift": len(doc_drift),
            "unparsable": len(unparsable),
            "index_extra_edges": len(index_extra_edges),
        },
        "ignore": ignore_config(root),
        "modules": modules,
        "islands": islands,
        "unknown": unknown_mods,
        "shims": shims,
        "test_only": test_only,
        "dark_switches": sorted(dark),
        "doc_drift": sorted(doc_drift),
        "unparsable": sorted(unparsable),
        "index_extra_edges": index_extra_edges,
    }
    sites = {"island:" + m: m for m in islands}
    sites.update({"unknown:" + m: m for m in unknown_mods})
    sites.update({"shim:" + m: m for m in shims})
    sites.update({"index-edge:" + e: e for e in index_extra_edges})
    sites.update({"test-only:" + m: m for m in test_only})
    sites.update({"dark-switch:" + n: w for n, w in dark.items()})
    sites.update({"doc-drift:" + k: w for k, w in doc_drift.items()})
    sites.update({"unparsable:" + m: m for m in unparsable})
    return ScanResult(state=state, sites=sites, reach=reach_report,
                      switches=switch_report)


# --------------------------------------------------------------------------
# acceptances
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Acceptance:
    item: str
    why: str
    since: str
    until: str
    who: str = ""
    problem: str = ""      # non-empty => malformed, never suppresses

    @property
    def valid(self) -> bool:
        return not self.problem

    def expired(self, today: date) -> bool:
        try:
            return today > date.fromisoformat(self.until)
        except ValueError:
            return True

    def as_dict(self) -> dict:
        out = {"item": self.item, "why": self.why,
               "since": self.since, "until": self.until}
        if self.who:
            out["who"] = self.who
        return out


def parse_acceptances(raw, *, today: date | None = None) -> list[Acceptance]:
    """Fail closed: anything we cannot fully validate is kept, marked with a
    ``problem``, and suppresses nothing. A typo in an acceptance must never be
    the thing that makes an island invisible.

    ``today`` binds the horizon to the CALENDAR. Without it the only rule is
    ``until - since <= MAX_HORIZON_DAYS``, which a pair of dates in 2999
    satisfies while suppressing forever; the cap measured the acceptance
    against itself and nothing measured it against now. Omitting ``today``
    keeps the date-shape and horizon checks and skips only that one, so a
    caller that genuinely has no clock (``--accept`` validating a candidate
    before writing it) still gets everything else.
    """
    out: list[Acceptance] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            out.append(Acceptance(item="<malformed>", why="", since="", until="",
                                  problem="entry is not an object"))
            continue
        item = str(entry.get("item", "")).strip()
        why = str(entry.get("why", "")).strip()
        since = str(entry.get("since", "")).strip()
        until = str(entry.get("until", "")).strip()
        who = str(entry.get("who", "")).strip()
        problems = []
        if not item:
            problems.append("missing 'item'")
        if len(why) < MIN_WHY_CHARS:
            problems.append(
                f"'why' must be at least {MIN_WHY_CHARS} characters -- say what "
                f"has to happen, not that it is known")
        try:
            d_since = date.fromisoformat(since)
        except ValueError:
            d_since = None
            problems.append("'since' must be an ISO date (YYYY-MM-DD)")
        try:
            d_until = date.fromisoformat(until)
        except ValueError:
            d_until = None
            problems.append("'until' must be an ISO date (YYYY-MM-DD)")
        if d_since and today and d_since > today:
            problems.append(
                f"'since' is {(d_since - today).days} days in the future -- an "
                f"acceptance that has not started yet never expires either; "
                f"date it from the day somebody actually looked away")
        if d_since and d_until:
            if d_until < d_since:
                problems.append("'until' is before 'since'")
            elif d_until - d_since > timedelta(days=MAX_HORIZON_DAYS):
                problems.append(
                    f"horizon is {(d_until - d_since).days} days; the cap is "
                    f"{MAX_HORIZON_DAYS} -- an acceptance nobody has to retype "
                    f"is a permanent one wearing a date")
        out.append(Acceptance(item=item, why=why, since=since, until=until,
                              who=who, problem="; ".join(problems)))
    return sorted(out, key=lambda a: (a.item, a.until, a.since))


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

@dataclass
class DriftItem:
    kind: str
    key: str            # stable, greppable, category-independent
    subject: str
    detail: str
    remedy: str
    accepted: bool = False
    note: str = ""

    @property
    def blocking(self) -> bool:
        if self.kind in NON_BLOCKING_KINDS:
            return False
        return not self.accepted

    def as_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "subject": self.subject,
                "detail": self.detail, "remedy": self.remedy,
                "accepted": self.accepted, "note": self.note}


@dataclass
class DriftReport:
    ok: bool
    first_run: bool
    snapshot_path: str
    items: list[DriftItem] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    wrote_snapshot: bool = False
    # Which tree the SNAPSHOT was generated against, versus the one just
    # scanned. Reported, never blocking: a baseline taken one commit ago is not
    # a defect, and a gate that goes red on every commit is a gate people
    # switch off. The consumers that RANK WORK out of these lists are the ones
    # that must fail closed on it -- see :func:`snapshot_freshness`.
    freshness: dict = field(default_factory=dict)

    @property
    def blocking(self) -> list[DriftItem]:
        return [i for i in self.items if i.blocking]

    @property
    def counts(self) -> dict:
        out: dict[str, int] = {}
        for i in self.items:
            out[i.kind] = out.get(i.kind, 0) + 1
        return dict(sorted(out.items()))

    def render(self) -> str:
        lines: list[str] = []
        counts = self.state.get("counts", {})
        head = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        if self.first_run:
            if self.wrote_snapshot:
                lines.append(f"architecture drift: FIRST RUN -- recorded "
                             f"{self.snapshot_path}")
            else:
                lines.append(f"architecture drift: NO BASELINE -- "
                             f"{self.snapshot_path} does not exist")
            lines.append(f"  {head}")
            lines.append("")
            for label, key in (("islands", "islands"),
                               ("unknown (nothing reaches them, and the "
                                "scanner will not guess)", "unknown"),
                               ("shims nothing reaches", "shims"),
                               ("reached only by tests", "test_only"),
                               ("dark switches", "dark_switches")):
                vals = self.state.get(key, [])
                verb = "recorded" if self.wrote_snapshot else "found"
                lines.append(f"  {label} {verb} ({len(vals)}):")
                for v in vals:
                    lines.append(f"    - {v}")
                if not vals:
                    lines.append("    (none)")
            lines.append("")
            if self.wrote_snapshot:
                lines.append("  Nothing is failing: this run only established the baseline.")
                lines.append("  Commit the snapshot -- from here on, every change to these")
                lines.append("  numbers has to be explained in a diff.")
            else:
                lines.append("  NOTHING WAS COMPARED. There is no baseline to compare")
                lines.append("  against, and a gate that reports OK against nothing is the")
                lines.append("  exact failure this subsystem exists to prevent.")
                lines.append("  Record one explicitly: `daedalus map` (writes the page too)")
                lines.append("  or `python -m daedalus.mapping.drift --init`.")
            return "\n".join(lines)

        status = "OK" if self.ok else "FAILED"
        lines.append(f"architecture drift: {status} -- {self.snapshot_path}")
        lines.append(f"  now: {head}")
        if self.freshness and not self.freshness.get("fresh"):
            lines.append(f"  baseline freshness: {self.freshness.get('reason')}")
            lines.append("    (advisory here; a consumer that ranks work out of "
                         "this snapshot must treat it as untrusted)")
        if not self.items:
            lines.append("  no drift against the snapshot.")
            return "\n".join(lines)

        for kind in KIND_ORDER:
            group = [i for i in self.items if i.kind == kind]
            if not group:
                continue
            lines.append("")
            lines.append(f"{kind} ({len(group)})")
            for item in sorted(group, key=lambda i: i.key):
                mark = "  ~ " if item.accepted else ("  ! " if item.blocking else "  + ")
                lines.append(f"{mark}{item.subject}")
                if item.detail:
                    lines.append(f"      {item.detail}")
                if item.note:
                    lines.append(f"      {item.note}")
                lines.append(f"      -> {item.remedy}")
        lines.append("")
        n_block = len(self.blocking)
        if not n_block:
            lines.append("Nothing blocking.")
            return "\n".join(lines)

        lines.append(f"{n_block} blocking. Each one is: wire it, document it, "
                     f"delete it, or accept it explicitly.")
        acceptable = [i for i in self.blocking if i.kind in ACCEPTABLE_KINDS]
        if acceptable:
            example = sorted(i.key for i in acceptable)[0]
            lines.append(f"  To accept temporarily, add to \"acceptances\" in "
                         f"{self.snapshot_path}:")
            lines.append(f'    {{"item": "{example}", "why": "<what has to happen>",')
            lines.append('     "since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "who": "<name>"}')
            lines.append(f"  'since' may not be in the future and 'until' may be at most "
                         f"{MAX_HORIZON_DAYS} days after 'since';")
            lines.append("  the item comes back when it passes.")
            lines.append("  To accept permanently, delete any acceptance for it and re-baseline")
            lines.append("  (--refresh); the count moves in the committed diff where it is reviewed.")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# snapshot i/o
# --------------------------------------------------------------------------

_SNAPSHOT_NOTE = (
    "GENERATED by daedalus.mapping.drift -- do not hand-edit anything except "
    "'acceptances'; every other field, INCLUDING repo_state, is covered by "
    "'digest'. Regenerate with: python -m daedalus.mapping.drift --refresh"
)

DIGEST_KEY = "digest"
_MECHANICAL_KEYS = ("schema", "repo_state", "counts", "ignore", "modules",
                    "islands", "unknown", "shims", "test_only", "dark_switches",
                    "doc_drift", "unparsable", "index_extra_edges")


def _digest(doc: dict) -> str:
    """A hash over the mechanical half only.

    ``acceptances`` is excluded because it is the one part a human is SUPPOSED
    to write; ``note`` because it is a constant. Canonical JSON with sorted
    keys, so the digest is a function of the values and not of the writer's
    key order -- two runs over an unchanged tree still produce identical bytes.

    ``repo_state`` is INSIDE, and that is not an accident. It is the field that
    says which tree was scanned, and a freshness stamp anybody can rewrite
    without invalidating the signature is decorative. The cost is that the
    digest changes on every commit even when no list moved -- which is correct:
    the snapshot really does describe a different tree.
    """
    body = {k: doc.get(k) for k in _MECHANICAL_KEYS}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def digest_ok(doc) -> bool:
    """Does this snapshot's own digest still cover its own mechanical lists?

    Public because it is not only :func:`check`'s business. Any verb that
    INHERITS lists from an existing snapshot rather than rescanning has to ask
    this first and refuse on a mismatch -- otherwise it re-signs whatever a text
    editor left behind and turns a caught hand-edit into a valid baseline.
    ``daedalus map --accept`` is exactly such a verb.
    """
    if not isinstance(doc, dict) or doc.get("__error__"):
        return False
    return doc.get(DIGEST_KEY) == _digest(doc)


def snapshot_bytes(state: dict, acceptances: Sequence[Acceptance]) -> str:
    """The exact text of the snapshot. Sorted, no timestamps, trailing newline:
    two runs over an unchanged tree must produce byte-identical output or the
    git diff -- the thing a human actually reads -- becomes noise.

    ``repo_state`` comes out of ``state``, not out of a probe taken here, so
    this stays a pure function of its arguments. A clock reading would not:
    ``generated_at`` is absent from this artifact on purpose, because the
    question worth answering is "which tree" (``repo_state.head``, stable
    across a no-op regeneration) and not "at what o'clock" (different on every
    run, and therefore a diff on every run).
    """
    doc = {
        "schema": SCHEMA_VERSION,
        "note": _SNAPSHOT_NOTE,
        "repo_state": dict(sorted((state.get("repo_state") or {}).items())),
        "counts": dict(sorted(state.get("counts", {}).items())),
        "ignore": dict(sorted((state.get("ignore") or {}).items())),
        "modules": sorted(state.get("modules", [])),
        "islands": sorted(state.get("islands", [])),
        "unknown": sorted(state.get("unknown", [])),
        "shims": sorted(state.get("shims", [])),
        "test_only": sorted(state.get("test_only", [])),
        "dark_switches": sorted(state.get("dark_switches", [])),
        "doc_drift": sorted(state.get("doc_drift", [])),
        "unparsable": sorted(state.get("unparsable", [])),
        "index_extra_edges": sorted(state.get("index_extra_edges", [])),
        "acceptances": [a.as_dict() for a in acceptances],
    }
    doc[DIGEST_KEY] = _digest(doc)
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def load_snapshot(path) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"__error__": str(exc)}


def write_snapshot(path, state: dict, acceptances: Sequence[Acceptance] = ()) -> str:
    """Write the baseline, EXCLUDING every item that has an acceptance entry.

    This exclusion is the load-bearing part. If an accepted island were baked
    into ``islands``, ``--refresh`` would silently become a third, undated way
    to accept -- and being the easiest one, it would be the only one anybody
    used. Keeping accepted items out of the baseline means they stay live
    drift, suppressed only for as long as their date holds.
    """
    accepted_keys = {a.item for a in acceptances}

    def keep(prefix: str, key: str) -> list[str]:
        return [v for v in state.get(key, []) if prefix + v not in accepted_keys]

    kept = dict(state)
    kept["islands"] = keep("island:", "islands")
    kept["unknown"] = keep("unknown:", "unknown")
    kept["shims"] = keep("shim:", "shims")
    unreached = set(kept["islands"]) | set(kept["unknown"]) | set(kept["shims"])
    kept["test_only"] = [m for m in keep("test-only:", "test_only")
                         if m in unreached]
    kept["dark_switches"] = keep("dark-switch:", "dark_switches")
    kept["doc_drift"] = keep("doc-drift:", "doc_drift")
    kept["unparsable"] = keep("unparsable:", "unparsable")
    kept["index_extra_edges"] = keep("index-edge:", "index_extra_edges")
    kept["counts"] = {
        "modules": len(kept.get("modules", [])),
        "unreached": len(unreached),
        "islands": len(kept["islands"]),
        "unknown": len(kept["unknown"]),
        "shims": len(kept["shims"]),
        "test_only": len(kept["test_only"]),
        "dark_switches": len(kept["dark_switches"]),
        "doc_drift": len(kept["doc_drift"]),
        "unparsable": len(kept["unparsable"]),
        "index_extra_edges": len(kept["index_extra_edges"]),
    }
    text = snapshot_bytes(kept, acceptances)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    return text


# --------------------------------------------------------------------------
# the comparison
# --------------------------------------------------------------------------

def _remedy(kind: str, subject: str) -> str:
    if kind == NEW_ISLAND:
        return ("wire it (import it from a package __init__, a CLI command or an "
                "entrypoint), delete it, or accept it with a date")
    if kind == BECAME_ISLAND:
        return ("find the caller that was deleted or renamed -- either restore the "
                "wiring or delete the module it used to reach")
    if kind == NEW_UNKNOWN:
        return ("nothing reaches it and the scanner will not guess: resolve the "
                "ambiguity. Import it for real (not in a dead branch and not "
                "behind a swallowed ImportError), delete it, or accept it with "
                "a date -- 'a string somewhere names it' is not wiring")
    if kind == NEW_SHIM:
        return ("a re-export nothing reaches: delete the forward and update the "
                "callers, wire it from a real entry point, or accept it with a "
                "date. A shim that forwards for nobody is dead code with a "
                "compatibility story attached")
    if kind == ENGINE_DISAGREEMENT:
        return ("the structural index carries this import edge and the "
                "reachability walk refused it (a dead branch, a swallowed "
                "ImportError, or a resolution the two engines read "
                "differently). Make them agree: the edge is NOT counted as "
                "reachability by either the page or this gate while they do not")
    if kind == TEST_ONLY:
        return ("not blocking: a test is evidence somebody intends to wire it. "
                "Wire it from a real entry point, or delete it -- this count is "
                "the one that grew to 55 the last time nobody watched it")
    if kind == NEW_DARK_SWITCH:
        return (f"document {subject} in docs/ -- outside a code fence, in a form "
                f"an operator would type, and with a sentence saying what it "
                f"turns on -- give it an on-by-default value, or delete the gate")
    if kind == VANISHED:
        return ("expected if you deleted it -- re-baseline (--refresh) so the "
                "snapshot stops claiming it exists")
    if kind == UNPARSABLE:
        return ("fix the syntax: neither engine can see inside it, so every "
                "island, switch and edge it holds is invisible to this gate")
    if kind == DOC_DRIFT:
        return ("make the docs and the code agree: document the name, or delete "
                "the stale mention")
    if kind == STALE_ACCEPTANCE:
        return "delete this acceptance -- what it was covering is gone"
    if kind == INVALID_ACCEPTANCE:
        return "fix the acceptance; while it is malformed it suppresses nothing"
    if kind == NOW_REACHED:
        return "nothing to do -- re-baseline (--refresh) to bank it"
    if kind == IGNORE_DRIFT:
        return ("re-run without the narrowing, or re-baseline under the new "
                "configuration so the snapshot records what was excluded")
    if kind == INVALID_SNAPSHOT:
        return ("the snapshot is unreadable, hand-edited or self-inconsistent; "
                "re-baseline (--refresh) after checking what changed")
    return "review"


def check(repo_root, snapshot_path=None, *, today: date | None = None,
          index=None, write_missing: bool = False, reach_report=None,
          switch_report=None, probe_dirty: bool = True) -> DriftReport:
    """Compare the generated state against the committed snapshot.

    A missing snapshot FAILS unless ``write_missing`` is set, which is the
    explicit "record a baseline" action rather than the default. The previous
    default -- write it and report OK -- meant ``rm docs/architecture-state
    .json`` was a green run, and a green run against nothing is exactly what
    this file exists to make impossible.
    """
    root = Path(repo_root).resolve()
    snap_path = Path(snapshot_path) if snapshot_path else root / SNAPSHOT_REL
    today = today or date.today()

    result = scan(root, index=index, reach_report=reach_report,
                  switch_report=switch_report, probe_dirty=probe_dirty)
    state = result.state

    snapshot = load_snapshot(snap_path)
    if snapshot is None:
        wrote = False
        if write_missing:
            write_snapshot(snap_path, state, ())
            wrote = True
        return DriftReport(ok=wrote, first_run=True, snapshot_path=str(snap_path),
                           items=[], state=state, snapshot={}, wrote_snapshot=wrote)

    items: list[DriftItem] = []

    err = snapshot.get("__error__")
    if err:
        items.append(DriftItem(
            kind=INVALID_SNAPSHOT, key="snapshot:unreadable",
            subject=str(snap_path), detail=f"could not be parsed: {err}",
            remedy=_remedy(INVALID_SNAPSHOT, "")))
        return DriftReport(ok=False, first_run=False, snapshot_path=str(snap_path),
                           items=items, state=state, snapshot={})

    acceptances = parse_acceptances(snapshot.get("acceptances"), today=today)

    stored_schema = snapshot.get("schema")
    if stored_schema != SCHEMA_VERSION:
        items.append(DriftItem(
            kind=INVALID_SNAPSHOT, key="snapshot:schema",
            subject=f"schema {stored_schema!r}",
            detail=f"this build writes and compares schema {SCHEMA_VERSION}; the "
                   f"lists in a schema-{stored_schema!r} snapshot were derived by "
                   f"a different engine and do not mean the same thing",
            remedy=_remedy(INVALID_SNAPSHOT, "")))
        return DriftReport(ok=False, first_run=False, snapshot_path=str(snap_path),
                           items=items, state=state, snapshot=snapshot)

    # ---- integrity: was anything hand-edited? ------------------------------
    stored_digest = snapshot.get(DIGEST_KEY)
    recomputed = _digest(snapshot)
    if stored_digest != recomputed:
        items.append(DriftItem(
            kind=INVALID_SNAPSHOT, key="snapshot:digest",
            subject=DIGEST_KEY,
            detail=("the mechanical lists do not match the digest written with "
                    "them: something was hand-edited. Pre-seeding an item into "
                    "'islands' or 'dark_switches' is not a way to accept it -- "
                    "an acceptance is dated and an acceptance is reviewed"),
            remedy=_remedy(INVALID_SNAPSHOT, "")))

    old_modules = set(snapshot.get("modules") or [])
    old_islands = set(snapshot.get("islands") or [])
    old_unknown = set(snapshot.get("unknown") or [])
    old_shims = set(snapshot.get("shims") or [])
    old_test_only = set(snapshot.get("test_only") or [])
    old_dark = set(snapshot.get("dark_switches") or [])
    old_drift = set(snapshot.get("doc_drift") or [])
    old_unparsable = set(snapshot.get("unparsable") or [])
    old_index_extra = set(snapshot.get("index_extra_edges") or [])

    stored_counts = snapshot.get("counts") or {}
    real_counts = {"modules": len(old_modules), "islands": len(old_islands),
                   "unknown": len(old_unknown), "shims": len(old_shims),
                   "unreached": len(old_islands | old_unknown | old_shims),
                   "test_only": len(old_test_only),
                   "dark_switches": len(old_dark), "doc_drift": len(old_drift),
                   "unparsable": len(old_unparsable),
                   "index_extra_edges": len(old_index_extra)}
    for key, real in real_counts.items():
        if key in stored_counts and stored_counts[key] != real:
            # The exact failure this whole module exists to prevent: a number
            # in an artifact that no longer matches the list beside it.
            items.append(DriftItem(
                kind=INVALID_SNAPSHOT, key=f"snapshot:counts.{key}",
                subject=f"counts.{key}",
                detail=f"snapshot says {stored_counts[key]}, its own "
                       f"'{key}' list has {real}",
                remedy=_remedy(INVALID_SNAPSHOT, "")))

    new_modules = set(state["modules"])
    new_islands = set(state["islands"])
    new_unknown = set(state["unknown"])
    new_shims = set(state["shims"])
    # Everything no entry point reaches, whatever class reach gave it. Used for
    # the good-news direction: a module that merely moved from one unreached
    # class to another has NOT been reached, and saying so was the bug.
    new_unreached = new_islands | new_unknown | new_shims
    new_test_only = set(state["test_only"])
    new_dark = set(state["dark_switches"])
    new_drift = set(state["doc_drift"])
    new_unparsable = set(state["unparsable"])
    new_index_extra = set(state["index_extra_edges"])

    # ---- integrity: do the lists name things that exist? -------------------
    # A count matching its own list proves only internal arithmetic. These
    # check the lists against reality and against each other, so an entry
    # cannot be pre-seeded to suppress a finding that has not landed yet.
    phantom_islands = sorted(old_islands - old_modules)
    if phantom_islands:
        items.append(DriftItem(
            kind=INVALID_SNAPSHOT, key="snapshot:islands.not-a-module",
            subject="islands",
            detail=f"lists {len(phantom_islands)} entr"
                   f"{'y' if len(phantom_islands) == 1 else 'ies'} that its own "
                   f"'modules' list does not contain: "
                   f"{', '.join(phantom_islands[:5])}",
            remedy=_remedy(INVALID_SNAPSHOT, "")))
    for list_key in ("unknown", "shims"):
        phantom = sorted(set(snapshot.get(list_key) or []) - old_modules)
        if phantom:
            items.append(DriftItem(
                kind=INVALID_SNAPSHOT, key=f"snapshot:{list_key}.not-a-module",
                subject=list_key,
                detail=f"lists {len(phantom)} entr"
                       f"{'y' if len(phantom) == 1 else 'ies'} that its own "
                       f"'modules' list does not contain: "
                       f"{', '.join(phantom[:5])}",
                remedy=_remedy(INVALID_SNAPSHOT, "")))
    phantom_test_only = sorted(old_test_only - (old_islands | old_unknown
                                                | old_shims))
    if phantom_test_only:
        items.append(DriftItem(
            kind=INVALID_SNAPSHOT, key="snapshot:test_only.not-an-island",
            subject="test_only",
            detail=f"lists {', '.join(phantom_test_only[:5])}, which none of its "
                   f"own 'islands', 'unknown' or 'shims' lists contains -- every "
                   f"test-only module is an unreached module first",
            remedy=_remedy(INVALID_SNAPSHOT, "")))

    read_names = {sw.name for sw in result.switches.env_switches}
    phantom_dark = sorted(old_dark - read_names)
    if phantom_dark:
        items.append(DriftItem(
            kind=INVALID_SNAPSHOT, key="snapshot:dark_switches.unread",
            subject="dark_switches",
            detail=f"names {', '.join(phantom_dark[:5])}, which no module in "
                   f"the tree reads from the environment -- a switch cannot be "
                   f"baselined before the code that reads it exists",
            remedy=_remedy(INVALID_SNAPSHOT, "")))

    # An accepted island is deliberately absent from the baseline
    # (:func:`write_snapshot`), so the baseline alone would read it as
    # "reached" and call it BECAME ISLAND the moment the module also appears in
    # ``modules``. The acceptance is itself a record that it is an island, so
    # it counts toward what the snapshot knows -- without suppressing anything.
    accepted_keys = {a.item for a in acceptances}
    # What the BASELINE actually establishes. Intersecting with ``modules`` is
    # the teeth behind the subset rule above: an island entry the snapshot's own
    # module list does not back is a hand-edit, and a hand-edit must not be able
    # to suppress the finding it was written to hide.
    baselined_islands = old_islands & old_modules
    # BECAME ISLAND means "it was REACHED and is not any more". A module the
    # snapshot recorded as unknown or as an unreached shim was never reached, so
    # it must not be described that way when it degrades into an island.
    known_unreached = ((old_islands | old_unknown | old_shims) & old_modules) | {
        k.split(":", 1)[1] for k in accepted_keys
        if k.split(":", 1)[0] in ("island", "unknown", "shim")}

    for mod in sorted(new_islands):
        tested = mod in new_test_only
        if mod in baselined_islands:
            # Already baselined as an island. The one thing that can still have
            # moved is its cover: it had a test in the snapshot and does not now.
            if not tested and mod in old_test_only:
                items.append(DriftItem(
                    kind=NEW_ISLAND, key="island:" + mod, subject=mod,
                    detail="was an island covered by a test in the snapshot; "
                           "nothing touches it at all now",
                    remedy=_remedy(NEW_ISLAND, mod)))
            continue
        if tested:
            items.append(DriftItem(
                kind=TEST_ONLY, key="test-only:" + mod, subject=mod,
                detail="nothing reaches it from any entry point; only its own "
                       "tests import it",
                remedy=_remedy(TEST_ONLY, mod)))
            continue
        was_reached = mod in old_modules and mod not in known_unreached
        kind = BECAME_ISLAND if was_reached else NEW_ISLAND
        detail = ("nothing reaches it from any entrypoint, and no test imports "
                  "it either" if kind == NEW_ISLAND else
                  "it was reachable in the snapshot and is not any more")
        items.append(DriftItem(kind=kind, key="island:" + mod, subject=mod,
                               detail=detail, remedy=_remedy(kind, mod)))

    # ---- the other two unreached classes -----------------------------------
    # Same shape as islands, deliberately not merged into them: the finding a
    # reader gets has to say WHICH kind of unreached this is, because the three
    # remedies are three different sentences. What they share is the property
    # that used to be missing entirely -- a module nothing reaches is COUNTED,
    # is named, and blocks until somebody explains it.
    for list_key, prefix, kind, old_set, why in (
            ("unknown", "unknown:", NEW_UNKNOWN, old_unknown,
             "nothing reaches it from any entry point; the only thing that "
             "names it is a string literal, or an import in a place where the "
             "import is no proof anything runs it"),
            ("shims", "shim:", NEW_SHIM, old_shims,
             "a module that only re-exports, and nothing reaches it from any "
             "entry point -- it forwards for nobody")):
        baselined = old_set & old_modules
        for mod in sorted(state[list_key]):
            if mod in baselined:
                if mod not in new_test_only and mod in old_test_only:
                    items.append(DriftItem(
                        kind=kind, key=prefix + mod, subject=mod,
                        detail="was covered by a test in the snapshot; nothing "
                               "touches it at all now",
                        remedy=_remedy(kind, mod)))
                continue
            if mod in new_test_only:
                items.append(DriftItem(
                    kind=TEST_ONLY, key="test-only:" + mod, subject=mod,
                    detail="nothing reaches it from any entry point; only its "
                           "own tests import it",
                    remedy=_remedy(TEST_ONLY, mod)))
                continue
            items.append(DriftItem(kind=kind, key=prefix + mod, subject=mod,
                                   detail=why, remedy=_remedy(kind, mod)))

    # ---- the two engines disagreeing about the import graph ----------------
    for edge in sorted(new_index_extra - old_index_extra):
        items.append(DriftItem(
            kind=ENGINE_DISAGREEMENT, key="index-edge:" + edge, subject=edge,
            detail="the structural index has this import edge and the "
                   "reachability walk does not. It is reported, never merged: "
                   "merging it is how a dead-branch import used to make its "
                   "target 'reachable'",
            remedy=_remedy(ENGINE_DISAGREEMENT, edge)))

    # ---- the good-news direction -------------------------------------------
    # ``new_unreached``, not ``new_islands``: a module that moved from island to
    # shim (or to unknown) is still reached by nothing, and announcing "something
    # reaches it now" would be the same false-green in a new costume.
    for prefix, old_set in (("island:", old_islands), ("unknown:", old_unknown),
                            ("shim:", old_shims)):
        for mod in sorted(old_set & new_modules):
            if mod not in new_unreached:
                items.append(DriftItem(
                    kind=NOW_REACHED, key=prefix + mod, subject=mod,
                    detail="nothing reached it in the snapshot; something "
                           "reaches it now",
                    remedy=_remedy(NOW_REACHED, mod)))

    for mod in sorted(old_modules - new_modules):
        items.append(DriftItem(
            kind=VANISHED, key="vanished:" + mod, subject=mod,
            detail="in the snapshot, not on disk",
            remedy=_remedy(VANISHED, mod)))

    for name in sorted(new_dark - old_dark):
        items.append(DriftItem(
            kind=NEW_DARK_SWITCH, key="dark-switch:" + name, subject=name,
            detail=f"off-by-default env gate at "
                   f"{result.sites.get('dark-switch:' + name, '?')}, "
                   f"introduced in no document",
            remedy=_remedy(NEW_DARK_SWITCH, name)))

    for mod in sorted(new_unparsable - old_unparsable):
        items.append(DriftItem(
            kind=UNPARSABLE, key="unparsable:" + mod, subject=mod,
            detail="could not be parsed, so it contributed no imports and no "
                   "switches to this run",
            remedy=_remedy(UNPARSABLE, mod)))

    for entry in sorted(new_drift - old_drift):
        side, _, name = entry.partition(":")
        detail = {
            "code-only": "the code reads it; no document mentions it",
            "doc-only": "documented, but no code reads it any more",
        }.get(side, "the docs and the code name it two different ways")
        items.append(DriftItem(
            kind=DOC_DRIFT, key="doc-drift:" + entry, subject=name,
            detail=detail, remedy=_remedy(DOC_DRIFT, name)))

    # ---- the ignore configuration -----------------------------------------
    # An ABSENT key reads as "nothing was excluded", not as "do not check".
    # Deleting the field must not be a quieter way to narrow the run than
    # setting the variable was.
    old_ignore = snapshot.get("ignore")
    if not isinstance(old_ignore, dict):
        old_ignore = {"env": "", "file": ""}
    new_ignore = state["ignore"]
    if old_ignore != new_ignore:
        items.append(DriftItem(
            kind=IGNORE_DRIFT, key="ignore:config",
            subject=_describe_ignore(new_ignore),
            detail=f"the baseline was taken under {_describe_ignore(old_ignore)}. "
                   f"A run that looks at less of the tree than the baseline did "
                   f"cannot be compared with it, and a green result from one "
                   f"must never be indistinguishable from a green result from "
                   f"the other",
            remedy=_remedy(IGNORE_DRIFT, "")))

    # ---- apply acceptances -------------------------------------------------
    # Only ACCEPTABLE_KINDS count as a match. An acceptance still sitting on an
    # island that has since been wired matches a NOW REACHED item, and must go
    # stale rather than quietly ride along on the good news.
    by_key: dict[str, list[DriftItem]] = {}
    for item in items:
        if item.kind in ACCEPTABLE_KINDS:
            by_key.setdefault(item.key, []).append(item)

    for acc in acceptances:
        matched = by_key.get(acc.item, [])
        if not acc.valid:
            items.append(DriftItem(
                kind=INVALID_ACCEPTANCE, key="acceptance:" + acc.item,
                subject=acc.item, detail=acc.problem,
                remedy=_remedy(INVALID_ACCEPTANCE, acc.item)))
            for item in matched:
                item.note = f"an acceptance exists for this but is invalid: {acc.problem}"
            continue
        if acc.expired(today):
            for item in matched:
                item.note = (f"acceptance EXPIRED on {acc.until} (accepted "
                             f"{acc.since}{' by ' + acc.who if acc.who else ''}: "
                             f"\"{acc.why}\") -- the reason outlived its horizon")
            if not matched:
                items.append(DriftItem(
                    kind=STALE_ACCEPTANCE, key="acceptance:" + acc.item,
                    subject=acc.item,
                    detail=f"expired {acc.until} and matches nothing on this run",
                    remedy=_remedy(STALE_ACCEPTANCE, acc.item)))
            continue
        if not matched:
            items.append(DriftItem(
                kind=STALE_ACCEPTANCE, key="acceptance:" + acc.item,
                subject=acc.item,
                detail=f"accepted until {acc.until}, but nothing on this run "
                       f"matches it -- it was fixed, deleted, or is already "
                       f"recorded in the baseline",
                remedy=_remedy(STALE_ACCEPTANCE, acc.item)))
            continue
        for item in matched:
            item.accepted = True
            item.note = (f"accepted until {acc.until}"
                         f"{' by ' + acc.who if acc.who else ''}: \"{acc.why}\"")

    ok = not any(i.blocking for i in items)
    return DriftReport(ok=ok, first_run=False, snapshot_path=str(snap_path),
                       items=items, state=state, snapshot=snapshot,
                       freshness=snapshot_freshness(
                           snapshot,
                           actual_head=(state.get("repo_state") or {}).get("head")))


def refresh(repo_root, snapshot_path=None, *, index=None, reach_report=None,
            switch_report=None, probe_dirty: bool = True) -> str:
    """Re-baseline. Acceptances are carried forward verbatim -- refreshing is
    never a way to quietly drop somebody's stated reason."""
    root = Path(repo_root).resolve()
    snap_path = Path(snapshot_path) if snapshot_path else root / SNAPSHOT_REL
    result = scan(root, index=index, reach_report=reach_report,
                  switch_report=switch_report, probe_dirty=probe_dirty)
    old = load_snapshot(snap_path) or {}
    acceptances = parse_acceptances(old.get("acceptances"))
    return write_snapshot(snap_path, result.state, acceptances)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="daedalus.mapping.drift",
        description="Compare the generated architecture map against the "
                    "committed snapshot. CI gate, not a pre-commit hook: it "
                    "parses the whole tree and takes seconds.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--refresh", action="store_true",
                    help="re-baseline the snapshot from the current state")
    ap.add_argument("--init", action="store_true",
                    help="write the FIRST baseline. Explicit on purpose: a "
                         "missing snapshot fails, so deleting it is never a "
                         "green run")
    args = ap.parse_args(argv)

    root = Path(args.repo).resolve()
    snap = Path(args.snapshot) if args.snapshot else root / SNAPSHOT_REL
    try:
        from daedalus.structcore import cached_index
        index = cached_index(str(root))
    except Exception:
        index = None

    if args.refresh or args.init:
        # The comparison gate below stays fail-open read-only inspection;
        # baseline writes start at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "cli.mapping_drift",
            REGISTRY_BY_ID["cli.mapping_drift"].effects,
            (process_guard_boundary_decision(),),
        )
    if args.refresh:
        refresh(root, snap, index=index)
        print(f"architecture drift: re-baselined {snap}")
        return 0

    if args.init:
        if snap.is_file():
            print(f"architecture drift: {snap} already exists -- use --refresh "
                  f"to re-baseline it, so the move shows up in a diff")
            return 1
        report = check(root, snap, index=index, write_missing=True)
        print(report.render())
        return 0

    report = check(root, snap, index=index)
    print(report.render())
    if report.first_run:
        # Fail CLOSED, matching `daedalus map --check`. This used to write the
        # baseline and exit 0, which made `rm docs/architecture-state.json` a
        # green run through a door reach.py itself classifies as an entry point.
        return 1
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
