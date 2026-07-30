"""Bounded, resumable, corroborated fan-out over the cheap external lane.

The volume half of the two-judge plan. Its one job is to run N advisory tasks
through the DeepSeek lane at bounded concurrency and land each answer on disk as
its own file, so that 1,200 tasks are a *queue* rather than an *event* -- a crash
at task 900 costs one task, not nine hundred.

Every design choice here is a measured failure from 29/30 July:

**BUDGET GUARD, INSTALLED ONCE, AT THE TOP.** The fan-out scripts that night
constructed the provider directly and never called
:func:`daedalus.budget.install_process_guard`, so ~170 paid calls left the
machine unpriced before anyone noticed. The guard is not optional here and not a
parameter -- a fan-out is exactly the shape that turns a missing guard into a
bill.

**CORROBORATION IS THE POINT, NOT A FEATURE.** That night produced 1,226 claims
whose largest agreement cluster was TWO, because the fan-out handed every agent a
different file. N agents on N different things cannot corroborate anything; N
agents on the SAME thing can. So ``votes`` is a first-class argument and every
result records how many independent answers it is made of.

**A FRESH PROVIDER PER CALL.** ``DeepSeekProvider.run`` resets ``self._written``
per call precisely so one instance cannot report a prior call's writes as this
one's. Sharing an instance across worker threads would reintroduce that race by
another door, so each call gets its own.

**THE GRAPH GOES IN THE PROMPT.** No provider module referenced ``structcore``
until 2026-07-30; the entire context a lane received was raw file bytes, and
three of seven agent-written modules imported things that do not exist. Tasks
that name paths get :func:`daedalus.lanes.graph_brief.render_brief` prepended.

**RESULTS ARE PUBLISHED, NOT WRITTEN.** Via :mod:`daedalus.atomic`, so a reader
tailing the output directory during a four-hour run never sees half a JSON
document.

Advisory only. There is no ``writable`` parameter and adding one would be a
mistake: a write lane needs :func:`daedalus.lanes.checks.run_checks` around every
file and a rollback story per task, and a fan-out has neither. Volume and writes
do not belong in the same primitive.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ..atomic import write_text_atomic
from .graph_brief import render_brief

__all__ = ["FanoutTask", "FanoutResult", "fan_out", "default_concurrency"]

#: Concurrency ceiling. The lane is network-bound, so this is far above the core
#: count -- but not unbounded: each worker holds a provider, a request and a
#: response body, and the box also has to keep running whatever else is on it.
#: MEASURED 2026-07-30: a hundred concurrent agents pushed a 105 s test suite
#: past a 900 s timeout, and the gate read that timeout as failing tests. If a
#: measurement is running, pass a low number and mean it.
DEFAULT_CONCURRENCY = 8

#: Per-call ceiling. Advisory calls that need longer than this are usually stuck.
DEFAULT_TIMEOUT_S = 300


def default_concurrency() -> int:
    """Concurrency from the environment, or :data:`DEFAULT_CONCURRENCY`."""
    raw = os.environ.get("DAEDALUS_FANOUT_CONCURRENCY", "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_CONCURRENCY
    except ValueError:
        return DEFAULT_CONCURRENCY


@dataclass(frozen=True)
class FanoutTask:
    """One question, asked ``votes`` times independently.

    ``key`` is the filename the answer lands under and the resume identity, so it
    must be stable across runs and safe as a path segment. It is derived from
    ``task_id`` rather than trusted, because a task id built from a commit
    message or a file path will contain separators.
    """

    task_id: str
    objective: str
    #: Repo-relative paths this task is about. Drives the graph brief. An empty
    #: list is the advisory default and stays advisory.
    paths: tuple[str, ...] = ()
    #: Independent answers to collect. >1 is what makes agreement meaningful.
    votes: int = 1
    #: Free-form, carried through to the result untouched. Use it for the label,
    #: the commit sha, the lens -- whatever the caller needs to join on later.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """A filename-safe, collision-free, stable identity.

        The digest is appended rather than the sanitised name being trusted:
        ``a/b`` and ``a\\b`` both sanitise to ``a_b``, and two tasks sharing a
        result file would have one silently overwrite the other's answer.

        Dot runs are collapsed after sanitising. Replacing separators already
        makes traversal impossible, but ``../../etc/passwd`` still produced
        ``.._.._etc_passwd`` -- a key that cannot escape and reads as though it
        were trying to. A name that looks like an attack invites someone to
        "harden" it later by a route that breaks resume.
        """
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_"
                       for c in self.task_id)
        while ".." in safe:
            safe = safe.replace("..", "_")
        safe = safe.lstrip("._")[:80] or "task"
        digest = hashlib.sha256(self.task_id.encode("utf-8")).hexdigest()[:10]
        return f"{safe}-{digest}"


@dataclass
class FanoutResult:
    task_id: str
    key: str
    votes_requested: int
    answers: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    #: True when this result was loaded from disk rather than paid for again.
    resumed: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.answers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "key": self.key,
            "votes_requested": self.votes_requested,
            "votes_collected": len(self.answers),
            "answers": self.answers,
            "errors": self.errors,
            "meta": self.meta,
        }


def _one_call(task: FanoutTask, vote: int, repo_root: str, model: str | None,
              timeout_s: int, brief: str) -> dict[str, Any]:
    """One advisory call. Returns the answer dict; raises on transport failure."""
    # Imported here, not at module scope: this module is imported by tooling that
    # must not pull the provider stack (and its network config) just to read the
    # dataclasses.
    from ..providers.deepseek import DeepSeekProvider

    objective = task.objective
    if brief:
        # BEFORE the question, not after. A model that has already read the
        # question treats the brief as supporting material; a model that reads
        # the brief first treats the question as being about the thing described.
        objective = (
            f"{brief}\n\n"
            "The brief above is DERIVED STRUCTURE: it says what exists and what "
            "reaches what. It is not evidence about behaviour, and a name absent "
            "from it does not exist. Now the task:\n\n"
            f"{objective}")

    provider = DeepSeekProvider()          # fresh per call -- see module docstring
    out = provider.run(
        objective=objective,
        repo_root=repo_root,
        paths=list(task.paths),
        agent={"name": f"fanout-{task.key}-v{vote}"},
        model=model,
        timeout_s=timeout_s,
        writable=False,                    # advisory only, structurally
    )
    return {
        "vote": vote,
        "provider": out.get("provider"),
        "persona": out.get("persona"),
        "report": out.get("report"),
        "notes": out.get("notes") or [],
    }


def fan_out(
    tasks: Sequence[FanoutTask],
    out_dir: str | Path,
    *,
    repo_root: str | Path = ".",
    concurrency: int | None = None,
    model: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    graph_hops: int = 1,
    brief_budget_chars: int = 6000,
    resume: bool = True,
    on_result: Callable[[FanoutResult], None] | None = None,
    progress_every: int = 25,
) -> dict[str, Any]:
    """Run every task, land every answer, return the run summary.

    Never raises for a failing task: a fan-out of 1,200 in which one task dies
    must produce 1,199 answers and a named failure, not an exception. Transport
    failures are recorded on the result and the queue continues -- which is also
    why the summary reports ``failed`` separately from ``ok`` rather than folding
    them into a rate.

    ``resume`` skips any task whose result file already exists AND parses. A file
    that exists but does not parse is re-run, because a truncated result is worse
    than a missing one: it looks like an answer.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    root = str(Path(repo_root).resolve())
    workers = concurrency or default_concurrency()

    # THE GUARD, FIRST, BEFORE ANY CALL CAN LEAVE. Not conditional, not a
    # parameter. See the module docstring for the 170 unpriced calls.
    uninstall = None
    guard_error = ""
    try:
        from ..budget import install_process_guard
        uninstall = install_process_guard()
    except Exception as exc:                     # noqa: BLE001
        # Fail CLOSED: a fan-out whose spend cannot be capped does not run. The
        # alternative -- proceeding unpriced and mentioning it in a summary
        # nobody reads until the invoice arrives -- is how this went wrong once.
        guard_error = f"{type(exc).__name__}: {exc}"
        # SAME SUMMARY SHAPE as a completed run, including `paid_calls` and
        # `results`. A refusal that returns a different dict forces every
        # consumer to write two code paths, and the one it will forget is the
        # refusal -- so a caller reading `paid_calls` would crash exactly when
        # the answer it needed was "zero, nothing was spent".
        return {
            "state": "refused",
            "reason": ("the budget process guard could not be installed, so "
                       "spend could not be capped; refusing to fan out. "
                       f"({guard_error})"),
            "tasks": len(tasks),
            "ok": 0,
            "failed": 0,
            "resumed": 0,
            "paid_calls": 0,
            "out_dir": str(out),
            "concurrency": workers,
            "results": [],
        }

    lock = threading.Lock()
    results: list[FanoutResult] = []
    counts = {"ok": 0, "failed": 0, "resumed": 0, "calls": 0}

    def _brief_for(task: FanoutTask) -> str:
        if not task.paths:
            return ""
        return render_brief(root, list(task.paths), hops=graph_hops,
                            budget_chars=brief_budget_chars)

    def _run_task(task: FanoutTask) -> FanoutResult:
        dest = out / f"{task.key}.json"
        if resume and dest.is_file():
            try:
                prior = json.loads(dest.read_text(encoding="utf-8"))
                res = FanoutResult(
                    task_id=prior.get("task_id", task.task_id),
                    key=task.key,
                    votes_requested=prior.get("votes_requested", task.votes),
                    answers=prior.get("answers") or [],
                    errors=prior.get("errors") or [],
                    meta=prior.get("meta") or dict(task.meta),
                    resumed=True)
                if res.answers:
                    return res
            except (OSError, ValueError):
                pass    # unparseable => re-run; a torn result reads as an answer

        res = FanoutResult(task_id=task.task_id, key=task.key,
                           votes_requested=task.votes, meta=dict(task.meta))
        brief = _brief_for(task)
        for vote in range(1, max(1, task.votes) + 1):
            try:
                res.answers.append(
                    _one_call(task, vote, root, model, timeout_s, brief))
            except Exception as exc:             # noqa: BLE001 -- one task, not the run
                res.errors.append(
                    f"vote {vote}: {type(exc).__name__}: {exc}\n"
                    + "".join(traceback.format_exception_only(type(exc), exc)))
            with lock:
                counts["calls"] += 1
        write_text_atomic(dest, json.dumps(res.to_dict(), indent=1))
        return res

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_task, t): t for t in tasks}
            done = 0
            for fut in as_completed(futures):
                task = futures[fut]
                try:
                    res = fut.result()
                except Exception as exc:         # noqa: BLE001
                    res = FanoutResult(task_id=task.task_id, key=task.key,
                                       votes_requested=task.votes,
                                       meta=dict(task.meta),
                                       errors=[f"{type(exc).__name__}: {exc}"])
                with lock:
                    results.append(res)
                    if res.resumed:
                        counts["resumed"] += 1
                    if res.ok:
                        counts["ok"] += 1
                    else:
                        counts["failed"] += 1
                    done += 1
                    n = done
                if on_result is not None:
                    try:
                        on_result(res)
                    except Exception:            # noqa: BLE001 -- a callback
                        pass                     # must not kill the queue
                if progress_every and n % progress_every == 0:
                    print(f"[fanout] {n}/{len(tasks)} "
                          f"ok={counts['ok']} failed={counts['failed']} "
                          f"resumed={counts['resumed']} paid_calls={counts['calls']}",
                          flush=True)
    finally:
        if uninstall is not None:
            try:
                uninstall()
            except Exception:                    # noqa: BLE001
                pass

    return {
        "state": "ran",
        "tasks": len(tasks),
        "ok": counts["ok"],
        "failed": counts["failed"],
        "resumed": counts["resumed"],
        # PAID CALLS, separate from task count: with votes>1 they differ, and the
        # number anyone asking "what did this cost" wants is this one. Note it is
        # a COUNT -- the budget ledger prices reservations at a deliberate
        # worst-case, so a ledger total is a ceiling and never an invoice.
        "paid_calls": counts["calls"],
        "out_dir": str(out),
        "concurrency": workers,
        "results": [r.to_dict() for r in results],
    }
