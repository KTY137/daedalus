"""Did the evaluator actually score the CANDIDATE's code?

ADR-015 Finding 1: the evolution runner called a bare ``pytest``, which put only
each test file's own basedir on ``sys.path``. The editable install pins
``daedalus`` to the primary checkout by absolute path via an ``_EditableFinder``
on ``sys.meta_path``, so nothing shadowed it and the candidate's edits were
invisible to the candidate's own tests. **The loop graded the host against
itself**, and every score it produced was a measurement of code nobody had
changed.

That was closed on 2026-07-29: the runner now uses ``sys.executable -m pytest``
with ``cwd`` set to the worktree, which puts the worktree on ``sys.path[0]``,
ahead of ``PathFinder``, ahead of ``_EditableFinder``. The candidate wins.

**This module exists because that is a MECHANISM, not a VERIFICATION.** The
candidate wins by an argument about import ordering, and nothing checks the
argument still holds. It stops holding if:

* ``PYTHONPATH`` is set in the environment the evaluator inherits;
* a candidate worktree has no ``daedalus/`` directory at all (a partial or
  destroyed candidate -- and on 2026-07-30 an external lane destroyed three of
  five modules while reporting success on all five);
* a future refactor changes how the editable install registers itself;
* somebody "simplifies" the invocation back to bare ``pytest``, which looks
  identical in a diff and is silently wrong.

In every one of those cases the failure is the WORST shape available: the tests
pass, the score is high, and it describes the wrong tree. So this asks the
question directly instead of reasoning about it, and a failed check voids the
EVALUATION rather than scoring the candidate. Those are different outcomes and
conflating them is the actual bug: a candidate scored 0 looks bad, while an
evaluation that could not run is *unknown*, and only one of them should be
allowed to influence a promotion.

Cheap: one interpreter start, ~0.3 s, against a suite run of seconds to minutes.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ProvenanceCheck", "check_import_provenance", "PROBE_SOURCE"]

#: Run in the CANDIDATE's interpreter, cwd and environment -- not here. Reporting
#: what ``daedalus`` resolves to in *this* process would answer a different
#: question than the one that matters, and answer it reassuringly.
#:
#: Reports rather than asserts, so the caller decides. A probe that exited
#: non-zero on mismatch would be indistinguishable from a probe that failed to
#: start, which is the distinction this whole module is about.
PROBE_SOURCE = (
    "import json,sys\n"
    "out={'argv0':sys.argv[0],'executable':sys.executable,"
    "'path0':(sys.path[0] if sys.path else None)}\n"
    "try:\n"
    "    import daedalus\n"
    "    out['daedalus_file']=getattr(daedalus,'__file__',None)\n"
    "    out['daedalus_path']=list(getattr(daedalus,'__path__',[]) or [])\n"
    "except Exception as exc:\n"
    "    out['import_error']=f'{type(exc).__name__}: {exc}'\n"
    "print(json.dumps(out))\n"
)


@dataclass(frozen=True)
class ProvenanceCheck:
    """Whether an evaluation in ``root`` would score the code in ``root``."""

    ok: bool
    root: str
    resolved: str | None
    reason: str
    raw: dict | None = None

    def as_error(self) -> str:
        """The message an evaluator should record when this fails.

        Deliberately says "evaluation" and never "candidate": the candidate has
        not been judged, and a reader must not be able to mistake this for a bad
        score.
        """
        return (f"EVALUATION VOID (not a candidate failure): {self.reason} "
                f"-- expected daedalus under {self.root}, "
                f"resolved to {self.resolved or 'nothing'}")


def _under(child: str | None, parent: Path) -> bool:
    if not child:
        return False
    try:
        Path(child).resolve().relative_to(parent)
        return True
    except (ValueError, OSError):
        return False


def check_import_provenance(
    root: str | Path,
    *,
    executable: str | None = None,
    timeout_s: float = 60.0,
) -> ProvenanceCheck:
    """Ask the candidate's own interpreter where ``daedalus`` resolves.

    FAIL-CLOSED in every direction. A probe that will not start, times out,
    returns unparseable output, or cannot import ``daedalus`` at all reports
    ``ok=False`` -- because "we could not establish which tree would be scored"
    and "the wrong tree would be scored" have the same consequence for a
    promotion decision, and neither is a green light.
    """
    base = Path(root).resolve()
    exe = executable or sys.executable
    try:
        proc = subprocess.run(
            [exe, "-c", PROBE_SOURCE],
            cwd=str(base), capture_output=True, text=True,
            timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return ProvenanceCheck(
            False, str(base), None,
            f"the provenance probe could not run ({type(exc).__name__}: {exc})")

    if proc.returncode != 0:
        return ProvenanceCheck(
            False, str(base), None,
            f"the provenance probe exited {proc.returncode}: "
            f"{(proc.stderr or '').strip()[:300]}")

    line = (proc.stdout or "").strip().splitlines()
    try:
        raw = json.loads(line[-1]) if line else {}
    except ValueError:
        return ProvenanceCheck(
            False, str(base), None,
            "the provenance probe produced unparseable output: "
            f"{(proc.stdout or '')[:200]!r}")

    if raw.get("import_error"):
        # Not necessarily fatal for the repo -- but it IS fatal for this
        # evaluation, because a suite that cannot import the package under test
        # is measuring nothing.
        return ProvenanceCheck(
            False, str(base), None,
            f"the candidate's interpreter cannot import daedalus: "
            f"{raw['import_error']}", raw)

    resolved = raw.get("daedalus_file")
    # __path__ is checked too: a namespace package has no __file__, and a
    # candidate whose package dir lost its __init__.py would otherwise resolve
    # to None and be read as "no answer" rather than "wrong tree".
    candidates = [resolved, *(raw.get("daedalus_path") or [])]
    if any(_under(c, base) for c in candidates):
        return ProvenanceCheck(True, str(base), resolved,
                               "daedalus resolves inside the candidate tree", raw)
    return ProvenanceCheck(
        False, str(base), resolved,
        "daedalus resolves OUTSIDE the candidate tree, so this run would score "
        "a different checkout -- ADR-015 Finding 1", raw)
