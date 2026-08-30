# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The type/data-structure graph's TRIPWIRE suite — passes against UNMODIFIED code.

This file contains no assertion about the type layer, because the type layer
does not exist yet. Everything here is a BASELINE: a captured fact about what
``daedalus/structcore`` produces over the adversarial fixture repo in
``tests/fixtures/typegraph/`` TODAY. Each one must still hold after the layer
ships. That is the whole point — the plan's regression thermometer
(docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md, "NON-GOALS /
INVARIANTEN") demands proof that the layer is ADDITIVE, and a proof you write
after the fact proves nothing.

WHY A SYNTHETIC FIXTURE AND NOT ``daedalus/`` ITSELF
---------------------------------------------------
The three thermometer facts have to be pinned against a tree that does not move.
``daedalus/`` moves on every commit — and while this lane runs, a second agent
system is editing it concurrently — so a captured snapshot of the real repo
would go red for reasons that have nothing to do with the feature, and would
then be "fixed" by re-capturing, which silently destroys the tripwire. The
fixture is frozen by construction, so a red line here means the code changed.

The three tripwires, and the invariant each one guards:

  I1  ``extract_units`` returns ONLY functions/methods. A ``type``/``field``
      node must never be a ``CodeUnit``, because ``all_units`` feeds
      ``clones.renamed_clusters`` — exact match on an abstracted fingerprint,
      no threshold, no ``max_cluster``, reported in the PRECISE tier. The
      fixture's two four-field dataclasses abstract to one fingerprint, so a
      leak is instantly visible.
  I2  ``graph.build_resolver(...).defs_by_file`` contains only function/method
      names. A class there displaces a same-named function (``setdefault``,
      first wins) and a field name there becomes a fabricated CALL edge in
      every slice (``graph.callees`` resolves every identifier token).
  I4  ``modules`` / ``import_edges`` / ``duplication`` are byte-identical to
      the pre-feature build. Type nodes in the import graph would dilute
      ``fenced_dominance``'s denominator and stand the fence's escalation down
      for a bookkeeping reason.

Every literal below was CAPTURED by running the unmodified code, never typed by
hand. Nothing here touches the network, a model, or a vendor CLI.

ONE WARNING FOR WHOEVER SHIPS THE LAYER (plan item M9): ``index._analyze_all``
reads a DISK cache, and ``cache.file_key`` mixes a sha256 of ``parse.py`` — so
extraction code that lives in ``parse.py`` invalidates every row, and extraction
code in a SIBLING module does not. Verified while building this suite: with the
cache warm, a monkeypatched ``_units_from_tree`` changed nothing at all, and the
suite stayed green against rows computed by the old code. That is precisely the
failure the plan predicts (empty type blocks, no error). This suite passes both
with the cache warm and under ``DAEDALUS_NO_CACHE=1``; if a later stage sees it
pass suspiciously, run it that way before believing it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore.index import resolution_context
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import extract_units

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "typegraph"


# --------------------------------------------------------------------------- #
# Captured baselines                                                           #
# --------------------------------------------------------------------------- #
# The fixture repo is 16 Python files and NOTHING else the index can see
# (README.md is a document, and documents are off unless asked for — every
# build_index call here passes documents=False explicitly so the env var
# DAEDALUS_INDEX_DOCUMENTS cannot move the baseline).
FIXTURE_MODULES = (
    "ambiguous_result_star_import.py",
    "ambiguous_result_try_import.py",
    "cross_module_annotation.py",
    "dataclass_field_count_collision.py",
    "field_names_are_common_identifiers.py",
    "future_annotations_forward_ref.py",
    "generic_containers.py",
    "kind_zoo.py",
    "name_collision_class_and_function.py",
    "pkg_nested/__init__.py",
    "pkg_nested/inner_types.py",
    "protocol_structural_match.py",
    "result_alpha.py",
    "result_beta.py",
    "union_shapes.py",
    "unresolvable_annotations.py",
)

# EMPTY, on purpose and by construction. Every function in the fixture is at
# most three lines long, which is below ``min_loc=4`` for the exact and renamed
# passes and below ``min_loc=6`` for the near pass, and no six consecutive
# normalised lines repeat across two files. So the fixture's real units cannot
# produce a cluster — which makes this the most sensitive form of the I1
# tripwire available: ONE class arriving in ``all_units`` turns a [] into a
# cluster, because the fixture's four-field dataclasses are a renamed pair.
DUPLICATION_BASELINE = {
    "unit_clusters": [],
    "renamed_clusters": [],
    "near_clusters": [],
    "window_clusters": [],
    "near_excluded_languages": [],
}

# Python-precise import edges (rel -> rels). The type layer must not add, drop
# or re-target a single one: this is the graph ``fenced_dominance`` measures.
IMPORT_EDGES_BASELINE = {
    "ambiguous_result_star_import.py": ["result_alpha.py", "result_beta.py"],
    "ambiguous_result_try_import.py": ["result_alpha.py", "result_beta.py"],
    "cross_module_annotation.py": ["kind_zoo.py", "pkg_nested/inner_types.py"],
}

# ``extract_units`` output, in ORDER, as (name, line). The order is load-bearing
# and not merely cosmetic: the clone passes consume ``all_units`` positionally,
# so a reordering is a behaviour change even when the set is unchanged.
UNITS_BASELINE = {
    "ambiguous_result_star_import.py": [("widen", 18)],
    "ambiguous_result_try_import.py": [("consume", 20), ("produce", 24)],
    "cross_module_annotation.py": [("owner", 26), ("ticket_of", 30)],
    "dataclass_field_count_collision.py": [("pair_span", 47), ("quad_alpha_label", 51)],
    "field_names_are_common_identifiers.py": [("describe", 32)],
    "future_annotations_forward_ref.py": [("take_quoted", 33), ("link", 37)],
    "generic_containers.py": [
        ("first_item", 21), ("by_sku", 25), ("grouped", 29), ("nested_tuple", 33)],
    "kind_zoo.py": [("__init__", 35), ("accept", 56)],
    "name_collision_class_and_function.py": [("Foo", 22), ("call_foo", 27)],
    "pkg_nested/__init__.py": [],
    "pkg_nested/inner_types.py": [("short_ref", 15)],
    # Six method definitions, three of them named ``emit`` — the structural
    # Protocol hazard. All six are units; ``defs_by_file`` keeps only two.
    "protocol_structural_match.py": [
        ("emit", 18), ("flush", 20), ("emit", 26), ("flush", 29),
        ("emit", 36), ("flush", 38)],
    "result_alpha.py": [("make_alpha", 17)],
    "result_beta.py": [("make_beta", 17)],
    "union_shapes.py": [
        ("take_optional", 27), ("take_pep604", 31), ("take_union", 35),
        ("take_nested", 39), ("produce_union", 43)],
    "unresolvable_annotations.py": [
        ("takes_any", 24), ("unannotated", 28), ("phantom", 32),
        ("phantom_container", 36)],
}

# ``defs_by_file`` — bare NAME -> unit, ``setdefault`` so the first definition
# wins. Note the collapse in protocol_structural_match.py (six defs, two keys)
# and the absence of ``pkg_nested/__init__.py`` (a file that defines nothing
# gets no bucket at all).
DEFS_BASELINE = {
    "ambiguous_result_star_import.py": ["widen"],
    "ambiguous_result_try_import.py": ["consume", "produce"],
    "cross_module_annotation.py": ["owner", "ticket_of"],
    "dataclass_field_count_collision.py": ["pair_span", "quad_alpha_label"],
    "field_names_are_common_identifiers.py": ["describe"],
    "future_annotations_forward_ref.py": ["link", "take_quoted"],
    "generic_containers.py": ["by_sku", "first_item", "grouped", "nested_tuple"],
    "kind_zoo.py": ["__init__", "accept"],
    "name_collision_class_and_function.py": ["Foo", "call_foo"],
    "pkg_nested/inner_types.py": ["short_ref"],
    "protocol_structural_match.py": ["emit", "flush"],
    "result_alpha.py": ["make_alpha"],
    "result_beta.py": ["make_beta"],
    "union_shapes.py": [
        "produce_union", "take_nested", "take_optional", "take_pep604", "take_union"],
    "unresolvable_annotations.py": [
        "phantom", "phantom_container", "takes_any", "unannotated"],
}

# Every type DECLARED in the fixture. If one of these appears as a unit name or
# as a ``defs_by_file`` key, a ClassDef has become a CodeUnit.
#
# ``Foo`` is deliberately NOT in this set: the fixture declares BOTH a class Foo
# and a function Foo in one file, so the name alone cannot distinguish a leak.
# That case is caught by shape (``_starts_a_function``) and by the dedicated
# line-number assertion in ``test_class_foo_did_not_displace_function_foo``.
DECLARED_TYPE_NAMES = frozenset({
    "Alpha", "Assignment", "Beta", "Config", "DeclaredEmitter", "Emitter",
    "Emitter", "FileEmitter", "Item", "Later", "Mode", "Node", "PairOnly",
    "PlainHolder", "Point", "QuadAlpha", "QuadBeta", "Record", "Result",
    "Sink", "Ticket", "User",
})

# Every class-body FIELD name in the fixture. None is in ``graph._STOP`` and
# every one is longer than two characters, so ``graph.identifiers`` keeps all of
# them — which is precisely why none may ever become a resolvable symbol.
DECLARED_FIELD_NAMES = frozenset({
    "FAST", "SLOW", "child", "fatal", "first", "fourth", "four", "host",
    "label", "left", "limit", "line", "module", "name", "note", "ok", "one",
    "parent", "path", "port", "reason", "retries", "right", "root", "second",
    "sku", "source", "summary", "tag", "third", "three", "ticket", "ticket_id",
    "two", "user", "user_id", "value", "weight", "x", "y",
})


def _starts_a_function(source: str) -> bool:
    """Is the first non-decorator, non-blank line of ``source`` a ``def``?

    A NAME check cannot catch the class/function homonym, and a name check is
    also what a future refactor would keep passing by accident. The shape of the
    extracted source is the ground truth: a ``CodeUnit`` whose body starts with
    ``class`` is a leaked type node no matter what it is called.
    """
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("@") or line.startswith("#"):
            continue
        return line.startswith("def ") or line.startswith("async def ")
    return False


def _fixture_files() -> list[tuple[str, str]]:
    """(rel, text) for every Python file in the fixture, sorted."""
    out = []
    for path in sorted(FIXTURE.rglob("*.py")):
        rel = path.relative_to(FIXTURE).as_posix()
        out.append((rel, path.read_text(encoding="utf-8")))
    return out


class FixtureCorpusIsIntact(unittest.TestCase):
    """The corpus itself is an artifact, so its shape is asserted before anything
    is measured over it. A hazard file deleted or renamed by a later stage would
    otherwise make the tripwires below pass by having nothing to trip on."""

    def test_the_fixture_repo_is_exactly_the_files_it_documents(self):
        rels = [rel for rel, _ in _fixture_files()]
        self.assertEqual(rels, sorted(FIXTURE_MODULES))

    def test_every_fixture_file_parses(self):
        """A fixture that does not parse yields zero units and zero types, which
        would read as 'the feature found nothing' rather than as a broken
        fixture. ``ast.parse`` failures inside structcore are swallowed by
        design (``_python_units`` returns []), so nothing downstream would say
        so."""
        import ast

        for rel, text in _fixture_files():
            with self.subTest(rel=rel):
                ast.parse(text)   # raises SyntaxError -> the test fails loudly

    def test_the_readme_names_every_hazard_file(self):
        readme = (FIXTURE / "README.md").read_text(encoding="utf-8")
        for rel in FIXTURE_MODULES:
            with self.subTest(rel=rel):
                self.assertIn(rel, readme)


class ExtractUnitsSeesOnlyFunctions(unittest.TestCase):
    """TRIPWIRE I1 — ``type``/``field`` are forest nodes only, never CodeUnits.

    To watch this go red: add ``ast.ClassDef`` to the isinstance test in
    ``parse._units_from_tree``. Both assertions here fail, and so does the
    ``duplication`` baseline below (the two four-field dataclasses become a
    renamed-clone cluster in the precise tier)."""

    def test_units_are_byte_for_byte_the_captured_baseline(self):
        for rel, text in _fixture_files():
            spec = spec_for(rel.rsplit("/", 1)[-1])
            units = extract_units(rel, text, spec)
            with self.subTest(rel=rel):
                self.assertEqual([(u.name, u.line) for u in units],
                                 UNITS_BASELINE[rel])

    def test_no_unit_is_a_class_or_a_field(self):
        for rel, text in _fixture_files():
            spec = spec_for(rel.rsplit("/", 1)[-1])
            for unit in extract_units(rel, text, spec):
                with self.subTest(rel=rel, name=unit.name, line=unit.line):
                    self.assertTrue(
                        _starts_a_function(unit.source),
                        f"{rel}:{unit.line} {unit.name} is not a function body:\n"
                        f"{unit.source[:200]}")
                    self.assertNotIn(unit.name, DECLARED_TYPE_NAMES)
                    self.assertNotIn(unit.name, DECLARED_FIELD_NAMES)


class IndexBaseline(unittest.TestCase):
    """TRIPWIRE I4 (+ the ``duplication`` half of I1) over the built index."""

    @classmethod
    def setUpClass(cls):
        # documents=False EXPLICITLY: ``documents_enabled(None)`` consults
        # DAEDALUS_INDEX_DOCUMENTS, so leaving it to the default would make
        # every baseline in this class depend on the caller's environment.
        cls.idx = build_index(FIXTURE, documents=False)

    def test_duplication_block_is_the_captured_baseline(self):
        self.assertEqual(self.idx["duplication"], DUPLICATION_BASELINE)

    def test_modules_are_code_files_only(self):
        """A ``type`` node must never appear here. ``modules`` keys are the
        denominator of ``fenced_dominance`` via ``graph._graph_nodes``, and a
        node with no forward import edges lands in the denominator and never in
        the numerator — pushing the fence's stand-down threshold the wrong way
        for a bookkeeping reason (real money, wrong cause)."""
        self.assertEqual(sorted(self.idx["modules"]), sorted(FIXTURE_MODULES))
        self.assertEqual(self.idx["n_files"], len(FIXTURE_MODULES))

    def test_import_edges_are_the_captured_baseline(self):
        self.assertEqual(self.idx["import_edges"], IMPORT_EDGES_BASELINE)

    def test_graph_nodes_are_code_files_only(self):
        """The safety-graph node set, asked the way the fence asks it."""
        from daedalus.structcore.graph import _graph_nodes

        self.assertEqual(sorted(_graph_nodes(self.idx)), sorted(FIXTURE_MODULES))

    def test_the_index_carries_no_type_layer_yet(self):
        """States the pre-condition out loud. When the layer ships, THIS is the
        assertion that legitimately changes — and it changes to name the new key
        explicitly, so nobody can add a relation layer without editing a line
        that says a relation layer was added.

        THE LAYER HAS SHIPPED (stage 3, 2026-07-30), and this assertion did NOT
        need to change — which is the outcome worth recording rather than one
        worth quietly accepting. ``types``, ``type_nodes`` and ``type_edges`` are
        published under an OPT-IN gate (``types=True`` /
        ``DAEDALUS_INDEX_TYPES=1``, mirroring ``documents``), so an unconfigured
        build still carries none of them and the sentence above is still true of
        the DEFAULT. What this test now pins is therefore stronger than what it
        was written to pin: not "the feature does not exist" but "the feature is
        off unless asked for". ``tests/test_typegraph_index.py`` owns the
        on-versus-off comparisons; if the default ever flips, this line is the
        one that has to be edited, and the edit still has to name the key.
        ``fields`` stays in the list because no such key was ever published — the
        field records live inside ``type_nodes``.
        """
        for key in ("types", "type_edges", "type_nodes", "fields"):
            with self.subTest(key=key):
                self.assertNotIn(key, self.idx)

    def test_rebuild_is_identical(self):
        again = build_index(FIXTURE, documents=False)
        for key in ("duplication", "modules", "import_edges",
                    "import_edges_reverse", "dependencies", "fan_in"):
            with self.subTest(key=key):
                self.assertEqual(again[key], self.idx[key])


class ResolverHoldsOnlyFunctions(unittest.TestCase):
    """TRIPWIRE I2 — ``defs_by_file`` is untouched by the type layer.

    Annotation resolution gets a NEW ``types_by_file`` table. To watch this go
    red: have ``build_resolver`` accept class units. ``Foo`` then resolves to
    the class (line 17, not 22), and any field name added to the table appears
    as a key here — and, one layer out, as a fabricated CALL edge in
    ``slice_text`` and as a new document in ``context_plan``'s BM25 corpus."""

    @classmethod
    def setUpClass(cls):
        idx = build_index(FIXTURE, documents=False)
        cls.resolver = resolution_context(FIXTURE, idx["scope_key"])

    def test_a_resolver_was_built(self):
        self.assertIsNotNone(self.resolver)

    def test_defs_by_file_is_the_captured_baseline(self):
        got = {rel: sorted(defs)
               for rel, defs in self.resolver.defs_by_file.items()}
        self.assertEqual(got, DEFS_BASELINE)

    def test_every_definition_is_a_function(self):
        for rel, defs in sorted(self.resolver.defs_by_file.items()):
            for name, unit in sorted(defs.items()):
                with self.subTest(rel=rel, name=name):
                    self.assertTrue(_starts_a_function(unit.source),
                                    f"{rel}:{unit.line} {name} is not a function")

    def test_no_field_name_is_resolvable(self):
        """The six names the review called out by name — ``path``, ``root``,
        ``name``, ``line``, ``source``, ``module`` — plus every other field in
        the corpus. None is in ``graph._STOP``, so each one would resolve."""
        for rel, defs in sorted(self.resolver.defs_by_file.items()):
            leaked = sorted(DECLARED_FIELD_NAMES & set(defs))
            with self.subTest(rel=rel):
                self.assertEqual(leaked, [])

    def test_no_class_name_is_resolvable(self):
        for rel, defs in sorted(self.resolver.defs_by_file.items()):
            leaked = sorted(DECLARED_TYPE_NAMES & set(defs))
            with self.subTest(rel=rel):
                self.assertEqual(leaked, [])

    def test_class_foo_did_not_displace_function_foo(self):
        """The homonym case, pinned by LINE because the name cannot tell them
        apart. class Foo is declared first, and ``setdefault`` means first wins,
        so admitting classes silently rebinds ``Foo`` from callable code to a
        class body — for this file and for every file that imports it."""
        defs = self.resolver.defs_by_file["name_collision_class_and_function.py"]
        foo = defs["Foo"]
        self.assertEqual((foo.name, foo.line), ("Foo", 22))
        self.assertTrue(_starts_a_function(foo.source))
        self.assertIn("value.upper()", foo.source)

    def test_callees_of_a_field_heavy_body_are_empty(self):
        """``describe`` mentions ``module``, ``line`` and ``source`` in its body.
        Today that yields NO call edges. With field names in the resolver it
        would yield three — and they reach the CALLEES block of a distilled
        slice, i.e. a model is told a function calls ``line``."""
        from daedalus.structcore.graph import callees

        defs = self.resolver.defs_by_file["field_names_are_common_identifiers.py"]
        focus = defs["describe"]
        all_units = [u for bucket in self.resolver.defs_by_file.values()
                     for u in bucket.values()]
        hits = callees(focus, all_units, self.resolver)
        self.assertEqual([u.name for u in hits], [])


class DeterminismAcrossProcesses(unittest.TestCase):
    """Two processes must produce byte-identical output.

    Not a style point: ``resolve`` returns the FIRST import that defines a name
    and ``callees`` iterates a set, so unordered iteration used to make the
    distilled slice depend on PYTHONHASHSEED (measured: 3 distinct slice hashes
    over 5 seeds). The type layer adds new dict/set iterations over annotations,
    so the guard is installed here BEFORE there is anything to guard — a later
    stage inherits a red test instead of writing its own."""

    SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from daedalus.structcore import build_index
from daedalus.structcore.index import resolution_context
idx = build_index(sys.argv[2], documents=False)
res = resolution_context(sys.argv[2], idx["scope_key"])
print(json.dumps({
    "duplication": idx["duplication"],
    "modules": sorted(idx["modules"]),
    "import_edges": idx["import_edges"],
    "import_edges_reverse": idx["import_edges_reverse"],
    "dependencies": idx["dependencies"],
    "fan_in": idx["fan_in"],
    "defs": {k: sorted(v) for k, v in sorted(res.defs_by_file.items())},
    "imports_by_file": {k: list(v)
                        for k, v in sorted(res.imports_by_file.items())},
}, sort_keys=True))
"""

    def _run(self, seed: str) -> str:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env.pop("DAEDALUS_INDEX_DOCUMENTS", None)
        proc = subprocess.run(
            [sys.executable, "-c", self.SCRIPT, str(REPO_ROOT), str(FIXTURE)],
            capture_output=True, text=True, env=env, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return proc.stdout.strip()

    def test_two_hash_seeds_agree_byte_for_byte(self):
        first = self._run("0")
        second = self._run("1")
        self.assertEqual(json.loads(first), json.loads(second))
        self.assertEqual(first, second)

    def test_the_subprocess_agrees_with_the_captured_baseline(self):
        payload = json.loads(self._run("0"))
        self.assertEqual(payload["duplication"], DUPLICATION_BASELINE)
        self.assertEqual(payload["defs"], DEFS_BASELINE)
        self.assertEqual(payload["import_edges"], IMPORT_EDGES_BASELINE)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
