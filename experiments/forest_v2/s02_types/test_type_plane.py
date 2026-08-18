"""Tests for the s02 type-plane extractor.

Run directly::

    python -m pytest experiments/forest_v2/s02_types/test_type_plane.py

Every test builds a throwaway source tree with a hand-computed expected
answer, so the extractor is graded against sources whose truth is known
rather than against its own output on the repository.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import type_plane as tp  # noqa: E402


def write_pkg(root: Path, name: str, modules: dict[str, str]) -> None:
    """Write ``modules`` (relative path -> source) into package ``name``."""
    base = root / name
    base.mkdir(parents=True, exist_ok=True)
    if "__init__.py" not in modules:
        (base / "__init__.py").write_text("", encoding="utf-8")
    for rel, source in modules.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")


def build(root: Path, name: str = "pkg") -> dict:
    return tp.build_type_plane(root, packages=(name,))


def buckets_of(report: dict) -> dict[str, int]:
    return report["graph"]["type_nodes_by_bucket"]


def node_names(report: dict, bucket: str) -> set[str]:
    graph = report["_graph_object"]
    return {
        node["name"]
        for node in graph.nodes.values()
        if node["plane"] == "type" and node["bucket"] == bucket
    }


def edges_of(report: dict, kind: str) -> list[dict]:
    graph = report["_graph_object"]
    return [edge for edge in graph.edges.values() if edge["kind"] == kind]


# --------------------------------------------------------------------------
# headline metric
# --------------------------------------------------------------------------
def test_signature_rates_match_hand_count(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            def resolved(a: int, b: str) -> bool:
                return bool(a) or bool(b)

            def missing_return(a: int):
                return a

            def missing_param(a, b: int) -> int:
                return b

            def unknown_name(a: NeverImported) -> int:
                return 1
            """
        },
    )
    report = build(tmp_path)
    totals = report["totals"]
    assert totals["functions"] == 4
    assert totals["methods"] == 0
    # syntactically complete: resolved + unknown_name
    assert totals["sig_annotated"] == 2
    # fully attributable: resolved only
    assert totals["sig_resolved"] == 1
    assert report["rates"]["sig_resolved_pct"] == 25.0
    assert report["rates"]["sig_annotated_pct"] == 50.0


def test_implicit_receiver_is_not_a_missing_annotation(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            class C:
                def method(self, a: int) -> None:
                    return None

                @classmethod
                def factory(cls) -> None:
                    return None
            """
        },
    )
    report = build(tmp_path)
    totals = report["totals"]
    assert totals["methods"] == 2
    assert totals["implicit_receivers"] == 2
    assert totals["params"] == 1  # only ``a``
    assert totals["sig_resolved"] == 2


def test_builtins_only_control_is_weaker_than_the_full_resolver(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "types_.py": """
            class Widget:
                pass
            """,
            "m.py": """
            from pkg.types_ import Widget

            def uses_repo_type(w: Widget) -> Widget:
                return w

            def uses_builtins(a: int) -> str:
                return str(a)
            """,
        },
    )
    report = build(tmp_path)
    totals = report["totals"]
    assert totals["sig_resolved"] == 2
    # the control cannot see the import binding, so only the builtin one counts
    assert totals["sig_resolved_builtins_only"] == 1
    assert (
        report["rates"]["sig_resolved_builtins_only_pct"]
        < report["rates"]["sig_resolved_pct"]
    )


# --------------------------------------------------------------------------
# attribution buckets
# --------------------------------------------------------------------------
def test_signatures_are_split_by_whether_they_need_repo_types(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "types_.py": """
            class Widget:
                pass
            """,
            "m.py": """
            from pkg.types_ import Widget

            def needs_repo(w: Widget) -> None:
                return None

            def stdlib_only(a: int) -> str:
                return str(a)
            """,
        },
    )
    report = build(tmp_path)
    totals = report["totals"]
    assert totals["sig_resolved"] == 2
    assert totals["sig_resolved_needs_repo_types"] == 1
    assert totals["sig_resolved_without_repo_types"] == 1
    assert (
        totals["sig_resolved_needs_repo_types"]
        + totals["sig_resolved_without_repo_types"]
        == totals["sig_resolved"]
    )


def test_repo_attribution_is_verified_against_the_symbol_table(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "real.py": """
            class Present:
                pass
            """,
            "m.py": """
            from pkg.real import Present
            from pkg.real import Absent

            def f(a: Present, b: Absent) -> None:
                return None
            """,
        },
    )
    report = build(tmp_path)
    assert "pkg.real.Present" in node_names(report, "repo")
    # imported from a repo module that does not define it -> attributed, unverified
    assert "pkg.real.Absent" in node_names(report, "repo_unverified")
    # unverified still counts as attributed: the signature is "resolved"
    assert report["totals"]["sig_resolved"] == 1


def test_stdlib_typing_and_third_party_buckets(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            import pathlib
            from typing import Optional
            from some_vendor_package import Client

            def f(p: pathlib.Path, o: Optional[int], c: Client) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    assert "pathlib.Path" in node_names(report, "stdlib")
    assert "typing.Optional" in node_names(report, "typing")
    assert "some_vendor_package.Client" in node_names(report, "third_party")
    assert report["totals"]["sig_resolved"] == 1


def test_locally_defined_class_resolves_without_an_import(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            class Local:
                pass

            def f(x: Local) -> Local:
                return x
            """
        },
    )
    report = build(tmp_path)
    assert "pkg.m.Local" in node_names(report, "repo")
    assert report["totals"]["sig_resolved"] == 1


def test_relative_imports_resolve_through_the_package(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "sub/__init__.py": "",
            "sub/leaf.py": """
            class Leaf:
                pass
            """,
            "sub/user.py": """
            from .leaf import Leaf
            from ..top import Top

            def f(a: Leaf, b: Top) -> None:
                return None
            """,
            "top.py": """
            class Top:
                pass
            """,
        },
    )
    report = build(tmp_path)
    repo = node_names(report, "repo")
    assert "pkg.sub.leaf.Leaf" in repo
    assert "pkg.top.Top" in repo


# --------------------------------------------------------------------------
# annotation shapes
# --------------------------------------------------------------------------
def test_unresolved_name_is_reported_with_a_source_locator(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            x: int = 0


            def f(a: NotBoundHere) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    rows = {row["name"]: row["sites"] for row in report["unresolved_annotation_names"]}
    assert "NotBoundHere" in rows
    # line 5: the dedented source opens with a blank line
    assert rows["NotBoundHere"] == ["pkg/m.py:5"]


def test_unresolved_names_are_reported_from_every_annotation_context(
    tmp_path: Path,
) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from dataclasses import dataclass

            MODULE_VAR: MissingVar = None


            @dataclass
            class D(MissingBase):
                field: MissingField = None
            """
        },
    )
    report = build(tmp_path)
    found = {row["name"] for row in report["unresolved_annotation_names"]}
    # a name that only ever appears as a base or a field must not hide
    assert {"MissingVar", "MissingBase", "MissingField"} <= found


def test_ellipsis_is_a_resolved_special_form(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from typing import Callable

            def f(cb: Callable[..., int], t: tuple[str, ...]) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    assert "..." in node_names(report, "special")
    assert buckets_of(report).get("unresolved", 0) == 0
    assert buckets_of(report).get("structural", 0) == 0
    assert report["totals"]["sig_resolved"] == 1


def test_literal_arguments_are_values_not_type_names(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from typing import Literal

            def f(mode: Literal["fast", "slow"]) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    assert buckets_of(report).get("structural", 0) == 0
    assert report["totals"]["sig_resolved"] == 1


def test_annotated_binds_only_its_first_argument(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from typing import Annotated

            def f(a: Annotated[int, "some metadata"]) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    assert "int" in node_names(report, "builtin")
    assert buckets_of(report).get("structural", 0) == 0


def test_string_forward_reference_is_parsed_and_resolved(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            class Later:
                pass

            def f(a: "Later | None") -> "Later":
                return a or Later()
            """
        },
    )
    report = build(tmp_path)
    assert "pkg.m.Later" in node_names(report, "repo")
    assert "typing.Union" in node_names(report, "typing")
    assert report["totals"]["sig_resolved"] == 1


def test_unparsable_forward_reference_is_structural(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": '''
            def f(a: "not a type <<<") -> None:
                return None
            '''
        },
    )
    report = build(tmp_path)
    assert "<bad-forward-ref>" in node_names(report, "structural")
    assert report["totals"]["sig_resolved"] == 0


# --------------------------------------------------------------------------
# graph shape
# --------------------------------------------------------------------------
def test_type_arg_edges_link_head_to_parameters(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            def f(a: dict[str, int]) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    pairs = {(e["src"], e["dst"]) for e in edges_of(report, "type_arg")}
    assert ("type:builtin:dict", "type:builtin:str") in pairs
    assert ("type:builtin:dict", "type:builtin:int") in pairs


def test_class_bases_become_subtype_edges(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            class Base:
                pass

            class Derived(Base):
                pass
            """
        },
    )
    report = build(tmp_path)
    pairs = {(e["src"], e["dst"]) for e in edges_of(report, "subtype_of")}
    assert ("sym:pkg.m.Derived", "type:repo:pkg.m.Base") in pairs
    assert report["totals"]["class_bases"] == 1


def test_dataclass_fields_are_counted_and_resolved(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class Row:
                name: str
                size: int
                other: Unknown = None

            class Plain:
                not_a_dataclass_field: str = ""
            """
        },
    )
    report = build(tmp_path)
    totals = report["totals"]
    assert totals["dataclasses"] == 1
    assert totals["dataclass_fields"] == 3
    assert totals["dataclass_fields_resolved"] == 2
    assert totals["class_fields"] == 4  # the plain class field is still a field
    kinds = {e["kind"] for e in report["_graph_object"].edges.values()}
    assert "field_type" in kinds


def test_module_level_annotation_is_a_var_edge(tmp_path: Path) -> None:
    write_pkg(tmp_path, "pkg", {"m.py": "TIMEOUT: float = 1.0\n"})
    report = build(tmp_path)
    pairs = {(e["src"], e["dst"]) for e in edges_of(report, "var_type")}
    assert ("sym:pkg.m.TIMEOUT", "type:builtin:float") in pairs
    assert report["totals"]["module_vars"] == 1


def test_type_aliases_are_detected_conservatively(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from typing import TypeVar, Dict

            T = TypeVar("T")
            Table = Dict[str, int]
            NOT_AN_ALIAS = sorted([3, 1])
            """
        },
    )
    report = build(tmp_path)
    assert report["totals"]["type_aliases"] == 2
    srcs = {e["src"] for e in edges_of(report, "alias_of")}
    assert {"sym:pkg.m.T", "sym:pkg.m.Table"} == srcs


def test_edges_are_deduplicated_and_weighted(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            def f(a: dict[str, int]) -> None:
                return None

            def g(a: dict[str, int]) -> None:
                return None
            """
        },
    )
    report = build(tmp_path)
    graph = report["_graph_object"]
    # the two signatures repeat the same dict -> str / dict -> int type_arg pair
    assert report["graph"]["edges_unique"] < report["graph"]["edges_weighted"]
    type_args = {(e["dst"], e["count"]) for e in edges_of(report, "type_arg")}
    assert ("type:builtin:str", 2) in type_args
    assert ("type:builtin:int", 2) in type_args
    # distinct parameter symbols stay distinct edges seen once each
    param_edges = edges_of(report, "param_type")
    assert len(param_edges) == 2
    assert all(e["count"] == 1 for e in param_edges)
    assert all("first_seen" in e for e in graph.edges.values())


# --------------------------------------------------------------------------
# frame guarantees
# --------------------------------------------------------------------------
def test_report_is_json_serialisable_and_declares_read_only(tmp_path: Path) -> None:
    import json

    write_pkg(tmp_path, "pkg", {"m.py": "def f() -> None:\n    return None\n"})
    report = build(tmp_path)
    payload = tp.summary(report)
    assert "_graph_object" not in payload
    assert payload["read_only"] is True
    assert payload["schema"] == tp.SCHEMA
    json.dumps(payload, sort_keys=True)


def test_unparseable_file_is_counted_not_fatal(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "good.py": "def f() -> None:\n    return None\n",
            "broken.py": "def f(:\n",
        },
    )
    report = build(tmp_path)
    assert report["totals"]["files_parsed"] == 2  # good.py + __init__.py
    assert report["totals"]["files_unparseable"] == 1


def test_extraction_is_deterministic(tmp_path: Path) -> None:
    write_pkg(
        tmp_path,
        "pkg",
        {
            "m.py": """
            from typing import Optional

            def f(a: Optional[int], b: dict[str, int]) -> bool:
                return True
            """
        },
    )
    first = tp.summary(build(tmp_path))
    second = tp.summary(build(tmp_path))
    assert first == second
