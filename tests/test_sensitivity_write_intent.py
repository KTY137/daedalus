"""Owner decision D6: protected artifacts are matched on WRITE INTENT.

The rule this file pins is narrow and has two halves, and the halves fail in
opposite directions, so both need their own tests:

* a read-only payload that merely NAMES a protected artifact must not be
  refused -- eight measured misfires, and the workaround agents invented for
  them (encoding paths so evidence would slip past the matcher) is an
  Invariant-7 anti-provenance effect;
* a write whose target IS a protected artifact must be refused however the
  caller spelled it -- relative, ``..``-laden, mis-cased, back-slashed, behind
  a symlink or junction, or under an 8.3 alias.

DYNAMIC RANGE. Every "blocked" assertion below is paired with an unprotected
sibling that must NOT be blocked under the same policy, and the policy used for
the bypass cases deliberately carries NO ``write_allow`` confinement. Without
that, ``path_write_blocked`` would refuse every path outside ``docs/`` on its
own and each bypass test would pass with the matcher deleted -- a test whose
subject is not the thing it claims to measure.
"""
from __future__ import annotations

import os
import sys

import pytest

from daedalus.sensitivity import (
    WriteIntentError,
    load_policy,
    mentions_protected_path,
    path_write_blocked,
    resolve_write_target,
    write_intent_blocked,
)


PROTECTED_REL = "implementation/sensitivity.py"
PROTECTED_SUBTREE = "spine/"
PLAN_REL = "docs/IKARUS_ARIADNE_MASTER_PLAN.md"

# No ``write_allow``: the ONLY thing that can refuse here is the protected list,
# so a passing bypass test proves the matcher and not the confinement.
UNCONFINED = {
    "policy": {
        "high_risk_paths": [PROTECTED_REL, PROTECTED_SUBTREE, PLAN_REL],
        "default_deny": True,
    }
}


@pytest.fixture()
def policy():
    return load_policy(UNCONFINED)


@pytest.fixture()
def tree(tmp_path):
    """A miniature repository carrying one protected file and one sibling.

    ``implementation`` is deliberately longer than eight characters so Windows
    mints an 8.3 alias for it; ``daedalus`` is exactly eight and would not.
    """
    (tmp_path / "implementation").mkdir()
    (tmp_path / "implementation" / "sensitivity.py").write_text("# protected\n")
    (tmp_path / "implementation" / "router.py").write_text("# ordinary\n")
    (tmp_path / "spine").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / PLAN_REL.split("/")[-1]).write_text("# plan\n")
    (tmp_path / "docs" / "notes.md").write_text("# ordinary\n")
    return tmp_path


# --------------------------------------------------------------------------
# FALSE POSITIVES -- the eight measured misfires
# --------------------------------------------------------------------------

READ_ONLY_COMMANDS = [
    "git log --oneline -- docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "git diff HEAD~1 -- docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "cat docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "grep -n Invariant docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "python -c 'print(open(\"docs/IKARUS_ARIADNE_MASTER_PLAN.md\").read())'",
]


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_the_retired_substring_rule_would_have_fired_on_these(command, policy):
    """Dynamic range for the two tests below.

    If this ever returns empty, the false-positive tests stop measuring
    anything: they would pass because nothing matched, not because intent
    matching worked.
    """
    assert mentions_protected_path(command, policy), (
        "the payload no longer names a protected artifact, so the "
        "false-positive tests below have lost their subject"
    )


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_read_only_command_naming_the_plan_is_not_blocked(command, policy, tree):
    assert (
        write_intent_blocked(command, op="read", policy=policy, repo_root=str(tree))
        is None
    )


@pytest.mark.parametrize("command", READ_ONLY_COMMANDS)
def test_command_line_is_refused_as_a_write_target(command, policy, tree):
    """A command string is not a verdict in either direction.

    The matcher must not answer "blocked" here -- that is the defect -- and it
    must not answer "allowed" either, because that would silently permit a real
    write whose target the boundary failed to resolve. It raises.
    """
    with pytest.raises(WriteIntentError):
        write_intent_blocked(command, op="write", policy=policy, repo_root=str(tree))


def test_read_ops_never_consult_the_protected_list(policy, tree):
    target = tree / "implementation" / "sensitivity.py"
    assert write_intent_blocked(target, op="read", policy=policy, repo_root=str(tree)) is None
    assert write_intent_blocked(target, op="diff", policy=policy, repo_root=str(tree)) is None
    assert write_intent_blocked(target, op="hash", policy=policy, repo_root=str(tree)) is None


# --------------------------------------------------------------------------
# BYPASSES -- one spelling per row, all naming the same protected file
# --------------------------------------------------------------------------

def _blocked(target, policy, tree, op="write"):
    return write_intent_blocked(target, op=op, policy=policy, repo_root=str(tree))


def test_plain_relative_path_to_a_protected_file_is_blocked(policy, tree):
    assert _blocked("implementation/sensitivity.py", policy, tree) is not None


def test_dot_dot_traversal_to_a_protected_file_is_blocked(policy, tree):
    assert _blocked("docs/../implementation/sensitivity.py", policy, tree) is not None
    assert _blocked("implementation/../implementation/./sensitivity.py", policy, tree) is not None


def test_upper_case_spelling_of_a_protected_file_is_blocked(policy, tree):
    assert _blocked("IMPLEMENTATION/SENSITIVITY.PY", policy, tree) is not None


def test_backslash_spelling_of_a_protected_file_is_blocked(policy, tree):
    assert _blocked("implementation\\sensitivity.py", policy, tree) is not None


def test_absolute_path_to_a_protected_file_is_blocked(policy, tree):
    assert _blocked(str(tree / "implementation" / "sensitivity.py"), policy, tree) is not None


def test_new_file_under_a_protected_subtree_is_blocked(policy, tree):
    """The target does not exist yet -- the create case, which is the common one."""
    assert _blocked("spine/brand_new.py", policy, tree, op="create") is not None
    assert _blocked("spine/nested/deeper/brand_new.py", policy, tree, op="create") is not None


def test_unlink_and_rename_of_a_protected_file_are_blocked(policy, tree):
    assert _blocked("implementation/sensitivity.py", policy, tree, op="unlink") is not None
    assert _blocked("implementation/sensitivity.py", policy, tree, op="rename_from") is not None


@pytest.mark.skipif(os.name != "nt", reason="8.3 aliases are a Windows filesystem feature")
def test_eight_dot_three_short_name_is_blocked(policy, tree):
    import ctypes
    from ctypes import wintypes

    fn = ctypes.windll.kernel32.GetShortPathNameW
    fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    fn.restype = wintypes.DWORD
    buf = ctypes.create_unicode_buffer(1024)
    long_path = str(tree / "implementation" / "sensitivity.py")
    used = fn(long_path, buf, len(buf))
    short = buf.value if 0 < used < len(buf) else ""
    if not short or "~" not in short:
        pytest.skip("this volume does not mint 8.3 aliases (NtfsDisable8dot3NameCreation)")
    assert _blocked(short, policy, tree) is not None


def test_symlinked_directory_into_the_protected_tree_is_blocked(policy, tree):
    link = tree / "alias"
    try:
        link.symlink_to(tree / "implementation", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no privilege to create a symlink on this host")
    assert _blocked("alias/sensitivity.py", policy, tree) is not None


def test_symlink_leaf_pointing_at_a_protected_file_is_blocked(policy, tree):
    link = tree / "docs" / "innocent.md"
    try:
        link.symlink_to(tree / "implementation" / "sensitivity.py")
    except (OSError, NotImplementedError):
        pytest.skip("no privilege to create a symlink on this host")
    # The named path is unprotected and even sits inside docs/. Only following
    # the leaf link reveals the real destination.
    assert _blocked("docs/innocent.md", policy, tree) is not None


# --------------------------------------------------------------------------
# DYNAMIC RANGE -- the matcher must still let ordinary writes through
# --------------------------------------------------------------------------

def test_unprotected_sibling_is_not_blocked(policy, tree):
    assert _blocked("implementation/router.py", policy, tree) is None
    assert _blocked("docs/notes.md", policy, tree) is None
    assert _blocked("docs/brand_new_note.md", policy, tree, op="create") is None


def test_a_path_merely_containing_the_protected_name_is_not_a_grant(policy, tree):
    """Over-matching is acceptable; under-matching is not.

    ``notes/implementation/sensitivity.py.bak`` is not the protected artifact,
    but the surviving substring rule still refuses it. That direction is the
    safe one and this test records it as intended, not accidental.
    """
    assert _blocked("notes/implementation/sensitivity.py.bak", policy, tree) is not None


# --------------------------------------------------------------------------
# CONTRACT
# --------------------------------------------------------------------------

def test_unknown_op_raises_rather_than_guessing(policy, tree):
    with pytest.raises(WriteIntentError):
        write_intent_blocked("docs/notes.md", op="maybe", policy=policy, repo_root=str(tree))


def test_empty_target_is_refused(policy, tree):
    with pytest.raises(WriteIntentError):
        write_intent_blocked("   ", op="write", policy=policy, repo_root=str(tree))


def test_resolution_collapses_dots_and_returns_absolute_paths(tree):
    resolved = resolve_write_target("docs/../implementation/sensitivity.py", repo_root=str(tree))
    assert resolved
    for item in resolved:
        assert os.path.isabs(item)
        assert ".." not in item.replace("\\", "/").split("/")


def test_the_substring_rule_can_never_grant(policy, tree):
    """Whatever the anchored rule decides, the historical predicate still runs.

    Pinning the composition rather than the outcome: if a future edit replaces
    the OR with an anchored-only match, a path the old rule refused would become
    writable, which is the one direction D6 does not authorise.
    """
    anchored = "/implementation/sensitivity.py"
    assert path_write_blocked(anchored, policy) is True
    assert _blocked("implementation/sensitivity.py", policy, tree) is not None


def test_report_only_helper_is_not_wired_into_any_gate():
    """``mentions_protected_path`` must stay a reporting helper.

    Its whole purpose is to let a receipt say "this payload named the plan"
    without that observation becoming a denial. If any enforcement module starts
    calling it, D6's defect returns under a new name.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in (root / "daedalus").rglob("*.py"):
        if path.name == "sensitivity.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "mentions_protected_path" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], (
        "the report-only mention helper is being consulted by: " + ", ".join(offenders)
    )


def test_python_version_supports_the_resolution_used_here():
    """``realpath`` only resolves Windows junctions from 3.8 onward."""
    assert sys.version_info >= (3, 8)
