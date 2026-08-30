# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from daedalus.spine import docrefs
from daedalus.spine.docrefs import Reference, resolve_reference


ROOT = Path(__file__).resolve().parents[1]


def _resolve(raw: str):
    return resolve_reference(
        Reference(doc_path="docs/example.md", line=1, raw=raw),
        ROOT,
    )


def test_git_core_autocrlf_is_not_reinterpreted_as_core_py():
    result = _resolve("core.autocrlf")
    assert result.state == "skipped"
    assert "known non-module dotted name" in result.why


def test_operation_status_code_is_not_reinterpreted_as_status_py():
    result = _resolve("status.code")
    assert result.state == "skipped"
    assert "known non-module dotted name" in result.why


def test_the_actual_stale_vendor_constant_remains_actionable():
    result = _resolve("vendors._LOCAL_HOSTS")
    assert result.state == "broken"
    assert result.module_path == "daedalus/council/vendors.py"


def test_a_nested_checkout_does_not_make_every_module_ambiguous(tmp_path):
    """The resolver's absent-module case, triggered wholesale by a copy.

    ``_suffix_index`` treats an ambiguous suffix as unresolvable, and says so:
    two files named ``index.py`` mean it cannot tell which one a sentence is
    about. That is the right call per suffix and a catastrophe per tree -- a
    nested checkout duplicates EVERY module at once, so every suffix goes
    ambiguous and the checker reports "no document mentions this" about modules
    that are documented.

    MEASURED 2026-08-26 on the live repository: a git worktree under
    ``.claude/worktrees/`` produced 3622 ambiguous suffixes, 3242 of them
    ambiguous only because of that copy. The name-based exclusion list held
    ``.worktrees`` and the directory was ``.claude/worktrees``; a list of names
    is always one name behind, so the rule here is structural instead.
    """
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "widget.py").write_text("X = 1" + chr(10), encoding="utf-8")
    nested = tmp_path / "nested"
    (nested / "pkg").mkdir(parents=True)
    # A worktree marks itself with a `.git` FILE; a clone with a directory.
    (nested / ".git").write_text("gitdir: /elsewhere" + chr(10), encoding="utf-8")
    (nested / "pkg" / "widget.py").write_text("X = 1" + chr(10), encoding="utf-8")

    index = docrefs._suffix_index(tmp_path)

    assert index["widget.py"] == ("pkg/widget.py",), index["widget.py"]
    assert not any(
        path.startswith("nested/") for paths in index.values() for path in paths
    )
