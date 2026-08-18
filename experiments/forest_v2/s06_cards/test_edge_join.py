"""EXPERIMENT s06 checks: an edge's ``node_id`` must address a card in the same build.

Why this file exists
--------------------
s06's most expensive input is s01's *verified* call resolution: every one of
those edges lands on a real ``def``/``class`` line, confirmed against source.
The corpus run attached 13,124 of them and **not one** could be followed,
because the two sides of the join minted the target's identity from different
vocabularies:

* ``node_cards.node_id`` builds ``code://{rel}#{kind}:{qualname}`` from the
  record's **node kind** — ``module`` | ``class`` | ``function`` | ``method``;
* ``s01_upstream`` built the target id from ``Resolution.kind``, which is not
  a node kind at all but s01's **resolution bucket** — ``local_function``,
  ``import_repo``, ``self_attr_method``, ``module_attr_repo``, ``super_method``
  and six more.

Eighty-five checks were green throughout, because every one of them looked at
one side or the other and none looked at the join.

The canonical side is the **node kind**, and the reason is not taste:

1. ``node_id`` is a pure function of a record.  A card must be able to mint
   the identity another slice points at; the resolution bucket is not a
   property of the record, so a corpus keyed on it could never be joined by
   the cards themselves.
2. The bucket describes the *route* from the call site to the target, not the
   target.  4,432 distinct repo targets were addressed under 10 buckets — an
   identity that varies with the path taken to it is not an identity.
3. The bucket is real evidence and is not discarded.  It is published once per
   build as ``calls_by_resolution`` in ``describe()``, the same discipline
   this slice already applied to provenance blocks: emit the shared fact once,
   not 8,466 times.

What is checked here
--------------------
The checks below drive ``_s01_code_records`` with an injected stand-in for
s01's two modules over a tiny tree written into ``tmp_path``.  The stand-in
speaks s01's **real bucket vocabulary**, so a drift back to bucket-keyed ids
fails here immediately — and it needs no sibling worktree, so this guard is
reproducible from slice s06 alone.

The guard is on the **join**, not on the string: it asserts that a known edge
set reaches its cards at the expected rate.  A future drift for some entirely
different reason — a path separator, an ordinal, a qualname convention — drops
the rate and reddens the same check.

Read-only, stdlib only, no repository imports.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import node_cards as nc  # noqa: E402
import s01_upstream as up  # noqa: E402


# --------------------------------------------------------------------------
# A stand-in for s01's two modules.  It reproduces the parts of the contract
# `_s01_code_records` consumes, and nothing else.
# --------------------------------------------------------------------------


@dataclass
class _Class:
    bases: list[str] = field(default_factory=list)


@dataclass
class _Module:
    name: str
    path: Path
    rel: str
    tree: ast.Module
    classes: dict = field(default_factory=dict)


@dataclass
class _Resolution:
    kind: str  # s01's RESOLUTION BUCKET, not a node kind
    status: str
    target: str
    site_rel: str
    site_line: int
    target_module: str = ""
    target_rel: str = ""
    target_line: int = 0


class _Index:
    def __init__(self, modules: dict) -> None:
        self.modules = modules
        self.unparseable: list = []

    def class_of(self, _module: str, base: str):
        for mod in self.modules.values():
            if base in mod.classes:
                return SimpleNamespace(module=mod.name, qualname=f"{mod.name}.{base}")
        return None


#: One tiny package.  Every call below is a call s01 would report `verified`,
#: and the bucket attached to each is the bucket s01 really uses for that
#: shape of call site.
TREE = {
    "pkg/alpha.py": '''
def helper(x):
    return x


class Widget:
    def paint(self):
        return helper(1)

    def repaint(self):
        return self.paint()


def build():
    w = Widget()
    return w.paint() + helper(2)


def wrapper():
    def inner():
        return 1

    return inner()
''',
    "pkg/beta.py": '''
from pkg.alpha import helper, Widget


def use():
    return helper(3)


def make():
    return Widget()
''',
}

#: ``(site_rel, site_line) -> (bucket, target_qualname, target_rel)``.
#: Line numbers are resolved by searching for the call text, so the fixture
#: does not carry a hand-counted offset that could rot.
CALLS = [
    ("pkg/alpha.py", "return helper(1)", "local_function", "pkg.alpha.helper", "pkg/alpha.py"),
    ("pkg/alpha.py", "return self.paint()", "self_method", "pkg.alpha.Widget.paint", "pkg/alpha.py"),
    ("pkg/alpha.py", "w = Widget()", "local_class", "pkg.alpha.Widget", "pkg/alpha.py"),
    ("pkg/alpha.py", "return w.paint() + helper(2)", "local_var_method", "pkg.alpha.Widget.paint", "pkg/alpha.py"),
    ("pkg/alpha.py", "return inner()", "local_function", "pkg.alpha.wrapper.inner", "pkg/alpha.py"),
    ("pkg/beta.py", "return helper(3)", "import_repo", "pkg.alpha.helper", "pkg/alpha.py"),
    ("pkg/beta.py", "return Widget()", "import_repo", "pkg.alpha.Widget", "pkg/alpha.py"),
]

#: ``pkg.alpha.wrapper.inner`` is a def nested inside a function.  s06 cards
#: module-level defs and their methods, so this target has no card and the
#: edge must be **dropped and counted**, never emitted as a dangling pointer.
EXPECTED_REPO_CALL_EDGES = 6
EXPECTED_NO_CARD = 1


def _write_tree(root: Path) -> None:
    for rel, text in TREE.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\n"), encoding="utf-8")


def _build_stub(root: Path):
    """The injected ``(index_module, resolver_module)`` pair."""
    modules: dict[str, _Module] = {}
    for rel in sorted(TREE):
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        name = rel[: -len(".py")].replace("/", ".")
        classes = {
            node.name: _Class(bases=[])
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        modules[name] = _Module(
            name=name, path=root / rel, rel=rel, tree=tree, classes=classes
        )

    resolutions: dict[str, list] = {name: [] for name in modules}
    for site_rel, needle, bucket, target, target_rel in CALLS:
        lines = (root / site_rel).read_text(encoding="utf-8").splitlines()
        matches = [i + 1 for i, line in enumerate(lines) if needle in line]
        assert len(matches) == 1, f"fixture call site is not unique: {needle!r}"
        site_module = site_rel[: -len(".py")].replace("/", ".")
        resolutions[site_module].append(
            _Resolution(
                kind=bucket,
                status="verified",
                target=target,
                site_rel=site_rel,
                site_line=matches[0],
                target_module=target_rel[: -len(".py")].replace("/", "."),
                target_rel=target_rel,
                target_line=1,
            )
        )

    index_module = SimpleNamespace(build_index=lambda _root: _Index(modules))
    resolver_module = SimpleNamespace(
        resolve_module=lambda _index, info: [
            (None, res) for res in resolutions[info.name]
        ]
    )
    return index_module, resolver_module


@pytest.fixture()
def corpus(tmp_path):
    _write_tree(tmp_path)
    records, counts = up._s01_code_records(tmp_path, s01=_build_stub(tmp_path))
    return records, counts


def _repo_call_edges(records):
    return [
        edge
        for record in records
        for edge in record.get("neighbors", ())
        if edge["relation"] == "calls"
        and not edge["node_id"].startswith("code://external#")
    ]


# --------------------------------------------------------------------------
# The join itself
# --------------------------------------------------------------------------


def test_every_repo_call_edge_reaches_a_card_in_the_same_build(corpus):
    """The guard the 13,124 lost edges needed: follow every edge, land on a card."""
    records, _counts = corpus
    ids = {nc.node_id(record) for record in records}
    edges = _repo_call_edges(records)

    dangling = sorted({e["node_id"] for e in edges if e["node_id"] not in ids})
    assert dangling == [], (
        f"{len([e for e in edges if e['node_id'] not in ids])} of {len(edges)} "
        f"repo call edges address no card in this build; "
        f"{len(dangling)} distinct dangling ids: {dangling}"
    )
    assert len(edges) == EXPECTED_REPO_CALL_EDGES, (
        f"fixture drifted: expected {EXPECTED_REPO_CALL_EDGES} repo call edges, "
        f"got {len(edges)}"
    )


def test_the_join_rate_is_published_and_complete(corpus):
    """The rate is a counter, not a claim: the build reports what joined."""
    _records, counts = corpus
    assert counts["calls_verified"] == len(CALLS)
    assert counts["calls_verified_joined"] == EXPECTED_REPO_CALL_EDGES
    assert counts["calls_verified_no_card"] == EXPECTED_NO_CARD
    assert (
        counts["calls_verified_joined"] + counts["calls_verified_no_card"]
        == counts["calls_verified"]
    )


def test_a_verified_target_with_no_card_is_dropped_and_counted(corpus):
    """A nested def has no card here.  The edge is declined, not left dangling."""
    records, counts = corpus
    ids = {nc.node_id(record) for record in records}
    assert "code://pkg/alpha.py#function:pkg.alpha.wrapper.inner" not in ids
    assert counts["calls_verified_no_card"] == EXPECTED_NO_CARD
    assert not any(
        "wrapper.inner" in edge["node_id"] for edge in _repo_call_edges(records)
    )


def test_call_edges_carry_the_node_kind_not_the_resolution_bucket(corpus):
    """The interface between s01 and s06 is the node kind, in id and in field."""
    records, _counts = corpus
    buckets = {bucket for _r, _n, bucket, _t, _tr in CALLS}
    for edge in _repo_call_edges(records):
        kind = edge["node_id"].split("#", 1)[1].split(":", 1)[0]
        assert kind in nc.CODE_NODE_KINDS, (
            f"{kind!r} is not a node kind: {edge['node_id']}"
        )
        assert kind not in buckets, f"resolution bucket leaked into a node_id: {kind}"
        assert edge["kind"] == kind, "edge kind disagrees with the id it points at"


def test_the_resolution_buckets_survive_as_a_published_aggregate(corpus):
    """Dropping the bucket from the id must not destroy s01's evidence."""
    _records, counts = corpus
    verified = counts["calls_by_resolution"]["verified"]
    assert verified["local_function"] == 2
    assert verified["import_repo"] == 2
    assert verified["self_method"] == 1
    assert verified["local_class"] == 1
    assert verified["local_var_method"] == 1
    assert sum(verified.values()) == counts["calls_verified"]
    # The bucket of an edge that had no card is counted too -- otherwise the
    # aggregate would quietly become "the buckets that happened to join".
    assert sum(verified.values()) == (
        counts["calls_verified_joined"] + counts["calls_verified_no_card"]
    )


def test_defines_and_derives_edges_join_too(corpus):
    """The other relations use the same minting path; check them, not assume."""
    records, _counts = corpus
    ids = {nc.node_id(record) for record in records}
    dangling = sorted(
        {
            edge["node_id"]
            for record in records
            for edge in record.get("neighbors", ())
            if edge["relation"] in ("defines", "defined_in")
            and edge["node_id"] not in ids
        }
    )
    assert dangling == [], f"structural edges address no card: {dangling}"


# --------------------------------------------------------------------------
# Mutation probe: put the defect back, watch this file go red
# --------------------------------------------------------------------------

_SOURCE = Path(up.__file__).read_text(encoding="utf-8")

#: The exact expression the fix replaced.  Restoring it reproduces the corpus
#: failure — 100% of repo call edges dangling — inside the suite.
_FIXED = 'target_id = _node_id(res.target_rel, target_kind, res.target)'
_DEFECT = 'target_id = _node_id(res.target_rel, res.kind, res.target)'


def _mutant():
    """Recompile ``s01_upstream`` with the defect put back, as a real module.

    A real ``sys.modules`` entry is not cosmetic here: the module defines
    ``@dataclass`` types, and ``dataclasses`` resolves annotations through
    ``sys.modules[cls.__module__]``.  Exec'ing into a bare dict fails inside
    the stdlib before it can reach the code under test.
    """
    assert _SOURCE.count(_FIXED) == 1, f"mutation target is not unique: {_FIXED!r}"
    name = "s01_upstream__mutant"
    module = ModuleType(name)
    module.__file__ = up.__file__
    sys.modules[name] = module
    try:
        exec(compile(_SOURCE.replace(_FIXED, _DEFECT), name, "exec"), module.__dict__)
    finally:
        sys.modules.pop(name, None)
    return module


def test_mutation_reintroducing_the_resolver_kind_breaks_every_repo_edge(tmp_path):
    """Reproduce the measured defect: the bucket in the id, nothing joins."""
    _write_tree(tmp_path)
    mutant = _mutant()
    records, counts = mutant._s01_code_records(tmp_path, s01=_build_stub(tmp_path))
    ids = {nc.node_id(record) for record in records}
    edges = _repo_call_edges(records)

    assert edges, "the mutant emitted no repo call edges at all"
    joined = [e for e in edges if e["node_id"] in ids]
    assert joined == [], (
        "the mutant still joins; this probe no longer reproduces the defect"
    )
    # Kept because it is against interest: the build's OWN counter does not
    # notice.  calls_verified_joined counts successful kind lookups, and
    # the lookup still succeeds in the mutant -- only the id minted from it is
    # wrong.  A counter is not a join check; following the edge is.
    assert counts["calls_verified_joined"] == EXPECTED_REPO_CALL_EDGES
