# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""A workflow that calls a file nobody kept is a test suite that does not run.

WHAT HAPPENED. `tools/iron_plan_guard.py` was deleted on 2026-08-22 by the
unification commit, executing the owner decision recorded in the plan's
retirement note -- which names CI explicitly. The deletion landed; the 170
workflow steps that invoked it did not. For three days every one of those 94
jobs was scheduled to fail on a missing file, and in 26 of them that step sat
above `pytest`.

Nobody noticed, and the reason is worth keeping: the runs were failing anyway,
for an unrelated billing reason, so a red badge carried no information. A signal
that is already saturated cannot report a new fault. This file is the part that
does not depend on the badge -- it answers "does CI reference anything that is
gone?" locally, in a second, whether or not a runner ever starts.

WHAT IT DOES NOT CLAIM. Passing here does not mean CI works. It means CI does
not name a file that is missing. Those are different sentences, and conflating
them is how the original rot survived.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:                                    # pragma: no cover
    yaml = None

# PyYAML is an optional extra, and two of the checks below do not need it at
# all: they are regex over text. Gating the WHOLE module behind
# ``importorskip`` made the anti-rot suite evaporate into a green skip on any
# environment without the extra -- which is this file's own subject matter,
# committed in this file. Only the tests that genuinely parse YAML skip.
needs_yaml = pytest.mark.skipif(yaml is None, reason="PyYAML is an optional extra")

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"
WORKFLOWS = GITHUB / "workflows"

# A repo-rooted script path, ANYWHERE in the workflow text.
#
# This started as a matcher for the invocation -- `python3? (-flag )* <path>` --
# and an adversarial sweep put 10 of 22 mutations straight through it: options
# that take a value (`python -X utf8 ...`), a folded `>-` scalar with the path
# on its own continuation line (a layout `gate1-ignition.yml` ALREADY uses), a
# backslash continuation, a quoted path, `uv run`, an interpreter supplied by
# `${{ }}`. Every one of those is a real way to run a script, and enumerating
# invocation shapes is a losing game: the next shape is always unlisted.
#
# So the question changed. Not "is this script invoked?" but "does this workflow
# NAME a repo-rooted script that does not exist?" -- shape-independent, and not
# evadable by how the command is written. It over-matches a path inside a
# comment, which is the safe direction: a commented-out step naming a deleted
# file is still rot, and somebody will uncomment it one day.
SCRIPT_TOKEN = re.compile(
    # The trailing guard rejects BOTH a longer word and a further extension.
    # Without the second half this matched `..._legacy.py` inside
    # `daedalus/kairos/_gated_writes_legacy.py.src` -- a retained package
    # resource that exists, in a workflow that asserts the `.py` module must
    # NOT be importable. The matcher accused a file of being missing that was
    # never supposed to be there.
    r"(?<![\w./\-])((?:scripts|tools|eval|daedalus)/[\w./\-]+\.[Pp][Yy])(?![\w])(?!\.\w)"
)
# `-m daedalus.something`, whatever launches it.
MODULE_TOKEN = re.compile(r"-m\s+(daedalus[\w.]*)")


def _workflow_files() -> list:
    if not WORKFLOWS.is_dir():
        return []
    return sorted(p for p in WORKFLOWS.iterdir() if p.suffix in (".yml", ".yaml"))


def _module_exists(dotted: str) -> bool:
    rel = dotted.replace(".", "/")
    return (ROOT / f"{rel}.py").exists() or (ROOT / rel / "__main__.py").exists()


@pytest.fixture(scope="module")
def workflows():
    files = _workflow_files()
    if not files:
        pytest.skip("no .github/workflows in this checkout")
    return files


@needs_yaml
def test_every_workflow_parses(workflows):
    """An unparsable workflow silently never runs; that must not be silent.

    This proves YAML well-formedness, NOT that GitHub accepts the file. PyYAML
    resolves a bare ``on:`` key to the boolean ``True`` (YAML 1.1), so a
    workflow can parse here and still be rejected by Actions.
    """
    broken = []
    for path in workflows:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            broken.append((path.name, str(exc).splitlines()[0]))
    assert broken == [], broken


def test_no_workflow_names_a_script_that_is_gone(workflows):
    """The `iron_plan_guard` regression, generalised past invocation shape."""
    dead = []
    for path in workflows:
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in sorted(set(SCRIPT_TOKEN.findall(text))):
            if not (ROOT / target).exists():
                dead.append(f"{path.name}: {target}")
    assert dead == [], (
        "CI names files that do not exist. Either restore them or remove the "
        "step -- a step that cannot run is not a check:\n  "
        + "\n  ".join(sorted(set(dead)))
    )


def test_no_workflow_names_a_module_that_is_gone(workflows):
    """Same rot, one import system further in."""
    dead = []
    for path in workflows:
        text = path.read_text(encoding="utf-8", errors="replace")
        for target in sorted(set(MODULE_TOKEN.findall(text))):
            if not _module_exists(target):
                dead.append(f"{path.name}: python -m {target}")
    assert dead == [], sorted(set(dead))


@needs_yaml
def test_no_job_was_left_without_steps(workflows):
    """Deleting a dead step must not empty a job. A job with no steps is a
    green tick that proves nothing, which is worse than the red it replaced."""
    empty = []
    for path in workflows:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, spec in (doc.get("jobs") or {}).items():
            if not isinstance(spec, dict):
                continue
            if "uses" in spec:            # a reusable-workflow call has no steps
                continue
            if not (spec.get("steps") or []):
                empty.append(f"{path.name}:{name}")
    assert empty == [], empty


def test_the_retired_guard_is_not_referenced_anywhere_under_github():
    """Named explicitly, because this one is a recorded owner decision: the
    plan's revision-7 retirement note lists CI among the surfaces the mechanical
    guard was withdrawn from.

    Scoped to all of ``.github/``, not just ``workflows/``. The earlier version
    said "anywhere" and looked only at workflows -- while ``.github/CODEOWNERS``
    still named the guard, and six other dead paths besides. A test whose name
    overstates its fixture is a guard with a blind spot shaped like its own
    title.
    """
    if not GITHUB.is_dir():
        pytest.skip("no .github in this checkout")
    offenders = []
    for path in sorted(GITHUB.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:                                # pragma: no cover
            continue
        if "iron_plan_guard" in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == [], (
        "the mechanical guard is retired (plan revision 7); these still name "
        f"it: {offenders}"
    )
