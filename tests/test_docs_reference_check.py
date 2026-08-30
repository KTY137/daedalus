# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The docs checker has to survive the same rot it exists to catch.

Three things are pinned here, and each one failed somewhere in this repository
before it was pinned:

1. The current pages actually resolve. This is the gate. A package move that
   leaves `eval/harness.py` in a live page turns this red in the same beat as
   the move, instead of three sessions later when somebody follows the path.
2. History is never blocking. `docs/archive/`, `docs/inventory/` and the dated
   findings are *supposed* to name a tree that is gone; a checker that "fixed"
   them would be deleting evidence.
3. It can say it did not measure. Instruments in this repository have failed
   toward LESS coverage and printed a clean result four separate times
   (docs/inventory/2026-08-24). An empty census must be a third outcome, not a
   pass.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "docs_reference_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("docs_reference_check", CHECKER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load()


def test_current_pages_name_only_files_that_exist(checker):
    result = checker.scan()
    assert result["scanned"] > 0, "empty census -- see the could-not-measure test"
    current = [f for f in result["findings"] if not f["history"]]
    assert current == [], (
        "a current page names a path that does not exist. Repair the page, or -- "
        "if the mention is deliberate -- add it to ALLOWED with the reason:\n"
        + "\n".join(f"  {f['file']}: {f['target']}" for f in current)
    )


def test_history_is_reported_but_never_blocking(checker):
    result = checker.scan()
    history = [f for f in result["findings"] if f["history"]]
    assert history, (
        "no dead references found in any history page. That is not plausible for "
        "a tree with 158 archived documents -- the classifier has probably stopped "
        "matching, which would also mean it is silently blocking on evidence."
    )
    assert checker.main(["--json"]) == 0


def test_history_classification_covers_kinds_not_only_directories(checker):
    # The plan's authority table calls handoffs, ADRs and inventories
    # history/backlog. Several of them sit at the top level of docs/.
    for rel in (
        "docs/archive/ERA3_PLAN.md",
        "docs/HANDOFF.md",
        "docs/HANDOFF_2026-07-30_NIGHT.md",
        "docs/AMENDMENT_PROPOSAL_004_BYTE_EXACT_RESOURCE_EOL.md",
        "docs/GATE0_OWNER_DECISIONS_20260817.md",
        "docs/adrs/011-event-spine.md",
        "docs/design/GUI_LANE_PLAN.md",
    ):
        assert checker._is_history(rel), rel
    for rel in ("README.md", "docs/STATUS.md", "docs/README.md",
                "docs/architecture-narrative.md", "docs/wiki/feature-backlog.md"):
        assert not checker._is_history(rel), rel


def test_a_date_shaped_name_is_not_enough_to_stop_being_checked(checker):
    r"""The classifier decides whether a page is REPAIRED or merely counted, so
    an over-broad pattern silently removes pages from the gate. The first
    version of this checker matched a bare `\d{8}`, which swallowed
    `RFC12345678_current_contract.md`; the fix anchors on `20xx`. These are the
    cases that must keep being checked."""
    for rel in (
        "docs/RFC12345678_current_contract.md",   # eight digits, not a date
        "docs/schema-1234-56-78.md",              # date-shaped, not a date
        "docs/port-8080-8443-notes.md",
        "docs/v2-2-0-contract.md",
    ):
        assert not checker._is_history(rel), (
            f"{rel} was classified as history; a page that is history is only "
            "counted, never repaired, so this is coverage lost in silence"
        )
    # ...and the real dated evidence must still classify as history, or the
    # tightening has traded one silent failure for a noisy one.
    for rel in (
        "docs/GATE0_OWNER_DECISIONS_20260817.md",
        "docs/HANDOFF_2026-07-30_NIGHT.md",
        "docs/inventory/2026-08-24/DENY_FLOOR_CORPUS.md",
    ):
        assert checker._is_history(rel), rel


def test_could_not_measure_is_a_distinct_outcome(checker, monkeypatch, capsys):
    """Four ways to measure nothing, each of which must exit 2.

    The first version of this test monkeypatched the census to `[]` and
    asserted that `main` branches on an empty list. It never exercised a
    condition that PRODUCES one -- so it proved the branch existed, not that
    the tool reaches it. An adversarial review then found two live paths to
    exit 0 or 1 while having read nothing. Those are cases 2-4."""
    # 1. nothing tracked
    monkeypatch.setattr(checker, "_tracked_markdown", lambda: [])
    assert checker.main([]) == 2, "an empty census must not exit 0"
    assert "COULD NOT MEASURE" in capsys.readouterr().err
    assert checker.main(["--json"]) == 2

    # 2. git itself missing -- used to raise FileNotFoundError, which exits 1,
    #    the SAME code as "dead references found".
    def no_git(*_a, **_k):
        raise FileNotFoundError(2, "The system cannot find the file specified", "git")

    monkeypatch.setattr(checker.subprocess, "run", no_git)
    assert checker.main([]) == 2, "a missing git must not look like a finding"
    monkeypatch.undo()

    # 3. files listed, none readable -- used to report "scanned N, clean", exit 0.
    monkeypatch.setattr(checker, "_tracked_markdown",
                        lambda: ["docs/gone-a.md", "docs/gone-b.md"])
    assert checker.main([]) == 2, "a census that read nothing must not exit 0"
    err = capsys.readouterr().err
    assert "COULD NOT MEASURE" in err and "none" in err

    # 4. partial read -- one real file, one that cannot be opened.
    monkeypatch.setattr(checker, "_tracked_markdown",
                        lambda: ["docs/STATUS.md", "docs/does-not-exist.md"])
    assert checker.main([]) == 2, "a partial census must not report clean"
    assert "COULD NOT MEASURE" in capsys.readouterr().err


def test_scanned_counts_reads_not_listings(checker, monkeypatch):
    """`scanned` was `len(files)` from the git listing. It has to be the number
    of files actually opened, or the headline number lies in the one direction
    that matters."""
    monkeypatch.setattr(checker, "_tracked_markdown",
                        lambda: ["docs/STATUS.md", "docs/does-not-exist.md"])
    result = checker.scan()
    assert result["listed"] == 2
    assert result["scanned"] == 1
    assert result["unreadable"] == ["docs/does-not-exist.md"]


def test_allowlist_entries_still_describe_absent_paths(checker):
    """An allowlist that outlives its reason is how a checker stops checking."""
    stale = [
        (rel, target)
        for (rel, target) in checker.ALLOWED
        if (ROOT / target).exists()
    ]
    assert stale == [], (
        "these paths exist now, so their allowlist entries mask nothing and "
        "should be deleted: " + repr(stale)
    )


def test_allowlist_entries_name_a_page_that_exists(checker):
    missing = [rel for (rel, _t) in checker.ALLOWED if not (ROOT / rel).exists()]
    assert missing == [], f"allowlist points at pages that are gone: {missing}"


def test_the_constitution_is_never_blocking(checker):
    """AGENTS.md forbids an ordinary session from editing the plan or its chain.
    A checker that can demand such an edit is a checker that will eventually be
    satisfied by someone making it -- so authority pages are reported under
    their own heading and never counted as current."""
    assert checker._is_authority("docs/IKARUS_ARIADNE_MASTER_PLAN.md")
    assert checker._is_authority("AGENTS.md")
    assert not checker._is_authority("docs/STATUS.md")
    # authority implies never-blocking
    for rel in checker.AUTHORITY:
        assert checker._is_history(rel), rel


def test_authority_findings_do_not_block_and_are_reported(checker, monkeypatch, capsys):
    """Synthesise one authority finding and prove the exit code stays 0 while
    the finding is still printed. An exemption nobody can see is a deletion."""
    real = checker.scan

    def fake():
        out = real()
        out["findings"] = out["findings"] + [{
            "file": "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
            "kind": "mention", "target": "tools/gone.py",
            "history": True, "authority": True,
        }]
        return out

    monkeypatch.setattr(checker, "scan", fake)
    assert checker.main([]) == 0, "an authority finding must not block"
    printed = capsys.readouterr().out
    assert "AUTHORITY" in printed and "tools/gone.py" in printed
