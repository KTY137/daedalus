"""EXPERIMENT s06 checks: the upstream is pinned by content, not by hope.

The defect this file guards
---------------------------
s06's code-plane numbers — 5,739 records, 12,788 joined call edges, 318
modules — are produced by slice s01's resolver, which lives in a **sibling
worktree**.  Nothing s06 commits determines them.  Before this pin, a card
recorded only ``"source": "s01_resolution"`` and an ``extractor_version`` of
``"1"``: a hardcoded constant that does not move when s01 moves.  Point the
run at a different s01 and every count changes while the description of where
they came from stays byte-identical.

That is a provenance defect of the same class as the lost join, and arguably
worse: a lost edge is missing evidence, but a number that cannot be recomputed
from its own slice is evidence that was never really there.  Master plan §4.7
wants origin, revision and inputs on a material claim; a path string is none
of those.

The pin is the two files s06 actually imports, content-addressed.
``s01_resolver`` imports only ``s01_index`` and the stdlib, so those two files
are the whole upstream input: digesting them pins it completely, and digesting
the rest of s01's directory would make the pin move for edits s06 never
consumed.

The digest is carried in the code-plane **provenance block**, which means it
reaches every card's ``card_id`` by content address.  Change the upstream and
the corpus changes identity loudly, rather than quietly reporting different
numbers under the same name.

What the pin does NOT claim
---------------------------
It does not make the corpus number reproducible from s06 alone — nothing can,
short of vendoring s01.  It makes the number **attributable**: the write-up
must name the external commit, and this pin is what lets a reader check that
the naming is true.  The commit's HEAD is reported next to the digest and is
explicitly not trusted on its own, because HEAD says nothing about uncommitted
edits and s01's worktree was in fact dirty when this was written.

Read-only, stdlib only, no repository imports, no sibling worktree required.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import node_cards as nc  # noqa: E402
import s01_upstream as up  # noqa: E402


def _fake_s01(root: Path, index_body: str = "A", resolver_body: str = "B") -> Path:
    """A directory shaped like s01's package, with known contents."""
    package = root / "experiments" / "forest_v2" / "s01_resolution"
    package.mkdir(parents=True, exist_ok=True)
    (package / "s01_index.py").write_text(index_body, encoding="utf-8")
    (package / "s01_resolver.py").write_text(resolver_body, encoding="utf-8")
    return package


def test_the_pin_names_exactly_the_two_modules_that_are_imported():
    """The pin's scope is the import surface, stated as a constant."""
    assert up.S01_INPUT_MODULES == ("s01_index.py", "s01_resolver.py")
    source = Path(up.__file__).read_text(encoding="utf-8")
    # The importer and the pin must agree, or the pin covers the wrong files.
    assert "import s01_index" in source
    assert "import s01_resolver" in source


def test_the_pin_digests_every_named_module(tmp_path):
    package = _fake_s01(tmp_path)
    pin = up.s01_input_digest(package)
    assert set(pin["input_files"]) == set(up.S01_INPUT_MODULES)
    for digest in pin["input_files"].values():
        assert digest.startswith("sha256:")
    assert pin["input_digest"].startswith("sha256:")


def test_the_pin_moves_when_either_upstream_module_moves(tmp_path):
    """The whole point: a different s01 is a different pin."""
    base = up.s01_input_digest(_fake_s01(tmp_path / "a"))
    other_index = up.s01_input_digest(_fake_s01(tmp_path / "b", index_body="A2"))
    other_resolver = up.s01_input_digest(
        _fake_s01(tmp_path / "c", resolver_body="B2")
    )
    same = up.s01_input_digest(_fake_s01(tmp_path / "d"))

    assert base["input_digest"] != other_index["input_digest"]
    assert base["input_digest"] != other_resolver["input_digest"]
    # ...and it is a digest, not a timestamp: identical input, identical pin.
    assert base["input_digest"] == same["input_digest"]


def test_an_unreadable_upstream_module_is_named_rather_than_skipped(tmp_path):
    """A missing input must not silently produce a confident-looking digest."""
    package = _fake_s01(tmp_path)
    (package / "s01_resolver.py").unlink()
    pin = up.s01_input_digest(package)
    assert pin["input_files"]["s01_resolver.py"] == "unreadable"
    assert pin["input_digest"] != up.s01_input_digest(_fake_s01(tmp_path / "x"))[
        "input_digest"
    ]


def test_the_revision_is_reported_beside_the_digest_and_not_instead_of_it(tmp_path):
    """HEAD cannot see uncommitted edits, so it is never the claim."""
    pin = up.s01_input_digest(_fake_s01(tmp_path))
    assert "revision" in pin
    assert pin["revision_covers_uncommitted_edits"] is False
    assert pin["input_digest"].startswith("sha256:")


def test_the_pin_reaches_the_card_id(tmp_path):
    """A corpus built on a different upstream must not wear the same identity.

    This is the check that makes the pin load-bearing rather than decorative:
    it rides in the provenance block, the block is content-addressed, and the
    card carries that address — so the upstream reaches ``card_id``.
    """
    record = {
        "plane": "code",
        "kind": "function",
        "path": "x.py",
        "qualname": "x.f",
        "start_line": 1,
        "end_line": 1,
    }

    def _card(package: Path) -> dict:
        book = nc.ProvenanceBook()
        ref = book.add(
            {
                "source": "s01_resolution",
                "plane": "code",
                "read_only": True,
                "promotes": "nothing",
                "upstream_pin": up.s01_input_digest(package),
            }
        )
        return nc.build_card(record, revision="git:same", provenance=ref)

    first = _card(_fake_s01(tmp_path / "a"))
    second = _card(_fake_s01(tmp_path / "b", resolver_body="B2"))

    assert first["node_id"] == second["node_id"], "the node is the same node"
    assert first["provenance"] != second["provenance"]
    assert first["card_id"] != second["card_id"], (
        "two upstreams produced one card identity; the pin is not reaching the id"
    )


#: A minimal but *working* s01 package.  It is deliberately a real import
#: target rather than a monkeypatch, so this check exercises the same
#: ``load_upstream`` -> ``find_s01`` -> ``_import_s01`` path the corpus run
#: takes.  A pin that is only asserted where a test constructed the block by
#: hand would not notice the wiring being removed.
_STUB_INDEX = '''
import ast
from pathlib import Path


class ModuleInfo:
    def __init__(self, name, path, rel, tree):
        self.name, self.path, self.rel, self.tree = name, path, rel, tree
        self.classes = {}


class ProjectIndex:
    def __init__(self, modules):
        self.modules = modules
        self.unparseable = []

    def class_of(self, module, base):
        return None


def build_index(root):
    modules = {}
    for path in sorted(Path(root).rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        name = rel[:-3].replace("/", ".")
        modules[name] = ModuleInfo(name, path, rel, ast.parse(path.read_text("utf-8")))
    return ProjectIndex(modules)
'''

_STUB_RESOLVER = '''
class Resolution:
    def __init__(self, kind, status, target, site_rel, site_line, target_rel):
        self.kind, self.status, self.target = kind, status, target
        self.site_rel, self.site_line, self.target_rel = site_rel, site_line, target_rel
        self.target_module = ""
        self.target_line = 0


def resolve_module(index, info):
    out = []
    for name, mod in index.modules.items():
        for node in mod.tree.body:
            if type(node).__name__ == "FunctionDef" and info.name == name:
                out.append(
                    (
                        None,
                        Resolution(
                            "local_function",
                            "verified",
                            f"{name}.{node.name}",
                            info.rel,
                            node.lineno,
                            mod.rel,
                        ),
                    )
                )
    return out
'''


def _working_s01(root: Path) -> Path:
    package = root / "s01pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "s01_index.py").write_text(_STUB_INDEX, encoding="utf-8")
    (package / "s01_resolver.py").write_text(_STUB_RESOLVER, encoding="utf-8")
    return package


def _load_with_stub_s01(tmp_path: Path):
    """Run the real ``load_upstream`` against an importable stand-in s01."""
    tree = tmp_path / "tree"
    (tree / "pkg").mkdir(parents=True, exist_ok=True)
    (tree / "pkg" / "mod.py").write_text("def f():\n    return f()\n", encoding="utf-8")
    package = _working_s01(tmp_path)
    for name in ("s01_index", "s01_resolver"):
        sys.modules.pop(name, None)
    try:
        return up.load_upstream(tree, s01_path=package)
    finally:
        for name in ("s01_index", "s01_resolver"):
            sys.modules.pop(name, None)
        while str(package) in sys.path:
            sys.path.remove(str(package))


def test_the_real_wiring_puts_the_pin_in_the_code_plane_block(tmp_path):
    """End-to-end through ``load_upstream``: the block a card points at is pinned."""
    upstream = _load_with_stub_s01(tmp_path)
    assert upstream.mode == "s01"
    assert upstream.gap is None

    blocks = [
        block
        for block in upstream.book.as_dict().values()
        if block.get("source") == "s01_resolution"
    ]
    assert len(blocks) == 1, "expected exactly one code-plane provenance block"
    pin = blocks[0].get("upstream_pin")
    assert pin is not None, (
        "the code-plane provenance block carries no upstream pin; the corpus "
        "counts are unattributable again"
    )
    assert set(pin["input_files"]) == set(up.S01_INPUT_MODULES)
    assert pin["input_digest"] == up.s01_input_digest(_working_s01(tmp_path))[
        "input_digest"
    ]

    # ...and the pinned block is the one the cards actually reference.
    refs = {ref for ref, _record in upstream.iter_records()}
    pinned_ref = nc.provenance_ref(blocks[0])
    assert pinned_ref in refs


def test_a_build_that_reached_s01_publishes_its_pin(tmp_path):
    """``describe()`` must surface the pin, or a reader cannot check the claim."""
    upstream = up.load_upstream(tmp_path, use_s01=False)
    described = upstream.describe()
    # The stand-in path has no upstream, and says so with the named gap rather
    # than an absent field.
    assert described["gap"] is not None
    assert described["gap"]["id"] == up.UPSTREAM_GAP_ID
    assert "s01_pin" not in described

    # The s01 path carries the pin through stats into describe().
    upstream.stats["s01_pin"] = {"input_digest": "sha256:" + "0" * 64}
    assert upstream.describe()["s01_pin"]["input_digest"].startswith("sha256:")
