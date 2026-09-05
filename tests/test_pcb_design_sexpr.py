"""The bounded S-expression reader: what it accepts, and what it refuses.

Every refusal here is a *typed* refusal. A parser that raises ``IndexError`` on
a truncated file has not refused it, it has crashed, and a crash carries no
reason a caller can report.
"""
from __future__ import annotations

import hashlib

import pytest

from daedalus.pcb_design.sexpr import (
    ABSOLUTE_MAX_BYTES,
    Atom,
    PcbRefusal,
    REFUSAL_REASONS,
    args,
    first,
    head,
    parse,
    parse_bytes,
    read_artifact,
    sublists,
    to_float,
)


def test_parses_a_minimal_kicad_shaped_expression():
    tree = parse('(kicad_pcb (version 20240108) (generator "pcbnew"))')
    assert head(tree) == "kicad_pcb"
    assert args(first(tree, "version")) == ("20240108",)
    assert args(first(tree, "generator")) == ("pcbnew",)


def test_quoting_is_retained_because_the_dialect_distinguishes_it():
    tree = parse('(kicad_pcb (layers (0 "F.Cu" signal)))')
    layer = first(first(tree, "layers"), "0")
    assert layer is not None
    assert layer[1] == Atom("F.Cu", quoted=True)
    assert layer[2] == Atom("signal", quoted=False)


def test_string_escapes_are_decoded():
    tree = parse(r'(property "Path" "C:\\tmp\\x" "say \"hi\"")')
    assert args(tree) == ("Path", "C:\\tmp\\x", 'say "hi"')


def test_whitespace_between_tokens_is_irrelevant():
    dense = parse('(a(b 1)(c "x"))')
    spread = parse('(a\n\t(b 1)\n\t(c "x")\n)')
    assert dense == spread


@pytest.mark.parametrize(
    "text, detail_fragment",
    [
        ("", "no expression found"),
        ("   \n\t ", "no expression found"),
        ("(kicad_pcb", "unterminated expression"),
        # The root closed on the first ')', so the second one is trailing
        # content rather than an unbalanced close. The reason stays exact.
        ("(kicad_pcb))", "content after the root expression"),
        ("(a) (b)", "content after the root expression"),
        ("(a) trailing", "content after the root expression"),
        ('(a "unterminated', "unterminated string"),
        (r'(a "bad \q escape")', "unknown string escape"),
        ('(a "trailing backslash \\', "unterminated string escape"),
        ("atom_without_a_list", "atom outside any expression"),
        (")", "unbalanced closing parenthesis"),
    ],
)
def test_malformed_input_is_a_typed_refusal(text, detail_fragment):
    with pytest.raises(PcbRefusal) as caught:
        parse(text)
    assert caught.value.reason == "malformed_sexpr"
    assert detail_fragment in caught.value.detail
    assert caught.value.to_dict()["refused"] is True


def test_every_refusal_reason_is_declared():
    with pytest.raises(ValueError):
        PcbRefusal("not_a_declared_reason", "x")
    assert "malformed_sexpr" in REFUSAL_REASONS


def test_depth_is_bounded_instead_of_crashing_the_interpreter():
    deep = "(" * 5000 + ")" * 5000
    with pytest.raises(PcbRefusal) as caught:
        parse(deep)
    assert caught.value.reason == "depth_exceeded"
    assert caught.value.context["max_depth"] == 200


def test_node_budget_is_bounded():
    with pytest.raises(PcbRefusal) as caught:
        parse("(a " + "b " * 50 + ")", max_nodes=10)
    assert caught.value.reason == "node_budget_exceeded"


def test_a_deep_but_admitted_nesting_still_parses():
    depth = 50
    tree = parse("(x" * depth + ")" * depth)
    node = tree
    for _ in range(depth - 1):
        node = first(node, "x")
        assert node is not None


def test_non_utf8_bytes_are_a_typed_refusal():
    with pytest.raises(PcbRefusal) as caught:
        parse_bytes(b'(kicad_pcb (generator "\xff\xfe"))')
    assert caught.value.reason == "invalid_encoding"


def test_a_utf8_bom_is_tolerated():
    tree = parse_bytes("\ufeff(kicad_pcb (version 20240108))".encode("utf-8"))
    assert head(tree) == "kicad_pcb"


def test_read_artifact_binds_size_and_digest(tmp_path):
    target = tmp_path / "small.kicad_pcb"
    payload = b"(kicad_pcb (version 20240108))\n"
    target.write_bytes(payload)
    artifact = read_artifact(target)
    assert artifact.size_bytes == len(payload)
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()
    assert artifact.identity() == {
        "name": "small.kicad_pcb",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_oversized_input_is_refused_before_it_is_read(tmp_path):
    target = tmp_path / "big.kicad_pcb"
    target.write_bytes(b"x" * 4096)
    with pytest.raises(PcbRefusal) as caught:
        read_artifact(target, max_bytes=1024)
    assert caught.value.reason == "input_too_large"
    assert caught.value.context == {"size_bytes": 4096, "max_bytes": 1024}


def test_the_size_bound_itself_is_bounded(tmp_path):
    target = tmp_path / "small.kicad_pcb"
    target.write_bytes(b"()")
    with pytest.raises(PcbRefusal) as caught:
        read_artifact(target, max_bytes=ABSOLUTE_MAX_BYTES + 1)
    assert caught.value.reason == "max_bytes_out_of_range"
    with pytest.raises(PcbRefusal):
        read_artifact(target, max_bytes=0)


def test_a_directory_is_not_a_file(tmp_path):
    with pytest.raises(PcbRefusal) as caught:
        read_artifact(tmp_path)
    assert caught.value.reason == "not_a_file"


def test_a_missing_path_is_a_typed_refusal(tmp_path):
    with pytest.raises(PcbRefusal) as caught:
        read_artifact(tmp_path / "absent.kicad_pcb")
    assert caught.value.reason == "not_a_file"


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_non_finite_numbers_are_not_coordinates(text):
    assert to_float(text) is None


def test_sublists_filters_by_head_and_skips_atoms():
    tree = parse("(root a (x 1) (y 2) (x 3))")
    assert [args(node) for node in sublists(tree, "x")] == [("1",), ("3",)]
    assert len(list(sublists(tree))) == 3
    assert head(Atom("a", False)) == ""
