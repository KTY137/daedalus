"""Do this repository's append-only journals survive the concurrency they have?

NOT a hypothetical. Many sessions share one checkout here, and five journals are
written by all of them at once: ``memory/events.local.jsonl``,
``runs/progress/events.jsonl``, ``memory/offload_metrics.local.jsonl``, the
kairos attempt archive, and the canary history.

Every one of them opened the file in buffered text mode and called ``write()``.
Whether that survives interleaving depends on whether the buffer flushes as ONE
operating-system write -- which, with small records and an 8192-byte default
buffer, it happens to. "Happens to" is the part worth testing: a long summary, a
stack trace, a file listing crosses the buffer and splits. And on Windows even a
single ``O_APPEND`` write is not enough, because the C runtime implements it as
seek-then-write, which is two operations.

The loss is SILENT, which is why it survived this long. Overwritten bytes leave
no malformed line, so every reader -- the projection worker's
``skipped_malformed`` counter, the health probe's ``unparsable lines`` -- reports
zero while a tenth of the journal is gone. Each test below therefore asserts the
absence of malformed lines FIRST and the record COUNT second: the count is the
assertion that actually fires, and it is the one no reader in this tree makes.

MEASURED 2026-09-02 on this machine, before the fix, against the writers as they
stood on main @54f09753:

    ``memory.append_event``, 6 processes x 20      116 and 119 of 120
    ``ProgressLog.append``, 6 processes x 20       115, 118 and 119 of 120
    ``metrics.record``, 6 processes x 20           111 of 120
    ``archive.record_attempt``, 4 processes x 15    54 of 60
    ``canary.append_history``, 4 processes x 8      50 of 64

Not one of those runs produced a single malformed line: every ``assert not
malformed`` below passed while the count assertion failed. That is the whole
finding. The size of the loss moves run to run because it is a race; that it
never announces itself does not.

Reproduce the primitive-level measurement with
``experiments/concurrency/probe_append_atomicity.py``.

These tests spawn real processes. They do not mock the filesystem, because the
thing under test IS the filesystem.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run_writers(script: str, per_worker_args, *, writers: int) -> None:
    """Run ``writers`` processes at once; every one must exit clean.

    A writer that dies is not evidence about atomicity, so this refuses loudly
    rather than letting a short journal be read as record loss.
    """

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, *per_worker_args(n)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for n in range(writers)
    ]
    for proc in procs:
        _out, err = proc.communicate(timeout=180)
        assert proc.returncode == 0, f"writer failed: {err}"


def _audit(journal: Path, key: str) -> tuple[int, list[int]]:
    """``(records that parse and carry ``key``, malformed line numbers)``."""

    raw = journal.read_bytes()
    parsed = 0
    malformed: list[int] = []
    for number, line in enumerate(raw.split(b"\n"), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            malformed.append(number)
            continue
        # A line that parses but is not a record is corruption too: two
        # interleaved writes can land as valid JSON of the wrong shape.
        if not isinstance(record, dict) or key not in record:
            malformed.append(number)
            continue
        parsed += 1
    return parsed, malformed


_MEMORY_WRITER = textwrap.dedent(
    """
    import pathlib, sys
    sys.path.insert(0, {repo!r})
    directory = pathlib.Path(sys.argv[1])
    import daedalus.memory as memory
    memory.MEMORY_DIR = directory
    memory.EVENTS_PATH = directory / "events.local.jsonl"
    memory.TODO_PATH = directory / "todos.local.md"
    worker, turns, padding = sys.argv[2], int(sys.argv[3]), "y" * int(sys.argv[4])
    for i in range(turns):
        memory.append_event(memory.MemoryEvent(
            kind="probe", source=worker,
            summary=f"{{worker}} event {{i}} {{padding}}"))
    """
)


def test_the_authoritative_journal_loses_nothing_under_concurrent_appends(
    tmp_path: Path,
):
    """``memory.append_event`` had the defect in the worst place.

    MEASURED 2026-09-02 before the fix: 116 and 119 of 120 records survived six
    concurrent appenders. This is the journal the projection index derives from
    and that the package docstring calls authoritative and append-only; losing
    records from it is not a degraded index, it is evidence that never existed.
    """

    directory = tmp_path / "memory"
    directory.mkdir()
    script = _MEMORY_WRITER.format(repo=str(REPO))
    _run_writers(
        script,
        lambda n: [str(directory), f"w{n}", "20", "400"],
        writers=6,
    )

    parsed, malformed = _audit(directory / "events.local.jsonl", "kind")
    assert not malformed, (
        f"{len(malformed)} corrupt line(s) in the authoritative journal at "
        f"{malformed[:10]}"
    )
    assert parsed == 6 * 20, (
        f"expected {6 * 20} events, found {parsed} -- the authoritative journal "
        f"dropped {6 * 20 - parsed} record(s) with no error and no malformed line"
    )


_PROGRESS_WRITER = textwrap.dedent(
    """
    import datetime, sys
    sys.path.insert(0, {repo!r})
    from daedalus.progress import ProgressEvent, ProgressLog
    log = ProgressLog(sys.argv[1])
    worker, turns = sys.argv[2], int(sys.argv[3])
    for i in range(turns):
        log.append(ProgressEvent(
            unit_id=f"{{worker}}-{{i}}", kind="queued", source="probe",
            ts=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            detail={{"pad": "z" * 400}}))
    """
)


def test_the_progress_log_loses_nothing_across_processes(tmp_path: Path):
    """A ``threading.Lock`` is not a cross-process lock, and looked like one.

    MEASURED 2026-09-02 before the fix: six processes appending 20 events each
    kept 115, 118 and 119 of 120 in three runs, with ``ProgressLog._lock`` held
    the whole time. ``runs/progress/events.jsonl`` is appended to by every loop
    run in this tree.

    The threading lock is not removed -- it still orders this process's own
    writers against ``read_all`` -- but it was never the guarantee its presence
    implied.
    """

    journal = tmp_path / "events.jsonl"
    script = _PROGRESS_WRITER.format(repo=str(REPO))
    _run_writers(script, lambda n: [str(journal), f"w{n}", "20"], writers=6)

    parsed, malformed = _audit(journal, "unit_id")
    assert not malformed, (
        f"{len(malformed)} corrupt line(s) in the progress log at {malformed[:10]}"
    )
    assert parsed == 6 * 20, (
        f"expected {6 * 20} events, found {parsed} -- a threading lock held "
        f"while {6 * 20 - parsed} record(s) were overwritten by another process"
    )


_METRICS_WRITER = textwrap.dedent(
    """
    import pathlib, sys
    sys.path.insert(0, {repo!r})
    import daedalus.metrics as metrics
    metrics.LOG = pathlib.Path(sys.argv[1])
    worker, turns, padding = sys.argv[2], int(sys.argv[3]), "m" * int(sys.argv[4])
    for i in range(turns):
        metrics.record(provider="ollama", action="offloaded",
                       owner=f"{{worker}}-{{i}}-{{padding}}", risk="low")
    """
)


def test_the_escalation_meter_loses_nothing_across_processes(tmp_path: Path):
    """``metrics`` is the SILENT-ESCALATION ALARM. A lossy alarm is worse than none.

    Its own module docstring says the failure it exists to catch is one that
    arrives "with no error and no alert" -- and its ``_WRITE_LOCK`` comment
    claims to stop parallel dispatch interleaving two rows, while being a
    ``threading.Lock`` that covers this process only. Every session on this
    machine writes this one file.

    MEASURED 2026-09-02 before the fix: 111 of 120 rows survived. The lost rows
    are not merely missing from a log: ``fallback_rate`` is computed FROM these
    rows, so dropping some of them moves the number the operator is shown. An
    alarm that silently loses its own evidence does not under-report by the
    amount it lost -- it reports a different rate.
    """

    journal = tmp_path / "offload_metrics.local.jsonl"
    script = _METRICS_WRITER.format(repo=str(REPO))
    _run_writers(script, lambda n: [str(journal), f"w{n}", "20", "600"], writers=6)

    parsed, malformed = _audit(journal, "action")
    assert not malformed, (
        f"{len(malformed)} corrupt row(s) in the escalation meter at "
        f"{malformed[:10]}"
    )
    assert parsed == 6 * 20, (
        f"expected {6 * 20} rows, found {parsed} -- the escalation alarm lost "
        f"{6 * 20 - parsed} of its own records silently"
    )


_ARCHIVE_WRITER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from daedalus.kairos.archive import Attempt, record_attempt
    path = sys.argv[1]
    worker, turns, padding = sys.argv[2], int(sys.argv[3]), "a" * int(sys.argv[4])
    for i in range(turns):
        record_attempt(path, Attempt(
            attempt_id=f"{{worker}}-{{i}}", outcome="tests_pass",
            summary="probe", meta={{"pad": padding}}))
    """
)


def test_the_attempt_archive_loses_nothing_across_processes(tmp_path: Path):
    """The kairos archive is a PERSISTENT CROSS-RUN store, so sharing it is normal.

    ``load_attempts`` feeds the next generation, so two runs pointed at one
    ``--archive`` path is a configuration rather than an accident. The
    function's own docstring names the exact cost of a lost record: later
    generations are left "with no way to tell that apart from 'there was
    nothing to say'". A silent loss produces precisely that.

    MEASURED 2026-09-02 before the fix: 54 of 60 records survived four writers.
    """

    journal = tmp_path / "attempts.jsonl"
    script = _ARCHIVE_WRITER.format(repo=str(REPO))
    _run_writers(script, lambda n: [str(journal), f"w{n}", "15", "3000"], writers=4)

    parsed, malformed = _audit(journal, "attempt_id")
    assert not malformed, (
        f"{len(malformed)} corrupt line(s) in the attempt archive at "
        f"{malformed[:10]}"
    )
    assert parsed == 4 * 15, (
        f"expected {4 * 15} attempts, found {parsed} -- the cross-run archive "
        f"dropped {4 * 15 - parsed} record(s) that later generations will read "
        f"as 'there was nothing to say'"
    )


_CANARY_WRITER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {repo!r})
    from daedalus.council.canary import CanaryRun, ProbeResult, append_history
    path = sys.argv[1]
    worker, runs, padding = sys.argv[2], int(sys.argv[3]), "c" * int(sys.argv[4])
    for i in range(runs):
        results = tuple(
            ProbeResult(vendor="ollama", model="qwen", endpoint="local",
                        probe=f"p{{k}}", severity="liveness", status="ok",
                        expected=padding)
            for k in range(2)
        )
        append_history(CanaryRun(run_id=f"{{worker}}-{{i}}", ts="2026-09-02T00:00:00Z",
                                 results=results), path)
    """
)


def test_the_canary_history_keeps_every_probe_result(tmp_path: Path):
    """``append_history`` writes a WHOLE RUN in one call, so a split loses a batch.

    ``daedalus canary`` is operator-invoked, so two runs pointed at one history
    file is a configuration rather than an accident, and the module calls this
    file "dumb, append-only". A batch write is the case where a buffered append
    is most exposed: the whole run crosses the buffer at once.

    MEASURED 2026-09-02 before the fix: 50 of 64 results survived four writers
    -- the largest proportional loss of the five, which is what batching does
    when the batch is not atomic.
    """

    journal = tmp_path / "history.jsonl"
    script = _CANARY_WRITER.format(repo=str(REPO))
    _run_writers(script, lambda n: [str(journal), f"w{n}", "8", "5000"], writers=4)

    parsed, malformed = _audit(journal, "run_id")
    assert not malformed, (
        f"{len(malformed)} corrupt line(s) in the canary history at "
        f"{malformed[:10]}"
    )
    assert parsed == 4 * 8 * 2, (
        f"expected {4 * 8 * 2} probe results, found {parsed} -- the history "
        f"lost {4 * 8 * 2 - parsed} result(s) with no error and no malformed line"
    )


def test_no_record_is_ever_split_across_a_line_boundary(tmp_path: Path):
    """Every line is exactly one record: no line holds two, none holds half.

    The count assertions above catch a record that vanished. This catches the
    other half of the same defect: two appends that landed on top of each other
    and produced one line carrying two record identities -- which a lenient
    reader can still parse, and therefore never counts as malformed.

    The contention here is deliberately higher than the counting tests (six
    writers, 20 KB records). MEASURED 2026-09-02 at the counting tests' load it
    reproduced in only 1 of 5 pre-fix runs, which is a coin flip rather than a
    guard; at this load it reproduced in 5 of 5. A flaky red proves nothing the
    run it happens to pass.
    """

    journal = tmp_path / "attempts.jsonl"
    script = _ARCHIVE_WRITER.format(repo=str(REPO))
    _run_writers(script, lambda n: [str(journal), f"w{n}", "15", "20000"], writers=6)

    raw = journal.read_bytes()
    assert raw.endswith(b"\n"), "the journal does not end on a record boundary"
    for number, line in enumerate(raw.rstrip(b"\n").split(b"\n"), start=1):
        text = line.decode("utf-8", errors="replace")
        found = text.count('"attempt_id"')
        assert found == 1, (
            f"line {number} holds {found} attempt ids, expected exactly 1: "
            + ("two appends landed on one line" if found > 1 else
               "an append overwrote another and left a record with no identity")
        )
