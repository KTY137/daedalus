"""THE SHADOW RUN -- Daedalus attempts work on Daedalus, and promotes nothing.

WHY THIS MODULE EXISTS, and why it is called a shadow run rather than a
bootstrap. The loop is closed: the picker chooses, an attempt runs, the ledger
records, the picker re-ranks. What is NOT true is that the resulting candidate
can be trusted, and the reason is measured rather than felt: the gate's
rejection rate against the three known-bad changes of a single day was 0/3.
The legacy gate is ``pytest`` over ``gate_paths``; a curated queue may instead
declare an exact argv command. This repo's suite has already been green over a
live repository deletion, a false success, seven gate bypasses and a silently
dropped task.

So the ruling this module implements, taken from the adversarial review:

    With 0/3, the gate is a hard block on PROMOTION, not on candidate
    GENERATION. Let the run collect, but call it a shadow run; no candidate
    gets less human review because it came back green.

Everything here follows from that. A shadow run produces candidates and says
exactly how much they are worth, which today is: "the configured gate command
ran". It refuses to render a green gate as evidence of quality, and it refuses
to promote.

THREE THINGS IT DOES THAT THE BARE PICKER CANNOT.

1. IT REFRESHES THE SOURCES FIRST. This was found by running the circle for
   real in a clean clone, which is the environment a bootstrap actually lives
   in. Both sources were withheld:

       map:       "records no repo_state.head"        (10 candidates withheld)
       inventory: "written against f40529c but HEAD is 41b94a9"  (12 withheld)

   Both gates were correct. The structural problem they expose is worse than
   either: the loop INVALIDATES ITS OWN INPUTS EVERY TIME IT SUCCEEDS. Both
   sources are derived artefacts stamped with the revision they describe, and
   every commit the loop lands makes them stale. A loop that must be manually
   re-seeded after each success is not a loop. So regeneration is step zero of
   the circle, not a chore beside it.

2. IT KNOWS WHETHER THE GATE CAN DISCRIMINATE, and refuses to guess. The
   requirement, again from review: a frozen gate must be shown to separate good
   patches from representative bad ones -- including a defect corpus held back
   until evaluation -- and critical defect classes must be killed COMPLETELY,
   because a global score averages a fatal blind spot into an acceptable
   number. Until such a measurement exists for the current revision, the answer
   is `unproven`, and unproven blocks promotion.

3. IT NEVER WRITES THE PRIMARY CHECKOUT. Inherited from
   :mod:`daedalus.spine.attempt`, which has no apply path at all, and asserted
   here again because this module is the one that would be tempted.

WHAT THIS MODULE IS NOT. It is not an autonomous loop driver. It runs ONE
iteration when asked. Scheduling, unattended operation and repetition are
deliberately somebody else's decision, because the preconditions for those --
a spend cap, a kill switch, wired containment -- are separately tracked and
several are still open.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]

#: Where a discrimination measurement is recorded. Absent means unproven; it
#: does NOT mean "fine so far".
DISCRIMINATION_REL_PATH = "runs/spine/gate_discrimination.json"

#: Defect classes a gate must kill COMPLETELY before its green means anything.
#: A survivor in any of these makes the gate unproven regardless of how good
#: the overall kill rate looks -- that averaging is the specific failure this
#: list exists to prevent.
CRITICAL_DEFECT_CLASSES = (
    "deletes-outside-the-worktree",
    "spends-money-without-a-gate",
    "sends-bytes-off-the-machine",
    "reports-failure-as-success",
)

#: The floor for the overall kill rate. Deliberately not 1.0: a gate that kills
#: every mutant a corpus author could think of has usually been fitted to the
#: corpus. It is the CRITICAL classes that must be absolute.
KILL_RATE_FLOOR = 0.80

EXIT_OK = 0
EXIT_NO_CANDIDATE = 2
EXIT_SOURCES_UNAVAILABLE = 3
EXIT_ERROR = 1


# --------------------------------------------------------------------------- #
# step zero: the sources                                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SourceRefresh:
    """What regeneration was attempted, and what it actually achieved.

    ``attempted`` and ``succeeded`` are separate on purpose. A regeneration
    command that exits 0 without making the source fresh is the failure mode
    that would otherwise be reported as success, and this repo has been bitten
    by precisely that shape more than once.
    """

    name: str
    attempted: bool
    succeeded: bool
    detail: str
    before_head: str | None = None
    after_head: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "attempted": self.attempted,
                "succeeded": self.succeeded, "detail": self.detail,
                "before_head": self.before_head, "after_head": self.after_head}


def _recorded_head(path: Path) -> str | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    state = doc.get("repo_state") if isinstance(doc, Mapping) else None
    if isinstance(state, Mapping):
        head = state.get("head")
        return str(head) if head else None
    return None


def refresh_sources(repo_root: str | Path,
                    runner: Callable[[Sequence[str], Path], Any] | None = None,
                    timeout_s: float = 900.0) -> tuple[SourceRefresh, ...]:
    """Regenerate the loop's derived sources so the circle can start.

    ``runner`` exists so tests can drive this without invoking the real
    generator; the product path uses a subprocess, because the generator is a
    CLI verb and re-implementing it here would create a second, drifting copy
    of the thing whose staleness caused the problem.
    """
    root = Path(repo_root)
    out: list[SourceRefresh] = []

    # Refresh writes the generated map into the PRIMARY checkout. A repository
    # that explicitly disabled that source chose the curated queue as its
    # authority; regenerating map anyway would violate both that declaration
    # and shadow mode's no-surprise boundary before an attempt even starts.
    from daedalus.config import resolve_project
    from daedalus.spine.picker import _picker_source_mode

    config = resolve_project(str(root))
    map_mode = _picker_source_mode(config, "map")
    if map_mode == "disabled":
        return (SourceRefresh(
            name="map", attempted=False, succeeded=True,
            detail="disabled by repo-local picker_sources.map; not refreshed"),)
    if map_mode == "invalid":
        return (SourceRefresh(
            name="map", attempted=False, succeeded=False,
            detail="invalid picker_sources.map; refresh refused"),)

    def _run(argv: Sequence[str]) -> tuple[int, str]:
        if runner is not None:
            res = runner(argv, root)
            if isinstance(res, tuple):
                return res
            return (0, str(res))
        proc = subprocess.run([str(a) for a in argv], cwd=str(root),
                              capture_output=True, text=True, timeout=timeout_s)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or ""))[-600:]

    snapshot = root / "docs" / "architecture-state.json"
    before = _recorded_head(snapshot)
    try:
        code, detail = _run([sys.executable, "-m", "daedalus.cli", "map"])
    except Exception as e:                       # noqa: BLE001 - reported, not raised
        code, detail = 1, f"{type(e).__name__}: {e}"
    after = _recorded_head(snapshot)
    # Exit 0 is NOT the success criterion. The criterion is that the artefact
    # now stamps a revision, because that is what the consumer checks.
    out.append(SourceRefresh(
        name="map", attempted=True,
        succeeded=(code == 0 and after is not None),
        detail=(detail if code != 0 else
                ("regenerated, but the snapshot still records no repo_state.head "
                 "-- its consumer cannot check it against the tree, so it stays "
                 "suppressed" if after is None else "regenerated and stamped")),
        before_head=before, after_head=after))
    return tuple(out)


# --------------------------------------------------------------------------- #
# whether a green gate means anything                                          #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateDiscrimination:
    """Has this gate been SHOWN to separate good patches from bad ones?

    Not "does it pass", not "is the suite green" -- whether it can tell the
    difference. Absent evidence is reported as ``unproven``, never as fine.
    """

    proven: bool
    reason: str
    measured_at: str | None = None
    measured_head: str | None = None
    kill_rate: float | None = None
    surviving_critical: tuple[str, ...] = ()
    gate_scope: str | None = None
    gate_paths: tuple[str, ...] = ()
    gate_argv: tuple[str, ...] = ()
    gate_bound: bool | None = None

    def to_dict(self) -> dict:
        return {"proven": self.proven, "reason": self.reason,
                "measured_at": self.measured_at,
                "measured_head": self.measured_head,
                "kill_rate": self.kill_rate,
                "surviving_critical": list(self.surviving_critical),
                "gate_scope": self.gate_scope,
                "gate_paths": list(self.gate_paths),
                "gate_argv": list(self.gate_argv),
                "gate_bound": self.gate_bound}


def _gate_binding(raw: Any, *, receipt: bool
                  ) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and canonicalise a discrimination gate description.

    A discrimination score belongs to the exact command that produced it.  A
    receipt which merely says "pytest" -- or whose ``gate_scope`` disagrees
    with its paths -- is not evidence about any gate.  Receipt bindings are
    narrower than requested bindings: this corpus tool measures only the real
    pytest gate, while a candidate may request a custom command such as the
    docref verifier.  The latter is valid as a request but cannot match a
    pytest receipt.
    """
    label = "receipt frozen_gate" if receipt else "requested gate"
    if not isinstance(raw, Mapping):
        return None, f"the {label} is missing or is not an object"

    argv_raw = raw.get("argv")
    paths_raw = raw.get("gate_paths")
    scope = str(raw.get("gate_scope") or "").strip()
    if not isinstance(argv_raw, (list, tuple)) or not argv_raw:
        return None, f"the {label} records no executable argv"
    if not isinstance(paths_raw, (list, tuple)):
        return None, f"the {label} gate_paths is not an array"
    argv = tuple(str(value) for value in argv_raw)
    paths = tuple(str(value).replace("\\", "/") for value in paths_raw)
    if any(not value or "\x00" in value for value in (*argv, *paths)):
        return None, f"the {label} contains an empty or NUL-bearing value"
    if len(set(paths)) != len(paths):
        return None, f"the {label} contains duplicate gate_paths"

    expected_scope = "whole-suite" if not paths else "scoped"
    allowed_scopes = {expected_scope}
    if not receipt:
        allowed_scopes.add("custom-command")
    if scope not in allowed_scopes:
        return None, (
            f"the {label} scope {scope!r} disagrees with gate_paths "
            f"(expected {expected_scope!r})")

    if receipt:
        # Import the production builder instead of copying its argv.  This
        # catches a forged receipt that names arbitrary tests or a custom
        # verifier while retaining a plausible-looking scope/path label.
        from daedalus.spine.attempt import pytest_gate_argv

        expected_argv = tuple(str(value) for value in pytest_gate_argv(paths))
        if argv != expected_argv:
            return None, (
                "the receipt frozen_gate argv is not the production pytest "
                "argv for its recorded gate_paths")

    return {
        "argv": argv,
        "gate_paths": paths,
        "gate_scope": scope,
    }, None


def gate_discrimination(repo_root: str | Path,
                        head: str | None = None, *,
                        expected_gate: Mapping[str, Any] | None = None,
                        require_gate_binding: bool = False,
                        ) -> GateDiscrimination:
    """Read the discrimination receipt and judge it. Fails closed.

    A receipt only counts when it is present, parseable, measured against THE
    CURRENT REVISION, internally consistent, clean on every critical class,
    and bound to the exact gate being authorised.  ``expected_gate`` has the
    receipt shape ``{"argv", "gate_paths", "gate_scope"}``.  Callers making a
    promotion decision set ``require_gate_binding=True``; callers displaying
    the historical measurement may omit it, but that unbound answer must not
    be read as authority for an arbitrary candidate gate.
    The revision clause is the same doctrine the map and inventory sources
    follow: a measurement of a tree that no longer exists is not a measurement
    of this one.

    TWO OF THESE SIX WERE PROSE UNTIL AN AUDIT FOUND THEM, and both let a
    forged promotion through:

    * **The revision clause failed OPEN when HEAD could not be read.** The test
      was ``if head and measured_head and not head.startswith(measured_head)``,
      so a falsy ``head`` skipped the staleness branch entirely. The caller in
      :func:`shadow_run` resolves HEAD inside a bare ``except`` that yields
      ``None`` — so a repository with no readable ``.git`` turned a receipt from
      ANY revision into ``proven=True``. ``picker._head_sha``'s own docstring
      said callers "fail OPEN on" None; this one's said "measured against THE
      CURRENT REVISION". Two documents, one code path, opposite claims.
      ``head`` is now resolved here when not supplied, and an unresolvable
      revision REFUSES.
    * **No sanity bound on the counts.** ``{"planted": 12, "killed": 99}``
      yielded a kill rate of 825%, which sails past an 80% floor. A rate is now
      rejected unless ``0 <= killed <= planted``.

    Still NOT defended, and deliberately named rather than quietly left: the
    receipt has no integrity protection. Anything that can write
    ``runs/spine/`` can author a receipt naming the current HEAD, and this
    function will believe it. That is a key-management decision, not a patch.
    """
    # Resolved HERE, not trusted from the caller, and refused when unknown.
    # Passing an explicit head stays supported because
    # tools/bootstrap_receipt.py deliberately asks about a DIFFERENT revision.
    if head is None:
        try:
            from daedalus.spine.picker import _head_sha

            head = _head_sha(repo_root)
        except Exception:                        # noqa: BLE001
            head = None
    if not head:
        return GateDiscrimination(
            False,
            "the current revision could not be read, so no receipt can be tied "
            "to it -- refusing rather than accepting a measurement of an "
            "unknown tree")

    path = Path(repo_root) / DISCRIMINATION_REL_PATH
    if not path.exists():
        return GateDiscrimination(
            False,
            "no discrimination measurement exists, so a green gate means only "
            "that the configured gate command ran")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:                       # noqa: BLE001
        return GateDiscrimination(
            False, f"the discrimination receipt is unreadable ({type(e).__name__})")
    if not isinstance(doc, Mapping):
        return GateDiscrimination(False, "the discrimination receipt is not an object")
    if doc.get("state") != "measured":
        return GateDiscrimination(
            False, "the discrimination receipt is not a completed measurement")

    measured_head = str(doc.get("head") or "").strip() or None
    measured_at = str(doc.get("measured_at") or "").strip() or None
    if head and measured_head and not head.startswith(measured_head):
        return GateDiscrimination(
            False,
            f"the gate was last shown to discriminate at {measured_head}, but "
            f"HEAD is {head[:len(measured_head)]}",
            measured_at, measured_head)
    if not measured_head:
        return GateDiscrimination(
            False, "the discrimination receipt records no head, so it cannot be "
                   "tied to a revision", measured_at, None)

    frozen, gate_error = _gate_binding(doc.get("frozen_gate"), receipt=True)
    if gate_error or frozen is None:
        return GateDiscrimination(
            False, gate_error or "the receipt gate binding is unusable",
            measured_at, measured_head)
    frozen_head = str((doc.get("frozen_gate") or {}).get("head") or "").strip()
    if frozen_head != measured_head:
        return GateDiscrimination(
            False,
            "the receipt frozen_gate head does not match the measurement head",
            measured_at, measured_head,
            gate_scope=frozen["gate_scope"],
            gate_paths=frozen["gate_paths"], gate_argv=frozen["argv"],
            gate_bound=False)

    requested = None
    if expected_gate is not None:
        requested, gate_error = _gate_binding(expected_gate, receipt=False)
        if gate_error or requested is None:
            return GateDiscrimination(
                False, gate_error or "the requested gate binding is unusable",
                measured_at, measured_head,
                gate_scope=frozen["gate_scope"],
                gate_paths=frozen["gate_paths"], gate_argv=frozen["argv"],
                gate_bound=False)
        if requested != frozen:
            return GateDiscrimination(
                False,
                "the discrimination receipt measured a different gate: "
                f"receipt scope={frozen['gate_scope']!r} "
                f"paths={list(frozen['gate_paths'])!r}, requested "
                f"scope={requested['gate_scope']!r} "
                f"paths={list(requested['gate_paths'])!r}",
                measured_at, measured_head,
                gate_scope=frozen["gate_scope"],
                gate_paths=frozen["gate_paths"], gate_argv=frozen["argv"],
                gate_bound=False)
    elif require_gate_binding:
        return GateDiscrimination(
            False,
            "the receipt proves one frozen pytest gate, but no candidate gate "
            "was supplied to bind this promotion decision",
            measured_at, measured_head,
            gate_scope=frozen["gate_scope"],
            gate_paths=frozen["gate_paths"], gate_argv=frozen["argv"],
            gate_bound=False)

    planted = doc.get("planted")
    killed = doc.get("killed")
    try:
        planted_f = float(planted)
        killed_f = float(killed)
    except (TypeError, ValueError):
        return GateDiscrimination(
            False, "the receipt does not record a usable planted/killed count",
            measured_at, measured_head)
    # SANITY BOUND, and it is load-bearing: without it {"planted": 12,
    # "killed": 99} produced a kill rate of 825% and cleared the 80% floor.
    # A rate above 1.0 is not a very good gate, it is a broken receipt.
    if not (planted_f > 0 and 0 <= killed_f <= planted_f):
        return GateDiscrimination(
            False,
            f"the receipt is internally inconsistent: killed={killed} of "
            f"planted={planted}",
            measured_at, measured_head)
    rate = killed_f / planted_f

    survivors = doc.get("surviving_classes") or []
    critical = tuple(c for c in survivors if c in CRITICAL_DEFECT_CLASSES)
    if critical:
        # Deliberately checked BEFORE the rate: a high overall score with a
        # fatal blind spot is the exact reading this refuses to accept.
        return GateDiscrimination(
            False,
            f"critical defect class(es) survived the gate: {', '.join(critical)}",
            measured_at, measured_head, rate, critical)
    if rate < KILL_RATE_FLOOR:
        return GateDiscrimination(
            False,
            f"kill rate {rate:.0%} is below the {KILL_RATE_FLOOR:.0%} floor",
            measured_at, measured_head, rate)
    return GateDiscrimination(
        True,
        f"kill rate {rate:.0%} at {measured_head}, no critical class survived",
        measured_at, measured_head, rate,
        gate_scope=frozen["gate_scope"],
        gate_paths=frozen["gate_paths"], gate_argv=frozen["argv"],
        gate_bound=(True if requested is not None else None))


# --------------------------------------------------------------------------- #
# the run                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ShadowResult:
    """One shadow iteration. Never promotes, and says so in words."""

    state: str
    refreshed: tuple[SourceRefresh, ...] = ()
    discrimination: GateDiscrimination | None = None
    task_id: str | None = None
    source: str | None = None
    attempt: Any = None
    degraded_sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    duration_s: float = 0.0

    @property
    def promotion_allowed(self) -> bool:
        """Always False while the gate is unproven. There is no override.

        A parameter here would be the whole design defeated by one keyword
        argument, which is how the containment module lost its inheritance
        flag as well.
        """
        return bool(self.discrimination and self.discrimination.proven)

    @property
    def routed_lane(self) -> str | None:
        """Which provider the router actually chose, read off the runner's own
        result rather than off the request.

        Surfaced because `--local-only` DECLARES availability and does not force
        the choice: measured, the router still selected `claude_cli` with that
        lane declared unavailable, and the run stopped only because offload
        refuses to execute a non-free lane. Nothing was billed, but a run that
        ends in `no_change` for that reason looks identical to one where the
        model simply had no idea -- and those are completely different problems.
        """
        detail = getattr(self.attempt, "runner_detail", None)
        if isinstance(detail, Mapping):
            value = detail.get("provider")
            return str(value) if value else None
        return None

    def verdict(self) -> str:
        """One line a human can act on, with the caveat welded to the result."""
        if self.state == "no_change":
            lane = self.routed_lane
            action = None
            detail = getattr(self.attempt, "runner_detail", None)
            if isinstance(detail, Mapping):
                action = detail.get("action")
            if action in ("escalate_to_claude", "senior"):
                return (f"no_change: the runner proposed nothing because the "
                        f"router sent this work to {lane!r}, which offload "
                        f"refuses to execute, so it escalated instead. Nothing "
                        f"was billed. This is NOT evidence that the task is hard "
                        f"or that a model tried and failed -- no model was asked.")
            return (f"no_change: a model was asked (lane {lane!r}) and proposed "
                    f"nothing to gate")
        if self.state != "gated":
            return f"{self.state}: no candidate is waiting"
        if not self.promotion_allowed:
            why = self.discrimination.reason if self.discrimination else "unmeasured"
            return ("SHADOW: a candidate patch exists and the gate ran. That is "
                    f"NOT evidence it is correct -- {why}. Review it as if it "
                    "were unreviewed, because it is.")
        return ("a candidate patch is waiting and the gate has demonstrated "
                "discrimination at this revision; promotion is still a human act")

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "promotion_allowed": self.promotion_allowed,
            "verdict": self.verdict(),
            "task_id": self.task_id,
            "source": self.source,
            "routed_lane": self.routed_lane,
            "refreshed": [r.to_dict() for r in self.refreshed],
            "discrimination": (self.discrimination.to_dict()
                               if self.discrimination else None),
            "degraded_sources": list(self.degraded_sources),
            "notes": list(self.notes),
            "duration_s": round(self.duration_s, 3),
            "attempt": (self.attempt.to_dict()
                        if hasattr(self.attempt, "to_dict") else None),
        }


def shadow_run(repo_root: str | Path, *,
               runner: Callable[[Any], Any],
               refresh: bool = True,
               limit: int = 10,
               artifact_dir: str | Path | None = None,
               keep_worktree: bool = False,
               refresh_runner: Callable[[Sequence[str], Path], Any] | None = None,
               ) -> ShadowResult:
    """Run ONE iteration of the circle and promote nothing.

    ``runner`` is required and has no default, mirroring
    :class:`daedalus.spine.attempt.TaskAttempt`: no run may quietly reach a
    model because a caller forgot an argument.
    """
    if runner is None or not callable(runner):
        raise ValueError("shadow_run requires an explicit runner callable")

    started = time.monotonic()
    root = Path(repo_root).resolve()
    refreshed: tuple[SourceRefresh, ...] = ()
    if refresh:
        refreshed = refresh_sources(root, runner=refresh_runner)

    from daedalus.spine.picker import build_queue

    queue = build_queue(limit=limit, repo_root=str(root))
    degraded = tuple(getattr(queue, "degraded_sources", ()) or ())
    notes = tuple(getattr(queue, "notes", ()) or ())

    head = None
    try:
        from daedalus.spine.picker import _head_sha

        head = _head_sha(root)
    except Exception:                            # noqa: BLE001
        head = None
    # A receipt proves ONE frozen gate, never "whatever gate the next
    # candidate happens to use".  Until a candidate exists there is nothing
    # to bind, so the promotion answer is deliberately unproven.
    disc = gate_discrimination(
        root, head=head, require_gate_binding=True)

    def _finish(state: str, **kw: Any) -> ShadowResult:
        return ShadowResult(state=state, refreshed=refreshed, discrimination=disc,
                            degraded_sources=degraded, notes=notes,
                            duration_s=time.monotonic() - started, **kw)

    if not queue.candidates:
        # "no candidates" and "the sources could not be consulted" are
        # different facts and must not collapse into one.
        return _finish("sources_unavailable" if degraded else "no_candidate")

    top = queue.candidates[0]
    from daedalus.spine.attempt import run_attempt
    from daedalus.spine.attempt import pytest_gate_argv
    from daedalus.spine.picker import resolve_spine_db_path

    task = top.to_task_spec()
    if task.gate_argv:
        requested_gate = {
            "argv": list(task.gate_argv),
            "gate_paths": list(task.gate_paths),
            "gate_scope": "custom-command",
        }
    else:
        requested_gate = {
            "argv": list(pytest_gate_argv(task.gate_paths)),
            "gate_paths": list(task.gate_paths),
            "gate_scope": ("whole-suite" if not task.gate_paths else "scoped"),
        }
    disc = gate_discrimination(
        root, head=head, expected_gate=requested_gate,
        require_gate_binding=True)
    ledger_path, ledger_error = resolve_spine_db_path(root)
    if ledger_error or ledger_path is None:
        notes = notes + (
            f"repo-bound spine ledger unavailable: {ledger_error}",)
        return _finish(
            "sources_unavailable",
            task_id=top.task_id,
            source=top.source)
    res = run_attempt(task, runner=runner, repo_root=str(root),
                      ledger_path=ledger_path,
                      artifact_dir=str(artifact_dir) if artifact_dir else None,
                      keep_worktree=keep_worktree)
    state = "gated" if getattr(res, "ok", False) else getattr(res, "state", "error")
    return _finish(state, task_id=top.task_id, source=top.source, attempt=res)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape. There
    # is no subcommand for the self-improvement circle, so this tail is the
    # only door: refresh sources, pick, attempt, gate. shadow_run builds the
    # picker queue (a git child), then runs offload_runner through the attempt
    # path -- a worktree, artifacts and a provider call with --live.
    #
    # Promotion is refused inside shadow_run and this call does not soften
    # that: begin_effect performs no effect, it authorises a START, and the
    # sealed promotion path is unchanged.
    from ..budget import process_guard_boundary_decision
    from .effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.bootstrap",
        REGISTRY_BY_ID["cli.bootstrap"].effects,
        (process_guard_boundary_decision(),),
    )

    p = argparse.ArgumentParser(
        prog="daedalus.spine.bootstrap",
        description="One SHADOW iteration of the self-improvement circle.",
        epilog=("Promotion is refused while the gate's discrimination is "
                "unproven, and there is no flag to override that. A green gate "
                "means the configured gate command ran.\n\n"
                "--local-only DECLARES availability; it does not force the "
                "router's choice. Measured: with claude_cli declared "
                "unavailable the router still selected it, and the run stopped "
                "only because offload refuses to execute a non-free lane and "
                "escalated instead. Nothing was billed -- but the flag's name "
                "promised more than it delivers, so the run now says out loud "
                "which lane it was actually routed to."))
    p.add_argument("--repo-root", default=str(ROOT))
    p.add_argument("--no-refresh", action="store_true",
                   help="skip source regeneration (they will likely be stale)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--live", action="store_true",
                   help="let the runner actually invoke a model")
    p.add_argument("--local-only", action="store_true",
                   help="declare only the local lane available. NOTE: this does "
                        "NOT force the router's choice -- see the epilog")
    p.add_argument("--artifact-dir", default=None)
    p.add_argument("--keep-worktree", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    from daedalus.spine.attempt import offload_runner

    kwargs: dict[str, Any] = {"live": bool(args.live)}
    if args.local_only:
        kwargs["availability"] = {"claude_cli": False, "ollama": True,
                                  "deepseek": False, "codex_cli": False}
    res = shadow_run(args.repo_root, runner=offload_runner(**kwargs),
                     refresh=not args.no_refresh, limit=args.limit,
                     artifact_dir=args.artifact_dir,
                     keep_worktree=args.keep_worktree)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2, default=str))
    else:
        for r in res.refreshed:
            mark = "ok " if r.succeeded else "!! "
            print(f"  {mark}{r.name}: {r.detail}")
        for d in res.degraded_sources:
            print(f"  !! source '{d}' could not be consulted")
        print(f"\n{res.verdict()}")
    if res.state == "sources_unavailable":
        return EXIT_SOURCES_UNAVAILABLE
    if res.state == "gated":
        return EXIT_OK
    if res.state in ("no_candidate", "no_change"):
        return EXIT_NO_CANDIDATE
    return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
