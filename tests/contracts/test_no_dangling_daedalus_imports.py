"""Every first-party import must name a module that exists.

WHY THIS EXISTS. The import census in ``test_import_scc_hierarchy.py`` resolves
each candidate against the set of tracked modules and silently drops the ones it
cannot resolve -- ``next((...), None)``. That is correct for what it measures, a
graph of real edges, and it means a DANGLING import produces no edge, no census
movement and no failure. An independent reviewer named this gap on 2026-09-02
and it went unclosed for one day.

It cost the next packet. G1-FLAT-06 deleted ``daedalus/token_policy.py`` after a
regex audit of its importers reported none outside tests. Two production modules
imported it as ``from ..token_policy import ...`` -- a form the regex could not
match, because ``from \\.token_policy`` does not match ``from ..token_policy``.
``daedalus/kairos/orchestrate.py`` and ``daedalus/providers/claude_cli.py`` both
went to a module that no longer existed, and nothing failed at collection time
because neither is imported by the fast suites.

An audit written as a regex over import TEXT will keep finding four of the five
spellings. This one resolves the same way the interpreter does.

WHAT IT CHECKS. For every tracked ``.py`` file in the repository -- package,
tests, tools, experiments -- each ``import``/``from ... import`` naming
``daedalus`` is resolved to an absolute dotted path, relative levels included,
and must correspond to a tracked module, a tracked package, or an attribute of
one. The last case is why a name is accepted when its PARENT resolves: ``from
daedalus.foundation.projects import ProjectRowNotFound`` names a class, not a
module, and this contract is about modules.

WHAT IT DOES NOT CHECK. Whether the imported ATTRIBUTE exists -- that is what
importing the module proves, and the suite does that everywhere. Nor does it
look inside strings: ``tests/test_project_row_rewrite.py`` executes subprocess
source held in a string literal, and no import walker sees it. That gap is real
and is closed by running the test, not by reading it.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tracked_python_files() -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=60,
    )
    return tuple(
        sorted(
            path
            for path in (
                raw.decode("utf-8") for raw in completed.stdout.split(b"\0") if raw
            )
            if path.endswith(".py") and not path.startswith(".claude/worktrees/")
        )
    )


def _module_name(relative: str) -> str:
    parts = relative[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _known_modules(files: tuple[str, ...]) -> frozenset[str]:
    """Every importable dotted name, including implicit parent packages."""
    names: set[str] = set()
    for relative in files:
        if not relative.startswith("daedalus/"):
            continue
        dotted = _module_name(relative)
        names.add(dotted)
        parts = dotted.split(".")
        for depth in range(1, len(parts)):
            names.add(".".join(parts[:depth]))
    return frozenset(names)


def _imported_targets(relative: str, source: str) -> list[tuple[int, str]]:
    """(lineno, absolute dotted target) for every first-party import."""
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError:
        return []
    package: str | None = None
    if relative.startswith("daedalus/"):
        dotted = _module_name(relative)
        package = dotted if relative.endswith("/__init__.py") else dotted.rpartition(".")[0]
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if package is None:
                    continue
                try:
                    base = importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), package
                    )
                except (ImportError, ValueError):
                    continue
            else:
                base = node.module or ""
            if not base.startswith("daedalus"):
                continue
            # The module half must exist. Each imported NAME may be a submodule
            # or an attribute, so a name is only required to resolve when its
            # own dotted form is treated as a module by another importer -- and
            # that case is covered by that importer's own row.
            candidates = [base]
        else:
            continue
        for candidate in candidates:
            if candidate == "daedalus" or candidate.startswith("daedalus."):
                out.append((node.lineno, candidate))
    return out


def test_no_tracked_file_imports_a_daedalus_module_that_does_not_exist() -> None:
    files = _tracked_python_files()
    known = _known_modules(files)
    dangling: list[str] = []
    checked = 0
    for relative in files:
        source = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
        # The cheap skip applies ONLY outside the package. Inside it, imports are
        # relative and the word "daedalus" need not appear in the file at all --
        # `from ..token_policy import trim_paths` contains neither the package
        # name nor a clue that it is first-party. The first draft skipped on that
        # substring and was therefore blind to exactly the import form that
        # motivated this contract: it passed under mutation, twice, before the
        # skip was identified as the reason.
        if not relative.startswith("daedalus/") and "daedalus" not in source:
            continue
        for lineno, target in _imported_targets(relative, source):
            checked += 1
            # NO parent fallback. The first draft accepted a target whose
            # PARENT resolved, reasoning that `from daedalus.x import y` might
            # name an attribute. It does -- but this walker already records only
            # the module half, so the parent rule bought nothing and cost
            # everything: the parent of any top-level module is `daedalus`,
            # which always resolves, so every dangling flat import was waved
            # through. Caught by mutation-testing the contract against the exact
            # import it was written for, which passed when it had to fail.
            if target in known:
                continue
            dangling.append(f"{relative}:{lineno}: imports {target}, which no tracked module provides")
    assert dangling == [], "\n".join(dangling)
    assert checked >= 500, f"only {checked} first-party imports seen; the walker drifted"


def test_the_walker_resolves_relative_levels_the_way_the_interpreter_does() -> None:
    # The exact spelling the regex audit missed: two dots, module named directly.
    two_dots = _imported_targets(
        "daedalus/kairos/orchestrate.py", "from ..token_policy import trim_paths\n"
    )
    assert two_dots == [(1, "daedalus.token_policy")]

    one_dot = _imported_targets(
        "daedalus/runbook.py", "from .schemas import AgentTask\n"
    )
    assert one_dot == [(1, "daedalus.schemas")]

    bare = _imported_targets("daedalus/core.py", "from . import router\n")
    assert bare == [(1, "daedalus")]

    absolute = _imported_targets("tests/test_x.py", "import daedalus.spine.ledger\n")
    assert absolute == [(1, "daedalus.spine.ledger")]

    foreign = _imported_targets("tests/test_x.py", "import json\nfrom pathlib import Path\n")
    assert foreign == []


def test_a_deleted_module_is_detected_as_dangling() -> None:
    files = _tracked_python_files()
    known = _known_modules(files)
    assert "daedalus.token_policy" not in known, (
        "this assertion pins the module whose deletion motivated the contract; "
        "if it comes back, rewrite the docstring rather than the assertion"
    )
    assert "daedalus.runtimes.providers.token_policy" in known
    assert "daedalus.runtimes.providers" in known, "implicit parent packages must count"
