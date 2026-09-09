"""Checks for the symbol extractor.

Run directly::

    python -m pytest experiments/forest_v2/s09_eval/test_symbols.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import symbols  # noqa: E402

SRC = '''
import dataclasses


def free(a: int) -> str:
    return str(a)


def unannotated(a):
    return a


class Outer:
    field: int = 0

    def method(self, x: str) -> None:
        pass

    class Inner:
        def deep(self):
            return 1
'''


# --------------------------------------------------------------------------
# what is addressable
# --------------------------------------------------------------------------
def test_nested_classes_recurse_but_closures_do_not() -> None:
    table = symbols.symbol_table(SRC)
    assert "Outer.Inner.deep" in table
    assert set(table) == {
        "free",
        "unannotated",
        "Outer",
        "Outer.method",
        "Outer.Inner",
        "Outer.Inner.deep",
    }


def test_a_closure_is_not_a_separate_symbol() -> None:
    src = "def outer():\n    def inner():\n        pass\n    return inner\n"
    assert set(symbols.symbol_table(src)) == {"outer"}


def test_unparseable_source_has_no_symbols_and_does_not_raise() -> None:
    assert symbols.symbol_table("def broken(:\n") == {}


# --------------------------------------------------------------------------
# identity is structural
# --------------------------------------------------------------------------
def test_reformatting_is_not_a_change() -> None:
    a = "def f(x):\n    return x+1\n"
    b = "def f(x):\n\n    return x + 1\n"
    assert symbols.changed_symbols(a, b) == {}


def test_a_comment_is_not_a_change_but_a_docstring_is() -> None:
    base = "def f():\n    return 1\n"
    commented = "def f():\n    # explanatory\n    return 1\n"
    documented = 'def f():\n    """Now documented."""\n    return 1\n'
    assert symbols.changed_symbols(base, commented) == {}
    assert symbols.changed_symbols(base, documented) == {"f": "modified"}


def test_change_kinds_are_distinguished() -> None:
    pre = "def kept():\n    return 1\n\n\ndef gone():\n    return 2\n"
    post = "def kept():\n    return 99\n\n\ndef fresh():\n    return 3\n"
    assert symbols.changed_symbols(pre, post) == {
        "kept": "modified",
        "gone": "removed",
        "fresh": "added",
    }


def test_a_rename_reads_as_a_deletion_plus_a_creation() -> None:
    # Recorded rather than solved: see the module docstring.
    pre = "def old_name():\n    return 1\n"
    post = "def new_name():\n    return 1\n"
    assert symbols.changed_symbols(pre, post) == {
        "old_name": "removed",
        "new_name": "added",
    }


# --------------------------------------------------------------------------
# Type-plane membership
# --------------------------------------------------------------------------
def test_annotation_detection_covers_params_returns_and_assignments() -> None:
    assert symbols.carries_annotation(SRC, "free") is True
    assert symbols.carries_annotation(SRC, "unannotated") is False
    assert symbols.carries_annotation(SRC, "Outer") is True  # field: int
    assert symbols.carries_annotation(SRC, "Outer.method") is True
    assert symbols.carries_annotation(SRC, "Outer.Inner.deep") is False


def test_annotation_detection_finds_nested_targets() -> None:
    assert symbols.carries_annotation(SRC, "Outer.Inner") is False


def test_a_missing_qualname_is_false_not_an_error() -> None:
    assert symbols.carries_annotation(SRC, "nope") is False


def test_star_args_annotations_count() -> None:
    src = "def f(*args: int, **kw: str):\n    pass\n"
    assert symbols.carries_annotation(src, "f") is True


# --------------------------------------------------------------------------
# the Type-plane ablation
# --------------------------------------------------------------------------
def test_stripping_removes_every_annotation_kind() -> None:
    src = (
        "def f(a: int, *rest: str, **kw: bytes) -> list[int]:\n"
        "    x: dict[str, int] = {}\n"
        "    return [a]\n"
    )
    out = symbols.strip_annotations(src)
    for gone in ("int", "str", "bytes", "list[int]", "dict[str, int]"):
        assert gone not in out
    # identifiers, defaults and control flow survive
    for kept in ("def f(", "a", "rest", "kw", "x = {}", "return [a]"):
        assert kept in out


def test_a_bare_declaration_keeps_its_name() -> None:
    # `y: int` has nothing left once the annotation goes, but the NAME belongs
    # to the code plane and must survive the ablation.
    out = symbols.strip_annotations("def f():\n    y: int\n")
    assert "y = None" in out
    assert "int" not in out


def test_the_control_is_unparsed_too() -> None:
    # Both arms must round-trip, or the comparison also measures ast.unparse.
    src = "def f( a ):\n\n\n    return   a\n"
    assert symbols.normalize_source(src) == "def f(a):\n    return a"


def test_ablation_is_a_no_op_when_nothing_is_annotated() -> None:
    src = "def f(a):\n    return a\n"
    assert symbols.strip_annotations(src) == symbols.normalize_source(src)


def test_unparseable_source_survives_both_transforms_unchanged() -> None:
    broken = "def f(:\n"
    assert symbols.strip_annotations(broken) == broken
    assert symbols.normalize_source(broken) == broken


def test_stripping_does_not_change_which_symbols_exist() -> None:
    src = (
        "class C:\n"
        "    field: int = 0\n"
        "    def m(self, x: str) -> None:\n"
        "        pass\n"
    )
    assert set(symbols.symbol_table(symbols.strip_annotations(src))) == set(
        symbols.symbol_table(symbols.normalize_source(src))
    )
