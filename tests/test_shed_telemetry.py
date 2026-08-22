"""The brief-shed covariate must be recorded, or graph-conditioning is unreadable.

WHAT IS BEING GUARDED
---------------------
``daedalus/providers/ollama.py`` drops the structural brief (``render_brief``)
out of a rewrite prompt whenever the estimated input exceeds the local context
window. That makes "did this attempt see the graph?" a variable the harness
assigns SILENTLY, by task size -- and a treatment assigned by size, never
written down, is indistinguishable from an effect of size. Giga plan Phase 3
(``docs/inventory/2026-08-21/GIGA_PLAN_2026-08-22.md``, last action; Lens E
dissent 4 and Lens D for_codex 5) requires the three fields to travel in the
lane record so the covariate exists before anyone compares briefed against
unbriefed runs.

WHY THE FIELDS MEAN EXACTLY WHAT THEY MEAN
------------------------------------------
* ``est_in`` -- the estimate the shed decision was MADE on (brief still in the
  prompt). It is the assignment variable, not the tokens the server billed;
  ``count_tokens`` is a cl100k over-count of a qwen prompt and these tests
  never pretend otherwise.
* ``brief_shed`` -- whether the brief was then removed to fit.
* ``brief_bytes`` -- the UTF-8 size of the brief that ACTUALLY reached the
  model. Zero once shed, zero when none was built.

NO NETWORK, NO PYTEST FIXTURES. Every test builds its own temp tree and swaps
module attributes back in a ``finally``, so each one is callable directly from
a plain ``python -c`` probe as well as by the suite -- the lane that wrote them
was not permitted to run a suite, and a test nobody can execute in isolation is
a claim, not a check.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.providers import ollama as ollama_mod  # noqa: E402
from daedalus.providers.ollama import OllamaProvider  # noqa: E402
from daedalus.schemas import ResourceUsage  # noqa: E402
from daedalus.spine.attempt import GateResult, TaskAttempt, TaskSpec  # noqa: E402
from daedalus.spine.receipts import (  # noqa: E402
    METERED_INPUT_REASON,
    UNMETERED_SPEND_REASON,
    AttemptContractSet,
    adapter_identity,
    canonicalise_attempt,
    normalise_shed_telemetry,
)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
class _Swap:
    """Replace module attributes for the duration of a block, then restore."""

    def __init__(self, module, **values):
        self._module = module
        self._values = values
        self._saved = {}

    def __enter__(self):
        for name, value in self._values.items():
            self._saved[name] = getattr(self._module, name)
            setattr(self._module, name, value)
        return self

    def __exit__(self, *_exc):
        for name, value in self._saved.items():
            setattr(self._module, name, value)
        return False


def _stub_chat(returned="EDITED\n"):
    """Stand in for native_chat. Records the prompt it was handed."""

    seen = {}

    def _chat(**kw):
        seen["messages"] = kw["messages"]
        return {"content": json.dumps({"content": returned})}

    return _chat, seen


def _rewrite_env(brief, window):
    """The three module hooks a shed decision depends on.

    ``count_tokens`` becomes ``len`` so the arithmetic in the test is the
    arithmetic in the code: est_in is then a character count and the window is
    comparable to it by inspection, instead of by a tokenizer whose numbers
    would have to be hard-coded and would rot.
    """

    return dict(
        render_brief=lambda *a, **k: brief,
        count_tokens=len,
        effective_input_window=lambda _reserve: window,
    )


# --------------------------------------------------------------------------- #
# the provider: one row per full-file prompt                                   #
# --------------------------------------------------------------------------- #
def test_a_prompt_that_kept_the_brief_records_the_bytes_it_carried():
    chat, seen = _stub_chat()
    rows = []
    brief = "SYMBOLS: alpha, beta\n"
    with _Swap(ollama_mod, native_chat=chat, **_rewrite_env(brief, 1_000_000)):
        content, reason = OllamaProvider()._full_file_content(
            "raise it", "target.py", "VALUE = 1\n", False, {}, [],
            None, 30, repo_root=".", telemetry=rows)

    assert reason is None and content == "EDITED\n"
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["rel"] == "target.py"
    assert row["brief_shed"] is False
    # The brief really is in the prompt, and brief_bytes is its size THERE --
    # not the size render_brief returned. The two differ by the "\n\n" join,
    # and a covariate that silently means the other one is a wrong number.
    prompt = "".join(m["content"] for m in seen["messages"])
    assert brief in prompt
    assert row["brief_bytes"] == len(f"\n\n{brief}".encode("utf-8"))
    assert row["est_in"] > 0


def test_a_prompt_that_shed_the_brief_says_so_and_reports_zero_bytes():
    chat, seen = _stub_chat()
    rows = []
    # A brief far larger than the window forces the shed; the file itself is
    # tiny, so the prompt fits comfortably once the brief is gone.
    brief = "X" * 100_000
    with _Swap(ollama_mod, native_chat=chat, **_rewrite_env(brief, 50_000)):
        content, reason = OllamaProvider()._full_file_content(
            "raise it", "target.py", "VALUE = 1\n", False, {}, [],
            None, 30, repo_root=".", telemetry=rows)

    assert reason is None and content == "EDITED\n"
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["brief_shed"] is True
    assert row["brief_bytes"] == 0
    # est_in is the estimate the DECISION was made on: the prompt WITH the
    # brief, which is what put this call over the window. If it were rewritten
    # to the post-shed estimate, the assignment variable would be lost and the
    # treatment would look uncaused.
    assert row["est_in"] > 100_000
    prompt = "".join(m["content"] for m in seen["messages"])
    assert "X" * 100 not in prompt


def test_a_file_skipped_after_the_shed_still_leaves_its_row():
    """The row is appended BEFORE the decision, so a refusal cannot erase it.

    A shed that ends in a skip is the most informative row there is -- the
    window was too small even without the brief -- and it is exactly the row a
    'record it once we succeed' implementation would drop.
    """
    rows = []
    # Under MAX_REWRITE_CHARS (a file above that is refused before any prompt
    # is built, and correctly leaves no row), over the window.
    huge = "VALUE = 1\n" * 200
    with _Swap(ollama_mod, **_rewrite_env("B" * 1_000, 100)):
        content, reason = OllamaProvider()._full_file_content(
            "raise it", "target.py", huge, False, {}, [],
            None, 30, repo_root=".", telemetry=rows)

    assert content is None and "input tok" in reason
    assert len(rows) == 1 and rows[0]["brief_shed"] is True


def test_the_rewrite_lane_reports_the_key_even_when_no_prompt_was_built():
    """Unconditional presence. An absent key would be indistinguishable from a
    lane that never makes a shed decision, and a covariate that is only there
    when it is interesting cannot be read across attempts."""

    with tempfile.TemporaryDirectory() as tmp:
        report = OllamaProvider()._run_rewrite(
            "raise it", tmp, ["../escape.py"], None, 30, None)

    assert "shed_telemetry" in report["handoff"]
    assert report["handoff"]["shed_telemetry"] == []
    assert report["handoff"]["skipped"] == {"../escape.py": "outside repo"}


def test_the_rewrite_lane_carries_the_rows_into_its_report():
    chat, _seen = _stub_chat("VALUE = 2\n")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
        with _Swap(ollama_mod, native_chat=chat,
                   **_rewrite_env("SYMBOLS: VALUE\n", 1_000_000)):
            report = OllamaProvider()._run_rewrite(
                "raise it", tmp, ["target.py"], None, 30, None)

        assert report["files_changed"] == ["target.py"], report["summary"]
        rows = report["handoff"]["shed_telemetry"]
        assert [r["rel"] for r in rows] == ["target.py"]
        assert rows[0]["brief_shed"] is False and rows[0]["brief_bytes"] > 0


# --------------------------------------------------------------------------- #
# the attempt record: the covariate reaches the canonical contracts            #
# --------------------------------------------------------------------------- #
def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _real_attempt(root):
    """One REAL finished attempt: real git worktree, real ledger, real store.

    Hand-built contracts would pass with the projection ripped out, so the
    result these tests project is produced by the live spine.
    """
    repo = Path(root) / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "shed@example.com")
    _git(repo, "config", "user.name", "shed")
    (repo / "target.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    def _runner(ctx):
        (ctx.worktree / "target.py").write_text("VALUE = 2\n", encoding="utf-8")

    def _gate(_ctx):
        return GateResult(passed=True, name="demo-gate", command=("echo", "ok"),
                          returncode=0, output="green\n", duration_s=0.4)

    attempt = TaskAttempt(
        TaskSpec(task_id="shed-telemetry-task", instruction="raise VALUE",
                 target_paths=("target.py",), gate_timeout_s=60.0),
        runner=_runner, gate=_gate, repo_root=str(repo),
        ledger_path=Path(root) / "spine.sqlite3",
        artifact_dir=Path(root) / "store", reap=False)
    return attempt, attempt.run()


def _project(attempt, result, rows):
    locator, error = attempt._persist_gate_output(
        result.gates, result.base_revision, result.finished_ts)
    assert locator, error
    return canonicalise_attempt(
        result,
        task=attempt.task,
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        base_revision=result.base_revision,
        adapter_id=adapter_identity(attempt._runner),
        evidence_locator=locator,
        budget=attempt.budget,
        usage=ResourceUsage(wall_time_ms=400),
        created_at=result.finished_ts,
        boundary_receipt=attempt._boundary_receipt,
        shed_telemetry=rows,
    )


def test_the_attempt_record_carries_the_covariate_and_meters_input_tokens():
    rows = [
        {"rel": "target.py", "brief_shed": True, "est_in": 9_000, "brief_bytes": 0},
        {"rel": "other.py", "brief_shed": False, "est_in": 1_200, "brief_bytes": 640},
    ]
    with tempfile.TemporaryDirectory() as tmp:
        attempt, result = _real_attempt(tmp)
        assert result.state == "clean"
        bare = _project(attempt, result, None)
        metered = _project(attempt, result, rows)

    # BASELINE: without telemetry nothing changes -- same zero, same declared
    # limitation. The feature is additive or it is a rewrite of every record.
    assert bare.shed_telemetry == ()
    assert bare.receipt.usage.input_tokens == 0
    assert UNMETERED_SPEND_REASON in bare.policy.reasons
    assert METERED_INPUT_REASON not in bare.policy.reasons

    # WITH telemetry: the three fields ride the set...
    assert metered.complete
    assert [r["rel"] for r in metered.shed_telemetry] == ["target.py", "other.py"]
    assert metered.shed_telemetry[0]["brief_shed"] is True
    assert metered.shed_telemetry[1]["brief_bytes"] == 640
    # ...and est_in becomes the spine's FIRST metered usage field, inside the
    # receipt's digest rather than beside it.
    assert metered.receipt.usage.input_tokens == 10_200
    assert metered.evidence.usage == metered.receipt.usage

    # The declared limitation is swapped in the same breath, because a digest
    # that keeps asserting "nothing measured them" after something did is a
    # signed false statement (Invariant 9).
    assert UNMETERED_SPEND_REASON not in metered.policy.reasons
    assert METERED_INPUT_REASON in metered.policy.reasons
    # Everything else about the decision is untouched.
    assert len(metered.policy.reasons) == len(bare.policy.reasons)
    assert metered.receipt.outcome == bare.receipt.outcome


def test_shed_rows_survive_the_ledger_round_trip():
    rows = ({"rel": "a.py", "brief_shed": True, "est_in": 7, "brief_bytes": 0},)
    wire = AttemptContractSet(shed_telemetry=rows).to_dict()
    assert wire["shed_telemetry"] == [dict(rows[0])]
    assert AttemptContractSet.from_dict(wire).shed_telemetry == rows


def test_a_ledger_row_written_before_the_field_existed_reads_back_empty():
    assert AttemptContractSet.from_dict({"error": None}).shed_telemetry == ()
    assert AttemptContractSet().to_dict()["shed_telemetry"] == []


# --------------------------------------------------------------------------- #
# the refusals -- disable one and one of these goes red                        #
# --------------------------------------------------------------------------- #
def _refused(rows):
    try:
        normalise_shed_telemetry(rows)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"accepted a row it must refuse: {rows!r}")


def test_a_row_claiming_both_a_shed_brief_and_injected_bytes_is_refused():
    """Not a rounding error: two different runs mixed into one record, which is
    the exact confound this telemetry exists to prevent."""
    assert "injected brief bytes" in _refused(
        [{"rel": "a.py", "brief_shed": True, "est_in": 10, "brief_bytes": 512}])


def test_malformed_rows_are_refused_rather_than_coerced():
    assert "missing brief_bytes" in _refused(
        [{"rel": "a.py", "brief_shed": False, "est_in": 10}])
    assert "brief_shed must be boolean" in _refused(
        [{"rel": "a.py", "brief_shed": "no", "est_in": 10, "brief_bytes": 0}])
    assert "non-negative integer" in _refused(
        [{"rel": "a.py", "brief_shed": False, "est_in": -1, "brief_bytes": 0}])
    # A bool is an int in Python; a True that arrives where a token count
    # belongs must not silently meter 1.
    assert "non-negative integer" in _refused(
        [{"rel": "a.py", "brief_shed": False, "est_in": True, "brief_bytes": 0}])
    assert "non-empty path" in _refused(
        [{"rel": "  ", "brief_shed": False, "est_in": 10, "brief_bytes": 0}])
    assert "sequence of rows" in _refused({"rel": "a.py"})


def test_a_malformed_row_is_reported_and_never_reaches_a_digest():
    """The refusal must not destroy the attempt, and must not be swallowed."""
    with tempfile.TemporaryDirectory() as tmp:
        attempt, result = _real_attempt(tmp)
        broken = _project(attempt, result, [{"rel": "a.py", "brief_shed": True,
                                             "est_in": 5, "brief_bytes": 99}])
    assert broken.receipt is None
    assert "injected brief bytes" in broken.error


if __name__ == "__main__":  # probe entry: `python tests/test_shed_telemetry.py`
    for _name, _fn in sorted(dict(globals()).items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print("PASS", _name)
