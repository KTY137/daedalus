"""The first production caller wired through the central effect boundary.

Gate 0 requires "a centralized start/guard path for every effectful runtime
entrypoint". Before this file, ``begin_effect`` had 14 call sites and all 14
were in tests: the boundary was a contract nothing in ``daedalus/`` had ever
been made to satisfy. ``python.attempt`` is the first row to actually go
through it.

WHY THIS ROW WENT FIRST, recorded here because the choice is the interesting
part. Its two guard contracts were already real -- the intent is committed to
the spine ledger before the first external effect, and
:mod:`daedalus.spine.attempt` documents four structural properties that keep an
attempt out of the primary checkout. The registry's own note said the only
thing missing was the receipt. So this row could become CENTRAL truthfully,
which ``python.offload`` could not: that row is UNGUARDED because it lacks
attempt-worktree containment, and its recorded migration is "route the live
write branch through TaskAttempt/run_attempt". Flipping offload to CENTRAL
would have deleted its blocker without building the containment the blocker is
about -- and the thing it must be routed INTO is what this file wires.

The tests that matter here are the negative ones. A registry row claiming
"central" is a string; the anchors are what make it a call.
"""
import subprocess
from pathlib import Path

import pytest

import daedalus.spine.effect_boundary as EB
from daedalus.spine.attempt import (
    STATE_CLEAN,
    STATE_WORKTREE_FAILED,
    GateResult,
    RunnerContext,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.ledger import STATE_FAILED, SpineLedger

ROOT = Path(__file__).resolve().parents[1]
ROW_ID = "python.attempt"
ATTEMPT_SOURCE = ROOT / "daedalus" / "spine" / "attempt.py"


# --------------------------------------------------------------------------- #
# fixtures (deliberately local -- see tests/test_spine_attempt.py)             #
# --------------------------------------------------------------------------- #
@pytest.fixture
def worktree_root(tmp_path, monkeypatch):
    root = tmp_path / "wt_root"
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(root))
    return root


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run_git(*args):
        subprocess.run(["git", *args], cwd=repo_path, check=True,
                       capture_output=True)

    run_git("init")
    run_git("config", "user.name", "Test User")
    run_git("config", "user.email", "test@example.com")
    (repo_path / "seed.txt").write_text("seed\n")
    run_git("add", "seed.txt")
    run_git("commit", "-m", "seed")
    return repo_path


@pytest.fixture
def ledger(tmp_path):
    led = SpineLedger(tmp_path / "spine" / "spine.sqlite3")
    try:
        yield led
    finally:
        led.close()


def spec(**kw):
    base = dict(task_id="boundary-task", instruction="add a widget")
    base.update(kw)
    return TaskSpec(**base)


def writing_runner(files):
    def _runner(ctx: RunnerContext):
        for rel, text in files.items():
            target = Path(ctx.worktree) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return {"wrote": sorted(files)}

    return _runner


def passing_gate():
    def _gate(ctx: RunnerContext):
        return GateResult(passed=True, name="fake", output="1 passed")

    return _gate


def _git_out(repo_path, *args):
    return subprocess.run(["git", *args], cwd=repo_path, check=True,
                          capture_output=True, text=True).stdout


# --------------------------------------------------------------------------- #
# the row is wired                                                             #
# --------------------------------------------------------------------------- #
def test_the_attempt_row_is_central_and_names_its_call_sites() -> None:
    row = EB.REGISTRY_BY_ID[ROW_ID]
    assert row.wiring is EB.Wiring.CENTRAL, (
        "python.attempt left the central path; Gate 0 has no wired row again")
    assert row.guard_contracts, "a central row with no guard contract is decorative"
    for contract in row.guard_contracts:
        assert EB.GUARD_CONTRACT_IMPLEMENTED[contract] is True, (
            f"{contract} is declared but has no mechanical implementation")

    anchored = {(anchor.target, anchor.call) for anchor in row.anchors}
    assert (
        "daedalus.spine.attempt:TaskAttempt._begin_effect_boundary",
        "begin_effect",
    ) in anchored
    assert (
        "daedalus.spine.attempt:TaskAttempt._run_with_ledger",
        "_begin_effect_boundary",
    ) in anchored


def test_begin_effect_now_admits_the_attempt_row() -> None:
    """The row that used to raise "not central" returns a receipt.

    This is the whole Gate-0 delta in one assertion: before the wiring, every
    one of the 50 rows refused here.
    """
    row = EB.REGISTRY_BY_ID[ROW_ID]
    receipt = EB.begin_effect(
        ROW_ID,
        row.effects,
        [EB.GuardDecision(name, True, "evidence") for name in row.guard_contracts],
    )
    assert receipt.entrypoint_id == ROW_ID
    assert receipt.registry_sha256 == EB.registry_sha256()
    assert len(receipt.receipt_sha256) == 64


def test_the_live_tree_satisfies_both_anchors() -> None:
    """The real source -- not a fixture -- is what the anchors are checked against."""
    report = EB.check_conformance(ROOT)
    anchor_failures = [
        row for row in report.findings
        if row.code == "registry.guard_anchor_missing" and row.subject == ROW_ID
    ]
    assert not anchor_failures, anchor_failures
    assert not [
        row for row in report.findings
        if row.code == "gate0.not_central" and row.subject == ROW_ID
    ], "python.attempt is still counted as a Gate-0 gap"


# --------------------------------------------------------------------------- #
# FAIL CLOSED: the checker                                                     #
# --------------------------------------------------------------------------- #
def test_a_central_row_without_a_begin_effect_anchor_is_a_blocker() -> None:
    """"Central" must cost a call site, not a word.

    THE INJECTED FAULT: someone edits one token -- ``Wiring.LOCAL_GUARDS`` to
    ``Wiring.CENTRAL`` -- on a row whose guard contracts happen to be
    implemented. Before this rule existed that was enough to clear the row's
    blocker and drop it out of ``gate0.not_central`` with no calling code
    anywhere, which made the matrix's headline number the cheapest thing in the
    repository to fake.
    """
    row = EB.REGISTRY_BY_ID[ROW_ID]
    unanchored = EB.EntrypointSpec(
        id=row.id, surface=row.surface, target=row.target, effects=row.effects,
        guard_contracts=row.guard_contracts, wiring=EB.Wiring.CENTRAL,
        anchors=(),
    )
    report = EB.check_conformance(ROOT, registry=(unanchored,))
    subjects = {
        (finding.code, finding.subject, finding.severity)
        for finding in report.findings
    }
    assert ("registry.central_without_boundary_anchor", ROW_ID, "blocker") in subjects
    assert report.structurally_conformant is False


# --------------------------------------------------------------------------- #
# MUTATION: removing the wiring must go red                                    #
# --------------------------------------------------------------------------- #
def _mutated_root(tmp_path: Path, old: str, new: str) -> Path:
    """A standalone tree holding the REAL attempt.py with one call removed.

    Never mutates the repository source: six other agents run tests in this
    checkout, and a temporarily broken guard here would inject faults into
    their runs. The real text is used rather than a stub so the test proves the
    anchor detects removal from the ACTUAL wiring, and the replacement count is
    asserted so a rename that makes the mutation a no-op fails loudly instead
    of passing as a green tick.
    """
    source = ATTEMPT_SOURCE.read_text(encoding="utf-8")
    assert source.count(old) == 1, (
        f"expected exactly one {old!r} in attempt.py, found {source.count(old)}; "
        "the mutation would not be testing what it claims")

    package = tmp_path / "daedalus" / "spine"
    package.mkdir(parents=True)
    (tmp_path / "daedalus" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "attempt.py").write_text(source.replace(old, new), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n", encoding="utf-8")
    return tmp_path


def _anchor_failures(report, call: str) -> list:
    return [
        row for row in report.findings
        if row.code == "registry.guard_anchor_missing"
        and row.subject == ROW_ID
        and call in row.detail
    ]


def test_removing_the_begin_effect_call_is_a_blocker(tmp_path) -> None:
    """Delete the boundary call itself; the anchor must notice."""
    root = _mutated_root(tmp_path, "return begin_effect(", "return _bypass(")
    row = EB.REGISTRY_BY_ID[ROW_ID]

    report = EB.check_conformance(root, registry=(row,))

    failures = _anchor_failures(report, "begin_effect")
    assert failures, (
        "attempt.py stopped calling begin_effect and the matrix still said "
        "central -- the anchor is not load-bearing")
    assert failures[0].severity == "blocker"
    assert report.structurally_conformant is False


def test_removing_the_seam_call_is_a_blocker(tmp_path) -> None:
    """Keep the helper, stop calling it. The second anchor is why this is caught.

    One anchor would not have been enough: a boundary helper that still calls
    ``begin_effect`` but that nothing invokes is exactly as unwired as one that
    was deleted, and the first anchor alone reports it as healthy.
    """
    root = _mutated_root(
        tmp_path, "self._begin_effect_boundary(", "self._skip_the_boundary(")
    row = EB.REGISTRY_BY_ID[ROW_ID]

    report = EB.check_conformance(root, registry=(row,))

    failures = _anchor_failures(report, "_begin_effect_boundary")
    assert failures, (
        "the attempt seam stopped calling the boundary helper and nothing "
        "noticed")
    assert failures[0].severity == "blocker"


# --------------------------------------------------------------------------- #
# FAIL CLOSED: a refused start must not become an effect                       #
# --------------------------------------------------------------------------- #
class _RefusingManager:
    """A manager pointed INSIDE the primary checkout, which is the one runtime
    input the attempt's containment properties depend on. Records whether the
    worktree was ever created."""

    def __init__(self, worktree_root: Path) -> None:
        self.worktree_root = worktree_root
        self.create_calls: list = []

    def create_worktree(self, base_revision, branch):
        self.create_calls.append((base_revision, branch))
        raise AssertionError(
            "create_worktree ran after the boundary refused the start")

    def reap_branches(self):
        return ()


def test_a_refused_start_creates_no_worktree_and_fails_the_intent(
        repo, worktree_root, ledger) -> None:
    """FAIL CLOSED. The boundary says no; the effect must not happen.

    A receipt that can be skipped is not a boundary, so the test asserts the
    consequence rather than the exception: no worktree was created, the ledger
    intent is FAILED rather than left OPEN, the primary checkout is untouched,
    and the result carries no receipt.
    """
    manager = _RefusingManager(repo / "inside_the_checkout")
    head_before = _git_out(repo, "rev-parse", "HEAD").strip()

    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=passing_gate(), repo_root=repo, ledger=ledger,
                         worktree_manager=manager).run()

    assert result.state == STATE_WORKTREE_FAILED
    assert "effect boundary refused the start" in (result.error or "")
    assert "containment.attempt" in (result.error or "")
    assert manager.create_calls == [], "an effect ran after a refusal"
    assert result.boundary_receipt is None

    assert result.intent_id is not None
    row = ledger.get(result.intent_id)
    assert row["state"] == STATE_FAILED, (
        "a refused start left an OPEN intent, so the ledger claims an effect "
        "may still be in flight")

    assert _git_out(repo, "status", "--porcelain").strip() == ""
    assert _git_out(repo, "rev-parse", "HEAD").strip() == head_before


def test_an_admitted_attempt_carries_its_receipt(repo, worktree_root,
                                                 ledger) -> None:
    """The happy path proves the boundary is on the live path, not beside it.

    If the wiring were dead code, this attempt would still succeed and the
    receipt would be ``None``.
    """
    result = TaskAttempt(spec(), runner=writing_runner({"a.txt": "a\n"}),
                         gate=passing_gate(), repo_root=repo, ledger=ledger).run()

    assert result.state == STATE_CLEAN, result.error
    assert result.boundary_receipt is not None, (
        "a completed attempt produced no effect-start receipt")
    assert len(result.boundary_receipt) == 64
    assert result.to_dict()["boundary_receipt"] == result.boundary_receipt
