"""EXPERIMENT s05 checks: run with ``python -m pytest`` on this file directly.

Every check here is about the ONE property this slice claims: a four-plane
extraction bound to a single revision reduces to a digest that survives replay
and moves when the content moves.  Nothing here asserts extraction quality.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import reference_planes as rp  # noqa: E402
import snapshot as snap  # noqa: E402


# --------------------------------------------------------------------------
# fixtures without files
# --------------------------------------------------------------------------


def _node(node_id: str, path: str = "a/b.py", **attrs):
    return {
        "id": node_id,
        "kind": "unit",
        "locator": {"path": path, "start_line": 1, "end_line": 2},
        "attrs": dict(attrs),
    }


def _doc(plane: str, revision: str = "rev-1", nodes=None, edges=None, producer="s05.check"):
    return {
        "schema": snap.CONTRACT,
        "plane": plane,
        "revision": revision,
        "producer": producer,
        "nodes": list(nodes if nodes is not None else [_node(f"{plane}:n1"), _node(f"{plane}:n2")]),
        "edges": list(
            edges
            if edges is not None
            else [{"src": f"{plane}:n1", "dst": f"{plane}:n2", "kind": "near", "attrs": {}}]
        ),
    }


def _four(revision: str = "rev-1"):
    return [_doc(plane, revision) for plane in snap.PLANES]


def _refuse(documents) -> str:
    with pytest.raises(snap.ContractError) as excinfo:
        snap.build_snapshot(documents)
    return excinfo.value.code


# --------------------------------------------------------------------------
# canonical form and digest algebra
# --------------------------------------------------------------------------


def test_canonical_bytes_ignore_key_insertion_order():
    a = {"b": 1, "a": {"y": [1, 2], "x": None}}
    b = {"a": {"x": None, "y": [1, 2]}, "b": 1}
    assert snap.canonical_bytes(a) == snap.canonical_bytes(b)


def test_canonical_bytes_are_utf8_without_escapes():
    payload = snap.canonical_bytes({"k": "Grün-Ökonomie"})
    assert "\\u" not in payload.decode("utf-8")
    assert payload.decode("utf-8") == '{"k":"Grün-Ökonomie"}'


def test_plane_name_is_part_of_the_plane_digest():
    """Two planes with byte-identical node sets must not share a digest."""
    left = snap.normalize_plane_document(_doc("code"))
    right = snap.normalize_plane_document(_doc("code"))
    right["plane"] = "data"
    assert snap.plane_digest(left) != snap.plane_digest(right)


def test_revision_is_part_of_the_snapshot_digest():
    one = snap.build_snapshot(_four("rev-1"))["snapshot_digest"]
    two = snap.build_snapshot(_four("rev-2"))["snapshot_digest"]
    assert one != two


def test_snapshot_digest_needs_all_four_plane_digests():
    with pytest.raises(snap.ContractError) as excinfo:
        snap.snapshot_digest("rev-1", {"code": "sha256:00", "type": "sha256:01"})
    assert excinfo.value.code == "missing_plane"


# --------------------------------------------------------------------------
# replay identity
# --------------------------------------------------------------------------


def test_two_builds_of_the_same_documents_agree():
    assert (
        snap.build_snapshot(_four())["snapshot_digest"]
        == snap.build_snapshot(_four())["snapshot_digest"]
    )


def test_element_order_does_not_move_the_digest():
    docs = _four()
    for doc in docs:
        doc["nodes"].append(_node(f"{doc['plane']}:n3"))
        doc["edges"].append(
            {"src": f"{doc['plane']}:n3", "dst": f"{doc['plane']}:n1", "kind": "near", "attrs": {}}
        )
    baseline = snap.build_snapshot(docs)["snapshot_digest"]
    rng = random.Random()
    shuffled = json.loads(json.dumps(docs))
    for doc in shuffled:
        rng.shuffle(doc["nodes"])
        rng.shuffle(doc["edges"])
    rng.shuffle(shuffled)
    assert snap.build_snapshot(shuffled)["snapshot_digest"] == baseline


def test_json_round_trip_does_not_move_the_digest():
    docs = _four()
    baseline = snap.build_snapshot(docs)["snapshot_digest"]
    revived = [json.loads(snap.canonical_bytes(doc).decode("utf-8")) for doc in docs]
    assert snap.build_snapshot(revived)["snapshot_digest"] == baseline


def test_producer_is_provenance_not_content():
    """s01-s04 may replace the placeholder producers without moving a digest."""
    docs = _four()
    baseline = snap.build_snapshot(docs)
    for doc in docs:
        doc["producer"] = "s01_code.extract"
    replaced = snap.build_snapshot(docs)
    assert replaced["snapshot_digest"] == baseline["snapshot_digest"]
    assert replaced["planes"]["code"]["producer"] == "s01_code.extract"


@pytest.mark.parametrize(
    "field, mutate",
    [
        ("node.id", lambda d: d[0]["nodes"][0].__setitem__("id", "code:n9")),
        ("node.kind", lambda d: d[0]["nodes"][0].__setitem__("kind", "other")),
        ("locator.path", lambda d: d[0]["nodes"][0]["locator"].__setitem__("path", "a/c.py")),
        ("locator.start_line", lambda d: d[0]["nodes"][0]["locator"].__setitem__("start_line", 0)),
        ("attrs", lambda d: d[0]["nodes"][0]["attrs"].__setitem__("weight", 1)),
        ("edge.kind", lambda d: d[0]["edges"][0].__setitem__("kind", "far")),
        ("edge.attrs", lambda d: d[0]["edges"][0]["attrs"].__setitem__("score", 0.5)),
    ],
)
def test_every_digested_field_is_load_bearing(field, mutate):
    baseline = snap.build_snapshot(_four())["snapshot_digest"]
    docs = _four()
    mutate(docs)
    if field == "node.id":  # keep the edge consistent, the change must still land
        docs[0]["edges"][0]["src"] = "code:n9"
    assert snap.build_snapshot(docs)["snapshot_digest"] != baseline, field


# --------------------------------------------------------------------------
# refusals -- invariant 6, no partial revision
# --------------------------------------------------------------------------


def test_incomplete_plane_set_is_refused():
    assert _refuse(_four()[:3]) == "missing_plane"


def test_repeated_plane_is_refused():
    docs = _four()
    assert _refuse(docs + [_doc("code")]) == "duplicate_plane"


def test_planes_from_different_revisions_are_refused():
    docs = _four()
    docs[1]["revision"] = "rev-2"
    assert _refuse(docs) == "revision_mismatch"


def test_repeated_node_id_is_refused():
    docs = _four()
    docs[0]["nodes"].append(_node("code:n1"))
    assert _refuse(docs) == "duplicate_node_id"


def test_dangling_edge_is_refused():
    docs = _four()
    docs[0]["edges"].append({"src": "code:n1", "dst": "code:nowhere", "kind": "near", "attrs": {}})
    assert _refuse(docs) == "dangling_edge"


def test_edge_into_another_plane_is_refused_with_its_own_code():
    """An extractor may not assert a cross-plane relation; a verifier must."""
    docs = _four()
    docs[0]["edges"].append({"src": "code:n1", "dst": "knowledge:n1", "kind": "documents", "attrs": {}})
    assert _refuse(docs) == "cross_plane_edge"


def test_unknown_key_is_refused_so_a_wall_clock_cannot_ride_along():
    docs = _four()
    docs[0]["nodes"][0]["built_at"] = "2026-08-18T00:00:00Z"
    assert _refuse(docs) == "unknown_key"


@pytest.mark.parametrize("path", ["/abs/mod.py", "C:/abs/mod.py"])
def test_absolute_locator_is_refused(path):
    docs = _four()
    docs[0]["nodes"][0]["locator"]["path"] = path
    assert _refuse(docs) == "absolute_locator"


def test_escaping_locator_is_refused():
    docs = _four()
    docs[0]["nodes"][0]["locator"]["path"] = "../outside/mod.py"
    assert _refuse(docs) == "bad_locator"


def test_backslash_locator_is_refused():
    docs = _four()
    docs[0]["nodes"][0]["locator"]["path"] = "a\\b.py"
    assert _refuse(docs) == "bad_locator"


def test_unknown_plane_is_refused():
    docs = _four()
    docs[0]["plane"] = "runtime"
    assert _refuse(docs) == "unknown_plane"


def test_foreign_schema_is_refused():
    docs = _four()
    docs[0]["schema"] = snap.CONTRACT + "x"
    assert _refuse(docs) == "bad_schema"


def test_refusal_yields_no_partial_manifest():
    with pytest.raises(snap.ContractError):
        snap.build_snapshot(_four()[:2])


# --------------------------------------------------------------------------
# extractors against a real (tiny) tree
# --------------------------------------------------------------------------


@pytest.fixture()
def tiny_tree(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n"
        "\n"
        "class Holder:\n"
        "    pass\n",
        encoding="utf-8",
    )
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "table.csv").write_text("alpha,beta\n1,2\n", encoding="utf-8")
    (conf / "obj.json").write_text('{"outer": {"inner": 1}, "other": 2}', encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "page.md").write_text("# Top\n\ntext\n\n## Sub\n\nmore\n", encoding="utf-8")
    return tmp_path


def _extract_tiny(root: Path, revision: str):
    return [
        rp.extract_code(root, revision, roots=("pkg",)),
        rp.extract_type(root, revision, roots=("pkg",)),
        rp.extract_data(root, revision, roots=("conf",)),
        rp.extract_knowledge(root, revision, roots=("notes",)),
    ]


def test_extractors_produce_a_buildable_snapshot(tiny_tree: Path):
    manifest = snap.build_snapshot(_extract_tiny(tiny_tree, "rev-1"))
    assert manifest["revision"] == "rev-1"
    assert manifest["node_total"] > 0
    assert set(manifest["planes"]) == set(snap.PLANES)
    assert all(manifest["planes"][p]["nodes"] > 0 for p in snap.PLANES)


def test_extraction_replays_to_the_same_digest(tiny_tree: Path):
    first = snap.build_snapshot(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    second = snap.build_snapshot(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    assert first == second


def test_a_changed_source_file_moves_the_digest(tiny_tree: Path):
    before = snap.build_snapshot(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    (tiny_tree / "pkg" / "mod.py").write_text(
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n"
        "\n"
        "def subtract(left: int, right: int) -> int:\n"
        "    return left - right\n",
        encoding="utf-8",
    )
    after = snap.build_snapshot(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    assert after != before


def test_line_ending_style_does_not_move_the_digest(tmp_path: Path):
    """A CRLF checkout and an LF checkout of the same text are one revision."""
    body = "# Top\n\ntext\n\n## Sub\n\nmore\n"
    digests = []
    for style in ("\n", "\r\n"):
        root = tmp_path / ("crlf" if style == "\r\n" else "lf")
        (root / "notes").mkdir(parents=True)
        with open(root / "notes" / "page.md", "w", encoding="utf-8", newline="") as handle:
            handle.write(body.replace("\n", style))
        doc = rp.extract_knowledge(root, "rev-1", roots=("notes",))
        digests.append(snap.plane_digest(snap.normalize_plane_document(doc)))
    assert digests[0] == digests[1]


def test_unparseable_python_is_recorded_not_fatal(tmp_path: Path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "broken.py").write_text("def (:\n", encoding="utf-8")
    doc = rp.extract_code(tmp_path, "rev-1", roots=("pkg",))
    module = doc["nodes"][0]
    assert module["kind"] == "module"
    assert module["attrs"]["parsed"] is False


def test_extractor_locators_are_relative_posix(tiny_tree: Path):
    for doc in _extract_tiny(tiny_tree, "rev-1"):
        for node in doc["nodes"]:
            path = node["locator"]["path"]
            assert "\\" not in path
            assert not path.startswith("/")
            assert str(tiny_tree) not in path


# --------------------------------------------------------------------------
# revision binding read out of git's files
# --------------------------------------------------------------------------


def _fake_commit_id(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(40))


def test_detached_head_revision(tmp_path: Path):
    commit = _fake_commit_id(random.Random())
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(commit + "\n", encoding="utf-8")
    assert rp.read_git_revision(tmp_path) == commit


def test_symbolic_head_revision(tmp_path: Path):
    commit = _fake_commit_id(random.Random())
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/work\n", encoding="utf-8")
    (git / "refs" / "heads" / "work").write_text(commit + "\n", encoding="utf-8")
    assert rp.read_git_revision(tmp_path) == commit


def test_worktree_gitdir_with_packed_refs(tmp_path: Path):
    commit = _fake_commit_id(random.Random())
    common = tmp_path / "main.git"
    common.mkdir()
    (common / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n" f"{commit} refs/heads/work\n",
        encoding="utf-8",
    )
    gitdir = common / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "HEAD").write_text("ref: refs/heads/work\n", encoding="utf-8")
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert rp.read_git_revision(tree) == commit


def test_no_checkout_yields_no_revision(tmp_path: Path):
    assert rp.read_git_revision(tmp_path) is None


# --------------------------------------------------------------------------
# revision atomicity: source evidence, not string equality
#
# Refutation received 2026-08-18: the builder bound four planes to one
# revision by STRING EQUALITY of the ``revision`` field.  A worktree mutated
# BETWEEN two plane extractions therefore reduced to one "atomic" digest for a
# tree state that never existed.  Master plan invariant 6 says a partial or
# mixed state must not masquerade as a revision -- so this is a gate.
#
# ``_build_with_mutation_between`` is the scenario harness; the assertions
# below are what the gate claims.  When the binding changed from string
# equality to source evidence, only the harness moved.
# --------------------------------------------------------------------------

_TINY_ORDER = ("code", "type", "data", "knowledge")
_TINY_ROOTS = {"code": ("pkg",), "type": ("pkg",), "data": ("conf",), "knowledge": ("notes",)}

#: a replacement that adds a definition, so a plane extracted before the write
#: and a plane extracted after it visibly disagree about the same file
_MOD_MUTATED = (
    "def add(left: int, right: int) -> int:\n"
    "    return left + right\n"
    "\n"
    "def sneak(value: str) -> str:\n"
    "    return value\n"
    "\n"
    "class Holder:\n"
    "    pass\n"
)

_ATOMICITY_CODES = frozenset({"scope_drift", "witness_conflict", "witness_scope_mismatch"})


def _build_with_mutation_between(
    root: Path,
    *,
    after: str,
    target: str,
    replacement: str,
    revert: bool = False,
):
    """Extract four planes, mutate ``target`` right after plane ``after``, build.

    Deterministic: no threads, no sleeps, no clock -- the write happens at a
    fixed point in a fixed extraction order.
    """
    original = (root / target).read_text(encoding="utf-8")
    documents = []
    for plane in _TINY_ORDER:
        documents.append(rp.EXTRACTORS[plane](root, "rev-1", roots=_TINY_ROOTS[plane]))
        if plane == after:
            (root / target).write_text(replacement, encoding="utf-8")
    if revert:
        (root / target).write_text(original, encoding="utf-8")
    return snap.build_snapshot(documents)


def test_mutation_between_plane_extractions_is_refused(tiny_tree: Path):
    """The worktree moves between plane 1 and plane 2; no digest may result."""
    try:
        manifest = _build_with_mutation_between(
            tiny_tree, after="code", target="pkg/mod.py", replacement=_MOD_MUTATED
        )
    except snap.ContractError as exc:
        assert exc.code in _ATOMICITY_CODES, exc
    else:
        pytest.fail(
            "a tree mutated between two plane extractions digested as ONE atomic "
            f"revision: revision={manifest['revision']!r} "
            f"snapshot_digest={manifest['snapshot_digest']} -- that snapshot "
            "describes a tree state that never existed at any instant"
        )


def test_mutation_reverted_before_the_build_is_still_refused(tiny_tree: Path):
    """Mutate, let one plane read it, revert.  Opening and closing state agree."""
    try:
        manifest = _build_with_mutation_between(
            tiny_tree,
            after="code",
            target="pkg/mod.py",
            replacement=_MOD_MUTATED,
            revert=True,
        )
    except snap.ContractError as exc:
        assert exc.code in _ATOMICITY_CODES, exc
    else:
        pytest.fail(
            "a mutate-and-revert between plane extractions digested as ONE atomic "
            f"revision: snapshot_digest={manifest['snapshot_digest']}"
        )


def test_mutation_of_a_single_reader_file_is_refused(tiny_tree: Path):
    """conf/obj.json is read by the data plane only -- no second reader to disagree."""
    try:
        manifest = _build_with_mutation_between(
            tiny_tree,
            after="data",
            target="conf/obj.json",
            replacement='{"outer": {"inner": 1}, "other": 2, "sneaked": 3}',
        )
    except snap.ContractError as exc:
        assert exc.code in _ATOMICITY_CODES, exc
    else:
        pytest.fail(
            "a file only one plane reads was mutated after that plane read it and "
            f"the build still produced snapshot_digest={manifest['snapshot_digest']}"
        )
