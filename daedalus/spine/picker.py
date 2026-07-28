"""spine/picker.py -- the measurement-sorted work queue, and ``daedalus improve``.

The loop is: PICK a task by measurement -> attempt it in an isolated worktree
(:mod:`daedalus.spine.attempt`) -> run gates -> hand a HUMAN a patch. This
module is the first and last step: it decides what is worth attempting, and it
renders the review packet a human reads before deciding to promote anything.

NO TASK WITHOUT EVIDENCE
------------------------
Every candidate carries three things and is refused without them:

``reason``    one sentence a human can disagree with,
``score``     a number,
``evidence``  the MEASUREMENT the score was computed from, as data -- the file
              it was read out of, the counts, the recall, the churn.

:func:`_candidate` enforces this: a candidate with an empty reason or empty
evidence raises rather than entering the queue. A queue that can be filled with
opinion is a queue that will be, and an unvalidated metric must never gate
autonomy -- so the metric has to stay auditable all the way to the terminal.

WHAT THE SCORE IS, AND WHAT IT IS NOT
-------------------------------------
``score = BAND + offset``.

The BAND (:data:`SOURCE_BANDS`) is the source's priority. It is a PRIOR, chosen
by a human, not a measurement -- islands before stale artifacts, both before
eval misses, all before hotspots. It is stated here as a constant instead of
being smuggled into a weighting so a reviewer can argue with it directly.

The OFFSET, within ``[0, BAND_SPAN]``, is the measurement: test counts and
entrypoint counts for inventory features, recall shortfall for eval misses,
normalised churn x complexity for hotspots. Two candidates from the same source
are ordered by evidence and nothing else.

Cross-band comparison is therefore NOT a claim that one island beats one
hotspot on evidence. It is the stated priority order. Do not read the ranking
as a measurement of importance; read it as "this source first, and within it,
this measurement".

CHEAP BY DEFAULT
----------------
Sources that require a fresh eval run or a whole-repo structural index are
OFF unless asked for (``--eval``, ``--hotspots``). The default queue is built
from files already on disk, so the picker stays fast enough to run before
every attempt. The honesty cost is stated at the point of use: a clean cheap
eval read means "nothing is RECORDED as missing", never "the eval passes".

NOTHING HERE APPLIES ANYTHING
-----------------------------
:func:`main` can run at most ONE attempt (``--once``), and an attempt produces
inert bytes (see :class:`daedalus.spine.attempt.PatchArtifact`). Promotion is a
separate human act. There is no ``--apply``, and adding one belongs in a
different module with a different review.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "ATTEMPT_INTENT_KIND",
    "ATTEMPT_MEMORY_PENALTY",
    "BAND_SPAN",
    "Candidate",
    "apply_attempt_memory",
    "attempt_history",
    "EXIT_CANDIDATE",
    "EXIT_FAILED",
    "EXIT_NO_CHANGE",
    "EXIT_SOURCE_UNAVAILABLE",
    "INVENTORY_REL_PATH",
    "PickedQueue",
    "SOURCE_BANDS",
    "SOURCE_ORDER",
    "build_queue",
    "eval_baseline_candidates",
    "eval_gate_candidates",
    "hotspot_candidates",
    "instruction_fingerprint",
    "inventory_candidates",
    "inventory_freshness",
    "load_inventory",
    "main",
    "rank",
    "render_queue",
    "review_packet",
]

ROOT = Path(__file__).resolve().parents[2]

INVENTORY_REL_PATH = "docs/FEATURE_INVENTORY.json"

# A git object name as it appears in HEAD / refs / packed-refs.
_SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# The shortest abbreviation a recorded head may use. git's own default floor is
# 7; anything shorter is not an identifier, it is a coincidence waiting to
# happen (a 1-char "prefix" matches ~1 HEAD in 16).
_MIN_ABBREV = 7
_ABBREV_SHA_RE = re.compile(rf"[0-9a-f]{{{_MIN_ABBREV},64}}")

# Source priority. A PRIOR, not a measurement -- see the module docstring.
SOURCE_BANDS: dict[str, float] = {
    "inventory_island": 400.0,
    "inventory_stale": 300.0,
    "eval_miss": 200.0,
    "hotspot": 100.0,
}

# The widest a measurement may move a candidate inside its band. Kept strictly
# smaller than the gap between bands so a measurement can never silently
# reorder the stated priority -- not even into a TIE that the sort's own
# tie-break would then have to settle. If a reorder is wanted, the BAND must be
# edited, which is a visible decision. A test pins this inequality.
BAND_SPAN = 50.0

SOURCE_ORDER: tuple[str, ...] = (
    "inventory_island", "inventory_stale", "eval_miss", "hotspot",
)

DEFAULT_LIMIT = 10

# Exit codes for ``--once``. THREE values, not two, because "a candidate is
# waiting for you" and "the runner changed nothing" are different facts and a
# wrapper that collapses them will eventually report an empty run as a ready
# patch. 0 means, and only ever means, a gated candidate exists.
EXIT_CANDIDATE = 0
EXIT_FAILED = 1
EXIT_NO_CHANGE = 2

# A FOURTH value, for the same reason there are three: "a source could not be
# consulted" and "the sources are healthy and there is no work" are different
# facts, and they were previously indistinguishable to a caller -- both exited 0
# on a dry run and both exited 1 under --once. Automation that cannot tell them
# apart eventually reads a broken adapter as "nothing to do" and goes quiet,
# which is precisely the failure a fail-closed source gate would otherwise
# introduce. 0 still means, and only ever means, that work is waiting.
EXIT_SOURCE_UNAVAILABLE = 3

EXIT_BY_STATE: dict[str, int] = {
    "clean": EXIT_CANDIDATE,
    "no_change": EXIT_NO_CHANGE,
}

# Statuses read out of the inventory's structured feature entries.
STATUS_ISLAND = "island"
STATUS_STALE = "stale"


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _slug(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit].strip("-")
    return slug or "task"


def _short_hash(text: str, n: int = 6) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:n]


def _strs(value: Any) -> tuple[str, ...]:
    """Coerce a possibly-absent, possibly-scalar inventory field to strings.

    Hand-maintained JSON does not have a schema checker standing behind it, so
    every list-shaped field is read defensively: a string where a list was
    expected is a typo, not a reason to drop a real work item.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value if str(v).strip())
    return ()


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else (hi if x > hi else x)


# --------------------------------------------------------------------------- #
# records                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Candidate:
    """One unit of work, with the measurement that put it in the queue.

    ``evidence`` is the audit trail: it names the file the numbers came from
    and carries the numbers themselves, so a human reading the review packet
    can re-derive the score without re-running the picker.
    """

    task_id: str
    source: str
    instruction: str
    reason: str
    score: float
    evidence: Mapping[str, Any] = field(default_factory=dict)
    gate_paths: tuple[str, ...] = ()

    @property
    def band(self) -> float:
        return SOURCE_BANDS.get(self.source, 0.0)

    @property
    def offset(self) -> float:
        """The measured part of the score -- the part that is not a prior."""
        return round(self.score - self.band, 4)

    def to_task_spec(self, base_revision: str | None = None):
        """Build the :class:`daedalus.spine.attempt.TaskSpec` for this candidate.

        Imported lazily: ranking a queue must not drag in the ledger, the
        worktree manager and the storage watermark, so ``--dry-run`` stays a
        read of two JSON files.
        """
        from daedalus.spine.attempt import TaskSpec

        return TaskSpec(
            task_id=self.task_id,
            instruction=self.instruction,
            base_revision=base_revision,
            gate_paths=tuple(self.gate_paths),
            metadata={
                "picker_source": self.source,
                "picker_score": self.score,
                "picker_reason": self.reason,
                "picker_evidence": dict(self.evidence),
            },
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "score": self.score,
            "band": self.band,
            "measured_offset": self.offset,
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "gate_paths": list(self.gate_paths),
            "instruction": self.instruction,
        }


@dataclass(frozen=True)
class PickedQueue:
    """A ranked queue plus what was and was not consulted to build it.

    ``sources`` and ``notes`` exist so an EMPTY queue is still informative. A
    picker that prints nothing when a file is missing teaches the operator that
    there is no work; this one says which file it could not read.
    """

    candidates: tuple[Candidate, ...]
    sources: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.candidates)

    @property
    def top(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def degraded_sources(self) -> tuple[str, ...]:
        """Sources that could NOT be consulted, so an empty queue is explained.

        "The source was withheld or unreadable" and "the sources are healthy and
        there is no work" are different facts, and a caller that cannot tell
        them apart will eventually read a broken adapter as "nothing to do" --
        which is the quiet failure this whole queue exists to avoid. Everything
        here is already visible in ``sources``/``notes`` for a human; this is
        the same fact in a shape a program can branch on.
        """
        bad = []
        for name, detail in sorted(self.sources.items()):
            if not isinstance(detail, Mapping):
                continue
            if detail.get("suppressed") or detail.get("error"):
                bad.append(name)
        return tuple(bad)

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "sources": dict(self.sources),
            "notes": list(self.notes),
            "degraded_sources": list(self.degraded_sources),
        }


class NoEvidence(ValueError):
    """A candidate was constructed without a reason or without evidence."""


def _candidate(*, task_id: str, source: str, instruction: str, reason: str,
               band_offset: float, evidence: Mapping[str, Any],
               gate_paths: Sequence[str] = ()) -> Candidate:
    """Construct a candidate, refusing one that carries no evidence.

    The refusal is a raise, not a skip: an evidence-free candidate is a bug in
    a source function, and silently dropping it would hide the bug while the
    queue quietly got shorter.
    """
    if not str(reason).strip():
        raise NoEvidence(f"candidate {task_id!r} has no reason")
    if not evidence:
        raise NoEvidence(f"candidate {task_id!r} carries no measurement")
    if source not in SOURCE_BANDS:
        raise NoEvidence(f"candidate {task_id!r} has unknown source {source!r}")
    offset = _clamp(float(band_offset), 0.0, BAND_SPAN)
    return Candidate(
        task_id=task_id, source=source, instruction=instruction, reason=reason,
        score=round(SOURCE_BANDS[source] + offset, 4),
        evidence=dict(evidence), gate_paths=tuple(str(p) for p in gate_paths))


# --------------------------------------------------------------------------- #
# source (a): the feature inventory                                            #
# --------------------------------------------------------------------------- #
def load_inventory(path: str | Path | None = None,
                   repo_root: str | Path | None = None) -> dict:
    """Read ``docs/FEATURE_INVENTORY.json``, or ``{}`` if it cannot be read.

    Missing, unreadable, not JSON, or JSON that is not an object all degrade to
    an empty inventory. The picker's job is to rank work, not to be the thing
    that breaks when a docs file is mid-edit -- and an empty queue is a truthful
    answer to "what does this file tell us", where a traceback is not.
    """
    if path is None:
        base = Path(repo_root) if repo_root else ROOT
        path = Path(base) / INVENTORY_REL_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _head_sha(repo_root: str | Path) -> str | None:
    """Current HEAD as a full sha, read STRAIGHT OFF DISK, or ``None``.

    Deliberately NOT ``git rev-parse``. This module spawns no child process at
    all, and ``test_there_is_no_apply_path_in_this_module`` enforces that by
    asserting the process-spawning stdlib module is never so much as NAMED in
    this file -- which is what makes "the picker cannot apply a patch"
    structural rather than a promise in a docstring. Answering "which revision
    am I on" is not worth weakening that for, so HEAD is resolved by reading
    git's own on-disk files.

    Handles the three shapes that occur here: ``.git`` as a directory (primary
    checkout), ``.git`` as a ``gitdir:`` pointer file (linked worktree, where
    refs live in the shared common dir), and a detached HEAD holding a raw sha.
    Anything unrecognised returns ``None``, which callers read as "cannot tell"
    and fail OPEN on -- never as "stale".
    """
    dot_git = Path(repo_root) / ".git"
    git_dir: Path | None = None
    if dot_git.is_dir():
        git_dir = dot_git
    else:
        pointer = _read_text(dot_git) or ""
        if pointer.startswith("gitdir:"):
            candidate = Path(pointer.split(":", 1)[1].strip())
            git_dir = candidate if candidate.is_absolute() else (
                Path(repo_root) / candidate)
    if git_dir is None or not git_dir.is_dir():
        return None

    head = (_read_text(git_dir / "HEAD") or "").strip()
    if not head:
        return None
    if not head.startswith("ref:"):
        return head if _SHA_RE.fullmatch(head) else None

    ref = head.split(":", 1)[1].strip()
    # A linked worktree keeps HEAD locally but shares refs/ through commondir.
    search_dirs = [git_dir]
    common = (_read_text(git_dir / "commondir") or "").strip()
    if common:
        common_path = Path(common)
        search_dirs.append(common_path if common_path.is_absolute()
                           else (git_dir / common_path))
    for base in search_dirs:
        loose = (_read_text(base / ref) or "").strip()
        if loose and _SHA_RE.fullmatch(loose):
            return loose
        packed = _read_text(base / "packed-refs") or ""
        for line in packed.splitlines():
            if line.startswith(("#", "^")):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip() == ref:
                return parts[0].strip()
    return None


def inventory_freshness(inventory: Mapping[str, Any],
                        repo_root: str | Path | None = None) -> dict:
    """Does the inventory describe the tree we are actually standing in?

    ``docs/FEATURE_INVENTORY.json`` is HAND-WRITTEN -- nothing in this repo
    generates it -- and it drives the two highest bands, so a stale one steers
    the whole loop toward work that may no longer exist. It stamps the revision
    it was written against in ``repo_state.head``; this compares that to real
    HEAD by PREFIX, because the file records a short sha and git reports a long
    one, and a mismatch (or an unreadable stamp) means the picker is reasoning
    about a different tree.

    A ``dirty: true`` snapshot is NOT treated as stale on its own: this repo is
    almost always dirty mid-session, and refusing to rank work whenever an
    editor has unsaved changes would make the loop unusable for exactly the
    person using it. The revision is the honest signal; dirtiness is reported
    but does not suppress.

    Fails OPEN (``fresh: True``) when git cannot answer at all -- a tarball
    checkout with no git is not evidence of staleness, and turning "I cannot
    tell" into "refuse everything" would be a worse failure than ranking.
    """
    state = inventory.get("repo_state") if isinstance(inventory, Mapping) else None
    recorded = (str(state.get("head") or "").strip()
                if isinstance(state, Mapping) else "")
    dirty = bool(state.get("dirty")) if isinstance(state, Mapping) else False

    if not isinstance(inventory, Mapping) or not inventory:
        return {"fresh": True, "reason": "no inventory to check",
                "recorded_head": None, "actual_head": None, "dirty": dirty}
    if not recorded:
        return {"fresh": False,
                "reason": "the inventory records no repo_state.head, so it "
                          "cannot be checked against the tree it describes",
                "recorded_head": None, "actual_head": None, "dirty": dirty}
    # A prefix comparison is only meaningful against a real abbreviated sha.
    # Without this, a recorded "a" matches roughly one HEAD in sixteen and the
    # gate silently reports fresh -- a check that passes by accident is worse
    # than no check, because it is believed.
    if not _ABBREV_SHA_RE.fullmatch(recorded):
        return {"fresh": False,
                "reason": (f"the inventory's recorded head {recorded!r} is not "
                           f"an abbreviated git sha (expected at least "
                           f"{_MIN_ABBREV} hex characters), so it cannot be "
                           f"checked against the tree it describes"),
                "recorded_head": recorded, "actual_head": None, "dirty": dirty}

    actual = _head_sha(repo_root or ROOT)
    if actual is None:
        return {"fresh": True,
                "reason": "git could not report HEAD; freshness unknown, "
                          "failing open",
                "recorded_head": recorded, "actual_head": None, "dirty": dirty}

    # ONE direction only: the file records an abbreviation of the full sha git
    # stores, so `actual.startswith(recorded)` is the containment that can be
    # true. Testing the reverse as well would let a SHORTER actual satisfy a
    # longer recorded value, which is not a prefix relationship any git
    # abbreviation produces.
    if actual.startswith(recorded):
        return {"fresh": True, "reason": "inventory matches HEAD",
                "recorded_head": recorded, "actual_head": actual[:len(recorded)],
                "dirty": dirty}
    return {"fresh": False,
            "reason": (f"the inventory was written against {recorded} but HEAD "
                       f"is {actual[:len(recorded)]}"),
            "recorded_head": recorded, "actual_head": actual[:len(recorded)],
            "dirty": dirty}


def _island_instruction(name: str, entrypoints: Sequence[str],
                        tests: Sequence[str], notes: str) -> str:
    where = ", ".join(entrypoints) or "(no entrypoint recorded)"
    test_note = (f"Its tests are {', '.join(tests)}; they must keep passing "
                 f"unchanged -- do not weaken or delete them."
                 if tests else
                 "It has NO recorded tests, so add one that exercises the new "
                 "caller path end to end.")
    return (
        f"Feature {name!r} ({where}) is an ISLAND: it is built but nothing in "
        f"the repo calls it. Either wire it into a real caller so the "
        f"capability is reachable from the CLI / API / harness, or delete it "
        f"and its tests. Do not do both, and do not leave a shim. {test_note} "
        f"Inventory notes: {notes or '(none)'}"
    )


def _stale_instruction(name: str, entrypoints: Sequence[str], notes: str) -> str:
    where = ", ".join(entrypoints) or "(no path recorded)"
    return (
        f"{name!r} ({where}) is recorded as STALE: it is carried in the tree "
        f"but is no longer part of the live system. Remove it, or -- if some "
        f"caller still depends on it -- leave it and correct the inventory "
        f"entry instead. The full test suite is the gate; anything that "
        f"breaks proves the entry was wrong. Inventory notes: {notes or '(none)'}"
    )


def inventory_candidates(inventory: Mapping[str, Any]) -> tuple[
        tuple[Candidate, ...], tuple[str, ...]]:
    """Candidates from the structured ``areas[].features[]`` entries.

    Returns ``(candidates, notes)``. Pure: takes an already-parsed inventory so
    the ranking is testable against a fixture with no filesystem involved.

    ONLY the structured feature entries are used. The top-level ``islands`` /
    ``stale`` arrays are prose -- one string per item, no tests, no
    entrypoints, no area -- which is precisely the "no evidence" case this
    module refuses to queue. They are counted and reported as a note instead,
    so a discrepancy between the prose summary and the structured entries is
    VISIBLE rather than quietly resolved in favour of whichever the picker
    happened to read.
    """
    candidates: list[Candidate] = []
    notes: list[str] = []
    areas = inventory.get("areas")
    if not isinstance(areas, (list, tuple)):
        return (), ("inventory has no 'areas' list; no structured features read",)

    counts = {STATUS_ISLAND: 0, STATUS_STALE: 0}
    for area in areas:
        if not isinstance(area, Mapping):
            continue
        area_name = str(area.get("area") or "unknown area")
        features = area.get("features")
        if not isinstance(features, (list, tuple)):
            continue
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            status = str(feature.get("status") or "").strip().lower()
            if status not in (STATUS_ISLAND, STATUS_STALE):
                continue
            name = str(feature.get("name") or "").strip()
            if not name:
                continue  # unnamed feature: nothing a human could act on
            counts[status] += 1
            tests = _strs(feature.get("tests"))
            entrypoints = _strs(feature.get("entrypoints"))
            notes_text = str(feature.get("notes") or "").strip()
            ident = f"{area_name}|{name}|{status}"
            evidence = {
                "measurement": f"{INVENTORY_REL_PATH} (structured feature entry)",
                "status": status,
                "area": area_name,
                "n_tests": len(tests),
                "tests": list(tests),
                "n_entrypoints": len(entrypoints),
                "entrypoints": list(entrypoints),
                "notes": notes_text,
            }
            if status == STATUS_ISLAND:
                # Measured: a tested island is cheap and safe to wire, because
                # the behaviour is already pinned; an untested one is a
                # research task wearing an engineering task's clothes.
                offset = (30.0 * min(len(tests), 3) / 3.0
                          + 10.0 * min(len(entrypoints), 2) / 2.0)
                candidates.append(_candidate(
                    task_id=f"island-{_slug(name)}-{_short_hash(ident)}",
                    source="inventory_island",
                    instruction=_island_instruction(name, entrypoints, tests,
                                                    notes_text),
                    reason=(f"island in {area_name}: built with "
                            f"{len(tests)} recorded test file(s) and zero "
                            f"callers"),
                    band_offset=offset, evidence=evidence, gate_paths=tests))
            else:
                offset = 10.0 * min(len(entrypoints), 3) / 3.0
                candidates.append(_candidate(
                    task_id=f"stale-{_slug(name)}-{_short_hash(ident)}",
                    source="inventory_stale",
                    instruction=_stale_instruction(name, entrypoints, notes_text),
                    reason=(f"stale artifact in {area_name}: "
                            f"{len(entrypoints)} recorded path(s) carried but "
                            f"no longer live"),
                    band_offset=offset, evidence=evidence))

    prose_islands = len(_strs(inventory.get("islands")))
    prose_stale = len(_strs(inventory.get("stale")))
    if prose_islands != counts[STATUS_ISLAND]:
        notes.append(
            f"{INVENTORY_REL_PATH}: {prose_islands} prose 'islands' entries vs "
            f"{counts[STATUS_ISLAND]} structured status=island features; only "
            f"the structured entries carry evidence and entered the queue")
    if prose_stale != counts[STATUS_STALE]:
        notes.append(
            f"{INVENTORY_REL_PATH}: {prose_stale} prose 'stale' entries vs "
            f"{counts[STATUS_STALE]} structured status=stale features; only "
            f"the structured entries carry evidence and entered the queue")
    return tuple(candidates), tuple(notes)


# --------------------------------------------------------------------------- #
# source (b): eval misses                                                      #
# --------------------------------------------------------------------------- #
def _eval_instruction(task_id: str, detail: str) -> str:
    return (
        f"Eval task {task_id!r} is not at full recall ({detail}). The slice "
        f"produced for its target is missing at least one label a competent "
        f"answer needs. Find out which -- run "
        f"'python -m daedalus.eval' and read the per-task 'missed' list -- and "
        f"fix the SLICER, or, if the label is genuinely wrong, correct the "
        f"label in daedalus/eval/tasks.py and say so explicitly. Never edit "
        f"daedalus/eval/baseline.json: the baseline is a human-invoked ratchet."
    )


def eval_baseline_candidates(baseline: Mapping[str, Any]) -> tuple[
        tuple[Candidate, ...], tuple[str, ...]]:
    """The CHEAP eval source: recorded misses in ``daedalus/eval/baseline.json``.

    Pure over an already-loaded baseline. Reading a stored measurement costs
    nothing, but it measures the past: a task recorded at recall 1.0 is NOT
    evidence that it passes now, only evidence that nothing was recorded as
    missing when the baseline was last written by hand. That limit is returned
    as a note so it reaches the operator's terminal, not just this docstring.
    Use ``--eval`` for a fresh verdict.
    """
    tasks = baseline.get("tasks")
    if not isinstance(tasks, Mapping):
        return (), ("eval baseline has no 'tasks' map; no recorded recall read",)
    candidates: list[Candidate] = []
    full = 0
    for task_id, row in sorted(tasks.items()):
        if not isinstance(row, Mapping):
            continue
        try:
            recall = float(row.get("recall"))
        except (TypeError, ValueError):
            continue
        if recall >= 1.0:
            full += 1
            continue
        tier = str(row.get("tier") or "unknown")
        evidence = {
            "measurement": "daedalus/eval/baseline.json (stored, not a fresh run)",
            "recall": recall,
            "shortfall": round(1.0 - recall, 4),
            "tier": tier,
            "label_provenance": str(row.get("label_provenance") or "unknown"),
        }
        candidates.append(_candidate(
            task_id=f"eval-{_slug(str(task_id))}-{_short_hash(str(task_id))}",
            source="eval_miss",
            instruction=_eval_instruction(str(task_id),
                                          f"recorded recall {recall:.3f}"),
            reason=(f"eval miss: baseline records recall {recall:.3f} for "
                    f"{task_id!r} ({tier} tier)"),
            band_offset=BAND_SPAN * _clamp(1.0 - recall),
            evidence=evidence))
    note = (f"eval baseline: {full} task(s) recorded at recall 1.0 -- that is "
            f"'nothing RECORDED as missing', not 'the eval passes now'; "
            f"pass --eval for a fresh run")
    return tuple(candidates), (note,)


def eval_gate_candidates(gate_result: Mapping[str, Any]) -> tuple[
        tuple[Candidate, ...], tuple[str, ...]]:
    """The EXPENSIVE eval source: a fresh ``harness.run_gate`` verdict.

    Pure over the gate's returned dict (the run itself happens in
    :func:`_run_eval_gate`), so ranking a regression is testable without an
    index build. Regressions and errored PRIMARY tasks both become candidates:
    a task that can no longer be evaluated is not a task that passes.
    """
    candidates: list[Candidate] = []
    notes: list[str] = []
    for row in gate_result.get("regressions") or ():
        if not isinstance(row, Mapping):
            continue
        task_id = str(row.get("id") or "")
        if not task_id:
            continue
        base = float(row.get("baseline_recall") or 0.0)
        cur = float(row.get("current_recall") or 0.0)
        evidence = {
            "measurement": "daedalus.eval.harness.run_gate (fresh run)",
            "baseline_recall": base,
            "current_recall": cur,
            "delta": round(cur - base, 4),
            "missed": list(row.get("missed") or ()),
        }
        candidates.append(_candidate(
            task_id=f"eval-regression-{_slug(task_id)}-{_short_hash(task_id)}",
            source="eval_miss",
            instruction=_eval_instruction(
                task_id, f"recall fell from {base:.3f} to {cur:.3f}"),
            reason=(f"eval REGRESSION: {task_id!r} recall {base:.3f} -> "
                    f"{cur:.3f}"),
            band_offset=BAND_SPAN * _clamp(base - cur),
            evidence=evidence))
    for row in gate_result.get("errored_primary") or ():
        if not isinstance(row, Mapping):
            continue
        task_id = str(row.get("id") or "")
        if not task_id:
            continue
        evidence = {
            "measurement": "daedalus.eval.harness.run_gate (fresh run)",
            "error": str(row.get("error") or "unknown error"),
            "target": str(row.get("target") or ""),
            "tier": "primary",
        }
        candidates.append(_candidate(
            task_id=f"eval-errored-{_slug(task_id)}-{_short_hash(task_id)}",
            source="eval_miss",
            instruction=(
                f"Primary eval task {task_id!r} ERRORS instead of producing a "
                f"recall: {evidence['error']}. Its target is "
                f"{evidence['target'] or 'unrecorded'}. Restore it to a "
                f"measurable state -- the gate cannot vouch for a task it "
                f"cannot run, and that is indistinguishable from a regression."),
            reason=(f"eval task {task_id!r} errors on a primary-tier target, "
                    f"so it produces no recall at all"),
            # An unmeasurable primary task tops its band: no number can be
            # produced for it, which is strictly worse than a low number.
            band_offset=BAND_SPAN, evidence=evidence))
    if not gate_result.get("passed", True):
        notes.append("eval gate FAILED (advisory) -- see the candidates above")
    return tuple(candidates), tuple(notes)


def _load_baseline() -> tuple[Mapping[str, Any], str | None]:
    """Load the stored eval baseline, returning ``(baseline, error)``.

    A named seam rather than an inline import: it is the one place the picker
    reaches into ``daedalus.eval``, so it is the one place a test has to
    displace to stay hermetic, and the one place to look when the cheap eval
    source goes quiet.
    """
    try:
        from daedalus.eval.harness import load_baseline
        return load_baseline(), None
    except Exception as e:
        return {}, f"{type(e).__name__}: {e}"


def _run_eval_gate() -> tuple[Mapping[str, Any] | None, str | None]:
    """Run the advisory eval gate, returning ``(result, error)``.

    Isolated so the opt-in cost (a full Tier-1 replay, which builds a
    structural index per repo) lives in exactly one place, and so a broken
    eval cannot take the whole queue down with it.
    """
    try:
        from daedalus.eval.harness import run_gate
        return run_gate(), None
    except Exception as e:  # a broken eval must not empty the queue
        return None, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# source (c): structcore hotspots                                              #
# --------------------------------------------------------------------------- #
def hotspot_candidates(index: Mapping[str, Any], top: int = 5) -> tuple[
        tuple[Candidate, ...], tuple[str, ...]]:
    """Candidates from ``idx['hotspots']`` -- churn x complexity, as scored by
    :func:`daedalus.structcore.index.score_modules`.

    Pure over an index dict. Only the first ``top`` rows are queued: the
    ranking has a long, flat tail, and a queue full of "this file is biggish"
    would drown the sources that carry a sharper signal.

    A hotspot is the WEAKEST evidence here, and its band says so. Churn x
    complexity says rot is likely, not that a specific defect exists -- so
    these tasks are refactors judged by the existing suite, never behaviour
    changes.
    """
    rows = index.get("hotspots")
    if not isinstance(rows, (list, tuple)) or not rows:
        return (), ("structural index carries no 'hotspots' ranking",)
    scores = [float(r.get("score") or 0.0) for r in rows
              if isinstance(r, Mapping)]
    top_score = max(scores) if scores else 0.0
    if top_score <= 0.0:
        return (), ("every hotspot scored 0; no complexity signal to rank on",)
    candidates: list[Candidate] = []
    for row in rows[:max(0, int(top))]:
        if not isinstance(row, Mapping):
            continue
        module = str(row.get("module") or "").strip()
        if not module:
            continue
        score = float(row.get("score") or 0.0)
        churn = int(row.get("churn") or 0)
        loc = int(row.get("loc") or 0)
        long_fns = int(row.get("long_functions") or 0)
        evidence = {
            "measurement": ("daedalus.structcore.index.score_modules "
                            "(churn x complexity)"),
            "module": module,
            "score": score,
            "top_score": top_score,
            "loc": loc,
            "churn": churn,
            "long_functions": long_fns,
            "cc_max": row.get("cc_max"),
        }
        candidates.append(_candidate(
            task_id=f"hotspot-{_slug(module)}-{_short_hash(module)}",
            source="hotspot",
            instruction=(
                f"{module} is the churn x complexity hotspot scored {score} "
                f"({loc} loc, {long_fns} long function(s), {churn} churned "
                f"lines over history). Reduce its complexity WITHOUT changing "
                f"behaviour: extract the long functions, keep every public "
                f"name and signature, and change no test. The existing suite "
                f"is the gate -- a green run on unchanged tests is the whole "
                f"proof that this was a refactor and not a rewrite."),
            reason=(f"hotspot: {module} scores {score} on churn x complexity "
                    f"({loc} loc, {churn} churned lines)"),
            band_offset=BAND_SPAN * _clamp(score / top_score),
            evidence=evidence))
    return tuple(candidates), ()


def _load_index(repo_root: str | Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        from daedalus.structcore.index import cached_index
        return cached_index(str(repo_root)), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# ranking                                                                      #
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# source (d): what has already been attempted (the loop's return path)         #
# --------------------------------------------------------------------------- #
# Mirrored rather than imported: importing it from daedalus.spine.attempt would
# drag the worktree manager and the storage watermark into every --dry-run, and
# ranking a queue must stay a cheap read. The duplication is DRIFT-CHECKED by a
# test that asserts this equals attempt.INTENT_KIND, so the copy cannot rot
# silently -- which is the only reason a copy is acceptable here at all.
ATTEMPT_INTENT_KIND = "attempt.candidate"

# How far an already-attempted candidate sinks. Deliberately >= BAND_SPAN so the
# penalty always drives the measured offset to the band floor: "I have tried
# this" outranks every within-band measurement, but -- because the result is
# re-clamped into [0, BAND_SPAN] -- it can still never push a candidate out of
# its stated band. Memory reorders within a priority; it does not overrule one.
ATTEMPT_MEMORY_PENALTY = BAND_SPAN

def instruction_fingerprint(instruction: str) -> str:
    """The DEFINITION half of a candidate's retry identity.

    ``task_id`` is lineage, not definition: an inventory id hashes
    ``area|name|status`` only, so the tests, entrypoints, notes and therefore
    the whole generated INSTRUCTION can change while the id stays byte-identical.
    Joining memory on the id alone would make a rewritten task inherit the old
    one's failures and sink on evidence about work nobody is proposing any more.

    Deliberately excludes score and evidence: those move on every inventory
    edit and are not what makes two attempts the same attempt.
    """
    return hashlib.sha256(str(instruction).encode("utf-8")).hexdigest()


def attempt_history(db_path: str | Path | None = None, *,
                    task_ids: Sequence[str] = ()) -> tuple[
                        dict[str, dict], str | None]:
    """Map ``task_id`` -> what the ledger remembers about attempting it.

    Looks up EXACTLY the ids asked about rather than scanning a recent window.
    A window would let the oldest attempts fall silently out of memory and
    their tasks become selectable again -- the very defect this memory exists
    to prevent, reintroduced by the optimisation meant to make it cheap.

    Opens the ledger READ-ONLY. The normal constructor creates the parent
    directory, sets ``journal_mode=WAL`` (a file write) and runs migrations
    inside ``BEGIN IMMEDIATE``, so opening a ledger to look at it MUTATES it --
    unacceptable in ``--dry-run``, whose entire contract is that it changes
    nothing. SQLite enforces that here; this function does not merely promise it.

    Returns ``(history, error)`` and NEVER raises: a missing ledger (a fresh
    checkout has attempted nothing) is an empty history, not a failure. The
    error string is surfaced as a queue note, because silently degrading to "no
    memory" is exactly how a loop would go back to repeating itself without
    saying so.
    """
    wanted = [str(t) for t in task_ids if str(t)]
    if not wanted:
        return {}, None
    try:
        from daedalus.spine.ledger import SpineLedger, default_db_path

        path = Path(db_path) if db_path else default_db_path()
        if not Path(path).exists():
            return {}, None
        ledger = SpineLedger(path, read_only=True)
        try:
            intents = ledger.intents_matching_payload(
                "task_id", wanted, kind=ATTEMPT_INTENT_KIND)
        finally:
            ledger.close()
    except Exception as e:  # unreadable, locked, corrupt, schema mismatch
        return {}, f"{type(e).__name__}: {e}"

    history: dict[str, dict] = {}
    for intent in intents:
        payload = intent.payload if isinstance(intent.payload, Mapping) else {}
        task_id = str(payload.get("task_id") or "").strip()
        # A LIKE match is a substring test; confirm the row really is one of
        # the ids asked for rather than one that merely contains it.
        if task_id not in wanted:
            continue
        rec = history.setdefault(
            task_id, {"n_attempts": 0, "last_state": None, "last_ts": None,
                      "last_outcome": None, "by_instruction": {}})
        rec["n_attempts"] += 1
        fingerprint = instruction_fingerprint(payload.get("instruction") or "")
        rec["by_instruction"][fingerprint] = (
            rec["by_instruction"].get(fingerprint, 0) + 1)
        # Newest-first, so the FIRST row seen for a task is its latest attempt.
        if rec["last_state"] is None:
            rec["last_state"] = intent.state
            rec["last_ts"] = intent.resolved_ts or intent.created_ts
            outcome = intent.result if isinstance(intent.result, Mapping) else {}
            rec["last_outcome"] = str(outcome.get("state") or "") or None
    return history, None


def apply_attempt_memory(candidates: Sequence[Candidate],
                         history: Mapping[str, Mapping[str, Any]]) -> tuple[
                             tuple[Candidate, ...], tuple[str, ...]]:
    """Sink candidates the ledger has already seen attempted, and say so.

    A PENALTY, not a filter. Dropping attempted work would let one transient
    runner failure delete a real task from the queue forever, and would let the
    queue silently empty -- both worse than showing the work with its history
    attached. The operator (and ``--once``) still sees every candidate; what
    changes is the order, and every moved candidate carries the evidence that
    moved it.
    """
    if not history:
        return tuple(candidates), ()
    out: list[Candidate] = []
    moved = 0
    redefined = 0
    for cand in candidates:
        rec = history.get(cand.task_id)
        if not rec:
            out.append(cand)
            continue
        fingerprint = instruction_fingerprint(cand.instruction)
        same = int(rec.get("by_instruction", {}).get(fingerprint, 0))
        evidence = dict(cand.evidence)
        evidence["prior_attempts"] = int(rec.get("n_attempts") or 0)
        evidence["prior_attempts_same_instruction"] = same
        evidence["last_attempt_state"] = rec.get("last_state")
        evidence["last_attempt_outcome"] = rec.get("last_outcome")
        evidence["last_attempt_ts"] = rec.get("last_ts")

        if not same:
            # LINEAGE matched, DEFINITION did not: the id is stable across
            # instruction rewrites, so this is genuinely different work wearing
            # a familiar name. Record the lineage, do not sink it -- penalising
            # it would be evidence about a task nobody is proposing any more.
            redefined += 1
            evidence["memory"] = ("same task_id, different instruction -- "
                                  "not treated as already attempted")
            out.append(replace(cand, evidence=evidence))
            continue

        moved += 1
        offset = _clamp(cand.offset - ATTEMPT_MEMORY_PENALTY, 0.0, BAND_SPAN)
        out.append(replace(
            cand,
            score=round(SOURCE_BANDS[cand.source] + offset, 4),
            evidence=evidence,
            reason=(f"{cand.reason}; already attempted "
                    f"{same}x with this exact instruction (last: "
                    f"{rec.get('last_outcome') or rec.get('last_state')})")))

    notes: list[str] = []
    if moved:
        notes.append(f"attempt memory: {moved} candidate(s) sank to their band "
                     f"floor because the spine ledger records a prior attempt "
                     f"at the same instruction")
    if redefined:
        notes.append(f"attempt memory: {redefined} candidate(s) share a task_id "
                     f"with a prior attempt but their instruction changed, so "
                     f"they were NOT penalised")
    if not notes:
        notes.append("attempt memory: the ledger has attempts recorded, but "
                     "none for a candidate currently in the queue")
    return tuple(out), tuple(notes)


def rank(candidates: Sequence[Candidate],
         limit: int | None = None) -> tuple[Candidate, ...]:
    """Deterministic ranking: score desc, untried first, source order, task_id.

    The tie-breaks are not decoration. Scores collide constantly (two islands
    with the same test count are genuinely equal on evidence), and a queue whose
    order depends on dict iteration or on which source ran first is not
    reproducible -- which would make "measurement picks the next task"
    unfalsifiable, since two runs could disagree with no cause to point at.

    ``prior_attempts`` ranks ahead of the other tie-breaks because the score
    alone cannot express memory at the bottom of a band. ``apply_attempt_memory``
    drives an attempted candidate's offset to the band FLOOR, and the floor is
    also where every candidate with no measured evidence already sits -- so a
    tried candidate and an untried one collide on score exactly when the
    distinction matters most. Expressing it as a tie-break rather than a bigger
    penalty is deliberate: a penalty large enough to separate them would have to
    leave the band, and the stated priority is not memory's to overrule.
    """
    order = {name: i for i, name in enumerate(SOURCE_ORDER)}

    def _tried(c: Candidate) -> int:
        try:
            return int(c.evidence.get("prior_attempts") or 0)
        except (TypeError, ValueError):
            return 0

    ranked = sorted(
        candidates,
        key=lambda c: (-c.score, _tried(c), order.get(c.source, len(order)),
                       c.task_id))
    if limit is not None and limit >= 0:
        ranked = ranked[:limit]
    return tuple(ranked)


def build_queue(repo_root: str | Path | None = None, *,
                limit: int | None = DEFAULT_LIMIT,
                include_eval: bool = False,
                include_hotspots: bool = False,
                inventory: Mapping[str, Any] | None = None,
                baseline: Mapping[str, Any] | None = None,
                use_attempt_memory: bool = True,
                enforce_inventory_freshness: bool = True,
                spine_db: str | Path | None = None) -> PickedQueue:
    """Build the ranked queue. Never raises on a bad or missing source file.

    ``include_eval`` and ``include_hotspots`` default to OFF: both cost a
    whole-repo analysis pass, and a picker that takes a minute to answer "what
    next" will not be run before every attempt, which would leave the loop
    picking by habit instead of by measurement.
    """
    root = Path(repo_root).resolve() if repo_root else ROOT
    candidates: list[Candidate] = []
    notes: list[str] = []
    sources: dict[str, Any] = {}

    inv = load_inventory(repo_root=root) if inventory is None else inventory
    inv_candidates, inv_notes = inventory_candidates(inv)
    notes.extend(inv_notes)
    freshness = inventory_freshness(inv, repo_root=root)
    if freshness["fresh"] or not enforce_inventory_freshness:
        candidates.extend(inv_candidates)
    else:
        # FAIL CLOSED. These are the two highest bands; letting a snapshot of a
        # different tree drive them means the loop works from a description of
        # a repo that no longer exists. Suppressed LOUDLY -- an empty queue with
        # a stated reason is a truthful answer, a confidently-ranked stale one
        # is not.
        notes.append(
            f"INVENTORY SUPPRESSED ({len(inv_candidates)} candidate(s) "
            f"withheld): {freshness['reason']}. Regenerate "
            f"{INVENTORY_REL_PATH}, or pass --stale-inventory to rank it anyway.")
    sources["inventory"] = {
        "path": str(Path(root) / INVENTORY_REL_PATH),
        "read": bool(inv),
        "candidates": len(inv_candidates) if (
            freshness["fresh"] or not enforce_inventory_freshness) else 0,
        "suppressed": (not freshness["fresh"]) and enforce_inventory_freshness,
        "freshness": freshness,
        "repo_state": inv.get("repo_state") if isinstance(inv, Mapping) else None,
    }

    if baseline is None:
        baseline, base_error = _load_baseline()
        if base_error:
            notes.append(f"eval baseline unavailable: {base_error}")
    base_candidates, base_notes = eval_baseline_candidates(baseline)
    candidates.extend(base_candidates)
    notes.extend(base_notes)
    sources["eval_baseline"] = {"candidates": len(base_candidates),
                                "cheap": True}

    if include_eval:
        gate, err = _run_eval_gate()
        if gate is None:
            notes.append(f"eval gate did not run: {err}")
            sources["eval_gate"] = {"ran": False, "error": err}
        else:
            gate_candidates, gate_notes = eval_gate_candidates(gate)
            candidates.extend(gate_candidates)
            notes.extend(gate_notes)
            sources["eval_gate"] = {"ran": True, "passed": gate.get("passed"),
                                    "n_checked": gate.get("n_checked"),
                                    "candidates": len(gate_candidates)}
    else:
        sources["eval_gate"] = {"ran": False,
                                "reason": "opt-in (--eval); a full Tier-1 replay"}

    if include_hotspots:
        idx, err = _load_index(root)
        if idx is None:
            notes.append(f"structural index did not build: {err}")
            sources["hotspots"] = {"ran": False, "error": err}
        else:
            hot_candidates, hot_notes = hotspot_candidates(idx)
            candidates.extend(hot_candidates)
            notes.extend(hot_notes)
            sources["hotspots"] = {"ran": True,
                                   "candidates": len(hot_candidates)}
    else:
        sources["hotspots"] = {"ran": False,
                               "reason": "opt-in (--hotspots); builds the "
                                         "whole-repo structural index"}

    if use_attempt_memory:
        history, hist_error = attempt_history(
            spine_db, task_ids=[c.task_id for c in candidates])
        if hist_error:
            notes.append(f"attempt memory unavailable: {hist_error}")
            sources["attempt_memory"] = {"read": False, "error": hist_error}
        else:
            candidates_t, mem_notes = apply_attempt_memory(candidates, history)
            candidates = list(candidates_t)
            notes.extend(mem_notes)
            sources["attempt_memory"] = {"read": True,
                                         "tasks_remembered": len(history)}
    else:
        sources["attempt_memory"] = {"read": False,
                                     "reason": "disabled by caller (--forget)"}

    return PickedQueue(candidates=rank(candidates, limit),
                       sources=sources, notes=tuple(notes))


# --------------------------------------------------------------------------- #
# rendering                                                                    #
# --------------------------------------------------------------------------- #
def _evidence_lines(evidence: Mapping[str, Any], indent: str = "    ") -> list[str]:
    lines = []
    for key in sorted(evidence):
        value = evidence[key]
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value) or "-"
        lines.append(f"{indent}{key} = {value}")
    return lines


def render_queue(queue: PickedQueue, *, verbose: bool = False) -> str:
    """Human-readable ranked queue. The ``--dry-run`` deliverable."""
    out: list[str] = []
    out.append(f"DAEDALUS IMPROVE -- ranked work queue ({len(queue)} candidate(s))")
    out.append("score is BAND (a stated priority) + a measured offset; "
               "cross-band order is priority, not evidence.")
    out.append("")
    if not queue.candidates:
        out.append("  (empty -- no source produced an evidence-backed candidate)")
    for i, c in enumerate(queue.candidates, 1):
        out.append(f"{i:>3}. {c.score:>8.2f}  [{c.source}]  {c.task_id}")
        out.append(f"     why : {c.reason}")
        out.append(f"     band: {c.band:.0f} + measured {c.offset:.2f}")
        gate = ", ".join(c.gate_paths) or "(whole suite)"
        out.append(f"     gate: {gate}")
        if verbose:
            out.extend(_evidence_lines(c.evidence, indent="     ev  "))
            out.append(f"     task: {c.instruction}")
        out.append("")
    out.append("sources:")
    for name in sorted(queue.sources):
        out.append(f"  {name}: {json.dumps(queue.sources[name], default=str)}")
    if queue.notes:
        out.append("")
        out.append("notes:")
        for n in queue.notes:
            out.append(f"  - {n}")
    out.append("")
    out.append("nothing has been run. use --once to attempt the top candidate.")
    return "\n".join(out)


def _gate_line(result: Any) -> str:
    gates = getattr(result, "gates", None)
    if gates is None:
        return "GATE: not run (no patch to judge)"
    verdict = "PASS" if getattr(gates, "passed", False) else "FAIL"
    bits = [f"GATE: {verdict}"]
    bits.append(f"name={getattr(gates, 'name', 'gate')}")
    bits.append(f"exit={getattr(gates, 'returncode', None)}")
    bits.append(f"{getattr(gates, 'duration_s', 0.0):.1f}s")
    if getattr(gates, "cancelled", False):
        bits.append("CANCELLED")
    if getattr(gates, "timed_out", False):
        bits.append("TIMED OUT")
    return "  ".join(bits)


def review_packet(candidate: Candidate, result: Any, *,
                  diff_limit: int = 20000,
                  gate_tail: int = 2000) -> str:
    """The thing a human reads before deciding. Contains the diff and the gate
    verdict, in full enough form to decide on, and states in three places that
    nothing was applied.

    The patch bytes are decoded for display only. A human promoting this must
    write ``artifact_path`` (the raw bytes) -- a diff round-tripped through a
    terminal is not the artifact that was hashed and gated.
    """
    bar = "=" * 78
    out: list[str] = [bar, "DAEDALUS IMPROVE -- HUMAN REVIEW PACKET", bar,
                      "NOTHING HAS BEEN APPLIED. This is a proposal.", ""]

    out.append("WHY THIS TASK")
    out.append(f"  task_id : {candidate.task_id}")
    out.append(f"  source  : {candidate.source}")
    out.append(f"  score   : {candidate.score} "
               f"(band {candidate.band:.0f} + measured {candidate.offset:.2f})")
    out.append(f"  reason  : {candidate.reason}")
    out.append("  evidence:")
    out.extend(_evidence_lines(candidate.evidence, indent="    "))
    out.append("")
    out.append("  instruction given to the runner:")
    out.append(f"    {candidate.instruction}")
    out.append("")

    out.append("ATTEMPT")
    out.append(f"  state    : {getattr(result, 'state', 'unknown')}")
    out.append(f"  branch   : {getattr(result, 'branch', '-')}")
    out.append(f"  base     : {getattr(result, 'base_revision', '-')}")
    out.append(f"  intent   : {getattr(result, 'intent_id', '-')} "
               f"(spine ledger)")
    out.append(f"  duration : {getattr(result, 'duration_s', 0.0):.1f}s")
    worktree = getattr(result, "worktree_path", None)
    if worktree:
        out.append(f"  worktree : {worktree} "
                   f"(removed: {getattr(result, 'worktree_removed', False)})")
    for label in ("error", "cleanup_error", "ledger_error"):
        value = getattr(result, label, None)
        if value:
            out.append(f"  {label:<9}: {value}")
    out.append("")

    out.append(_gate_line(result))
    gates = getattr(result, "gates", None)
    if gates is not None:
        command = " ".join(str(c) for c in getattr(gates, "command", ()) or ())
        if command:
            out.append(f"  command: {command}")
        output = getattr(gates, "output", "") or ""
        if output:
            tail = output[-gate_tail:]
            if len(tail) < len(output):
                out.append(f"  output (last {gate_tail} of {len(output)} chars):")
            else:
                out.append("  output:")
            for line in tail.splitlines():
                out.append(f"    {line}")
    out.append("")

    artifact = getattr(result, "artifact", None)
    empty_patch = artifact is not None and not getattr(artifact, "diff_bytes",
                                                       artifact.diff)
    if artifact is None:
        out.append("DIFF: none -- the attempt produced no patch.")
    elif empty_patch:
        # An empty patch is captured and hashed like any other, but showing it
        # as a diff -- and, worse, offering an apply command for it below --
        # would let "the runner did nothing" read as "here is a change".
        out.append(f"DIFF: EMPTY -- the runner changed no file "
                   f"(sha256 {artifact.diff_sha256} is the digest of zero "
                   f"bytes). There is nothing to promote.")
    else:
        out.append(f"DIFF  sha256 {artifact.diff_sha256}  "
                   f"{artifact.byte_length} bytes  "
                   f"{len(artifact.changed_paths)} file(s)")
        for path in artifact.changed_paths:
            out.append(f"  {path}")
        out.append("--- 8< " + "-" * 60)
        text = artifact.diff
        if len(text) > diff_limit:
            out.append(text[:diff_limit])
            out.append(f"... [truncated for display: {len(text)} chars total; "
                       f"the full patch is the artifact, not this packet]")
        else:
            out.append(text)
        out.append("--- >8 " + "-" * 60)
    out.append("")

    out.append("NEXT STEP -- YOURS, NOT THE LOOP'S")
    artifact_path = getattr(result, "artifact_path", None)
    if artifact is None or empty_patch:
        out.append("  nothing to apply. This attempt produced no change, so "
                   "there is no decision to make.")
    elif artifact_path:
        out.append(f"  the patch bytes are at: {artifact_path}")
        out.append(f"  apply   : git apply --index {artifact_path}")
    else:
        out.append("  the patch was not persisted (no artifact dir); "
                   "re-run with --artifact-dir to keep the bytes")
    branch = getattr(result, "branch", None)
    if branch and not empty_patch and artifact is not None:
        out.append(f"  inspect : git diff {getattr(result, 'base_revision', 'HEAD')}"
                   f"..{branch}")
    out.append("  discard : do nothing. no ref is merged and no file is "
               "changed until you act.")
    out.append("  the gate verdict above is EVIDENCE, not permission. "
               "Promotion is a human decision.")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _default_attempt(candidate: Candidate, args: Any) -> Any:
    """Run one real :class:`daedalus.spine.attempt.TaskAttempt`.

    Split out as the single injection seam so ``--dry-run`` can be tested by
    passing an ``attempt_fn`` that raises: proving the flag does not attempt
    anything requires a way to observe an attempt that never happens.
    """
    from daedalus.spine.attempt import offload_runner, run_attempt

    spec = candidate.to_task_spec()
    return run_attempt(
        spec,
        runner=offload_runner(live=bool(args.live)),
        repo_root=args.repo_root,
        artifact_dir=args.artifact_dir,
        keep_worktree=bool(args.keep_worktree))


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="daedalus improve",
        description=(
            "Rank the repo's own work by measurement and, with --once, attempt "
            "the top item in an isolated worktree. NEVER applies anything: the "
            "output is a patch plus a gate verdict for a human to promote or "
            "discard."),
        epilog=(
            "There is no --apply flag and there will not be one here. "
            "Promotion is a human act. Exit codes for --once: "
            "0 = a gated candidate patch is waiting for you, "
            "2 = the attempt ran and changed nothing, "
            "3 = a source could not be consulted, so 'no candidate' is NOT "
            "evidence that there is no work, "
            "1 = anything else (gate failed, runner failed, no candidate)."))
    parser.add_argument("--once", action="store_true",
                        help="attempt exactly ONE candidate (the top of the "
                             "queue) and print a review packet; still applies "
                             "nothing")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the ranked queue and exit without running "
                             "anything (the default when --once is absent)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"how many candidates to rank (default "
                             f"{DEFAULT_LIMIT})")
    parser.add_argument("--eval", action="store_true", dest="include_eval",
                        help="also consult a FRESH advisory eval gate run "
                             "(slow: replays every task, builds an index)")
    parser.add_argument("--hotspots", action="store_true",
                        dest="include_hotspots",
                        help="also consult churn x complexity hotspots (slow: "
                             "builds the whole-repo structural index)")
    parser.add_argument("--live", action="store_true",
                        help="with --once, let the runner actually invoke a "
                             "model in the worktree (default: advisory, which "
                             "normally produces no change)")
    parser.add_argument("--repo-root",
                        help="repo to pick work from (default: this checkout)")
    parser.add_argument("--artifact-dir",
                        help="directory to write the candidate patch bytes to")
    parser.add_argument("--keep-worktree", action="store_true",
                        help="leave the candidate worktree on disk for "
                             "inspection")
    parser.add_argument("--forget", action="store_true",
                        help="ignore the spine ledger's record of prior "
                             "attempts (by default an already-attempted "
                             "candidate sinks to the floor of its band)")
    parser.add_argument("--stale-inventory", action="store_true",
                        help="rank inventory candidates even when the "
                             "inventory was written against a different "
                             "revision than HEAD (default: withhold them)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="show each candidate's full evidence and "
                             "instruction")
    parser.add_argument("--json", action="store_true",
                        help="emit the queue as JSON instead of a table")
    return parser


def main(argv: Sequence[str] | None = None, *,
         attempt_fn: Callable[[Candidate, Any], Any] | None = None) -> int:
    """``daedalus improve``. Returns a process exit code; applies nothing.

    Default behaviour with no flags is the DRY RUN. An operator who types
    ``daedalus improve`` to see what it does must not thereby start a model
    run in a worktree -- the destructive-by-default reading of an ambiguous
    command is the one that has to be wrong.
    """
    import sys as _sys

    args = _build_parser().parse_args(
        list(argv) if argv is not None else _sys.argv[1:])
    queue = build_queue(args.repo_root, limit=args.limit,
                        include_eval=args.include_eval,
                        include_hotspots=args.include_hotspots,
                        use_attempt_memory=not args.forget,
                        enforce_inventory_freshness=not args.stale_inventory)

    degraded = queue.degraded_sources

    if args.json:
        print(json.dumps(queue.to_dict(), indent=2, default=str))
        if not args.once:
            return EXIT_SOURCE_UNAVAILABLE if degraded else 0

    if not args.once:
        if not args.json:
            print(render_queue(queue, verbose=args.verbose))
            if degraded:
                print(f"\nINCOMPLETE: {', '.join(degraded)} could not be "
                      f"consulted, so this queue is not the whole picture "
                      f"(exit {EXIT_SOURCE_UNAVAILABLE}).")
        return EXIT_SOURCE_UNAVAILABLE if degraded else 0

    top = queue.top
    if top is None:
        print("no evidence-backed candidate to attempt; "
              "nothing was run.")
        for note in queue.notes:
            print(f"  - {note}")
        if degraded:
            # NOT "there is no work": we do not know that. Saying so with the
            # same exit code as a healthy empty queue is how a silently broken
            # source becomes an idle loop nobody investigates.
            print(f"  ! {', '.join(degraded)} could not be consulted -- this is "
                  f"NOT evidence that there is nothing to do.")
            return EXIT_SOURCE_UNAVAILABLE
        return EXIT_FAILED

    print(f"attempting 1 of {len(queue)}: {top.task_id}  (score {top.score})")
    print(f"  why: {top.reason}")
    if not args.live:
        print("  runner is ADVISORY (no --live): the model is not invoked, so "
              "a 'no_change' result is the expected outcome.")
    print("")
    run = attempt_fn or _default_attempt
    result = run(top, args)
    print(review_packet(top, result))
    return EXIT_BY_STATE.get(getattr(result, "state", "unknown"), EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
