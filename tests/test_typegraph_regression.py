"""THE THREE REGRESSION THERMOMETERS — the proof that the type layer is ADDITIVE.

The plan calls these non-negotiable, and they are the only tests in the suite
whose job is to fail when a FUTURE change breaks the foundation, rather than to
describe what this lane built. Each one builds the SAME tree twice, with the
type layer off and with it on, and asserts byte-identity of an artifact that
existed before the layer did:

  T1  ``index["duplication"]``            -- invariant I1
  T2  ``build_resolver(...).defs_by_file``-- invariant I2
  T3  ``context_plan.lexical_seed_scores``-- invariant I2, second order

WHY EACH ONE EXISTS (the named failure mode, not a style preference)

T1. ``all_units`` feeds ``clones.renamed_clusters``, which is an EXACT match on
    an ABSTRACTED (Type-2) fingerprint with no similarity threshold and no
    ``max_cluster`` bound, and is reported in the PRECISE tier of the report. A
    dataclass has no interesting body under Type-2 abstraction, so every
    dataclass with the same field count collapses to ONE fingerprint. This repo
    has 176 of them. If a ``TypeDecl`` ever became a ``CodeUnit``, ~176 classes
    would be published as "renamed clones" with full confidence. Classes are
    absent from ``all_units`` today only because of an ``isinstance`` accident in
    ``_units_from_tree``; T1 turns that accident into a guarded invariant.

T2. ``SymbolResolver.resolve`` takes the FIRST match on a bare name, so a class
    ``Foo`` in ``defs_by_file`` displaces a function ``Foo``. Worse,
    ``graph.callees`` resolves EVERY identifier token in a unit body, and field
    names like ``path``/``root``/``name``/``line``/``source``/``module`` are in
    no stop-word list -- each mention would become a fabricated CALL edge in
    ``slice_text``. The fixture file ``field_names_are_common_identifiers.py``
    exists to make that concrete.

T3. The second-order half of I2, and the silent one. ``context_plan._symbol_names``
    reads ``defs_by_file`` WHOLESALE into the BM25 lexical corpus. Extra names
    do not merely add matches: they lengthen the document, and BM25's length
    normalisation then DEMOTES exactly the dataclass-rich files -- a repo-wide
    re-ranking with no error, no exception and no log line. T3 calls the real
    ``lexical_seed_scores`` end to end (see ``TheSeedIsReachableEndToEnd`` for
    the proof that the corpus is genuinely populated and the assertion cannot
    pass vacuously).

WHY NOT A STORED SNAPSHOT OF ``daedalus/``: another agent system is editing this
working tree concurrently, so a captured baseline of the real repo would fail
for reasons that have nothing to do with this layer. Every comparison here is
OFF-vs-ON over the same bytes in the same process, which is the stronger form
anyway: it isolates the flag as the only variable.

TWO TREES, ON PURPOSE. The fixture corpus (``tests/fixtures/typegraph/``) is
shaped so that ``duplication`` is COMPLETELY EMPTY -- excellent sensitivity (a
leak has to create a cluster out of nothing) but it means T1 on the fixture
alone compares two empty dicts, and a comparison of two empty dicts passes for
any reason at all. So a second, tiny tree is generated here whose duplication
block is NON-EMPTY in two sub-blocks, and whose three same-arity dataclasses are
the 176-dataclass catastrophe in miniature. ``TheCatastropheIsReal`` then feeds
those same three classes to ``renamed_clusters`` as CodeUnits and shows the
false cluster appearing -- so the number T1 protects is in the record, and T1 is
demonstrably not a test that passes because nothing can ever happen.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from daedalus.context_plan import _symbol_names, lexical_seed_scores
from daedalus.structcore import clones as clones_mod
from daedalus.structcore.index import build_index, resolution_context
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import CodeUnit, extract_units

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "typegraph"

# Env keys that can move a build. Pinned for the whole module so no thermometer
# reading is a fact about the operator's shell.
_PINNED = ("DAEDALUS_INDEX_TYPES", "DAEDALUS_INDEX_DOCUMENTS",
           "DAEDALUS_CACHE_DIR", "DAEDALUS_NO_CACHE",
           "DAEDALUS_SCAN_MIN_PARALLEL", "DAEDALUS_SCAN_WORKERS")
_SAVED: dict[str, str | None] = {}
_TMP_CACHE = ""
_SECOND_TREE = ""


# --------------------------------------------------------------------------- #
# The second tree: small, generated, and deliberately clone-bearing            #
# --------------------------------------------------------------------------- #
# THREE dataclasses, FIVE fields each, no two field names shared. Under Type-2
# abstraction (identifiers replaced by placeholders) their bodies are the same
# token sequence, so if a class ever reaches ``all_units`` they become one
# renamed cluster of three. That is the 176-dataclass failure at 3-member scale.
_MODELS = '''\
"""Three same-arity dataclasses -- the Type-2 collision in miniature."""
from dataclasses import dataclass


@dataclass
class Alpha:
    first: str
    second: int
    third: bool
    fourth: float
    fifth: str


@dataclass
class Beta:
    alpha: str
    bravo: int
    charlie: bool
    delta: float
    echo: str


@dataclass
class Gamma:
    one: str
    two: int
    three: bool
    four: float
    five: str
'''

# Two byte-identical functions in two files, each well over ``min_loc`` (4), so
# the duplication block of this tree is NOT empty and T1 compares something.
_CLONE_BODY = '''\
"""A real duplicate, so ``duplication`` is non-empty in both builds."""


def summarise(rows):
    total = 0
    for row in rows:
        total += len(row)
    if total > 10:
        return "big"
    if total > 5:
        return "medium"
    return "small"
'''

# Annotations that actually resolve, so the ON build has a non-trivial type
# graph to publish. A thermometer against an empty layer proves nothing.
_USAGE = '''\
"""Annotated call sites, so the ON build has real edges to publish."""
from models import Alpha, Beta, Gamma


def widen(source: Alpha) -> Beta:
    return Beta("", 0, False, 0.0, "")


def narrow(source: Beta) -> Gamma:
    return Gamma("", 0, False, 0.0, "")
'''


def _write_second_tree(root: Path) -> None:
    (root / "models.py").write_text(_MODELS, encoding="utf-8")
    (root / "clone_a.py").write_text(_CLONE_BODY, encoding="utf-8")
    (root / "clone_b.py").write_text(_CLONE_BODY, encoding="utf-8")
    (root / "usage.py").write_text(_USAGE, encoding="utf-8")


def setUpModule() -> None:
    global _TMP_CACHE, _SECOND_TREE
    for name in _PINNED:
        _SAVED[name] = os.environ.get(name)
        os.environ.pop(name, None)
    # ``build_index`` writes a sqlite row per file. Without this the thermometers
    # would read and write the developer's real cache, and one of the questions
    # below is precisely what the cache serves.
    _TMP_CACHE = tempfile.mkdtemp(prefix="tgreg-cache-")
    os.environ["DAEDALUS_CACHE_DIR"] = _TMP_CACHE
    _SECOND_TREE = tempfile.mkdtemp(prefix="tgreg-tree-")
    _write_second_tree(Path(_SECOND_TREE))


def tearDownModule() -> None:
    for name, value in _SAVED.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    shutil.rmtree(_TMP_CACHE, ignore_errors=True)
    shutil.rmtree(_SECOND_TREE, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Canonicalisation helpers                                                     #
# --------------------------------------------------------------------------- #
def _bytes_of(value) -> str:
    """Serialise WITHOUT sorting keys.

    ``sort_keys=True`` would launder an ordering regression into a pass, and
    ordering is load-bearing here: ``duplication``'s clusters are lists whose
    order reaches the report, and ``fan_in``/``modules`` are explicitly sorted
    upstream so that two processes agree. Byte-identity means the bytes, in
    order.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=False, indent=None)


def _canonical_defs(resolver) -> str:
    """``defs_by_file`` flattened to text, preserving insertion order at BOTH
    levels. ``CodeUnit`` is not JSON-serialisable, and comparing the dicts with
    ``==`` would ignore order, so every field of every unit is spelled out."""
    rows = []
    for rel, bucket in resolver.defs_by_file.items():
        rows.append([rel, [
            [name, u.language, u.module, u.name, u.line, u.end_line, u.loc,
             u.source]
            for name, u in bucket.items()
        ]])
    return _bytes_of(rows)


def _build(root, *, types: bool) -> dict:
    """``documents`` and ``types`` are ALWAYS explicit: both consult an env var
    when left as None, so a default would make every reading below a fact about
    the caller's shell rather than about the code."""
    return build_index(root, documents=False, types=types)


def _resolver_for(idx: dict):
    return resolution_context(idx.get("root", ""), key=idx.get("scope_key"))


class _TwoBuilds(unittest.TestCase):
    """One tree, two builds, one flag different. Subclasses set ``TREE``."""

    TREE: Path | str = FIXTURE

    @classmethod
    def setUpClass(cls):
        cls.off = _build(cls.TREE, types=False)
        cls.on = _build(cls.TREE, types=True)


# --------------------------------------------------------------------------- #
# T1 -- duplication (invariant I1)                                             #
# --------------------------------------------------------------------------- #
class T1DuplicationIsByteIdentical(_TwoBuilds):
    """A leaked type record shows up as a clone cluster that was not there.

    To watch this go red: append the extracted ``TypeDecl``s to ``all_units`` in
    ``build_index`` (the naive implementation of step 1 of the plan).
    """

    TREE = FIXTURE

    def test_the_whole_duplication_block_is_byte_identical(self):
        self.assertEqual(_bytes_of(self.off["duplication"]),
                         _bytes_of(self.on["duplication"]))

    def test_each_sub_block_is_byte_identical_separately(self):
        """Per sub-block, so a failure names the pass that broke rather than
        handing a reader a diff of the whole dict."""
        for key in ("unit_clusters", "renamed_clusters", "near_clusters",
                    "window_clusters", "near_excluded_languages"):
            with self.subTest(sub_block=key):
                self.assertEqual(_bytes_of(self.off["duplication"][key]),
                                 _bytes_of(self.on["duplication"][key]))

    def test_the_fixture_block_is_empty_so_a_leak_must_create_a_cluster(self):
        """The fixture's sensitivity, stated rather than assumed.

        Every function in the corpus is below every clone pass's ``min_loc``, so
        all four sub-blocks are empty. That makes the fixture the most sensitive
        tripwire available -- a leaked class cannot hide inside a pre-existing
        cluster, it has to create one from nothing. It ALSO means this class
        alone compares two empty dicts, which is why the second tree exists.
        """
        for key in ("unit_clusters", "renamed_clusters", "near_clusters",
                    "window_clusters"):
            with self.subTest(sub_block=key):
                self.assertEqual(self.on["duplication"][key], [])

    def test_the_layer_was_actually_on(self):
        """Guards against the worst failure mode of an off/on test: both builds
        silently being the same build."""
        self.assertNotIn("types", self.off)
        self.assertTrue(self.on["types"]["enabled"])
        self.assertGreater(self.on["types"]["count"], 0)
        self.assertGreater(self.on["types"]["n_fields"], 0)


class T1DuplicationIsByteIdenticalOnANonEmptyTree(_TwoBuilds):
    """T1 again, on a tree whose duplication block is NOT empty.

    Two empty dicts compare equal for any reason, including "the clone passes
    did not run". Here they ran and found something, so the comparison has
    content on both sides.
    """

    @classmethod
    def setUpClass(cls):
        cls.TREE = Path(_SECOND_TREE)
        super().setUpClass()

    def test_this_tree_really_does_have_clones(self):
        """Non-vacuity, asserted before the identity claim is worth anything."""
        block = self.on["duplication"]
        found = {k: len(block[k]) for k in
                 ("unit_clusters", "renamed_clusters", "near_clusters",
                  "window_clusters")}
        self.assertGreater(sum(found.values()), 0, found)
        self.assertGreater(len(block["unit_clusters"]), 0, found)

    def test_duplication_is_byte_identical(self):
        self.assertEqual(_bytes_of(self.off["duplication"]),
                         _bytes_of(self.on["duplication"]))

    def test_no_cluster_names_a_type_or_a_field(self):
        """The direct reading of I1: whatever is IN the clone report came from a
        function. A leaked class would appear under its own class name.

        Checked against the type layer's own published node list, so the test
        cannot drift out of date if the fixture grows a class.
        """
        declared = {n["name"] for n in self.on["type_nodes"]}
        self.assertTrue(declared, "no type nodes -- the check would be vacuous")
        blob = _bytes_of(self.on["duplication"])
        members = []
        for key in ("unit_clusters", "renamed_clusters", "near_clusters"):
            for cluster in self.on["duplication"][key]:
                # Every clone pass publishes its group as ``sites``; a member row
                # is {module, name, line, loc}.
                for site in cluster["sites"]:
                    members.append(site["name"])
        self.assertTrue(members, "no cluster members -- the check would be vacuous")
        for name in sorted(declared):
            with self.subTest(declared_name=name):
                self.assertNotIn(name, members)
        # And the class names do not appear anywhere in the serialised block,
        # not even in a path or a fingerprint.
        for name in sorted(declared):
            with self.subTest(declared_name=name, where="serialised block"):
                self.assertNotIn(f'"{name}"', blob)

    def test_the_type_layer_saw_these_classes(self):
        """The three dataclasses ARE extracted -- they are simply not units. If
        this fails, the tree stopped exercising the hazard and the identity
        assertions above became decorative."""
        kinds = sorted(n["decl_kind"] for n in self.on["type_nodes"]
                       if n["kind"] == "type")
        self.assertEqual(kinds, ["dataclass", "dataclass", "dataclass"])
        self.assertEqual(self.on["types"]["n_fields"], 15)


class TheCatastropheIsReal(unittest.TestCase):
    """The number T1 protects, measured rather than asserted.

    Feeds the second tree's three dataclasses to ``renamed_clusters`` AS
    ``CodeUnit``s -- which is exactly what a leak into ``all_units`` would do --
    and records that the false cluster appears. Without this, a reader has to
    take on faith that the Type-2 pass would collapse same-arity dataclasses.
    """

    def test_three_dataclasses_as_units_become_one_renamed_cluster(self):
        root = Path(_SECOND_TREE)
        text = (root / "models.py").read_text(encoding="utf-8")
        spec = spec_for("models.py")
        assert spec is not None
        lines = text.splitlines()

        # Build the units a naive "ClassDef is a unit" implementation would emit.
        leaked: list[CodeUnit] = []
        for name, start in (("Alpha", 4), ("Beta", 13), ("Gamma", 22)):
            body = "\n".join(lines[start:start + 7])
            self.assertIn(f"class {name}:", body, "fixture drifted")
            leaked.append(CodeUnit(language="python", module="models.py",
                                   name=name, line=start + 1,
                                   end_line=start + 7, loc=7, source=body))

        real = extract_units("models.py", text, spec)
        clean = clones_mod.renamed_clusters(list(real), {"python": spec}, root)
        dirty = clones_mod.renamed_clusters(list(real) + leaked,
                                            {"python": spec}, root)

        self.assertEqual(clean, [], "the honest build reports no renamed clones")
        self.assertEqual(len(dirty), 1,
                         "a leak must produce exactly the false cluster")
        got = sorted(site["name"] for site in dirty[0]["sites"])
        self.assertEqual(got, ["Alpha", "Beta", "Gamma"])
        self.assertEqual(dirty[0]["names"], ["Alpha", "Beta", "Gamma"])
        # Reported in the PRECISE tier with no similarity threshold and no
        # ``max_cluster`` bound -- which is why this is a catastrophe and not a
        # nuisance. At repo scale the same collapse takes 176 dataclasses.
        self.assertEqual(dirty[0]["count"], 3)
        self.assertEqual(dirty[0]["kind"], "renamed")


# --------------------------------------------------------------------------- #
# T2 -- defs_by_file (invariant I2)                                            #
# --------------------------------------------------------------------------- #
class T2DefsByFileIsByteIdentical(_TwoBuilds):
    """The resolver table is the blast radius of I2, so it is compared whole.

    To watch this go red: pass anything type-shaped into ``build_resolver``'s
    unit list in ``build_index``, or merge ``typegraph.types_by_file`` into
    ``defs_by_file``.
    """

    TREE = FIXTURE

    def test_both_builds_produced_a_resolver(self):
        """Non-vacuity first: ``resolution_context`` returns None for a key it
        does not hold, and ``None == None`` would pass every assertion below."""
        self.assertIsNotNone(_resolver_for(self.off))
        self.assertIsNotNone(_resolver_for(self.on))
        self.assertNotEqual(self.off["scope_key"], self.on["scope_key"],
                            "the two builds must not share a resolver slot")

    def test_defs_by_file_is_byte_identical(self):
        self.assertEqual(_canonical_defs(_resolver_for(self.off)),
                         _canonical_defs(_resolver_for(self.on)))

    def test_the_table_is_populated(self):
        resolver = _resolver_for(self.on)
        self.assertGreater(len(resolver.defs_by_file), 5)
        total = sum(len(b) for b in resolver.defs_by_file.values())
        self.assertGreater(total, 10)

    def test_every_name_in_the_table_came_from_extract_units(self):
        """The airtight form of "contains no class or field name at all".

        Rather than list the names that are allowed (a list that would rot, and
        that would have to carve an exception for the fixture's ``Foo``, which is
        legitimately BOTH a class and a function), this asks the untouched
        pre-feature extractor what each file defines and requires the resolver's
        bucket to be a subset of that. Anything type-shaped is by construction
        not in the answer.
        """
        resolver = _resolver_for(self.on)
        checked = 0
        for rel, bucket in sorted(resolver.defs_by_file.items()):
            path = Path(self.TREE) / rel
            spec = spec_for(rel)
            if spec is None or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            allowed = {u.name for u in extract_units(rel, text, spec)}
            with self.subTest(rel=rel):
                self.assertLessEqual(set(bucket), allowed)
            checked += 1
        self.assertGreater(checked, 5, "nothing was checked")

    def test_no_declared_type_name_entered_the_table_as_a_type(self):
        """A class named ``Foo`` may be in the table only because a FUNCTION
        named ``Foo`` is defined there too (the fixture declares both on
        purpose). So the check is on the DECLARATION SITE, not on the name: no
        unit in the table may sit on a line where a type is declared.
        """
        resolver = _resolver_for(self.on)
        declared_sites = {(n["module"], n["line"]) for n in self.on["type_nodes"]
                          if n["kind"] == "type"}
        self.assertTrue(declared_sites, "no type nodes -- vacuous")
        unit_sites = {(rel, u.line)
                      for rel, bucket in resolver.defs_by_file.items()
                      for u in bucket.values()}
        self.assertEqual(declared_sites & unit_sites, set())

    def test_no_field_name_entered_the_table(self):
        """Field names are the ``callees`` hazard: ``graph.callees`` resolves
        EVERY identifier token in a body, so ``path``/``root``/``name``/``line``/
        ``source``/``module`` in ``defs_by_file`` become fabricated CALL edges in
        every slice. Checked per file, because a field name may legitimately
        coincide with a method name in some OTHER file."""
        resolver = _resolver_for(self.on)
        fields_by_rel: dict[str, set[str]] = {}
        for node in self.on["type_nodes"]:
            if node["kind"] == "field":
                fields_by_rel.setdefault(node["module"], set()).add(node["name"])
        self.assertTrue(fields_by_rel, "no field nodes -- vacuous")
        for rel, names in sorted(fields_by_rel.items()):
            bucket = set(resolver.defs_by_file.get(rel, {}))
            with self.subTest(rel=rel):
                self.assertEqual(sorted(names & bucket), [])

    def test_the_six_generic_identifiers_are_not_resolvable(self):
        """The named hazard, spelled out. ``field_names_are_common_identifiers``
        declares fields called exactly these six; none is in ``graph._STOP`` and
        every one survives ``graph.identifiers``."""
        resolver = _resolver_for(self.on)
        rel = "field_names_are_common_identifiers.py"
        self.assertIn(rel, resolver.defs_by_file)
        for name in ("path", "root", "name", "line", "source", "module"):
            with self.subTest(identifier=name):
                self.assertIsNone(resolver.resolve(name, rel))

    def test_imports_by_file_is_byte_identical_too(self):
        """The resolver's other half. A type edge that reached
        ``import_targets_by_rel`` would move it."""
        self.assertEqual(_bytes_of(sorted(
            (k, list(v)) for k, v in
            _resolver_for(self.off).imports_by_file.items())),
            _bytes_of(sorted(
                (k, list(v)) for k, v in
                _resolver_for(self.on).imports_by_file.items())))


class T2DefsByFileOnTheSecondTree(_TwoBuilds):
    """T2 on the generated tree, where every class is a dataclass and the field
    names are known by construction."""

    @classmethod
    def setUpClass(cls):
        cls.TREE = Path(_SECOND_TREE)
        super().setUpClass()

    def test_defs_by_file_is_byte_identical(self):
        self.assertEqual(_canonical_defs(_resolver_for(self.off)),
                         _canonical_defs(_resolver_for(self.on)))

    def test_models_defines_no_symbol_at_all(self):
        """``models.py`` is nothing but three dataclasses. The honest resolver
        answer is that it defines NOTHING -- either no bucket, or an empty one.
        A leak turns that into three entries."""
        resolver = _resolver_for(self.on)
        self.assertEqual(sorted(resolver.defs_by_file.get("models.py", {})), [])

    def test_no_class_and_no_field_name_is_resolvable_from_the_user(self):
        resolver = _resolver_for(self.on)
        for name in ("Alpha", "Beta", "Gamma", "first", "second", "third",
                     "fourth", "fifth", "alpha", "bravo", "one", "two"):
            with self.subTest(name=name):
                self.assertIsNone(resolver.resolve(name, "usage.py"))
        # The positive control: a real function IS resolvable, so "refuse
        # everything" cannot pass this test.
        self.assertIsNotNone(resolver.resolve("widen", "usage.py"))


# --------------------------------------------------------------------------- #
# T3 -- the lexical seed (invariant I2, second order)                          #
# --------------------------------------------------------------------------- #
# Objectives chosen to make a leak DETECTABLE rather than merely possible:
#   * the six generic field names are the direct I2b probe -- under a leak they
#     become term hits in files that score zero today;
#   * the class names probe the ``TypeDecl`` half;
#   * the last three are ordinary planner queries, which is where the SILENT
#     failure lives: they do not mention a field at all, but a leak lengthens
#     the dataclass-rich documents and BM25 length normalisation re-ranks them.
_OBJECTIVES = (
    "path root name line source module",
    "Record describe holder",
    "Alpha Beta Gamma result",
    "resolve the ambiguous result import",
    "generic containers and union shapes",
    "protocol structural match emit flush",
    "annotation",
)


class T3TheLexicalSeedIsUnchanged(_TwoBuilds):
    """``lexical_seed_scores`` is the real entry point (``plan_context`` calls it
    at context_plan.py:588); it is called here directly with the built index, no
    mock and no stub, so the corpus it scores is the one the planner scores.

    To watch this go red: put anything into ``defs_by_file``. Even names that
    match no query term move every score, because they change the document
    lengths that BM25 normalises against.
    """

    TREE = FIXTURE

    def test_the_corpus_is_really_populated(self):
        """NON-VACUITY, and the reason this test is not a mock.

        ``_symbol_names`` returns ``{}`` when the resolver is missing, and with
        an empty symbol corpus the seed degrades to path terms only -- at which
        point it could not detect the defect it exists to detect, and would still
        pass. So: the resolver is found, symbols were harvested, and they are the
        same symbols in both builds.
        """
        off_symbols = _symbol_names(self.off)
        on_symbols = _symbol_names(self.on)
        self.assertTrue(off_symbols, "empty corpus -- T3 would be vacuous")
        self.assertGreater(sum(len(v) for v in on_symbols.values()), 10)
        self.assertEqual(_bytes_of(sorted(
            (k, list(v)) for k, v in off_symbols.items())),
            _bytes_of(sorted((k, list(v)) for k, v in on_symbols.items())))

    def test_more_than_one_module_scores_so_ranking_is_observable(self):
        """``_normalise_max`` divides by the maximum, so a single-document
        result is always ``{x: 1.0}`` and would hide any re-ranking. At least one
        objective must score several modules for the identity claim to have
        teeth."""
        widths = [len(lexical_seed_scores(self.on, objective).scores)
                  for objective in _OBJECTIVES]
        self.assertGreater(max(widths), 2, dict(zip(_OBJECTIVES, widths)))

    def test_scores_are_byte_identical_for_every_objective(self):
        for objective in _OBJECTIVES:
            with self.subTest(objective=objective):
                off = lexical_seed_scores(self.off, objective)
                on = lexical_seed_scores(self.on, objective)
                self.assertEqual(_bytes_of(off.to_dict()),
                                 _bytes_of(on.to_dict()))

    def test_the_ranking_order_is_byte_identical_too(self):
        """Equal score dicts could still be reached in a different order; the
        planner consumes the ORDER (``fuse_seed_scores`` then packs top-down),
        so it is compared on its own."""
        for objective in _OBJECTIVES:
            with self.subTest(objective=objective):
                off = list(lexical_seed_scores(self.off, objective).scores)
                on = list(lexical_seed_scores(self.on, objective).scores)
                self.assertEqual(off, on)

    def test_a_field_name_query_matches_nothing_it_should_not(self):
        """The sharpest single reading. Under a leak, the six field names of
        ``field_names_are_common_identifiers.py`` enter that file's document six
        times over, and it jumps to the top of this query. Today it must score
        exactly as it does with the layer off -- and, separately, the query must
        not be answered by a file solely because it DECLARES those fields."""
        objective = "path root name line source module"
        off = lexical_seed_scores(self.off, objective)
        on = lexical_seed_scores(self.on, objective)
        self.assertEqual(_bytes_of(off.to_dict()), _bytes_of(on.to_dict()))
        rel = "field_names_are_common_identifiers.py"
        symbols = _symbol_names(self.on).get(rel, ())
        for name in ("path", "root", "line", "source"):
            with self.subTest(field=name):
                self.assertNotIn(name, symbols)

    def test_matched_terms_are_byte_identical(self):
        """``matched_terms`` is published in the receipt, so a leak that somehow
        left the scores alone would still be caught by WHICH terms hit."""
        for objective in _OBJECTIVES:
            with self.subTest(objective=objective):
                off = lexical_seed_scores(self.off, objective)
                on = lexical_seed_scores(self.on, objective)
                self.assertEqual(
                    _bytes_of({k: list(v) for k, v in
                               sorted(off.matched_terms.items())}),
                    _bytes_of({k: list(v) for k, v in
                               sorted(on.matched_terms.items())}))


class T3OnTheSecondTree(_TwoBuilds):
    """T3 where the field names are known by construction, and where a leak
    would be unmissable: ``models.py`` contributes ZERO symbols today."""

    @classmethod
    def setUpClass(cls):
        cls.TREE = Path(_SECOND_TREE)
        super().setUpClass()

    def test_models_contributes_no_lexical_evidence(self):
        self.assertEqual(_symbol_names(self.on).get("models.py", ()), ())

    def test_a_class_name_query_scores_identically(self):
        for objective in ("Alpha Beta Gamma", "widen narrow summarise",
                          "first second third fourth fifth", "models"):
            with self.subTest(objective=objective):
                off = lexical_seed_scores(self.off, objective)
                on = lexical_seed_scores(self.on, objective)
                self.assertEqual(_bytes_of(off.to_dict()),
                                 _bytes_of(on.to_dict()))

    def test_a_field_name_query_answers_nothing(self):
        """``first``/``second``/... appear ONLY as dataclass fields anywhere in
        this tree, so the honest lexical answer is the empty set. If a leak put
        them in the corpus, ``models.py`` would answer -- and this is the one
        assertion in the file that would fail with a NON-empty result rather than
        with a diff."""
        result = lexical_seed_scores(
            self.on, "first second third fourth fifth bravo charlie echo")
        self.assertEqual(dict(result.scores), {})

    def test_the_layer_was_on_and_had_something_to_say(self):
        self.assertTrue(self.on["types"]["enabled"])
        self.assertEqual(self.on["types"]["count"], 3)
        self.assertGreater(self.on["types"]["n_edges"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
