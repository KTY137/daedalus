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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "BAND_SPAN",
    "Candidate",
    "EXIT_CANDIDATE",
    "EXIT_FAILED",
    "EXIT_NO_CHANGE",
    "INVENTORY_REL_PATH",
    "PickedQueue",
    "SOURCE_BANDS",
    "SOURCE_ORDER",
    "build_queue",
    "eval_baseline_candidates",
    "eval_gate_candidates",
    "hotspot_candidates",
    "inventory_candidates",
    "load_inventory",
    "main",
    "rank",
    "render_queue",
    "review_packet",
]

ROOT = Path(__file__).resolve().parents[2]

INVENTORY_REL_PATH = "docs/FEATURE_INVENTORY.json"

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

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "sources": dict(self.sources),
            "notes": list(self.notes),
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
def rank(candidates: Sequence[Candidate],
         limit: int | None = None) -> tuple[Candidate, ...]:
    """Deterministic ranking: score desc, then source order, then task_id.

    The two tie-breaks are not decoration. Scores collide constantly (two
    islands with the same test count are genuinely equal on evidence), and a
    queue whose order depends on dict iteration or on which source ran first
    is not reproducible -- which would make "measurement picks the next task"
    unfalsifiable, since two runs could disagree with no cause to point at.
    """
    order = {name: i for i, name in enumerate(SOURCE_ORDER)}
    ranked = sorted(
        candidates,
        key=lambda c: (-c.score, order.get(c.source, len(order)), c.task_id))
    if limit is not None and limit >= 0:
        ranked = ranked[:limit]
    return tuple(ranked)


def build_queue(repo_root: str | Path | None = None, *,
                limit: int | None = DEFAULT_LIMIT,
                include_eval: bool = False,
                include_hotspots: bool = False,
                inventory: Mapping[str, Any] | None = None,
                baseline: Mapping[str, Any] | None = None) -> PickedQueue:
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
    candidates.extend(inv_candidates)
    notes.extend(inv_notes)
    sources["inventory"] = {
        "path": str(Path(root) / INVENTORY_REL_PATH),
        "read": bool(inv),
        "candidates": len(inv_candidates),
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
                        include_hotspots=args.include_hotspots)

    if args.json:
        print(json.dumps(queue.to_dict(), indent=2, default=str))
        if not args.once:
            return 0

    if not args.once:
        if not args.json:
            print(render_queue(queue, verbose=args.verbose))
        return 0

    top = queue.top
    if top is None:
        print("no evidence-backed candidate to attempt; "
              "nothing was run.")
        for note in queue.notes:
            print(f"  - {note}")
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
