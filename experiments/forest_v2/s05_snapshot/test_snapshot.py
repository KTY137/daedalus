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
    node_list = list(nodes if nodes is not None else [_node(f"{plane}:n1"), _node(f"{plane}:n2")])
    return {
        "schema": snap.CONTRACT,
        "plane": plane,
        "revision": revision,
        "producer": producer,
        "nodes": node_list,
        "edges": list(
            edges
            if edges is not None
            else [{"src": f"{plane}:n1", "dst": f"{plane}:n2", "kind": "near", "attrs": {}}]
        ),
        "witness": {
            n["locator"]["path"]: rp.text_digest(f"content of {n['locator']['path']}")
            for n in node_list
        },
    }


def _four(revision: str = "rev-1"):
    return [_doc(plane, revision) for plane in snap.PLANES]


def _agreeing_scope(documents):
    """TEST HELPER ONLY: a scope bracket that trivially agrees with the witnesses.

    It proves NOTHING about atomicity -- it is derived from the very documents
    it is supposed to bracket.  It exists so the checks about *other* contract
    rules do not have to build a filesystem.  The atomicity gate at the bottom
    of this file uses a real bracket scanned off a real tree.
    """
    files: dict[str, str] = {}
    for doc in documents:
        files.update(doc.get("witness", {}))
    return {"roots": ["a"], "opened": dict(files), "closed": dict(files)}


def _build(documents, scope=None):
    return snap.build_snapshot(documents, _agreeing_scope(documents) if scope is None else scope)


def _refuse(documents, scope=None) -> str:
    with pytest.raises(snap.ContractError) as excinfo:
        _build(documents, scope)
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
    one = _build(_four("rev-1"))["snapshot_digest"]
    two = _build(_four("rev-2"))["snapshot_digest"]
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
        _build(_four())["snapshot_digest"]
        == _build(_four())["snapshot_digest"]
    )


def test_element_order_does_not_move_the_digest():
    docs = _four()
    for doc in docs:
        doc["nodes"].append(_node(f"{doc['plane']}:n3"))
        doc["edges"].append(
            {"src": f"{doc['plane']}:n3", "dst": f"{doc['plane']}:n1", "kind": "near", "attrs": {}}
        )
    baseline = _build(docs)["snapshot_digest"]
    rng = random.Random()
    shuffled = json.loads(json.dumps(docs))
    for doc in shuffled:
        rng.shuffle(doc["nodes"])
        rng.shuffle(doc["edges"])
    rng.shuffle(shuffled)
    assert _build(shuffled)["snapshot_digest"] == baseline


def test_json_round_trip_does_not_move_the_digest():
    docs = _four()
    baseline = _build(docs)["snapshot_digest"]
    revived = [json.loads(snap.canonical_bytes(doc).decode("utf-8")) for doc in docs]
    assert _build(revived)["snapshot_digest"] == baseline


def test_producer_is_provenance_not_content():
    """s01-s04 may replace the placeholder producers without moving a digest."""
    docs = _four()
    baseline = _build(docs)
    for doc in docs:
        doc["producer"] = "s01_code.extract"
    replaced = _build(docs)
    assert replaced["snapshot_digest"] == baseline["snapshot_digest"]
    assert replaced["planes"]["code"]["producer"] == "s01_code.extract"


@pytest.mark.parametrize(
    "field, mutate",
    [
        ("node.id", lambda d: d[0]["nodes"][0].__setitem__("id", "code:n9")),
        ("node.kind", lambda d: d[0]["nodes"][0].__setitem__("kind", "other")),
        ("locator.path", lambda d: _relocate(d[0], "a/c.py")),
        ("locator.start_line", lambda d: d[0]["nodes"][0]["locator"].__setitem__("start_line", 0)),
        ("locator.end_line", lambda d: d[0]["nodes"][0]["locator"].__setitem__("end_line", 9)),
        ("attrs", lambda d: d[0]["nodes"][0]["attrs"].__setitem__("weight", 1)),
        ("edge.src", lambda d: d[0]["edges"][0].__setitem__("src", "code:n2")),
        ("edge.dst", lambda d: d[0]["edges"][0].__setitem__("dst", "code:n1")),
        ("edge.kind", lambda d: d[0]["edges"][0].__setitem__("kind", "far")),
        ("edge.attrs", lambda d: d[0]["edges"][0]["attrs"].__setitem__("score", 0.5)),
        ("witness.digest", lambda d: _rewitness(d, "a/b.py", "other bytes")),
    ],
)
def test_every_digested_field_is_load_bearing(field, mutate):
    baseline = _build(_four())["snapshot_digest"]
    docs = _four()
    mutate(docs)
    if field == "node.id":  # keep the edge consistent, the change must still land
        docs[0]["edges"][0]["src"] = "code:n9"
    assert _build(docs)["snapshot_digest"] != baseline, field


def _relocate(doc, path: str):
    """Move a node to another file AND witness that file: one coherent relocation."""
    doc["nodes"][0]["locator"]["path"] = path
    doc["witness"][path] = rp.text_digest(f"content of {path}")


def _rewitness(documents, path: str, content: str):
    """Restate one file's content digest wherever it is witnessed.

    One field per document, but it has to move in every plane that read the
    file -- a witness that moves in one plane only is a different defect
    (``witness_conflict``), which its own check covers.
    """
    for doc in documents:
        if path in doc["witness"]:
            doc["witness"][path] = rp.text_digest(content)


def test_a_source_change_no_extractor_looks_at_still_moves_the_digest():
    """The witness is what makes this true; nodes and edges alone would not move."""
    baseline = _build(_four())["snapshot_digest"]
    docs = _four()
    for doc in docs:
        doc["witness"]["a/b.py"] = rp.text_digest("same view, different bytes")
    changed = _build(docs)
    assert changed["snapshot_digest"] != baseline
    assert changed["node_total"] == _build(_four())["node_total"]


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
        _build(_four()[:2])


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
    manifest = _build(_extract_tiny(tiny_tree, "rev-1"))
    assert manifest["revision"] == "rev-1"
    assert manifest["node_total"] > 0
    assert set(manifest["planes"]) == set(snap.PLANES)
    assert all(manifest["planes"][p]["nodes"] > 0 for p in snap.PLANES)


def test_extraction_replays_to_the_same_digest(tiny_tree: Path):
    first = _build(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    second = _build(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    assert first == second


def test_a_changed_source_file_moves_the_digest(tiny_tree: Path):
    before = _build(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
    (tiny_tree / "pkg" / "mod.py").write_text(
        "def add(left: int, right: int) -> int:\n"
        "    return left + right\n"
        "\n"
        "def subtract(left: int, right: int) -> int:\n"
        "    return left - right\n",
        encoding="utf-8",
    )
    after = _build(_extract_tiny(tiny_tree, "rev-1"))["snapshot_digest"]
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

_ATOMICITY_CODES = frozenset(
    {"scope_drift", "witness_conflict", "witness_scope_mismatch", "witness_outside_scope"}
)

_TINY_SCOPE_ROOTS = ("conf", "notes", "pkg")


def _tiny_scope_scan(root: Path):
    return rp.scan_scope(root, _TINY_SCOPE_ROOTS, rp.SCOPE_SUFFIXES)


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
    fixed point in a fixed extraction order.  This harness is the only thing
    that moved when the binding changed from string equality to source
    evidence; the assertions below did not.
    """
    original = (root / target).read_text(encoding="utf-8")
    opened = _tiny_scope_scan(root)
    documents = []
    for plane in _TINY_ORDER:
        documents.append(rp.EXTRACTORS[plane](root, "rev-1", roots=_TINY_ROOTS[plane]))
        if plane == after:
            (root / target).write_text(replacement, encoding="utf-8")
    if revert:
        (root / target).write_text(original, encoding="utf-8")
    closed = _tiny_scope_scan(root)
    scope = {"roots": list(_TINY_SCOPE_ROOTS), "opened": opened, "closed": closed}
    return snap.build_snapshot(documents, scope)


def test_an_untouched_tree_still_builds(tiny_tree: Path):
    """The gate must refuse drift, not refuse everything -- fail-closed, not broken."""
    manifest = rp.build_atomic_snapshot(
        tiny_tree, "rev-1", plane_roots=_TINY_ROOTS, scope_roots=_TINY_SCOPE_ROOTS
    )
    assert manifest["revision_binding"] == "source-evidence"
    assert manifest["scope"]["witnessed_files"] == manifest["scope"]["files"]
    assert manifest["node_total"] > 0


def test_mutation_between_plane_extractions_is_refused(tiny_tree: Path):
    """The worktree moves between plane 1 and plane 2; no digest may result."""
    try:
        manifest = _build_with_mutation_between(
            tiny_tree, after="code", target="pkg/mod.py", replacement=_MOD_MUTATED
        )
    except snap.ContractError as exc:
        assert exc.code in _ATOMICITY_CODES, exc
        assert exc.code == "scope_drift", exc  # the bracket sees it first
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
        # the bracket agrees with itself; two planes read the same file differently
        assert exc.code == "witness_conflict", exc
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
        assert exc.code == "scope_drift", exc
    else:
        pytest.fail(
            "a file only one plane reads was mutated after that plane read it and "
            f"the build still produced snapshot_digest={manifest['snapshot_digest']}"
        )


def test_single_reader_mutation_reverted_is_refused_by_the_witness(tiny_tree: Path):
    """The hardest case: one reader, and the bracket is clean at both ends.

    Only the witness/bracket cross-check can see this -- the tree looks
    untouched, and no second plane exists to disagree.
    """
    try:
        manifest = _build_with_mutation_between(
            tiny_tree,
            after="code",  # before the data plane reads conf/obj.json
            target="conf/obj.json",
            replacement='{"outer": {"inner": 1}, "other": 2, "sneaked": 3}',
            revert=True,
        )
    except snap.ContractError as exc:
        assert exc.code == "witness_scope_mismatch", exc
    else:
        pytest.fail(
            "a single-reader mutate-and-revert produced "
            f"snapshot_digest={manifest['snapshot_digest']}"
        )


def test_a_transient_no_plane_read_is_deliberately_NOT_refused(tiny_tree: Path):
    """The documented limit of the gate, kept as evidence rather than as prose.

    conf/obj.json is written after the data plane already read it and reverted
    before the closing scan.  No plane's content depends on the transient
    state, both brackets agree, and every witness matches the bracket -- so the
    snapshot really is a function of one tree state and the build proceeds.
    Widening the gate to refuse this would need a filesystem watch, not a scan.
    """
    manifest = _build_with_mutation_between(
        tiny_tree,
        after="data",  # after the only reader of conf/obj.json
        target="conf/obj.json",
        replacement='{"outer": {"inner": 1}, "other": 2, "sneaked": 3}',
        revert=True,
    )
    clean = rp.build_atomic_snapshot(
        tiny_tree, "rev-1", plane_roots=_TINY_ROOTS, scope_roots=_TINY_SCOPE_ROOTS
    )
    assert manifest["snapshot_digest"] == clean["snapshot_digest"]


def test_a_revision_label_alone_no_longer_binds_the_planes():
    """The refuted claim, kept as a check: equal labels, disagreeing evidence."""
    docs = _four()
    assert all(doc["revision"] == "rev-1" for doc in docs)
    docs[1]["witness"]["a/b.py"] = rp.text_digest("what the type plane actually read")
    assert _refuse(docs) == "witness_conflict"


def test_a_plane_reading_outside_the_declared_scope_is_refused():
    docs = _four()
    scope = _agreeing_scope(docs)
    docs[0]["nodes"][0]["locator"]["path"] = "outside/mod.py"
    docs[0]["witness"]["outside/mod.py"] = rp.text_digest("unbracketed")
    assert _refuse(docs, scope) == "witness_outside_scope"


def test_nodes_without_any_source_evidence_are_refused():
    docs = _four()
    docs[0]["witness"] = {}
    assert _refuse(docs) == "nodes_without_witness"


def test_a_locator_the_plane_never_read_is_refused():
    docs = _four()
    docs[0]["nodes"][0]["locator"]["path"] = "a/never-read.py"
    assert _refuse(docs) == "unwitnessed_locator"


def test_a_missing_scope_bracket_is_not_an_option():
    """An atomicity gate the caller can skip is not a gate."""
    with pytest.raises(TypeError):
        snap.build_snapshot(_four())  # noqa: PLE1120 - the point of the check


@pytest.mark.parametrize(
    "broken",
    [
        {"roots": [], "opened": {}, "closed": {}},
        {"roots": ["a"], "opened": {}},
        {"roots": ["a"], "opened": {}, "closed": {}, "extra": 1},
        {"roots": ["a"], "opened": {"a/b.py": "sha256:short"}, "closed": {}},
        {"roots": ["a"], "opened": {"/abs/b.py": "sha256:" + "0" * 64}, "closed": {}},
    ],
)
def test_a_malformed_scope_is_refused(broken):
    with pytest.raises(snap.ContractError):
        snap.build_snapshot(_four(), broken)


def test_the_scope_bracket_is_not_part_of_snapshot_identity(tiny_tree: Path):
    """A file inside the scope that no plane reads must not move the digest."""
    baseline = rp.build_atomic_snapshot(
        tiny_tree, "rev-1", plane_roots=_TINY_ROOTS, scope_roots=_TINY_SCOPE_ROOTS
    )
    (tiny_tree / "notes" / "unread.json").write_text('{"ignored": true}', encoding="utf-8")
    after = rp.build_atomic_snapshot(
        tiny_tree, "rev-1", plane_roots=_TINY_ROOTS, scope_roots=_TINY_SCOPE_ROOTS
    )
    assert after["snapshot_digest"] == baseline["snapshot_digest"]
    assert after["scope"]["digest"] != baseline["scope"]["digest"]
    assert after["scope"]["unread_files"] == baseline["scope"]["unread_files"] + 1


def test_the_witness_is_the_text_the_extractor_consumed(tiny_tree: Path):
    """Not a second read: the recorded digest is the digest of the parsed text."""
    doc = rp.extract_code(tiny_tree, "rev-1", roots=("pkg",))
    text = (tiny_tree / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert doc["witness"]["pkg/mod.py"] == rp.text_digest(text)
