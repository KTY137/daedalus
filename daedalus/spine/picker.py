# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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

Once a candidate has been ATTEMPTED, the ledger's record of how that attempt
ended puts a CEILING on its offset (:data:`OUTCOME_POLICY`). That is still a
measurement -- the loop's own return path -- and it obeys the band like every
other one: memory reorders inside a priority and can never leave it.

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
import math
import re
import sys
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
    "MAP_STATE_REL_PATH",
    "WORK_QUEUE_SCHEMA",
    "DEFAULT_WORK_QUEUE_REL_PATH",
    "DEFAULT_SPINE_DB_REL_PATH",
    "OUTCOME_POLICY",
    "OutcomePolicy",
    "PickedQueue",
    "SOURCE_BANDS",
    "SOURCE_ORDER",
    "UNKNOWN_OUTCOME",
    "build_queue",
    "eval_baseline_candidates",
    "eval_gate_candidates",
    "hotspot_candidates",
    "instruction_fingerprint",
    "inventory_candidates",
    "inventory_freshness",
    "load_inventory",
    "load_map_state",
    "load_work_queue",
    "main",
    "map_candidates",
    "map_state_trustworthy",
    "outcome_policy",
    "rank",
    "render_queue",
    "review_packet",
    "resolve_spine_db_path",
    "work_queue_candidates",
]

ROOT = Path(__file__).resolve().parents[2]

INVENTORY_REL_PATH = "docs/FEATURE_INVENTORY.json"
WORK_QUEUE_SCHEMA = "daedalus-work-queue/1"
DEFAULT_WORK_QUEUE_REL_PATH = ".agentenv/work-queue.json"
DEFAULT_SPINE_DB_REL_PATH = "runs/spine/spine.sqlite3"

# A git object name as it appears in HEAD / refs / packed-refs.
_SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# The shortest abbreviation a recorded head may use. git's own default floor is
# 7; anything shorter is not an identifier, it is a coincidence waiting to
# happen (a 1-char "prefix" matches ~1 HEAD in 16).
_MIN_ABBREV = 7
_ABBREV_SHA_RE = re.compile(rf"[0-9a-f]{{{_MIN_ABBREV},64}}")

# Source priority. A PRIOR, not a measurement -- see the module docstring.
#
# The two map_* bands sit ABOVE the inventory ones, and that ordering is the
# whole argument for this source existing. Both describe "built but unreachable",
# but docs/FEATURE_INVENTORY.json is HAND-WRITTEN and was measured thirty commits
# stale, while docs/architecture-state.json is GENERATED and covered by a digest
# and a drift gate. When two sources disagree about the same tree, the one that
# cannot silently rot is the one to work from.
SOURCE_BANDS: dict[str, float] = {
    # An explicitly curated, revision-bound task outranks inferred work. The
    # queue is an operator decision, not a stronger measurement.
    "work_queue": 900.0,
    "map_island": 800.0,
    "map_shim": 700.0,
    # Prose that contradicts the code it describes. Ranked BELOW unreachable
    # capability and ABOVE a stale inventory entry, on importance alone.
    #
    # Deliberately NOT ranked by how convenient it is. As of 2026-07-29 this is
    # the only source whose candidates the installed self-policy actually
    # permits a local writer to touch -- every other source produces surgery
    # under ``daedalus/`` against a ``write_allow`` of ``docs/``, ``tests/``,
    # ``README.md``, so the intersection is empty and the loop selects only work
    # it may not do. That makes this source the one that closes the loop, which
    # is a powerful reason to inflate its band and exactly the wrong one: the
    # band states IMPORTANCE, and "I am allowed to do this" is not a measurement
    # of importance. Smuggling permission into the prior is how a priority order
    # stops meaning what it says.
    "docref": 500.0,
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
    "work_queue", "map_island", "map_shim",
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
    target_paths: tuple[str, ...] = ()
    gate_argv: tuple[str, ...] = ()
    gate_cwd: str = "."
    gate_timeout_s: float = 900.0
    base_revision: str | None = None
    # SWE-bench's FAIL_TO_PASS / PASS_TO_PASS schema (docs/ABSORPTION.md F1) --
    # see the matching fields on daedalus.spine.attempt.TaskSpec for the full
    # rationale. Empty (the default) means this candidate carries no
    # correctness task and the gate falls through to gate_argv/gate_paths
    # exactly as it did before these fields existed. ``correctness_before_state``
    # is the pre-verified receipt the lists were measured under (e.g. an entry
    # read from daedalus.eval.correctness's minted corpus) -- carried, never
    # re-derived here, because ranking a queue must not run pytest.
    fail_to_pass: tuple[str, ...] = ()
    pass_to_pass: tuple[str, ...] = ()
    correctness_before_state: Mapping[str, Any] = field(default_factory=dict)

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
            base_revision=base_revision or self.base_revision,
            gate_paths=tuple(self.gate_paths),
            target_paths=tuple(self.target_paths),
            gate_argv=tuple(self.gate_argv),
            gate_cwd=self.gate_cwd,
            gate_timeout_s=float(self.gate_timeout_s),
            fail_to_pass=tuple(self.fail_to_pass),
            pass_to_pass=tuple(self.pass_to_pass),
            correctness_before_state=dict(self.correctness_before_state),
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
            "target_paths": list(self.target_paths),
            "gate": {
                "argv": list(self.gate_argv),
                "cwd": self.gate_cwd,
                "timeout_s": self.gate_timeout_s,
            },
            "correctness": {
                "fail_to_pass": list(self.fail_to_pass),
                "pass_to_pass": list(self.pass_to_pass),
                "before_state_verified": bool(
                    self.correctness_before_state.get("verified")),
            },
            "base_revision": self.base_revision,
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
               gate_paths: Sequence[str] = (),
               target_paths: Sequence[str] = (),
               gate_argv: Sequence[str] = (),
               gate_cwd: str = ".",
               gate_timeout_s: float = 900.0,
               base_revision: str | None = None) -> Candidate:
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
        evidence=dict(evidence), gate_paths=tuple(str(p) for p in gate_paths),
        target_paths=tuple(str(p) for p in target_paths),
        gate_argv=tuple(str(arg) for arg in gate_argv),
        gate_cwd=str(gate_cwd), gate_timeout_s=float(gate_timeout_s),
        base_revision=(str(base_revision) if base_revision else None))


# --------------------------------------------------------------------------- #
# source (0): an explicitly curated, revision-bound work queue                #
# --------------------------------------------------------------------------- #
class WorkQueueInvalid(ValueError):
    """The enabled queue exists, but cannot safely drive an attempt."""


def _project_config(repo_root: Path) -> Mapping[str, Any] | None:
    from daedalus.config import resolve_project

    data = resolve_project(str(repo_root))
    return data if isinstance(data, Mapping) else None


def _confined_path(repo_root: Path, raw: Any, *, label: str) -> Path:
    """Resolve a configured path and prove it stays under ``repo_root``.

    ``Path.resolve`` follows an existing symlink in any parent component, so a
    lexically innocent ``.agentenv/link/queue.json`` cannot escape through a
    junction/symlink. Non-existing leaf files remain valid, which is necessary
    to distinguish an enabled-but-ABSENT source from an INVALID path.
    """
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise WorkQueueInvalid(f"{label} must be a non-empty path")
    root = repo_root.resolve()
    supplied = Path(str(raw))
    candidate = (supplied if supplied.is_absolute()
                 else root / supplied).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkQueueInvalid(
            f"{label} escapes repo root {root}: {raw!r}") from exc
    return candidate


def resolve_spine_db_path(
        repo_root: str | Path | None = None, *,
        explicit: str | Path | None = None,
        project_config: Mapping[str, Any] | None = None
        ) -> tuple[Path | None, str | None]:
    """The repo-bound attempt ledger path, without creating it.

    The historical default lived under agent_env even when ``repo_root`` named
    another repository. That split the loop: the writer recorded PnP attempts
    while the picker remembered agent_env attempts. The default is now
    ``<repo>/runs/spine/spine.sqlite3`` and a configured override is accepted
    only when its resolved target remains inside that same repository.

    DELIBERATELY DOES NOT READ ``DAEDALUS_SPINE_DB``, and this is the ruling,
    not an oversight (resolver author, 2026-07-29): that env var belongs to the
    process-global ledger surface -- :func:`daedalus.spine.ledger.default_db_path`
    -- where tests and isolated worktrees point the WHOLE process elsewhere.
    This resolver answers a different question: "where does THIS repository
    keep its attempt memory", and the answer must be repo-confined (pinned by
    ``tests/test_picker_work_queue.py``) so that picking for a foreign repo can
    never read or write agent_env's ledger through an inherited environment.
    They look like two resolvers for one question; they are one resolver per
    question. Three queue tests once assumed otherwise, set the env var, and
    silently measured the developer's real ledger -- red in the full suite,
    green alone. If you are here to "unify" them, read that history first.
    """
    root = Path(repo_root).resolve() if repo_root else ROOT
    cfg = project_config if project_config is not None else _project_config(root)
    raw: Any = explicit
    if raw is None:
        spine = cfg.get("spine") if isinstance(cfg, Mapping) else None
        if spine is None:
            raw = DEFAULT_SPINE_DB_REL_PATH
        elif not isinstance(spine, Mapping):
            return None, "spine config must be an object"
        else:
            raw = spine.get("ledger_path", DEFAULT_SPINE_DB_REL_PATH)
    try:
        return _confined_path(root, raw, label="spine.ledger_path"), None
    except WorkQueueInvalid as exc:
        return None, str(exc)


def _picker_source_mode(config: Mapping[str, Any] | None,
                        name: str) -> str:
    """Return ``enabled``, ``disabled`` or ``legacy`` for a picker source."""
    if config is None:
        return "legacy"
    declared = config.get("picker_sources")
    if declared is None:
        return "enabled"
    if not isinstance(declared, Mapping):
        return "invalid"
    value = declared.get(name, "enabled")
    if value is False or str(value).strip().lower() == "disabled":
        return "disabled"
    if value is True or str(value).strip().lower() == "enabled":
        return "enabled"
    return "invalid"


def load_work_queue(
        repo_root: str | Path | None = None, *,
        project_config: Mapping[str, Any] | None = None
        ) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    """Read the configured queue and report one exact source state.

    States are deliberately not booleans:

    ``disabled`` -- the repo did not opt in (healthy and intentional)
    ``absent``   -- enabled, but the configured file is missing
    ``invalid``  -- path escape, unreadable bytes, JSON/schema-shape error
    ``valid``    -- bytes parsed as an object; task validation follows below
    """
    root = Path(repo_root).resolve() if repo_root else ROOT
    cfg = project_config if project_config is not None else _project_config(root)
    setting = cfg.get("work_queue") if isinstance(cfg, Mapping) else None
    if setting is None or setting is False:
        return None, {
            "state": "disabled",
            "enabled": False,
            "reason": "no enabled repo-local work_queue configuration",
        }

    if isinstance(setting, str):
        enabled, raw_path = True, setting
    elif isinstance(setting, Mapping):
        enabled_value = setting.get("enabled", True)
        if not isinstance(enabled_value, bool):
            return None, {
                "state": "invalid", "enabled": False,
                "error": "work_queue.enabled must be boolean",
            }
        enabled = enabled_value
        raw_path = setting.get("path", DEFAULT_WORK_QUEUE_REL_PATH)
    else:
        return None, {
            "state": "invalid", "enabled": False,
            "error": "work_queue must be a path string, object, or false",
        }

    if not enabled:
        return None, {
            "state": "disabled", "enabled": False,
            "reason": "disabled by repo-local work_queue.enabled",
        }
    try:
        path = _confined_path(root, raw_path, label="work_queue.path")
    except WorkQueueInvalid as exc:
        return None, {
            "state": "invalid", "enabled": True, "path": str(raw_path),
            "error": str(exc),
        }
    base = {"enabled": True, "path": str(path)}
    if not path.exists():
        return None, {
            **base, "state": "absent",
            "error": "enabled work queue file does not exist",
        }
    if not path.is_file():
        return None, {
            **base, "state": "invalid",
            "error": "enabled work queue path is not a file",
        }
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, {
            **base, "state": "invalid",
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not isinstance(data, Mapping):
        return None, {
            **base, "state": "invalid",
            "error": "work queue JSON root must be an object",
        }
    return data, {
        **base,
        "state": "valid",
        "schema": data.get("schema"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
    }


def _queue_repo_path(repo_root: Path, raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise WorkQueueInvalid(f"{field_name} must contain non-empty strings")
    if raw != raw.strip() or "\\" in raw:
        raise WorkQueueInvalid(
            f"{field_name} must use canonical repo-relative '/' paths: {raw!r}")
    path = Path(raw)
    if any(part in {".", ".."} for part in path.parts):
        raise WorkQueueInvalid(
            f"{field_name} must not contain '.' or '..' segments: {raw!r}")
    if path.as_posix() != raw:
        raise WorkQueueInvalid(
            f"{field_name} is not a canonical repo-relative path: {raw!r}")
    if path.is_absolute() or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise WorkQueueInvalid(f"{field_name} path must be repo-relative: {raw!r}")
    resolved = _confined_path(repo_root, path, label=field_name)
    return resolved.relative_to(repo_root.resolve()).as_posix()


def work_queue_candidates(
        queue: Mapping[str, Any], *,
        repo_root: str | Path,
        source: Mapping[str, Any],
        project_config: Mapping[str, Any] | None = None
        ) -> tuple[tuple[Candidate, ...], tuple[str, ...], dict[str, Any]]:
    """Validate an entire ``daedalus-work-queue/1`` source, then admit work.

    Validation is whole-file and fail-closed: one malformed ready task makes
    the source ``invalid`` instead of silently shortening the operator's queue.
    Non-ready tasks are valid records but are not candidates.
    """
    root = Path(repo_root).resolve()
    if queue.get("schema") != WORK_QUEUE_SCHEMA:
        raise WorkQueueInvalid(
            f"schema must be {WORK_QUEUE_SCHEMA!r}, got {queue.get('schema')!r}")
    repo_state = queue.get("repo_state")
    if not isinstance(repo_state, Mapping):
        raise WorkQueueInvalid("repo_state must be an object")
    base_revision = str(repo_state.get("head") or "").strip().lower()
    if not _SHA_RE.fullmatch(base_revision):
        raise WorkQueueInvalid(
            "repo_state.head must be a full 40- or 64-hex candidate base "
            "revision")
    tasks = queue.get("tasks")
    if not isinstance(tasks, list):
        raise WorkQueueInvalid("tasks must be an array")

    cfg = project_config if project_config is not None else _project_config(root)
    policy_block = cfg.get("policy") if isinstance(cfg, Mapping) else None
    policy = None
    if isinstance(policy_block, Mapping) and policy_block:
        from daedalus.sensitivity import load_policy
        policy = load_policy(dict(cfg))

    seen: set[str] = set()
    candidates: list[Candidate] = []
    notes: list[str] = []
    non_ready = 0
    blocked = 0
    observed_head = _head_sha(root)
    queue_sha = str(source.get("sha256") or "")
    queue_path = str(source.get("path") or "")
    for index, raw_task in enumerate(tasks):
        where = f"tasks[{index}]"
        if not isinstance(raw_task, Mapping):
            raise WorkQueueInvalid(f"{where} must be an object")
        task_id = str(raw_task.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", task_id):
            raise WorkQueueInvalid(f"{where}.id is missing or not a stable id")
        if task_id in seen:
            raise WorkQueueInvalid(f"duplicate task id {task_id!r}")
        seen.add(task_id)
        state = str(raw_task.get("state") or "").strip().lower()
        if state not in {"ready", "blocked", "done", "disabled"}:
            raise WorkQueueInvalid(
                f"{where}.state must be ready, blocked, done, or disabled")
        if state != "ready":
            non_ready += 1
            continue

        instruction = str(raw_task.get("instruction") or "").strip()
        if not instruction:
            raise WorkQueueInvalid(f"{where}.instruction is required")
        authority_refs = raw_task.get("authority_refs")
        if (not isinstance(authority_refs, list) or not authority_refs
                or any(not isinstance(ref, str) or not ref.strip()
                       for ref in authority_refs)):
            raise WorkQueueInvalid(
                f"{where}.authority_refs must be a non-empty string array")
        raw_targets = raw_task.get("target_paths")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise WorkQueueInvalid(
                f"{where}.target_paths must be a non-empty array")
        targets = tuple(
            _queue_repo_path(root, path,
                             field_name=f"{where}.target_paths")
            for path in raw_targets)
        if len(set(targets)) != len(targets):
            raise WorkQueueInvalid(f"{where}.target_paths contains duplicates")

        gate = raw_task.get("gate")
        if not isinstance(gate, Mapping):
            raise WorkQueueInvalid(f"{where}.gate must be an object")
        argv = gate.get("argv")
        if (not isinstance(argv, list) or not argv
                or any(not isinstance(arg, str) or not arg
                       or "\x00" in arg for arg in argv)):
            raise WorkQueueInvalid(
                f"{where}.gate.argv must be a non-empty string array")
        gate_cwd = gate.get("cwd", ".")
        if gate_cwd != ".":
            raise WorkQueueInvalid(
                f"{where}.gate.cwd must be '.'; subdirectory execution is "
                "not implemented")
        timeout = gate.get("timeout_s")
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(float(timeout)) or float(timeout) <= 0):
            raise WorkQueueInvalid(
                f"{where}.gate.timeout_s must be a positive finite number")
        priority = raw_task.get("priority", 0.0)
        if (isinstance(priority, bool)
                or not isinstance(priority, (int, float))
                or not math.isfinite(float(priority))
                or not 0.0 <= float(priority) <= BAND_SPAN):
            raise WorkQueueInvalid(
                f"{where}.priority must be between 0 and {BAND_SPAN}")

        blocked_paths = list(targets) if policy is None else []
        if policy is not None:
            from daedalus.sensitivity import path_write_blocked
            blocked_paths.extend(
                path for path in targets if path_write_blocked(path, policy))
        if blocked_paths:
            blocked += 1
            notes.append(
                f"WORK QUEUE TASK {task_id} SUPPRESSED: write policy blocks "
                f"{', '.join(blocked_paths)}")
            continue

        evidence = {
            "measurement": f"{WORK_QUEUE_SCHEMA} curated priority",
            "queue_path": queue_path,
            "queue_sha256": queue_sha,
            "queue_schema": WORK_QUEUE_SCHEMA,
            "candidate_base_revision": base_revision,
            "picker_observed_head": observed_head,
            "authority_refs": list(authority_refs),
            "target_paths": list(targets),
            "gate": {
                "argv": list(argv),
                "cwd": gate_cwd,
                "timeout_s": float(timeout),
            },
            "policy_feasible": True,
            "curated_priority": float(priority),
        }
        candidates.append(_candidate(
            task_id=task_id,
            source="work_queue",
            instruction=instruction,
            reason=(
                f"repo-curated ready task at candidate base "
                f"{base_revision[:12]} with {len(targets)} policy-feasible "
                f"target path(s)"),
            band_offset=float(priority),
            evidence=evidence,
            target_paths=targets,
            gate_argv=tuple(argv),
            gate_cwd=gate_cwd,
            gate_timeout_s=float(timeout),
            base_revision=base_revision))

    detail = {
        "tasks": len(tasks),
        "ready": len(candidates),
        "non_ready": non_ready,
        "policy_blocked": blocked,
        "candidate_base_revision": base_revision,
        "picker_observed_head": observed_head,
        "suppressed": blocked > 0,
    }
    return tuple(candidates), tuple(notes), detail


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


def _repo_state_freshness(doc: Mapping[str, Any], label: str,
                          repo_root: str | Path | None = None) -> dict:
    """Does ``doc`` describe the tree we are actually standing in?

    ONE implementation, shared by every source that stamps the revision it was
    written against in ``repo_state.head``. It is a shared function rather than
    a rule each source re-states because this repo has already paid for the
    other design: five separate host predicates drifted apart here, two of them
    ending up MORE permissive than the safety core they were supposed to mirror.

    The comparison is by PREFIX, because these files record a short sha and git
    reports a long one, and a mismatch (or an unreadable stamp) means the
    caller is reasoning about a different tree.

    A ``dirty: true`` snapshot is NOT treated as stale on its own: this repo is
    almost always dirty mid-session, and refusing to rank work whenever an
    editor has unsaved changes would make the loop unusable for exactly the
    person using it. The revision is the honest signal; dirtiness is reported
    but does not suppress.

    Fails OPEN (``fresh: True``) when git cannot answer at all -- a tarball
    checkout with no git is not evidence of staleness, and turning "I cannot
    tell" into "refuse everything" would be a worse failure than ranking.
    """
    state = doc.get("repo_state") if isinstance(doc, Mapping) else None
    recorded = (str(state.get("head") or "").strip()
                if isinstance(state, Mapping) else "")
    dirty = bool(state.get("dirty")) if isinstance(state, Mapping) else False

    if not isinstance(doc, Mapping) or not doc:
        return {"fresh": True, "reason": f"no {label} to check",
                "recorded_head": None, "actual_head": None, "dirty": dirty}
    if not recorded:
        return {"fresh": False,
                "reason": f"the {label} records no repo_state.head, so it "
                          "cannot be checked against the tree it describes",
                "recorded_head": None, "actual_head": None, "dirty": dirty}
    # A prefix comparison is only meaningful against a real abbreviated sha.
    # Without this, a recorded "a" matches roughly one HEAD in sixteen and the
    # gate silently reports fresh -- a check that passes by accident is worse
    # than no check, because it is believed.
    if not _ABBREV_SHA_RE.fullmatch(recorded):
        return {"fresh": False,
                "reason": (f"the {label}'s recorded head {recorded!r} is not "
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
        return {"fresh": True, "reason": f"{label} matches HEAD",
                "recorded_head": recorded, "actual_head": actual[:len(recorded)],
                "dirty": dirty}
    return {"fresh": False,
            "reason": (f"the {label} was written against {recorded} but HEAD "
                       f"is {actual[:len(recorded)]}"),
            "recorded_head": recorded, "actual_head": actual[:len(recorded)],
            "dirty": dirty}


def inventory_freshness(inventory: Mapping[str, Any],
                        repo_root: str | Path | None = None) -> dict:
    """Does the inventory describe the tree we are actually standing in?

    ``docs/FEATURE_INVENTORY.json`` drives the two highest bands, so a stale one
    steers the whole loop toward work that may no longer exist.
    """
    return _repo_state_freshness(inventory, "inventory", repo_root)


# --------------------------------------------------------------------------- #
# source (e): the GENERATED architecture map                                    #
# --------------------------------------------------------------------------- #
MAP_STATE_REL_PATH = "docs/architecture-state.json"


def load_map_state(path: str | Path | None = None,
                   repo_root: str | Path | None = None) -> dict:
    """Read ``docs/architecture-state.json``, or ``{}`` if it cannot be read.

    Same degrade-to-empty contract as :func:`load_inventory`: the picker's job
    is to rank work, not to be the thing that breaks when a generated file is
    mid-write.
    """
    if path is None:
        base = Path(repo_root) if repo_root else ROOT
        path = Path(base) / MAP_STATE_REL_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def map_state_trustworthy(state: Mapping[str, Any],
                          repo_root: str | Path | None = None) -> dict:
    """May the loop rank work out of this snapshot? Two questions, both required.

    INTEGRITY -- has anyone hand-edited the generated file? ``daedalus.mapping.drift``
    states the rule: *any verb that INHERITS lists from an existing snapshot
    rather than rescanning has to ask this first and refuse on a mismatch*.
    Ranking work out of those lists is exactly such a verb.

    FRESHNESS -- does the snapshot describe the tree we are standing in? This
    question used to be missing, and its absence was justified in this very
    docstring with the sentence "a generated file's defence is its digest".
    That was wrong, and it cost something measurable. A digest proves nobody
    tampered with the file; it says NOTHING about which tree was scanned. A
    snapshot generated thirty commits ago verifies its digest perfectly.

    What that bought: an agent executed the loop's top recommendation, which
    asserted ``daedalus/compaction.py`` was an unreachable island. On the live
    tree it was not an island at all -- it was ``unknown``, because of a string
    literal in a smoke-test prompt. The picker had SUPPRESSED the stale
    inventory (which has a freshness gate) while TRUSTING the stale map (which
    had none), and acted on a description of a tree that no longer existed.

    So both questions are asked, and both must pass. A snapshot that records no
    ``repo_state.head`` cannot answer the second one and is therefore NOT
    trusted -- fail closed, the same rule the inventory follows. Until the
    generator stamps the revision it scanned, that is the honest verdict, and
    reporting "I have no trustworthy map" beats ranking work from a tree that
    is gone.
    """
    if not state:
        return {"trusted": True, "reason": "no map snapshot to check"}
    try:
        from daedalus.mapping.drift import digest_ok

        ok = bool(digest_ok(dict(state)))
    except Exception as e:  # mapping unavailable -> cannot verify -> do not trust
        return {"trusted": False,
                "reason": f"could not verify the snapshot digest ({type(e).__name__}: {e})"}
    if not ok:
        return {"trusted": False,
                "integrity": False,
                "reason": ("the snapshot's mechanical lists do not match the digest "
                           "written with them -- it has been hand-edited. Regenerate "
                           "with `daedalus map`")}

    fresh = _repo_state_freshness(state, "map snapshot", repo_root)
    if not fresh["fresh"]:
        return {"trusted": False, "integrity": True, "freshness": fresh,
                "reason": (f"the snapshot's digest verifies, but {fresh['reason']}. "
                           f"Regenerate with `daedalus map`")}
    return {"trusted": True, "integrity": True, "freshness": fresh,
            "reason": f"snapshot digest verifies and {fresh['reason']}"}


def _map_island_instruction(module: str, test_only: bool) -> str:
    how = ("Its ONLY importers are tests, so the behaviour is already pinned: "
           "wiring it up is cheap and a regression would be caught."
           if test_only else
           "NOTHING imports it at all -- not even a test. Whatever you decide, "
           "add a test that exercises the path you keep.")
    return (
        f"Module {module!r} is an ISLAND in the generated architecture map: the "
        f"reachability engine cannot get to it from ANY entry point. {how} "
        f"Either wire it into a real caller so the capability is reachable from "
        f"the CLI / API / harness, or delete it together with its tests. Do not "
        f"do both, and do not leave a shim behind -- a shim is a separate "
        f"finding with its own remedy. Re-run `daedalus map --check` afterwards; "
        f"the island count must go down, not sideways."
    )


def _map_shim_instruction(module: str) -> str:
    return (
        f"Module {module!r} is a SHIM in the generated architecture map: it "
        f"exists only to re-export from somewhere else, and nothing reaches it. "
        f"The remedy is NOT the island remedy -- do not 'wire it in'. Find its "
        f"importers (there should be none), confirm the real module it forwards "
        f"to is reachable on its own, and then remove the shim and its entry in "
        f"the map's shim list. If something DOES still import it, the finding is "
        f"wrong and the map should be corrected instead."
    )


def docref_candidates(report: Mapping[str, Any] | Any, *, top: int = 5) -> tuple[
        tuple[Candidate, ...], tuple[str, ...]]:
    """Candidates from :mod:`daedalus.spine.docrefs`: prose the tree contradicts.

    THE ONE THAT CLOSES THE LOOP. Every other source in this module produces
    source surgery under ``daedalus/``; the installed self-policy permits
    ``docs/``, ``tests/`` and ``README.md``. Measured 2026-07-29, the
    intersection was EMPTY -- the picker ranked seventeen candidates and a local
    writer was permitted to attempt none of them. This source produces work
    inside the permitted tree without widening the tree, which is the difference
    between closing the loop and lowering the fence to reach it.

    ONE CANDIDATE PER DOCUMENT, NOT PER REFERENCE. A doc with eleven broken
    references is one editing session, not eleven attempts: they share a file,
    a gate run and a rollback, and eleven attempts against one file would be
    eleven chances to collide with each other for one unit of work. The
    per-reference detail still travels, in the evidence.

    The gate is the scan itself, not pytest. ``docrefs.verify_fix`` checks the
    DENOMINATOR first -- deleting the paragraph withdraws the claim and lowers
    ``resolving`` in one move, which would otherwise read as a fix. That
    asymmetry is the whole reason this source is safe to point a weak model at,
    so a candidate that does not carry it is not this source's candidate.
    """
    broken = getattr(report, "broken", None)
    if broken is None and isinstance(report, Mapping):
        broken = report.get("broken")
    if not broken:
        return (), ()

    def _field(ref: Any, name: str) -> Any:
        return (ref.get(name) if isinstance(ref, Mapping)
                else getattr(ref, name, None))

    by_doc: dict[str, list[Any]] = {}
    for ref in broken:
        doc = str(_field(ref, "doc_path") or "").replace("\\", "/")
        if not doc:
            continue
        by_doc.setdefault(doc, []).append(ref)

    # ``resolving`` is a SEQUENCE of references, not a count -- it carries the
    # evidence, which is what makes docrefs.verify_fix's denominator check
    # possible at all. ``files_scanned`` really is an int. Counting the first
    # with ``int()`` was this function's first bug.
    def _count(name: str) -> int:
        value = (report.get(name) if isinstance(report, Mapping)
                 else getattr(report, name, None))
        if value is None:
            return 0
        return len(value) if hasattr(value, "__len__") else int(value)

    resolving = _count("resolving")
    scanned = _count("files_scanned")

    # Per-document resolving counts, for the gate's second denominator. The
    # corpus count alone is blind to a document that held no resolving
    # reference: gutting it changes nothing corpus-wide, so the one move the
    # denominator exists to catch would pass. Measured by Minos.
    def _seq(name: str) -> Sequence[Any]:
        value = (report.get(name) if isinstance(report, Mapping)
                 else getattr(report, name, None))
        return value if hasattr(value, "__iter__") and not isinstance(value, str) else ()

    doc_resolving: dict[str, int] = {}
    for ref in _seq("resolving"):
        key = str(_field(ref, "doc_path") or "").replace("\\", "/")
        if key:
            doc_resolving[key] = doc_resolving.get(key, 0) + 1
    # A document with zero resolving references has no entry and a real count
    # of 0 -- that is the case the second denominator exists for, so it must
    # NOT be confused with "we could not count". The distinction is whether the
    # report carried the evidence sequence at all.
    counted_per_doc = bool(doc_resolving) or resolving == 0

    candidates: list[Candidate] = []
    notes: list[str] = []
    # Worst document first: most broken references is the biggest single
    # correction available, and ties broken by path so the order is stable
    # across runs rather than dependent on dict insertion.
    ranked = sorted(by_doc.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for doc, refs in ranked[:max(0, int(top))]:
        detail = []
        for ref in refs[:12]:
            detail.append({
                "line": _field(ref, "line"),
                "raw": str(_field(ref, "raw") or "")[:160],
                "module_path": _field(ref, "module_path"),
                "symbol": _field(ref, "symbol"),
                "why": str(_field(ref, "why") or "")[:200],
            })
        # A reference whose line number is missing or unparseable contributes no
        # window rather than a guessed one: pointing an editor at the wrong
        # lines is worse than letting it read the whole file.
        window_lines: list[int] = []
        for d in detail:
            try:
                line_no = int(d["line"])
            except (TypeError, ValueError):
                continue
            if line_no > 0 and line_no not in window_lines:
                window_lines.append(line_no)
        # Bounded so a document with a hundred broken references cannot move
        # further than the band allows -- the gap to the next band is what keeps
        # a measurement from silently reordering a human's stated priority.
        offset = min(40.0, 4.0 * len(refs))
        candidates.append(_candidate(
            task_id=f"docref-{_slug(doc)}-{_short_hash(doc)}",
            source="docref",
            # WORDING IS LOAD-BEARING, measured on the first live loop run: the
            # earlier phrasing of the guard sentence ("DO NOT delete ...
            # removing the claim ... make the reference go away") tripped
            # change_risk's keyword escalation -- the sentence FORBIDDING
            # deletion was read as intent to delete, every docref write routed
            # "high -> stays on Claude", and the free-lane gate bounced the
            # whole lane. The classifier is deliberately blunt; the instruction
            # is ours. So it states the same invariant in preserving verbs.
            instruction=(
                f"{doc} contains {len(refs)} reference(s) to code that does not "
                f"exist in this tree. Correct the PROSE to match the tree, or "
                f"correct the reference to name what the code is actually "
                f"called now.\n\n"
                f"Every sentence, paragraph and file must SURVIVE the edit: the "
                f"verifier counts the RESOLVING references before it judges the "
                f"broken one, so a withdrawn claim lowers that count and fails "
                f"the gate. Correcting the wording is the only accepted move -- "
                f"a statement that quietly vanishes is treated as evidence "
                f"destroyed, not as a fix.\n\n"
                f"Broken references:\n" + "\n".join(
                    f"  line {d['line']}: {d['raw']}  -- {d['why']}"
                    for d in detail)),
            reason=(f"{doc} makes {len(refs)} statement(s) about code that is "
                    f"not in this tree"),
            band_offset=offset,
            evidence={
                "measurement": "daedalus.spine.docrefs.scan (derived every run)",
                "doc_path": doc,
                "broken_in_this_doc": len(refs),
                "references": detail,
                # WINDOWED-REWRITE hint for the local write lane. The first
                # end-to-end attempt proved the default +/-40 fragment too
                # expensive for an unattended loop: two HANDOFF windows asked
                # the model to regenerate 1,352 words and were still running
                # after four minutes. Docref is unusually precise -- the scan
                # names the exact broken line -- so it requests only that line
                # here. Live probes at +/-8 and +/-2 showed the bench reflowing
                # 17->10 and 5->4 lines; exact-line windows make the splice
                # invariant structural rather than aspirational.
                # Other callers that pass bare line numbers retain the
                # provider's conservative DEFAULT_WINDOW_RADIUS unchanged.
                # Consumed via
                # TaskSpec.metadata["picker_evidence"]["rewrite_windows"];
                # a consumer that ignores it gets today's full-file rewrite.
                # Drawn from `detail`, not `refs`, so the model is only pointed
                # at lines the instruction actually named (both cap at 12).
                "rewrite_windows": {
                    doc: [{"line": line, "radius": 0} for line in window_lines]
                } if window_lines else {},
                "corpus_resolving": resolving,
                "corpus_broken": len(broken),
                "corpus_files_scanned": scanned,
            },
            # THE GATE IS THE RE-SCAN, NOT PYTEST. ``gate_paths=(doc,)`` became
            # ``pytest docs/THAT.md``, which exits non-zero on a path pytest
            # cannot collect -- every docref attempt failed its gate always,
            # for a reason that had nothing to do with the fix. Fail-closed and
            # indistinguishable from a real finding, which is the worse half.
            #
            # ``--ref`` is built from ``refs``, not ``detail``: detail is capped
            # at twelve for the instruction, and a fix that left reference #13
            # broken would otherwise pass. The raw text is the UNTRUNCATED one
            # for the same reason detail truncates -- the gate refuses to judge
            # a target it cannot find verbatim, so a 160-char copy would block.
            gate_argv=(
                sys.executable, "-m", "daedalus.spine.docref_gate",
                "--repo-root", ".", "--doc", doc,
                "--expect-resolving", str(resolving),
                *(("--expect-doc-resolving", str(doc_resolving.get(doc, 0)))
                  if counted_per_doc else ()),
                *(arg for ref in refs
                  for arg in ("--ref", str(_field(ref, "raw") or ""))),
            ),
            gate_cwd=".",
            target_paths=(doc,),
        ))
    if len(ranked) > top:
        notes.append(
            f"DOCREF: {len(ranked)} document(s) carry broken references; "
            f"the {top} worst are queued")
    if not counted_per_doc:
        notes.append(
            "DOCREF: the scan report carried no per-reference evidence, so the "
            "per-document denominator could not be measured; these gates run on "
            "the corpus count alone and are blind to a gutted document that "
            "held no resolving reference")
    return tuple(candidates), tuple(notes)


def _spectral_row(spectral: Mapping[str, Mapping[str, Any]] | None,
                  module: str) -> dict[str, Any]:
    """Spectral facts for one module, or nothing at all.

    ENRICHMENT ONLY. These keys decorate a candidate the map already produced
    for reachability reasons; they never create one, never remove one, and
    never touch ``band_offset``. A module with no spectral row contributes no
    keys rather than zeroes -- absent means NOT MEASURED, and a zero here would
    read as a measurement that says something.
    """
    if not spectral:
        return {}
    row = spectral.get(module)
    return dict(row) if isinstance(row, Mapping) and row else {}


def map_candidates(state: Mapping[str, Any], *,
                   spectral: Mapping[str, Mapping[str, Any]] | None = None,
                   ) -> tuple[tuple[Candidate, ...], tuple[str, ...]]:
    """Candidates from the generated map: islands and shims, with their evidence.

    Islands and shims are deliberately DIFFERENT sources with different
    instructions. They look alike in a count ("unreached") and need opposite
    remedies -- an island is capability nobody can get to and usually wants
    wiring; a shim is indirection nobody uses and wants removing. Collapsing
    them into one "unreached" bucket would hand a fixer the wrong verb.

    ``spectral`` is optional evidence enrichment from
    :func:`daedalus.mapping.spectral.spectral_evidence` -- structure
    measurements attached to the SAME modules, so a fixer can see whether the
    package around an island is tight or a pass-through. Omitted by default:
    the ranking, the bands and the candidate set are byte-identical with and
    without it. It is evidence, not a gate.
    """
    if not isinstance(state, Mapping) or not state:
        return (), ()
    islands = _strs(state.get("islands"))
    shims = _strs(state.get("shims"))
    test_only = set(_strs(state.get("test_only")))
    counts = state.get("counts") if isinstance(state.get("counts"), Mapping) else {}
    digest = str(state.get("digest") or "")

    candidates: list[Candidate] = []
    for module in islands:
        is_test_only = module in test_only
        # Measured: an island whose tests already exist is cheap and safe to
        # wire, because the behaviour is pinned before anything is moved. One
        # with no importer at all is a research task wearing an engineering
        # task's clothes -- same reasoning the inventory source uses.
        offset = 30.0 if is_test_only else 10.0
        candidates.append(_candidate(
            task_id=f"map-island-{_slug(module)}-{_short_hash(module)}",
            source="map_island",
            instruction=_map_island_instruction(module, is_test_only),
            reason=(f"{module} is unreachable from every entry point"
                    + (" and is imported only by tests" if is_test_only else
                       " and has no importer at all")),
            band_offset=offset,
            evidence={
                "measurement": f"{MAP_STATE_REL_PATH} (generated, digest-covered)",
                "classification": "island",
                "module": module,
                "imported_only_by_tests": is_test_only,
                "snapshot_digest": digest,
                "snapshot_islands": len(islands),
                "snapshot_modules": counts.get("modules"),
                **_spectral_row(spectral, module),
            },
            gate_paths=()))

    for module in shims:
        candidates.append(_candidate(
            task_id=f"map-shim-{_slug(module)}-{_short_hash(module)}",
            source="map_shim",
            instruction=_map_shim_instruction(module),
            reason=f"{module} is a re-export shim that nothing reaches",
            band_offset=10.0,
            evidence={
                "measurement": f"{MAP_STATE_REL_PATH} (generated, digest-covered)",
                "classification": "shim",
                "module": module,
                "snapshot_digest": digest,
                "snapshot_shims": len(shims),
                "snapshot_modules": counts.get("modules"),
                **_spectral_row(spectral, module),
            },
            gate_paths=()))

    notes: list[str] = []
    unknown = _strs(state.get("unknown"))
    if unknown:
        # Reported, never ranked: "the engine could not classify this" is a
        # finding about the MAP, and turning it into a work item would send a
        # fixer to change code because a scanner was confused.
        notes.append(
            f"map: {len(unknown)} module(s) the reachability engine could not "
            f"classify -- reported, not ranked (fix the map, not the module)")
    return tuple(candidates), tuple(notes)


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

# The deepest sink memory can express: the whole span, which lands a candidate
# exactly on its band FLOOR. Deliberately equal to BAND_SPAN and never larger --
# "I have tried this and it is finished with me" outranks every within-band
# measurement, but it can still never push a candidate out of its stated band.
# Memory reorders within a priority; it does not overrule one.
ATTEMPT_MEMORY_PENALTY = BAND_SPAN


# --------------------------------------------------------------------------- #
# the OUTCOME POLICY                                                           #
# --------------------------------------------------------------------------- #
# Memory first shipped sinking EVERY attempted candidate by the same amount.
# That made three very different facts indistinguishable in the SCORE -- a run
# that produced a CLEAN gated patch now waiting on a human, a run whose gates
# REJECTED the diff, and a run where the worktree never even came up -- and left
# the difference visible only in the reason TEXT, which nothing sorts by. A
# distinction that only exists in prose is a distinction the loop does not have.
#
# The table below is the missing argument, written as DATA so a reviewer can
# disagree with a number instead of with a paragraph. The question it answers is
# not "did the attempt succeed". It is:
#
#     given that we already ran this exact instruction and it ended in state S,
#     how much of this candidate's measured standing should survive?
#
# Two axes decide it:
#
#   1. Did the attempt teach us something about the TASK, or only about the
#      MACHINE? A rejected diff is evidence about the work. A worktree that
#      would not build is evidence about the box -- and sinking work for it is
#      how one bad afternoon buries a real task at the bottom of the queue.
#   2. Is a HUMAN already holding the output? A ``clean`` attempt has produced a
#      gated patch waiting on a review decision. Model time cannot advance that,
#      and a second attempt does not merely waste a lane: it hands the reviewer
#      two patches for one instruction and makes them choose.
#
# RESIDUAL is the fraction of BAND_SPAN an attempted candidate may KEEP, and it
# is applied as a CEILING, not as a subtraction. A subtraction made the
# outcome's effect depend on where the measurement happened to sit -- the same
# ``no_change`` sank a well-measured island by half a band and a bare one not at
# all -- so identical outcomes got incomparable treatment. A ceiling states one
# claim per outcome ("attempted work of this kind may stand no higher than
# here"), and because it is a ``min()`` it can only ever lower a candidate.
# Memory never promotes.
#
# SEVERITY exists because the band floor is a HARD BOTTOM. ``clean`` and
# ``gates_failed`` both belong at it, and there is nothing below it that does
# not leave the band -- which is not memory's to do. So that last distinction is
# carried as a tie-break in :func:`rank`, exactly as ``prior_attempts`` already
# is, and for exactly the same reason: the score cannot express an order the
# band forbids, and a tie-break can.
#
# Still a PENALTY, never a filter. Every attempted candidate stays in the queue
# at every residual, including 0.0. One transient failure must not be able to
# delete real work.
@dataclass(frozen=True)
class OutcomePolicy:
    """What one recorded attempt outcome means for picking that work again.

    ``residual``  fraction of :data:`BAND_SPAN` an attempted candidate may keep.
    ``severity``  floor tie-break, 0..1; HIGHER means re-pick this one LAST.
    ``meaning``   what the outcome says about the task, for the reason line.
    ``verdict``   why that residual -- one sentence a human can refuse.
    """

    outcome: str
    residual: float
    severity: float
    meaning: str
    verdict: str

    def ceiling(self, n_same: int = 1) -> float:
        """The highest offset this candidate may keep after ``n_same`` attempts.

        Repeats COMPOUND. One worktree failure is an accident; five in a row is
        a broken task, and a policy that treated them alike would leave the loop
        re-picking a candidate it cannot even check out -- the original defect,
        reintroduced through the outcomes that were judged harmless. ``residual
        ** n`` is monotone, bounded, and never actually reaches the floor while
        ``residual > 0``, so a compounding sink is still a penalty and still
        never a filter.
        """
        n = max(1, int(n_same))
        return round(BAND_SPAN * (self.residual ** n), 4)


OUTCOME_POLICY: dict[str, OutcomePolicy] = {
    # A patch PASSED the gates and is sitting in the review queue. The bottleneck
    # is a human, and no amount of model time moves a human.
    "clean": OutcomePolicy(
        outcome="clean", residual=0.0, severity=0.95,
        meaning="a gated patch already exists and is waiting on a human",
        verdict="re-attempting is close to pointless and worse than idle: the "
                "blocker is a review decision, and a second patch for one "
                "instruction makes the reviewer choose between two"),
    # A diff existed and the gates refused it. Unlike `clean`, more model time
    # CAN still move this -- so it sinks to the same floor but is picked back up
    # before `clean` is (see severity).
    "gates_failed": OutcomePolicy(
        outcome="gates_failed", residual=0.0, severity=0.90,
        meaning="the runner produced a diff and the gates rejected it",
        verdict="real evidence about this task: the instruction as written "
                "leads somewhere the gates do not accept, so re-running it "
                "unchanged is a re-roll of dice we have already seen land"),
    # The advisory / nothing-proposed case. Says the least of any outcome that
    # actually reached a model.
    "no_change": OutcomePolicy(
        outcome="no_change", residual=0.5, severity=0.50,
        meaning="the runner ran and proposed nothing",
        verdict="weak evidence either way -- an advisory lane, a vague "
                "instruction and a genuinely finished feature all look like "
                "this -- but a lane was spent, so it sinks to half its band",
    ),
    # From here down: the machine failed, not the work. Sinking hard here is how
    # one flaky provider call buries a real task.
    "runner_failed": OutcomePolicy(
        outcome="runner_failed", residual=0.8, severity=0.30,
        meaning="the runner itself raised",
        verdict="infrastructure, not evidence: nothing was learned about the "
                "task, and a hard sink would let one flaky provider call bury "
                "real work"),
    "worktree_failed": OutcomePolicy(
        outcome="worktree_failed", residual=0.9, severity=0.20,
        meaning="no isolated checkout could be produced; no model was reached",
        verdict="the attempt never got far enough to learn anything at all, so "
                "it barely moves -- and compounding handles the case where the "
                "checkout is broken for this task specifically"),
    "cancelled": OutcomePolicy(
        outcome="cancelled", residual=0.9, severity=0.15,
        meaning="a human or the cancel token stopped the attempt",
        verdict="says nothing about the work's merit and often means the "
                "operator intends to resume, so it is very nearly a no-op"),
    "storage_unavailable": OutcomePolicy(
        outcome="storage_unavailable", residual=0.95, severity=0.10,
        meaning="the storage guard refused before anything ran",
        verdict="the furthest an outcome gets from evidence about the task: a "
                "condition of the box that will clear on its own"),
}

# The outcome is missing or is a string nobody has classified. FAIL CLOSED to
# the flat behaviour this policy replaced, for two independent reasons:
#
#   * an intent with NO result is an attempt still IN FLIGHT. Re-picking it
#     races a run that is already holding this task, in the same worktree
#     branch. That is the one case where a soft sink is actively unsafe.
#   * an unrecognised state is a state nobody has argued about yet, and an
#     unargued state must not become the escape hatch that makes memory WEAKER
#     than it was before the policy existed.
#
# A drift test pins OUTCOME_POLICY's keys against attempt.ATTEMPT_STATES, so a
# newly added state is a RED test rather than a silent fall through to here.
UNKNOWN_OUTCOME = OutcomePolicy(
    outcome="unknown", residual=0.0, severity=1.0,
    meaning="the ledger records an attempt with no recognised result state",
    verdict="fail closed: an attempt with no result is still in flight, and "
            "re-picking it races the run that already holds this task")


def outcome_policy(outcome: Any) -> OutcomePolicy:
    """The policy row for a recorded outcome; :data:`UNKNOWN_OUTCOME` if unknown.

    Never raises and never returns ``None``: the caller is on the ranking path,
    where a missing row must degrade to the safest reading rather than to a
    traceback or -- far worse -- to no penalty at all.
    """
    key = str(outcome or "").strip()
    return OUTCOME_POLICY.get(key, UNKNOWN_OUTCOME)


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


def _definition_fingerprint(
        instruction: str, *,
        base_revision: Any = None,
        target_paths: Sequence[Any] = (),
        gate: Mapping[str, Any] | None = None) -> str:
    """Retry identity for curated work; byte-compatible for legacy tasks.

    A queue task is not the same work merely because its prose stayed the same:
    a new candidate base, target scope, or executable gate changes the
    proposition being attempted. Legacy tasks declare none of these fields and
    retain the historical instruction-only fingerprint exactly.
    """
    targets = tuple(str(path) for path in (target_paths or ()))
    gate_map = dict(gate) if isinstance(gate, Mapping) else {}
    if not base_revision and not targets and not gate_map:
        return instruction_fingerprint(instruction)
    body = {
        "instruction": str(instruction),
        "base_revision": str(base_revision) if base_revision else None,
        "target_paths": list(targets),
        "gate": {
            "argv": [str(arg) for arg in (gate_map.get("argv") or ())],
            "cwd": str(gate_map.get("cwd", ".")),
            "timeout_s": gate_map.get("timeout_s"),
        } if gate_map else {},
    }
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _candidate_definition_fingerprint(candidate: Candidate) -> str:
    gate = ({
        "argv": list(candidate.gate_argv),
        "cwd": candidate.gate_cwd,
        "timeout_s": candidate.gate_timeout_s,
    } if candidate.gate_argv else None)
    return _definition_fingerprint(
        candidate.instruction,
        base_revision=candidate.base_revision,
        target_paths=candidate.target_paths,
        gate=gate)


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
                      "last_outcome": None, "by_instruction": {},
                      "by_definition": {}})
        rec["n_attempts"] += 1
        fingerprint = _definition_fingerprint(
            payload.get("instruction") or "",
            base_revision=payload.get("base_revision"),
            target_paths=payload.get("target_paths") or (),
            gate=payload.get("gate") if isinstance(
                payload.get("gate"), Mapping) else None)
        rec["by_instruction"][fingerprint] = (
            rec["by_instruction"].get(fingerprint, 0) + 1)
        definition = rec["by_definition"].setdefault(
            fingerprint,
            {"n_attempts": 0, "last_state": None, "last_ts": None,
             "last_outcome": None})
        definition["n_attempts"] += 1
        if definition["last_state"] is None:
            definition["last_state"] = intent.state
            definition["last_ts"] = intent.resolved_ts or intent.created_ts
            outcome = intent.result if isinstance(
                intent.result, Mapping) else {}
            definition["last_outcome"] = (
                str(outcome.get("state") or "") or None)
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

    HOW FAR it sinks is :data:`OUTCOME_POLICY`'s decision, not a constant: the
    outcome is applied as a CEILING on the measured offset, so the score itself
    distinguishes "a patch is waiting for you" from "the gates said no" from
    "the worktree would not build". Before this, all three sank identically and
    the difference survived only in the reason text.
    """
    if not history:
        return tuple(candidates), ()
    out: list[Candidate] = []
    sunk = 0
    held = 0
    redefined = 0
    redefined_instruction = 0
    redefined_definition = 0
    by_outcome: dict[str, int] = {}
    for cand in candidates:
        rec = history.get(cand.task_id)
        if not rec:
            out.append(cand)
            continue
        fingerprint = _candidate_definition_fingerprint(cand)
        definition_label = (
            "task definition"
            if cand.base_revision or cand.target_paths or cand.gate_argv
            else "instruction")
        definition = rec.get("by_definition", {}).get(fingerprint)
        same = int(
            definition.get("n_attempts", 0)
            if isinstance(definition, Mapping) else
            rec.get("by_instruction", {}).get(fingerprint, 0))
        evidence = dict(cand.evidence)
        evidence["prior_attempts"] = int(rec.get("n_attempts") or 0)
        evidence["prior_attempts_same_instruction"] = same
        evidence["prior_attempts_same_definition"] = same
        matched = definition if isinstance(definition, Mapping) else rec
        evidence["last_attempt_state"] = matched.get("last_state")
        evidence["last_attempt_outcome"] = matched.get("last_outcome")
        evidence["last_attempt_ts"] = matched.get("last_ts")

        if not same:
            # LINEAGE matched, DEFINITION did not: the id is stable across
            # definition changes, so this is genuinely different work wearing
            # a familiar name. Record the lineage, do not sink it -- penalising
            # it would be evidence about a task nobody is proposing any more.
            redefined += 1
            curated_definition = bool(
                cand.base_revision or cand.target_paths or cand.gate_argv)
            if curated_definition:
                redefined_definition += 1
            else:
                redefined_instruction += 1
            evidence["memory"] = ("same task_id, different task definition -- "
                                  "not treated as already attempted")
            out.append(replace(cand, evidence=evidence))
            continue

        policy = outcome_policy(matched.get("last_outcome"))
        ceiling = policy.ceiling(same)
        offset = _clamp(min(cand.offset, ceiling), 0.0, BAND_SPAN)
        by_outcome[policy.outcome] = by_outcome.get(policy.outcome, 0) + 1
        if offset < cand.offset:
            sunk += 1
        else:
            # Remembered, but the measurement already had it at or below its
            # outcome's ceiling. Counted separately because "memory moved 4
            # candidates" would otherwise be a claim about work that did not
            # move, and the note is the only place an operator sees this.
            held += 1
        # The audit trail for the number above: the ceiling, what it was applied
        # to, and the argument for that ceiling -- so a human reading the review
        # packet can re-derive the score and refuse the policy, not just the sort.
        evidence["memory_outcome_residual"] = policy.residual
        evidence["memory_outcome_severity"] = policy.severity
        evidence["memory_offset_ceiling"] = ceiling
        evidence["memory_offset_before"] = cand.offset
        evidence["memory_policy"] = policy.verdict
        out.append(replace(
            cand,
            score=round(SOURCE_BANDS[cand.source] + offset, 4),
            evidence=evidence,
            reason=(f"{cand.reason}; already attempted "
                    f"{same}x with this exact {definition_label} (last: "
                    f"{matched.get('last_outcome') or matched.get('last_state')}) -- "
                    f"{policy.meaning}, so it may stand no higher than "
                    f"{ceiling:.2f} in its band")))

    notes: list[str] = []
    remembered = sunk + held
    if remembered:
        breakdown = ", ".join(f"{n}x {name}"
                              for name, n in sorted(by_outcome.items()))
        notes.append(f"attempt memory: {remembered} candidate(s) match a prior "
                     f"attempt at the same task definition ({breakdown}); {sunk} "
                     f"sank to their outcome's ceiling, {held} already stood at "
                     f"or below it")
    if redefined_instruction:
        notes.append(
            f"attempt memory: {redefined_instruction} candidate(s) share a "
            "task_id with a prior attempt but their instruction changed, so "
            "they were NOT penalised")
    if redefined_definition:
        notes.append(
            f"attempt memory: {redefined_definition} candidate(s) share a "
            "task_id with a prior attempt but their task definition changed, "
            "so they were NOT penalised")
    if not notes:
        notes.append("attempt memory: the ledger has attempts recorded, but "
                     "none for a candidate currently in the queue")
    return tuple(out), tuple(notes)


def rank(candidates: Sequence[Candidate],
         limit: int | None = None) -> tuple[Candidate, ...]:
    """Deterministic ranking: score desc, mildest outcome, fewest attempts,
    source order, task_id.

    The tie-breaks are not decoration. Scores collide constantly (two islands
    with the same test count are genuinely equal on evidence), and a queue whose
    order depends on dict iteration or on which source ran first is not
    reproducible -- which would make "measurement picks the next task"
    unfalsifiable, since two runs could disagree with no cause to point at.

    The memory tie-breaks rank ahead of the rest because the score alone cannot
    express memory at the bottom of a band. ``apply_attempt_memory`` drives a
    fully-sunk candidate's offset to the band FLOOR, and the floor is also where
    every candidate with no measured evidence already sits -- so tried and
    untried, and ``clean`` and ``gates_failed``, all collide on score exactly
    when the distinction matters most. Expressing it as a tie-break rather than
    a bigger penalty is deliberate: a penalty large enough to separate them
    would have to leave the band, and the stated priority is not memory's to
    overrule.

    OUTCOME SEVERITY is checked BEFORE the attempt count, because the count is
    the weaker fact. A task attempted once and returned ``clean`` has a patch
    waiting on a human; a task attempted three times whose worktree never built
    has taught us nothing at all. The second is the better next pick despite
    having been tried more often. Untried candidates carry no severity and read
    as ``0.0``, so they still come first at any given score.
    """
    order = {name: i for i, name in enumerate(SOURCE_ORDER)}

    def _tried(c: Candidate) -> int:
        try:
            return int(c.evidence.get("prior_attempts") or 0)
        except (TypeError, ValueError):
            return 0

    def _severity(c: Candidate) -> float:
        # Set only by apply_attempt_memory, and only on candidates it actually
        # sank -- a candidate whose INSTRUCTION was rewritten keeps its lineage
        # in prior_attempts but must not inherit the old outcome's severity.
        try:
            return float(c.evidence.get("memory_outcome_severity") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(
        candidates,
        key=lambda c: (-c.score, _severity(c), _tried(c),
                       order.get(c.source, len(order)), c.task_id))
    if limit is not None and limit >= 0:
        ranked = ranked[:limit]
    return tuple(ranked)


def build_queue(repo_root: str | Path | None = None, *,
                limit: int | None = DEFAULT_LIMIT,
                include_eval: bool = False,
                include_hotspots: bool = False,
                include_spectral: bool = False,
                inventory: Mapping[str, Any] | None = None,
                map_snapshot: Mapping[str, Any] | None = None,
                baseline: Mapping[str, Any] | None = None,
                use_attempt_memory: bool = True,
                enforce_inventory_freshness: bool = True,
                spine_db: str | Path | None = None) -> PickedQueue:
    """Build the ranked queue. Never raises on a bad or missing source file.

    ``include_eval``, ``include_hotspots`` and ``include_spectral`` default to
    OFF: each costs a whole-repo analysis pass, and a picker that takes a minute
    to answer "what next" will not be run before every attempt, which would
    leave the loop picking by habit instead of by measurement.
    ``include_spectral`` is MEASURED at ~10s (``reach.analyse`` over this tree)
    and adds only evidence keys -- it cannot change the queue's contents or
    order.
    """
    root = Path(repo_root).resolve() if repo_root else ROOT
    candidates: list[Candidate] = []
    notes: list[str] = []
    sources: dict[str, Any] = {}
    project_config = _project_config(root)

    queue_data, queue_source = load_work_queue(
        root, project_config=project_config)
    if queue_data is not None:
        try:
            queue_cands, queue_notes, queue_detail = work_queue_candidates(
                queue_data, repo_root=root, source=queue_source,
                project_config=project_config)
        except WorkQueueInvalid as exc:
            queue_source = {
                **queue_source,
                "state": "invalid",
                "error": str(exc),
            }
            notes.append(f"WORK QUEUE INVALID: {exc}")
        else:
            candidates.extend(queue_cands)
            notes.extend(queue_notes)
            queue_source = {**queue_source, **queue_detail}
    elif queue_source.get("state") in {"absent", "invalid"}:
        notes.append(
            f"WORK QUEUE {str(queue_source.get('state')).upper()}: "
            f"{queue_source.get('error')}")
    sources["work_queue"] = queue_source

    map_mode = _picker_source_mode(project_config, "map")
    if map_mode == "disabled":
        sources["map"] = {
            "state": "disabled", "read": False, "candidates": 0,
            "reason": "disabled by repo-local picker_sources.map",
        }
    elif map_mode == "invalid":
        sources["map"] = {
            "state": "invalid", "read": False, "candidates": 0,
            "error": "picker_sources.map must be enabled or disabled",
        }
    else:
        map_path = Path(root) / MAP_STATE_REL_PATH
        if (project_config is not None and map_snapshot is None
                and not map_path.exists()):
            sources["map"] = {
                "state": "absent", "path": str(map_path), "read": False,
                "candidates": 0,
                "error": "enabled map source file does not exist",
            }
            notes.append(f"MAP ABSENT: {map_path}")
        else:
            map_state = (
                load_map_state(repo_root=root)
                if map_snapshot is None else map_snapshot)
            map_trust = map_state_trustworthy(map_state, repo_root=root)
            spectral_rows: Mapping[str, Mapping[str, Any]] | None = None
            spectral_note = "off"
            if include_spectral:
                # Never raises out of build_queue: the contract is "never raises
                # on a bad or missing source", and an optional enrichment is the
                # last thing that should be allowed to take the queue down.
                try:
                    from ..mapping import spectral as spectral_mod
                    reading = spectral_mod.analyse(root)
                    if reading.get("available"):
                        spectral_rows = spectral_mod.spectral_evidence(reading)
                        spectral_note = f"on ({len(spectral_rows)} module rows)"
                    else:
                        spectral_note = f"unavailable: {reading.get('reason')}"
                        notes.append(f"SPECTRAL UNAVAILABLE: {reading.get('reason')}")
                except Exception as exc:  # noqa: BLE001 - enrichment must not block
                    spectral_note = f"failed: {exc}"
                    notes.append(f"SPECTRAL FAILED: {exc}")
            map_cands, map_notes = map_candidates(map_state, spectral=spectral_rows)
            if map_trust["trusted"]:
                candidates.extend(map_cands)
                notes.extend(map_notes)
            else:
                # A hand-edited generated file is worse than a missing one: it
                # looks authoritative. Withheld for the same reason the
                # inventory is, and said out loud for the same reason.
                notes.append(
                    f"MAP SUPPRESSED ({len(map_cands)} candidate(s) withheld): "
                    f"{map_trust['reason']}")
            sources["map"] = {
                "state": "valid" if map_trust["trusted"] else "invalid",
                "path": str(map_path),
                "read": bool(map_state),
                "candidates": len(map_cands) if map_trust["trusted"] else 0,
                "suppressed": not map_trust["trusted"],
                "trust": map_trust,
                "spectral": spectral_note,
            }

    # source: prose the tree contradicts. Derived every run, so unlike the map
    # and the inventory it has no snapshot that can go stale and no digest to
    # verify -- the scan IS the measurement, taken now, against this tree.
    # Never raises (docrefs.scan promises that); a failure here must cost the
    # queue this one source, never the whole queue.
    docref_mode = _picker_source_mode(project_config, "docref")
    if docref_mode == "disabled":
        sources["docref"] = {
            "state": "disabled", "read": False, "candidates": 0,
            "reason": "disabled by repo-local picker_sources.docref",
        }
    elif docref_mode == "invalid":
        sources["docref"] = {
            "state": "invalid", "read": False, "candidates": 0,
            "error": "picker_sources.docref must be enabled or disabled",
        }
    else:
        try:
            from . import docrefs

            docref_report = docrefs.scan(root)
            doc_cands, doc_notes = docref_candidates(docref_report)
            candidates.extend(doc_cands)
            notes.extend(doc_notes)
            sources["docref"] = {
                "state": "valid",
                "read": True,
                "candidates": len(doc_cands),
                "files_scanned": int(getattr(docref_report, "files_scanned", 0)),
                # resolving/broken/skipped are sequences of references, not
                # counts: the picker reports the size, the candidate carries the
                # detail, and verify_fix needs the references themselves.
                "resolving": len(getattr(docref_report, "resolving", ()) or ()),
                "broken": len(getattr(docref_report, "broken", ()) or ()),
                "skipped": len(getattr(docref_report, "skipped", ()) or ()),
            }
        except Exception as exc:                     # noqa: BLE001
            # Reported, not swallowed: a source that failed is a different fact
            # from a source that found nothing, and a queue that hides the
            # difference is the shape this repo keeps finding in stale
            # artifacts.
            sources["docref"] = {
                "state": "error", "read": False, "candidates": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
            notes.append(f"DOCREF SOURCE FAILED: {type(exc).__name__}: {exc}")

    inventory_mode = _picker_source_mode(project_config, "inventory")
    if inventory_mode == "disabled":
        sources["inventory"] = {
            "state": "disabled", "read": False, "candidates": 0,
            "reason": "disabled by repo-local picker_sources.inventory",
        }
    elif inventory_mode == "invalid":
        sources["inventory"] = {
            "state": "invalid", "read": False, "candidates": 0,
            "error": "picker_sources.inventory must be enabled or disabled",
        }
    else:
        inv_path = Path(root) / INVENTORY_REL_PATH
        if (project_config is not None and inventory is None
                and not inv_path.exists()):
            sources["inventory"] = {
                "state": "absent", "path": str(inv_path), "read": False,
                "candidates": 0,
                "error": "enabled inventory source file does not exist",
            }
            notes.append(f"INVENTORY ABSENT: {inv_path}")
        else:
            inv = (
                load_inventory(repo_root=root)
                if inventory is None else inventory)
            inv_candidates, inv_notes = inventory_candidates(inv)
            notes.extend(inv_notes)
            freshness = inventory_freshness(inv, repo_root=root)
            if freshness["fresh"] or not enforce_inventory_freshness:
                candidates.extend(inv_candidates)
            else:
                # FAIL CLOSED. Letting a snapshot of a different tree drive
                # these bands means working from a repo that no longer exists.
                notes.append(
                    f"INVENTORY SUPPRESSED ({len(inv_candidates)} candidate(s) "
                    f"withheld): {freshness['reason']}. Regenerate "
                    f"{INVENTORY_REL_PATH}, or pass --stale-inventory to rank "
                    "it anyway.")
            sources["inventory"] = {
                "state": "valid" if (
                    freshness["fresh"] or not enforce_inventory_freshness
                ) else "invalid",
                "path": str(inv_path),
                "read": bool(inv),
                "candidates": len(inv_candidates) if (
                    freshness["fresh"] or not enforce_inventory_freshness) else 0,
                "suppressed": (
                    not freshness["fresh"]) and enforce_inventory_freshness,
                "freshness": freshness,
                "repo_state": (
                    inv.get("repo_state")
                    if isinstance(inv, Mapping) else None),
            }

    baseline_mode = _picker_source_mode(project_config, "eval_baseline")
    if baseline_mode == "disabled":
        sources["eval_baseline"] = {
            "state": "disabled", "candidates": 0, "cheap": True,
            "reason": "disabled by repo-local picker_sources.eval_baseline",
        }
    elif baseline_mode == "invalid":
        sources["eval_baseline"] = {
            "state": "invalid", "candidates": 0, "cheap": True,
            "error": (
                "picker_sources.eval_baseline must be enabled or disabled"),
        }
    else:
        base_error = None
        if baseline is None:
            baseline, base_error = _load_baseline()
            if base_error:
                notes.append(f"eval baseline unavailable: {base_error}")
        base_candidates, base_notes = eval_baseline_candidates(baseline)
        candidates.extend(base_candidates)
        notes.extend(base_notes)
        sources["eval_baseline"] = {
            "state": "invalid" if base_error else "valid",
            "candidates": len(base_candidates),
            "cheap": True,
            **({"error": base_error} if base_error else {}),
        }

    eval_gate_mode = _picker_source_mode(project_config, "eval_gate")
    if eval_gate_mode == "disabled":
        sources["eval_gate"] = {
            "state": "disabled", "ran": False,
            "reason": "disabled by repo-local picker_sources.eval_gate",
        }
    elif eval_gate_mode == "invalid":
        sources["eval_gate"] = {
            "state": "invalid", "ran": False,
            "error": "picker_sources.eval_gate must be enabled or disabled",
        }
    elif include_eval:
        gate, err = _run_eval_gate()
        if gate is None:
            notes.append(f"eval gate did not run: {err}")
            sources["eval_gate"] = {
                "state": "invalid", "ran": False, "error": err}
        else:
            gate_candidates, gate_notes = eval_gate_candidates(gate)
            candidates.extend(gate_candidates)
            notes.extend(gate_notes)
            sources["eval_gate"] = {
                "state": "valid", "ran": True,
                "passed": gate.get("passed"),
                "n_checked": gate.get("n_checked"),
                "candidates": len(gate_candidates)}
    else:
        sources["eval_gate"] = {
            "state": "disabled", "ran": False,
            "reason": "opt-in (--eval); a full Tier-1 replay"}

    hotspot_mode = _picker_source_mode(project_config, "hotspots")
    if hotspot_mode == "disabled":
        sources["hotspots"] = {
            "state": "disabled", "ran": False,
            "reason": "disabled by repo-local picker_sources.hotspots",
        }
    elif hotspot_mode == "invalid":
        sources["hotspots"] = {
            "state": "invalid", "ran": False,
            "error": "picker_sources.hotspots must be enabled or disabled",
        }
    elif include_hotspots:
        idx, err = _load_index(root)
        if idx is None:
            notes.append(f"structural index did not build: {err}")
            sources["hotspots"] = {
                "state": "invalid", "ran": False, "error": err}
        else:
            hot_candidates, hot_notes = hotspot_candidates(idx)
            candidates.extend(hot_candidates)
            notes.extend(hot_notes)
            sources["hotspots"] = {
                "state": "valid", "ran": True,
                "candidates": len(hot_candidates)}
    else:
        sources["hotspots"] = {
            "state": "disabled", "ran": False,
            "reason": "opt-in (--hotspots); builds the "
                      "whole-repo structural index"}

    db_path, db_path_error = resolve_spine_db_path(
        root, explicit=spine_db, project_config=project_config)
    enriched_memory_source = (
        project_config is not None
        or any(candidate.source == "work_queue" for candidate in candidates))
    if use_attempt_memory:
        if db_path_error:
            notes.append(f"attempt memory path invalid: {db_path_error}")
            sources["attempt_memory"] = {
                "state": "invalid", "read": False, "error": db_path_error,
            }
        else:
            history, hist_error = attempt_history(
                db_path, task_ids=[c.task_id for c in candidates])
            if hist_error:
                notes.append(f"attempt memory unavailable: {hist_error}")
                sources["attempt_memory"] = {
                    "state": "invalid", "path": str(db_path),
                    "read": False, "error": hist_error,
                }
            else:
                candidates_t, mem_notes = apply_attempt_memory(
                    candidates, history)
                candidates = list(candidates_t)
                notes.extend(mem_notes)
                sources["attempt_memory"] = (
                    {
                        "state": "valid", "path": str(db_path), "read": True,
                        "tasks_remembered": len(history),
                    } if enriched_memory_source else {
                        "read": True,
                        "tasks_remembered": len(history),
                    })
    else:
        sources["attempt_memory"] = {
            "state": "disabled", "read": False,
            "path": str(db_path) if db_path is not None else None,
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
        gate = (
            "argv: " + json.dumps(list(c.gate_argv))
            if c.gate_argv else
            (", ".join(c.gate_paths) or "(whole suite)"))
        out.append(f"     gate: {gate}")
        if c.target_paths:
            out.append(f"     target: {', '.join(c.target_paths)}")
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
    reaped = getattr(result, "reaped", ()) or ()
    branch_is_gone = any(
        isinstance(report, Mapping)
        and report.get("branch") == branch
        and report.get("action") in {"deleted", "absent"}
        for report in reaped
    )
    if branch and not branch_is_gone and not empty_patch and artifact is not None:
        out.append(f"  inspect : git diff {getattr(result, 'base_revision', 'HEAD')}"
                   f"..{branch}")
    out.append("  discard : do nothing. no ref is merged and no file is "
               "changed until you act.")
    out.append("  the gate verdict above is EVIDENCE, not permission. "
               "Promotion is a human decision.")
    return "\n".join(out)


def _console_safe(text: str, encoding: str | None) -> str:
    """Render arbitrary gate output through the active console encoding.

    Windows PowerShell may expose a CP-1252 stdout even when a verifier emits
    Unicode progress glyphs such as Vite's check mark.  The attempt and ledger
    are already complete when the review packet is printed, so an encoding
    exception here would turn a clean result into CLI exit 1.  Preserve the
    exact text when representable and escape only unsupported code points.
    """
    codec = encoding or "utf-8"
    try:
        return str(text).encode(
            codec, errors="backslashreplace").decode(codec)
    except LookupError:
        return str(text).encode(
            "ascii", errors="backslashreplace").decode("ascii")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _default_attempt(candidate: Candidate, args: Any) -> Any:
    """Run one real :class:`daedalus.spine.attempt.TaskAttempt`.

    Split out as the single injection seam so ``--dry-run`` can be tested by
    passing an ``attempt_fn`` that raises: proving the flag does not attempt
    anything requires a way to observe an attempt that never happens.

    It is also where one MissionContract per picked candidate is minted: the
    picker is the only live code that decides what to work on next, so it is
    the only place a mission can honestly be compiled from user-facing intent.
    """
    from daedalus.spine.attempt import offload_runner, run_attempt

    spec = candidate.to_task_spec()
    ledger_path, ledger_error = resolve_spine_db_path(args.repo_root)
    if ledger_error or ledger_path is None:
        raise RuntimeError(
            f"repo-bound spine ledger is unavailable: {ledger_error}")

    # ONE MISSION PER PICKED CANDIDATE. Failure to compile a mission must not
    # stop the attempt -- the ranked work is still real work -- so the mission
    # is optional and its absence falls back to TaskAttempt's task-derived
    # default, which is a deterministic id, not a fresh uuid per attempt.
    # THE REVISION IS READ OFF DISK, NOT SPAWNED. The hunk that landed this
    # mission call in 464f666e ran `git rev-parse HEAD` as a child process --
    # naming, to do it, the one stdlib module this file may not name -- and said
    # in its own note that it did so "to avoid importing the loop from the
    # picker". That was the wrong trade twice over: it broke
    # `test_there_is_no_apply_path_in_this_module`, the structural guard that
    # makes "the picker cannot apply a patch" a property of the file rather than
    # a promise in a docstring -- and it was not needed, because this module
    # already answers the question without a child process. `_head_sha` exists
    # for precisely this, twenty lines of its docstring explain why, and it
    # handles the linked-worktree and detached-HEAD shapes that `git -C` would
    # have handled. Importing the loop's `_head_revision` would have been the
    # same defeat one frame down: the picker would still spawn, and the guard
    # would merely stop being able to see it. -- HERACLES 2026-08-24, on the
    # owner's ruling that the picker must not spawn.
    #
    # `_head_sha` returns None when it cannot tell. A missing revision then
    # means NO MISSION, not a spawn -- the same disposition this code already
    # gives a failed compile, and honest, because the mission is optional here
    # by design.
    from datetime import datetime as _datetime, timezone as _timezone

    from daedalus.schemas import ResourceBudget
    from daedalus.spine.receipts import mission_contract_for_candidate

    mission_id = None
    head = _head_sha(args.repo_root)
    if head:
        try:
            mission = mission_contract_for_candidate(
                candidate,
                source_revision=head,
                created_at=_datetime.now(_timezone.utc).isoformat(),
                budget=ResourceBudget(max_wall_time_s=int(candidate.gate_timeout_s)),
            )
            mission_id = mission.mission_id
        except Exception:                   # noqa: BLE001 - reported by absence
            mission_id = None
    return run_attempt(
        spec,
        runner=offload_runner(live=bool(args.live)),
        repo_root=args.repo_root,
        ledger_path=ledger_path,
        artifact_dir=args.artifact_dir,
        mission_id=mission_id,
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
    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape, so
    # both doors pass it: `daedalus improve` through cli.main's dispatch and
    # `python -m daedalus.spine.picker` around it. Above the dry-run default
    # too: the default being safe is a property of the current flag table, and
    # the boundary has to be a property of the function.
    #
    # With --once --live this reaches _default_attempt -> run_attempt, which
    # creates a git worktree, deposits artifacts, spawns the gate child and
    # calls a provider. python.attempt and python.offload keep their own
    # boundaries under their own leases; this is the console start above them,
    # and it declares the union those inner rows deliberately refuse because
    # it installs the process-wide spend net for the whole run and therefore
    # does meter what it names.
    from ..budget import process_guard_boundary_decision
    from .effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.picker",
        REGISTRY_BY_ID["cli.picker"].effects,
        (process_guard_boundary_decision(),),
    )

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
    print(_console_safe(
        review_packet(top, result),
        getattr(_sys.stdout, "encoding", None)))
    return EXIT_BY_STATE.get(getattr(result, "state", "unknown"), EXIT_FAILED)


if __name__ == "__main__":
    raise SystemExit(main())
