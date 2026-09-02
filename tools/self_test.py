"""Prove the acceptance checks can FAIL -- by actually breaking the system.

A check that has never gone red is a claim, not a control. This repo learned
that three times in one day on its own safety code, and `runs/ab/oracle_check.py`
applies the same rule to the A/B scorer. This applies it to the acceptance run.

METHOD. For each covered check, take a disposable clone, seed exactly ONE defect
that the check claims to detect, and require THAT check to report FAIL. A defect
nobody catches is reported as UNFALSIFIABLE and the run exits non-zero, because
an unfalsifiable property is worse than a missing one: it reads as covered.

TWO RULES THAT COST A ROUND EACH, BOTH FOUND BY REVIEW:

  * A MUTATION THAT DOES NOT APPLY, OR APPLIES TO DEAD CODE, PROVES NOTHING.
    The first run scored five "SURVIVED" results that were every one of them a
    defect in the MUTATION: two committed before the check took its own
    baseline, one inserted a no-op, one patched a branch the check never
    drives, and one edited a function a plan-only run never reaches. Blaming
    the checks for that would have been exactly backwards.
  * A MUTATION IS ONLY EVIDENCE IF THE BASELINE WAS GREEN. A check that was
    already FAIL or UNAVAILABLE before the defect was seeded tells you nothing
    when it comes back red. Those are reported INCONCLUSIVE, never CAUGHT.

WHAT THIS DOES NOT COVER, STATED RATHER THAN IMPLIED: see ``UNMUTATED`` below.
The contract of this file is "every check LISTED here can go red", not "every
check in the harness" -- the wider claim was in an earlier docstring while the
table covered 11 of 16, which is the same prose-without-a-control this repo
keeps finding.

NOTHING HERE TOUCHES THE WORKING REPOSITORY. Every mutation is applied inside a
throwaway clone with its own HOME and spine DB. That is what makes it safe to
really move HEAD, really leak a branch and really corrupt the chain -- the
things a timid self-test would only simulate, and therefore would not prove.
"""
from __future__ import annotations

import json
from pathlib import Path

import system_check as sc
from system_check import FAIL, PASS, Sandbox


def _patch(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"mutation target absent in {path.name}: {old[:70]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# --------------------------------------------------------------------------- #
# mutations                                                                    #
# --------------------------------------------------------------------------- #
def m_attempt_moves_head(sb: Sandbox) -> None:
    """Make the ATTEMPT commit to the primary checkout.

    The first version committed before the check ran -- before the check took
    its OWN baseline -- so the check correctly observed no change during the
    attempt. A falsification must break the property at the moment it is
    measured, not beforehand.
    """
    _patch(sb.repo / "daedalus" / "spine" / "attempt.py",
           "        return self._reap(result)",
           "        import subprocess as _sp  # SEEDED DEFECT\n"
           "        _p = str(self.repo_root)\n"
           "        open(_p + '/SEEDED_HEAD_MOVE.txt', 'w').write('x')\n"
           "        _sp.run(['git', '-C', _p, 'add', 'SEEDED_HEAD_MOVE.txt'], capture_output=True)\n"
           "        _sp.run(['git', '-C', _p, '-c', 'user.email=a@b.c', '-c',\n"
           "                 'user.name=S', 'commit', '-qm', 'seeded'], capture_output=True)\n"
           "        return self._reap(result)")


def m_attempt_edits_a_tracked_file(sb: Sandbox) -> None:
    """Make the attempt edit a tracked file in the primary checkout."""
    _patch(sb.repo / "daedalus" / "spine" / "attempt.py",
           "        return self._reap(result)",
           "        _rp = str(self.repo_root) + '/README.md'  # SEEDED DEFECT\n"
           "        open(_rp, 'a', encoding='utf-8').write('\\nseeded\\n')\n"
           "        return self._reap(result)")


def m_leak_a_branch(sb: Sandbox) -> None:
    """Unwire the reaper: one ref per attempt, forever."""
    _patch(sb.repo / "daedalus" / "spine" / "attempt.py",
           "        return self._reap(result)",
           "        return result  # SEEDED DEFECT: reaper unwired")


def m_intent_not_durable_before_effect(sb: Sandbox) -> None:
    """Defer the INSERT so no row exists while the runner executes.

    The first version inserted ``time.sleep(0)`` and changed nothing at all. A
    no-op mutation cannot falsify anything, and scoring it as "survived" blamed
    the check for the mutation's uselessness.
    """
    _patch(sb.repo / "daedalus" / "spine" / "ledger.py",
           "        with self._txn() as c:\n"
           "            cur = c.execute(\n"
           '                "INSERT INTO intents"',
           "        if str(kind).startswith('attempt'):  # SEEDED DEFECT\n"
           "            return Intent(id=-1, kind=kind, effect_key=effect_key,\n"
           "                          payload=json.loads(payload_json),\n"
           "                          payload_json=payload_json,\n"
           "                          payload_sha=payload_sha, created_ts=ts,\n"
           "                          state=STATE_INTENDED)\n"
           "        with self._txn() as c:\n"
           "            cur = c.execute(\n"
           '                "INSERT INTO intents"')


def m_forget_attempts(sb: Sandbox) -> None:
    """Turn attempt memory off: the loop spins in place again."""
    _patch(sb.repo / "daedalus" / "spine" / "picker.py",
           "    if use_attempt_memory:",
           "    if False:  # SEEDED DEFECT: memory off")


def m_degraded_exits_zero(sb: Sandbox) -> None:
    """Make a withheld source exit 0, reading as "there is no work".

    BOTH return sites. The first version patched only the ``--once`` path while
    the check drives ``--dry-run``, so the seeded defect was never on the code
    path under test.
    """
    path = sb.repo / "daedalus" / "spine" / "picker.py"
    text = path.read_text(encoding="utf-8")
    old = "return EXIT_SOURCE_UNAVAILABLE if degraded else 0"
    if text.count(old) < 2:
        raise AssertionError("expected both the dry-run and --once exit sites")
    path.write_text(text.replace(old, "return 0  # SEEDED DEFECT"), encoding="utf-8")


def m_allow_remote_ollama(sb: Sandbox) -> None:
    """Remove the guard that refuses a non-loopback endpoint."""
    _patch(sb.repo / "daedalus" / "providers" / "ollama.py",
           "        refusal = self._refuse_if_remote()",
           "        refusal = None  # SEEDED DEFECT: remote endpoint allowed")


def m_add_apply_flag(sb: Sandbox) -> None:
    """Give the ranking module a promotion flag."""
    _patch(sb.repo / "daedalus" / "spine" / "picker.py",
           '    parser.add_argument("--forget", action="store_true",',
           '    parser.add_argument("--apply", action="store_true",\n'
           '                        help="SEEDED DEFECT")\n'
           '    parser.add_argument("--forget", action="store_true",')


def m_room_trusts_everyone(sb: Sandbox) -> None:
    """Hand an external vendor a trusted-lane attachment."""
    _patch(sb.repo / "runs" / "council" / "room.py",
           '    name = (who or "").strip().lower()\n'
           '    if name == "claude":\n'
           '        return "trusted"',
           '    return "trusted"  # SEEDED DEFECT\n'
           '    name = (who or "").strip().lower()\n'
           '    if name == "claude":\n'
           '        return "trusted"')


def m_offload_writes(sb: Sandbox) -> None:
    """Make a plan-only run touch the tree.

    ``_slice_budget()`` is only called inside the ollama WRITE branch, which a
    plan-only run never reaches -- the first version of this mutation was dead
    code. ``offload()`` itself is on the plan path.
    """
    _patch(sb.repo / "daedalus" / "offload.py",
           "    if availability is None:",
           "    open(str(repo_root) + '/SEEDED_PLAN_WRITE.txt', 'w').write('x')\n"
           "    if availability is None:")


def m_enqueue_collides(sb: Sandbox) -> None:
    """Restore the second-resolution filename, so two enqueues collide.

    The real defect this seeds: a task queue that silently drops a task when
    two arrive in the same second. Found by the acceptance run, not by any
    unit test -- 1753 of them were green over it.
    """
    _patch(sb.repo / "daedalus" / "file_bridge.py",
           "    if path.exists():",
           "    if False:  # SEEDED DEFECT: colliding names overwrite silently")


def m_break_map_snapshot(sb: Sandbox) -> None:
    """Corrupt the generated snapshot so the drift gate must object."""
    snap = sb.repo / "docs" / "architecture-state.json"
    doc = json.loads(snap.read_text(encoding="utf-8"))
    doc["islands"] = []
    doc["counts"] = {**(doc.get("counts") or {}), "islands": 0}
    snap.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def m_bus_always_verifies(sb: Sandbox) -> None:
    """A verifier that cannot fail -- the decorative kind."""
    _patch(sb.repo / "runs" / "council" / "room.py",
           "def verify_room(store_path: str | Path | None = None) -> tuple[bool, list[str]]:",
           "def verify_room(store_path=None):\n"
           "    return True, []  # SEEDED DEFECT: verifier always passes\n\n\n"
           "def _verify_room_real(store_path: str | Path | None = None) -> tuple[bool, list[str]]:")


def m_break_cli_dispatch(sb: Sandbox) -> None:
    """Break the single entry point's verb listing."""
    _patch(sb.repo / "daedalus" / "cli.py",
           "def main(",
           "def main(argv=None):  # SEEDED DEFECT\n"
           "    return 0\n\n\n"
           "def _main_real(")


def m_context_drops_its_receipt(sb: Sandbox) -> None:
    """Emit a context plan with no provenance receipt."""
    # Anchored on a line that occurs ONCE, inside ContextPlanningResult.
    # The first version patched `def to_dict(self)`, which matches
    # LexicalSeedResult's method 300 lines earlier -- so the mutation applied
    # cleanly to the wrong class and changed nothing the check reads. A
    # mutation that lands somewhere real but irrelevant looks exactly like a
    # check that cannot detect anything.
    _patch(sb.repo / "daedalus" / "orchestration" / "context_plan.py",
           '            "dss": self.dss.to_dict(),',
           '            "dss": {_k: _v for _k, _v in self.dss.to_dict().items()\n'
           "                    if _k != 'receipt'},  # SEEDED DEFECT")


def m_eval_returns_no_score(sb: Sandbox) -> None:
    """Make the measurement harness stop producing a number."""
    _patch(sb.repo / "daedalus" / "eval" / "harness.py",
           "def eval_task_tier1(task: dict, idx: dict | None = None) -> dict:",
           "def eval_task_tier1(task, idx=None):  # SEEDED DEFECT\n"
           "    return {'task': task.get('id'), 'recall': None}\n\n\n"
           "def _eval_task_tier1_real(task: dict, idx: dict | None = None) -> dict:")


# (check name, mutation, the defect it seeds)
MUTATIONS = [
    ("cli.entrypoint", m_break_cli_dispatch,
     "the entry point stops listing its verbs"),
    ("context.produces_a_budgeted_plan", m_context_drops_its_receipt,
     "a context plan ships with no provenance receipt"),
    ("offload.plans_without_mutating", m_offload_writes,
     "a plan-only run writes to the tree"),
    ("map.drift_gate_is_green", m_break_map_snapshot,
     "the committed snapshot no longer matches the tree"),
    ("picker.ranks_with_evidence", m_break_map_snapshot,
     "the generated source is emptied, so the queue starves"),
    ("picker.exit_code_distinguishes_degraded", m_degraded_exits_zero,
     "a withheld source exits 0, reading as 'no work'"),
    ("spine.intent_is_recorded_BEFORE_the_effect", m_intent_not_durable_before_effect,
     "the ledger row is not durable until after the effect"),
    ("spine.attempt_leaves_the_primary_untouched", m_attempt_moves_head,
     "HEAD moves during an attempt"),
    ("spine.attempt_leaves_the_primary_untouched", m_attempt_edits_a_tracked_file,
     "a tracked file is edited in the primary checkout"),
    ("spine.attempt_leaves_the_primary_untouched", m_leak_a_branch,
     "the candidate branch is never reaped"),
    ("spine.circle_closes", m_forget_attempts,
     "attempt memory is off, so the loop re-picks forever"),
    ("eval.replays_a_task_and_scores_it", m_eval_returns_no_score,
     "the replay stops producing a recall number"),
    ("bridge.enqueue_watch_report_archive", m_enqueue_collides,
     "two enqueues in one second overwrite, so a task is silently lost"),
    ("safety.remote_ollama_is_refused", m_allow_remote_ollama,
     "a remote endpoint is fed repository content"),
    ("safety.picker_cannot_apply", m_add_apply_flag,
     "the ranking module offers a promotion flag"),
    ("safety.room_prompt_gates_by_speaker", m_room_trusts_everyone,
     "an external vendor receives a trusted-lane attachment"),
    ("safety.bus_chain_detects_a_break", m_bus_always_verifies,
     "the chain verifier cannot fail"),
]

# Checks with NO seeded defect, and the honest reason. Listed so the gap is a
# stated limit rather than something a reader has to notice by counting.
UNMUTATED = {
    "doctor.reports_readiness":
        "deliberately tolerant -- it must report 'not ready' WITHOUT failing, "
        "so there is no wrong answer to seed",
    "web.serves_and_terminates":
        "breaking the server would test this harness's timeout handling rather "
        "than a product property; the readiness deadline covers it",
}


def _run_one(name: str, sb: Sandbox):
    spec = next((c for c in sc.CHECKS if c["name"] == name), None)
    if spec is None:
        raise AssertionError(f"unknown check: {name}")
    res = spec["fn"](sb)
    res.core = spec["core"]
    return res


def run_self_test(only: str | None = None) -> int:
    print("acceptance self-test -- seeding real defects into disposable clones")
    print("nothing below touches the working repository.\n")

    names = sorted({m[0] for m in MUTATIONS})
    if only:
        names = [n for n in names if only in n]

    baseline_sb = Sandbox()
    if not baseline_sb.build():
        print(f"could not build the baseline clone: {baseline_sb.error}")
        return 1
    baseline = {}
    try:
        print("baseline (no defect seeded) -- a mutation only counts where this is PASS:")
        for name in names:
            res = _run_one(name, baseline_sb)
            baseline[name] = res.outcome
            print(f"  [{res.outcome:11s}] {name}")
            if res.outcome != PASS and res.detail:
                print(f"                {res.detail[:110]}")
    finally:
        baseline_sb.destroy()

    print("\nseeded defects:")
    rows = []
    for name, mutate, _what in MUTATIONS:
        if only and only not in name:
            continue
        sb = Sandbox()
        try:
            if not sb.build():
                rows.append((name, mutate.__name__, "CLONE_FAILED", sb.error))
                continue
            try:
                mutate(sb)
            except AssertionError as e:
                rows.append((name, mutate.__name__, "NOT_APPLICABLE", str(e)))
                print(f"  [n/a ] {mutate.__name__:32s} {e}")
                continue
            if baseline.get(name) != PASS:
                rows.append((name, mutate.__name__, "INCONCLUSIVE",
                             f"baseline was {baseline.get(name)}"))
                print(f"  [??  ] {mutate.__name__:32s} -> {name}")
                print(f"         INCONCLUSIVE: baseline was {baseline.get(name)}, "
                      f"so going red would prove nothing")
                continue
            res = _run_one(name, sb)
            caught = res.outcome == FAIL
            rows.append((name, mutate.__name__,
                         "CAUGHT" if caught else "SURVIVED", res.detail))
            print(f"  [{'ok  ' if caught else 'MISS'}] {mutate.__name__:32s} -> {name}")
            if not caught:
                print(f"         SURVIVED: the check reported {res.outcome}. "
                      f"This property is UNFALSIFIABLE and reads as covered.")
            elif res.detail:
                print(f"         caught: {res.detail[:100]}")
        finally:
            sb.destroy()

    caught = [r for r in rows if r[2] == "CAUGHT"]
    survived = [r for r in rows if r[2] == "SURVIVED"]
    inconclusive = [r for r in rows if r[2] in ("INCONCLUSIVE", "NOT_APPLICABLE",
                                                "CLONE_FAILED")]
    print(f"\n{'=' * 70}")
    print(f"seeded {len(rows)}: {len(caught)} caught, {len(survived)} SURVIVED, "
          f"{len(inconclusive)} inconclusive")
    for name, mut, _s, _d in survived:
        print(f"  ! {mut} -> {name}: nothing went red (UNFALSIFIABLE)")
    for name, mut, status, detail in inconclusive:
        print(f"  ? {mut} -> {name}: {status} -- {str(detail)[:90]}")
    if UNMUTATED and not only:
        print("\nchecks with no seeded defect (stated, not hidden):")
        for name, why in sorted(UNMUTATED.items()):
            print(f"  - {name}: {why}")
    print("=" * 70)
    return 1 if (survived or inconclusive) else 0
