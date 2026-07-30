"""Stage 1 of the type/data-structure graph: EXTRACTION in ``parse.py``.

What this suite is for, in one sentence: prove that the extractor reads every
declaration shape and every annotation spelling in the adversarial fixture
corpus, and prove that it did so WITHOUT moving ``extract_units`` a single byte.

The second half is the load-bearing one. Classes are absent from ``all_units``
today only because ``parse._units_from_tree`` tests ``isinstance(node,
(FunctionDef, AsyncFunctionDef))``. That accident is now a deliberate invariant
(I1): a ``ClassDef`` reaching ``all_units`` would be fingerprinted by
``clones.renamed_clusters`` — exact match on an abstracted fingerprint, no
similarity threshold, no cluster cap, published in the PRECISE tier — so every
dataclass sharing a field count would be reported as a full-confidence renamed
clone. ``tests/test_typegraph_fixture.py`` holds the captured baselines that
catch it at index level; the tests here catch it at the source of the leak, and
also pin the STRUCTURAL guard that makes the leak impossible rather than merely
untested: ``TypeDecl``/``FieldDecl``/``SignatureDecl`` carry no ``source`` and
no ``loc``, so the clone pass raises ``AttributeError`` instead of quietly
producing a wrong report.

Every annotation assertion below is about RAW TEXT. Nothing in stage 1 resolves
a name, and nothing in stage 1 knows what repo it is looking at — an annotation
is a string until stage 2 has the whole file set to resolve it against.

Corpus: ``tests/fixtures/typegraph/`` (see its README for the hazard per file).
This suite reads those files off disk and never writes anything, never builds an
index, never touches the disk cache, the network, a model or a vendor CLI.
"""
from __future__ import annotations

import ast
import dataclasses
import sys
import unittest
from pathlib import Path

from daedalus.structcore import languages, parse

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "typegraph"

# The corpus, as repo-relative POSIX paths -- the same namespace
# ``CodeUnit.module`` uses, so a record's ``module`` is comparable to a unit's.
CORPUS = tuple(sorted(p.relative_to(FIXTURES).as_posix()
                      for p in FIXTURES.rglob("*.py")))


def _read(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


def _facts(rel: str) -> parse.PyTypeFacts:
    return parse.python_type_facts(rel, _read(rel))


def _types(rel: str) -> dict[str, parse.TypeDecl]:
    return {t.qualname: t for t in _facts(rel).types}


def _signatures(rel: str) -> dict[str, parse.SignatureDecl]:
    return {s.qualname: s for s in _facts(rel).signatures}


def _fields(rel: str, owner: str) -> list[parse.FieldDecl]:
    return [f for f in _facts(rel).fields if f.owner == owner]


def _param(sig: parse.SignatureDecl, name: str) -> parse.ParamDecl:
    return next(p for p in sig.params if p.name == name)


class CorpusIsWhatWeThinkItIs(unittest.TestCase):
    """A guard on the guard: if the corpus moves, these tests stop meaning what
    they claim, so the file list is pinned here as well as in the fixture
    suite."""

    def test_the_corpus_is_the_documented_file_set(self):
        self.assertEqual(CORPUS, (
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
        ))


# ==========================================================================  #
# I1 -- the extractor did not move the unit extractor                          #
# ==========================================================================  #
class UnitsAreUntouched(unittest.TestCase):
    """The whole point of stage 1: additive. If any test in this class fails,
    the clone passes have been handed something they must never see."""

    def test_units_are_identical_through_the_new_entry_point(self):
        """``python_units_imports_and_types`` must be a strict superset of
        ``python_units_and_imports``: same units, same order, same bytes, and
        the same import records. Order matters because the clone passes consume
        ``all_units`` positionally."""
        for rel in CORPUS:
            with self.subTest(rel=rel):
                text = _read(rel)
                old_units, old_imports = parse.python_units_and_imports(rel, text)
                units, imports, _ = parse.python_units_imports_and_types(rel, text)
                self.assertEqual(units, old_units)
                self.assertEqual(imports, old_imports)

    def test_units_are_identical_to_the_public_extractor(self):
        spec = languages.spec_for("x.py")
        for rel in CORPUS:
            with self.subTest(rel=rel):
                text = _read(rel)
                units, _, _ = parse.python_units_imports_and_types(rel, text)
                self.assertEqual(units, parse.extract_units(rel, text, spec))

    def test_no_unit_is_a_class_or_a_field(self):
        """Cross-check against the ast directly: the unit names for each file
        are EXACTLY the FunctionDef/AsyncFunctionDef names, so no class name and
        no field name is in there."""
        for rel in CORPUS:
            with self.subTest(rel=rel):
                text = _read(rel)
                tree = ast.parse(text)
                expected = sorted(
                    node.name for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                units, _, facts = parse.python_units_imports_and_types(rel, text)
                self.assertEqual(sorted(u.name for u in units), expected)
                unit_names = {u.name for u in units}
                for decl in facts.types:
                    if decl.kind != "class":
                        self.assertNotIn(decl.name, unit_names)
                for fld in facts.fields:
                    self.assertNotIn(fld.name, unit_names)

    def test_a_type_record_is_not_shaped_like_a_code_unit(self):
        """The structural half of I1. ``clones.fingerprint`` reads ``.source``
        and ``metrics.file_metrics`` reads ``.loc``; neither exists on a type
        record, so a leak into ``all_units`` is an AttributeError at the first
        clone pass instead of 176 dataclasses published as renamed clones.

        This is the OPPOSITE choice from ``markdown.DocSection``, which was made
        field-compatible with ``CodeUnit`` on purpose so it could reach
        ``build_resolver``."""
        unit_only = {"source", "loc"}
        for cls in (parse.TypeDecl, parse.FieldDecl, parse.SignatureDecl,
                    parse.ParamDecl):
            with self.subTest(cls=cls.__name__):
                names = {f.name for f in dataclasses.fields(cls)}
                self.assertEqual(names & unit_only, set())
                self.assertFalse(issubclass(cls, parse.CodeUnit))

    def test_every_record_type_is_frozen_and_hashable(self):
        """Frozen so a record cannot be mutated after it crosses a process
        boundary, and hashable so a consumer can dedupe without inventing a key.
        ``PyTypeFacts`` being all-tuples is also what makes it safe as a plain
        dataclass default on ``FileAnalysis`` (no ``default_factory``)."""
        for cls in (parse.TypeDecl, parse.FieldDecl, parse.ParamDecl,
                    parse.SignatureDecl, parse.AliasImport, parse.PyTypeFacts,
                    parse.Annotation):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(cls.__dataclass_params__.frozen)
        self.assertEqual(hash(parse.PyTypeFacts()), hash(parse.PyTypeFacts()))

    def test_annotation_capture_does_not_mutate_the_shared_tree(self):
        """The unit walk, the import walk and the type walk share ONE tree.
        ``annotation_text`` rewrites forward-ref strings into the names they
        spell, so it must copy first -- otherwise the walk that runs second sees
        a tree the walk that ran first edited under it.

        The source here is chosen to make the mutation OBSERVABLE: a bare
        ``Constant`` is REPLACED (which cannot be seen from the parent), while a
        quoted name nested inside a subscript is rewritten IN PLACE. A test over
        a file with only top-level quoted annotations passes even without the
        copy, which is how this test was found to be vacuous."""
        text = ('class Holder:\n'
                '    child: dict[str, "Later"]\n'
                'def f(a: list["Later"]) -> tuple[int, "Later"]: ...\n'
                'class Later: pass\n')
        tree = ast.parse(text)
        before = ast.dump(tree)
        facts = parse._type_facts_from_tree(tree, "x.py")
        self.assertEqual(ast.dump(tree), before)
        # ...and the capture really did fold the quoted spelling, so the guard
        # is not passing merely because nothing happened.
        self.assertEqual(facts.fields[0].annotation, "dict[str, Later]")
        self.assertEqual(facts.signatures[0].returns, "tuple[int, Later]")


# ==========================================================================  #
# Declaration shapes                                                          #
# ==========================================================================  #
class DeclarationKinds(unittest.TestCase):
    """kind_zoo.py exists so a stage that only understands ``@dataclass`` fails
    HERE rather than somewhere that looks like an unrelated miss."""

    def test_the_kind_zoo_is_classified_shape_by_shape(self):
        types = _types("kind_zoo.py")
        self.assertEqual(
            {q: t.kind for q, t in types.items()},
            {"User": "dataclass", "PlainHolder": "class", "Point": "namedtuple",
             "Config": "typeddict", "Mode": "enum", "Sink": "protocol"},
        )

    def test_bases_and_decorators_are_raw_text(self):
        types = _types("kind_zoo.py")
        self.assertEqual(types["User"].bases, ())
        self.assertEqual(types["User"].decorators, ("dataclass",))
        self.assertEqual(types["Config"].bases, ("TypedDict",))
        self.assertEqual(types["Config"].decorators, ())
        self.assertEqual(types["Sink"].bases, ("Protocol",))

    def test_a_declared_base_is_recorded_and_a_structural_match_is_not(self):
        """``inherits`` is stage 3's edge, but the EVIDENCE for it is here:
        ``DeclaredEmitter`` says ``(Emitter)`` and ``FileEmitter`` says nothing
        while implementing the same members. Stage 1 must report the difference
        rather than erase it -- ``emit``/``flush`` are common enough that the
        coincidence is the normal case."""
        types = _types("protocol_structural_match.py")
        self.assertEqual(types["Emitter"].kind, "protocol")
        self.assertEqual(types["DeclaredEmitter"].bases, ("Emitter",))
        self.assertEqual(types["FileEmitter"].bases, ())
        self.assertEqual(types["FileEmitter"].kind, "class")

    def test_a_class_and_a_function_of_the_same_name_are_both_reported(self):
        """I2's hazard file. ``defs_by_file`` must keep the FUNCTION ``Foo``
        (``setdefault``, first wins, and the ClassDef comes first in source
        order), which is asserted in the fixture suite. Stage 1's job is the
        other half: report both facts, in their own tables, so nothing has to
        choose."""
        rel = "name_collision_class_and_function.py"
        self.assertEqual(_types(rel)["Foo"].kind, "class")
        self.assertEqual(_types(rel)["Foo"].line, 16)
        sig = _signatures(rel)["Foo"]
        self.assertEqual(sig.line, 22)
        self.assertEqual(sig.returns, "str")
        # And the class did not become a unit.
        units, _, _ = parse.python_units_imports_and_types(rel, _read(rel))
        self.assertEqual([(u.name, u.line) for u in units],
                         [("Foo", 22), ("call_foo", 27)])

    def test_qualnames_follow_python_s_own_shape(self):
        text = (
            "class Outer:\n"
            "    class Inner:\n"
            "        x: int\n"
            "    def method(self) -> None:\n"
            "        def helper() -> int:\n"
            "            return 0\n"
            "        class Local:\n"
            "            y: str\n"
            "def top() -> None: ...\n"
        )
        facts = parse.python_type_facts("m.py", text)
        self.assertEqual([t.qualname for t in facts.types],
                         ["Outer", "Outer.Inner", "Outer.method.<locals>.Local"])
        self.assertEqual([s.qualname for s in facts.signatures],
                         ["Outer.method", "Outer.method.<locals>.helper", "top"])
        # Leaf names stay leaf names -- that is what CodeUnit.name holds, so it
        # is what a consumer joins a signature to a unit on.
        self.assertEqual([t.name for t in facts.types], ["Outer", "Inner", "Local"])

    def test_a_type_alias_is_a_declaration_and_a_bare_assignment_is_not(self):
        text = (
            "from typing import NewType, TypeAlias\n"
            "Vec: TypeAlias = list[int]\n"
            "UserId = NewType('UserId', int)\n"
            "Shortcut = int\n"
            "COUNT = 3\n"
        )
        facts = parse.python_type_facts("m.py", text)
        self.assertEqual([(t.qualname, t.kind, t.alias_target) for t in facts.types],
                         [("Vec", "alias", "list[int]"),
                          ("UserId", "alias", "int")])
        # ``Shortcut = int`` is refused on purpose: at module level that shape is
        # far more often a constant, and minting a type node for it would
        # fabricate a declaration nobody wrote.
        self.assertEqual(facts.fields, ())

    def test_a_syntax_error_yields_empty_facts_and_never_raises(self):
        facts = parse.python_type_facts("broken.py", "class Foo(:\n")
        self.assertEqual(facts, parse.PyTypeFacts(module="broken.py"))
        units, imports, facts2 = parse.python_units_imports_and_types(
            "broken.py", "def f(:\n")
        self.assertEqual((units, imports), ([], []))
        self.assertEqual(facts2, parse.PyTypeFacts(module="broken.py"))

    def test_declarations_inside_a_type_checking_guard_are_found(self):
        """``if TYPE_CHECKING:`` and ``try/except ImportError`` are the two
        places a real repo hides its type vocabulary. The descent carries the
        class-body flag through every statement container, so a field declared
        under an ``if`` in a class body is still a field."""
        text = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from other import Late\n"
            "    class Guarded:\n"
            "        x: Late\n"
            "class Conditional:\n"
            "    if TYPE_CHECKING:\n"
            "        y: int\n"
            "    else:\n"
            "        z: str\n"
        )
        facts = parse.python_type_facts("m.py", text)
        self.assertEqual([t.qualname for t in facts.types],
                         ["Guarded", "Conditional"])
        self.assertEqual([(f.owner, f.name, f.annotation) for f in facts.fields],
                         [("Guarded", "x", "Late"),
                          ("Conditional", "y", "int"),
                          ("Conditional", "z", "str")])
        self.assertIn("Late", [a.local for a in facts.aliases])


# ==========================================================================  #
# Fields                                                                      #
# ==========================================================================  #
class Fields(unittest.TestCase):

    def test_dataclass_fields_are_annotated_class_body_assignments(self):
        rel = "dataclass_field_count_collision.py"
        self.assertEqual(
            [(f.name, f.annotation, f.origin) for f in _fields(rel, "QuadAlpha")],
            [("one", "int", "annassign"), ("two", "str", "annassign"),
             ("three", "float", "annassign"), ("four", "bool", "annassign")],
        )

    def test_field_names_that_are_ordinary_identifiers_are_still_only_fields(self):
        """I2b. ``path``/``root``/``name``/``line``/``source``/``module`` are in
        no stop-list, so if they ever reached ``defs_by_file`` then
        ``graph.callees`` -- which resolves EVERY identifier token in a body --
        would fabricate a CALL edge per mention and a slice would tell a model
        that a function calls ``line``. Stage 1 keeps them in the fields table
        and nowhere else."""
        rel = "field_names_are_common_identifiers.py"
        self.assertEqual([f.name for f in _fields(rel, "Record")],
                         ["path", "root", "name", "line", "source", "module"])
        units, _, facts = parse.python_units_imports_and_types(rel, _read(rel))
        self.assertEqual([u.name for u in units], ["describe"])
        self.assertEqual({f.origin for f in facts.fields}, {"annassign"})

    def test_an_instance_attribute_is_a_field_with_no_annotation(self):
        """``self.x = ...`` is real state and usually unannotated. It is
        reported with ``origin="self"`` and an EMPTY annotation rather than
        skipped (a skip is a silent coverage lie) and rather than guessed from
        the assigned value (that is the inference sidecar's job, not the
        core's)."""
        rows = _fields("kind_zoo.py", "PlainHolder")
        self.assertEqual([(f.name, f.annotation, f.origin) for f in rows],
                         [("limit", "int", "annassign"),
                          ("limit", "", "self"),
                          ("tag", "", "self")])

    def test_enum_members_are_values_and_never_carry_an_annotation(self):
        rows = _fields("kind_zoo.py", "Mode")
        self.assertEqual([(f.name, f.annotation, f.origin) for f in rows],
                         [("FAST", "", "enum_member"), ("SLOW", "", "enum_member")])

    def test_typeddict_and_namedtuple_fields_are_first_class(self):
        self.assertEqual(
            [(f.name, f.annotation) for f in _fields("kind_zoo.py", "Config")],
            [("host", "str"), ("port", "int")])
        self.assertEqual(
            [(f.name, f.annotation) for f in _fields("kind_zoo.py", "Point")],
            [("x", "float"), ("y", "float")])

    def test_a_receiver_is_read_from_the_signature_not_assumed_to_be_self(self):
        """A renamed receiver still owns its attributes, and a staticmethod's
        first argument is NOT a receiver -- so ``this.value`` is a field and
        ``obj.value`` inside the staticmethod is not."""
        text = (
            "class Holder:\n"
            "    def __init__(this, value: int) -> None:\n"
            "        this.value = value\n"
            "    @staticmethod\n"
            "    def build(obj, value: int) -> None:\n"
            "        obj.value = value\n"
        )
        facts = parse.python_type_facts("m.py", text)
        self.assertEqual([(f.owner, f.name, f.origin) for f in facts.fields],
                         [("Holder", "value", "self")])
        sigs = {s.qualname: s for s in facts.signatures}
        self.assertEqual(sigs["Holder.__init__"].receiver, "this")
        self.assertEqual(sigs["Holder.build"].receiver, "")

    def test_an_annotated_instance_attribute_keeps_its_annotation(self):
        text = ("class Holder:\n"
                "    def __init__(self) -> None:\n"
                "        self.items: list[int] = []\n")
        facts = parse.python_type_facts("m.py", text)
        self.assertEqual([(f.name, f.annotation, f.origin) for f in facts.fields],
                         [("items", "list[int]", "self")])


# ==========================================================================  #
# Signatures                                                                  #
# ==========================================================================  #
class Signatures(unittest.TestCase):

    def test_parameter_positions_are_reading_order(self):
        text = ("def f(a, /, b, c=1, *rest, d, e=2, **kw) -> None: ...\n")
        sig = parse.python_type_facts("m.py", text).signatures[0]
        self.assertEqual(
            [(p.name, p.position, p.kind, p.has_default) for p in sig.params],
            [("a", 0, "posonly", False), ("b", 1, "arg", False),
             ("c", 2, "arg", True), ("rest", 3, "vararg", False),
             ("d", 4, "kwonly", False), ("e", 5, "kwonly", True),
             ("kw", 6, "kwarg", False)],
        )

    def test_defaults_are_attributed_to_the_right_positional_parameters(self):
        sig = parse.python_type_facts("m.py", "def f(a, b=1, c=2): ...\n").signatures[0]
        self.assertEqual([(p.name, p.has_default) for p in sig.params],
                         [("a", False), ("b", True), ("c", True)])

    def test_a_missing_annotation_is_an_empty_string_not_a_guess(self):
        sig = _signatures("unresolvable_annotations.py")["unannotated"]
        self.assertEqual(_param(sig, "payload").annotation, "")
        self.assertEqual(sig.returns, "")
        self.assertTrue(parse.normalize_annotation(sig.returns).missing)

    def test_async_and_decorators_are_recorded(self):
        text = ("import functools\n"
                "@functools.wraps(print)\n"
                "async def go(x: int) -> str: ...\n")
        sig = parse.python_type_facts("m.py", text).signatures[0]
        self.assertTrue(sig.is_async)
        self.assertEqual(sig.decorators, ("functools.wraps(print)",))

    def test_the_owner_of_a_method_is_its_class_and_of_a_function_is_nothing(self):
        sigs = _signatures("protocol_structural_match.py")
        self.assertEqual(sigs["FileEmitter.emit"].owner, "FileEmitter")
        self.assertEqual(_signatures("union_shapes.py")["take_union"].owner, "")

    def test_there_is_exactly_one_signature_per_code_unit(self):
        """A ``consumes``/``produces`` edge starts at a FUNCTION, and the only
        function nodes that exist are ``CodeUnit``s -- so a signature that has no
        unit is an edge with no source, and a unit that has no signature is a
        function the layer is silently blind to.

        The join key is ``(module, line)``: ``CodeUnit.name`` is a bare leaf and
        collapses ``Cls.emit`` onto ``emit`` (three of them in
        protocol_structural_match.py), while a line number is unique per
        declaration. Measured over ``daedalus/`` itself while implementing:
        2243 units, 2243 signatures, zero files disagreeing."""
        for rel in CORPUS:
            with self.subTest(rel=rel):
                units, _, facts = parse.python_units_imports_and_types(rel, _read(rel))
                self.assertEqual(sorted((u.module, u.line) for u in units),
                                 sorted((s.module, s.line) for s in facts.signatures))
                self.assertEqual(sorted(u.name for u in units),
                                 sorted(s.name for s in facts.signatures))

    def test_repeated_method_names_do_not_collapse(self):
        """``defs_by_file`` is keyed by bare name with ``setdefault``, so it
        holds ONE ``emit``. The signature table is keyed by qualname, so it
        holds all three -- which is the point of it being a separate table
        (I2)."""
        sigs = _signatures("protocol_structural_match.py")
        self.assertEqual(
            sorted(q for q in sigs if q.endswith(".emit")),
            ["DeclaredEmitter.emit", "Emitter.emit", "FileEmitter.emit"])


# ==========================================================================  #
# PEP 563, forward refs, quoted annotations                                    #
# ==========================================================================  #
class StringAnnotations(unittest.TestCase):
    """PEP 563 is the NORMAL case: most of ``daedalus/`` carries
    ``from __future__ import annotations``.

    A correction to the fixture's own docstring, found while implementing: that
    import does NOT stringify annotations in the ast. PEP 563 defers evaluation
    at COMPILE time (the code object stores strings); ``ast.parse`` still yields
    real expression nodes, so ``Node | None`` under the future import is a
    ``BinOp``, not a ``Constant``. What the future import actually enables is
    the SELF and FORWARD reference being legal at all -- and those are written
    as plain names, which is why an extractor that reads only ``ast.Name`` finds
    them fine. The genuinely quoted spelling (``item: "Later"``) is a
    ``Constant`` regardless of the future import, and that is the case
    ``annotation_text`` folds onto the unquoted text so a consumer never sees
    two spellings of one type."""

    def test_the_future_import_is_reported(self):
        self.assertTrue(_facts("future_annotations_forward_ref.py").future_annotations)
        self.assertFalse(_facts("union_shapes.py").future_annotations)

    def test_a_self_reference_and_a_forward_reference_read_as_plain_names(self):
        rows = _fields("future_annotations_forward_ref.py", "Node")
        self.assertEqual([(f.name, f.annotation) for f in rows],
                         [("label", "str"), ("parent", "Node | None"),
                          ("child", "Later | None")])
        # ``Later`` is declared BELOW its first use. Stage 1 must not care:
        # resolution happens against the finished file, one stage later.
        self.assertIn("Later", _types("future_annotations_forward_ref.py"))

    def test_a_quoted_forward_reference_folds_onto_the_unquoted_text(self):
        sig = _signatures("future_annotations_forward_ref.py")["take_quoted"]
        self.assertEqual(_param(sig, "item").annotation, "Later")
        self.assertEqual(sig.returns, "Node | None")

    def test_a_string_nested_inside_a_generic_is_folded_too(self):
        text = ('def f(a: dict[str, "Later"], b: list["Later"]) -> "Later": ...\n'
                'class Later: pass\n')
        sig = parse.python_type_facts("m.py", text).signatures[0]
        self.assertEqual([p.annotation for p in sig.params],
                         ["dict[str, Later]", "list[Later]"])
        self.assertEqual(sig.returns, "Later")

    def test_a_string_inside_a_string_is_folded_to_the_bottom(self):
        sig = parse.python_type_facts("m.py", 'def f(a: \'"Later"\'): ...\n').signatures[0]
        self.assertEqual(_param(sig, "a").annotation, "Later")

    def test_literal_strings_are_values_and_are_left_alone(self):
        """Folding inside ``Literal`` would turn the VALUE ``"a"`` into a type
        called ``a`` -- a fabricated declaration from a string that was never a
        name. Same for every ``Annotated`` argument after the first."""
        text = ('from typing import Annotated, Literal\n'
                'def f(a: Literal["x", "y"], b: Annotated["Later", "meta"]): ...\n')
        sig = parse.python_type_facts("m.py", text).signatures[0]
        self.assertEqual(_param(sig, "a").annotation, "Literal['x', 'y']")
        self.assertEqual(_param(sig, "b").annotation, "Annotated[Later, 'meta']")

    def test_an_unparseable_string_annotation_is_kept_as_written(self):
        sig = parse.python_type_facts(
            "m.py", 'def f(a: "not a type at all"): ...\n').signatures[0]
        self.assertEqual(_param(sig, "a").annotation, "'not a type at all'")
        self.assertTrue(parse.normalize_annotation(
            _param(sig, "a").annotation).unparsed)

    def test_whitespace_in_an_annotation_is_canonicalized(self):
        """``dict[str,Item]`` and ``dict[str, Item]`` mean one thing, so they
        must produce one string -- otherwise the same type is counted twice."""
        sig = parse.python_type_facts(
            "m.py", "def f(a: dict[str,Item], b: dict[str,  Item]): ...\n").signatures[0]
        self.assertEqual({p.annotation for p in sig.params}, {"dict[str, Item]"})


# ==========================================================================  #
# Normalization helpers (pure, no repo knowledge)                             #
# ==========================================================================  #
class UnionNormalization(unittest.TestCase):
    """Pitfall-Policy 1: strip ``Optional``, one edge per union member sharing a
    ``union_id``. PEP 604 ``X | None`` is exactly ``Optional[X]``."""

    def test_the_four_spellings_normalize_as_the_fixture_documents(self):
        sigs = _signatures("union_shapes.py")
        cases = {
            "take_optional": ("Optional[Alpha]", ("Alpha",), True, False),
            "take_pep604": ("Alpha | None", ("Alpha",), True, False),
            "take_union": ("Union[Alpha, Beta]", ("Alpha", "Beta"), False, True),
            "take_nested": ("Optional[Union[Alpha, Beta]]",
                            ("Alpha", "Beta"), True, True),
        }
        for name, (raw, members, optional, union) in cases.items():
            with self.subTest(name=name):
                param = _param(sigs[name], "value")
                self.assertEqual(param.annotation, raw)
                ann = parse.normalize_annotation(param.annotation)
                self.assertEqual(ann.members, members)
                self.assertEqual(ann.optional, optional)
                self.assertEqual(ann.union, union)

    def test_none_never_becomes_a_member(self):
        for raw in ("Alpha | None", "Optional[Alpha]", "Optional[Union[Alpha, Beta]]",
                    "Alpha|Beta|None"):
            with self.subTest(raw=raw):
                self.assertNotIn("None", parse.normalize_annotation(raw).members)
                self.assertNotIn("None", parse.flatten_union(raw))

    def test_a_bare_none_return_is_the_absence_of_a_return_type(self):
        ann = parse.normalize_annotation("None")
        self.assertTrue(ann.is_none)
        self.assertFalse(ann.optional)
        self.assertEqual(ann.members, ())
        self.assertEqual(parse.flatten_union("None"), ())

    def test_source_order_is_preserved_and_never_sorted(self):
        self.assertEqual(parse.flatten_union("Union[Zeta, Alpha]"), ("Zeta", "Alpha"))
        self.assertEqual(parse.normalize_annotation("Zeta | Alpha").members,
                         ("Zeta", "Alpha"))

    def test_a_non_union_is_its_own_single_member(self):
        self.assertEqual(parse.flatten_union("Item"), ("Item",))

    def test_nesting_does_not_multiply_members(self):
        self.assertEqual(parse.flatten_union("Optional[Union[Alpha, Beta]]"),
                         ("Alpha", "Beta"))

    def test_a_container_with_two_elements_is_not_a_union(self):
        """``list[tuple[str, Item]]`` mentions two nominals, but they are not
        alternatives -- flagging it as a union would give both edges a shared
        ``union_id`` and claim the function takes one OR the other."""
        ann = parse.normalize_annotation("list[tuple[str, Item]]")
        self.assertEqual(ann.members, ("str", "Item"))
        self.assertFalse(ann.union)

    def test_the_union_id_is_content_derived_and_stable(self):
        first = parse.union_id("a/b.py", "Cls.method", "param", "value")
        self.assertEqual(first, "a/b.py#Cls.method:param:value")
        self.assertEqual(first, parse.union_id("a/b.py", "Cls.method", "param", "value"))
        # Two members of ONE site share it; two sites never collide.
        self.assertNotEqual(first, parse.union_id("a/b.py", "Cls.method",
                                                  "return", ""))
        self.assertNotEqual(first, parse.union_id("a/c.py", "Cls.method",
                                                  "param", "value"))


class GenericNormalization(unittest.TestCase):
    """Pitfall-Policy 2 / the TYGAR lesson: NO node per instantiation. The
    vocabulary must stay bounded by the number of declarations, not by the
    number of call sites."""

    def test_three_instantiations_of_one_element_type_yield_one_nominal(self):
        sigs = _signatures("generic_containers.py")
        expected = {
            "first_item": ("list[Item]", "list", ("Item",)),
            "by_sku": ("dict[str, Item]", "dict", ("Item",)),
            "grouped": ("Mapping[str, list[Item]]", "Mapping", ("Item",)),
            "nested_tuple": ("list[tuple[str, Item]]", "list", ("str", "Item")),
        }
        for name, (raw, container, members) in expected.items():
            with self.subTest(name=name):
                param = sigs[name].params[0]
                self.assertEqual(param.annotation, raw)
                ann = parse.normalize_annotation(param.annotation)
                self.assertEqual(ann.container, container)
                self.assertEqual(ann.members, members)

    def test_the_container_chain_is_recorded_outermost_first(self):
        self.assertEqual(
            parse.normalize_annotation("Mapping[str, list[Item]]").containers,
            ("Mapping", "list"))

    def test_a_mapping_key_is_dropped_but_counted(self):
        """``dict[str, User]`` is evidence about ``User``. The key type is
        dropped by the element rule -- so it is published in ``dropped`` rather
        than vanishing, because a coverage number that silently omits it is a
        lower bound presented as a total."""
        ann = parse.normalize_annotation("dict[str, User]")
        self.assertEqual(ann.members, ("User",))
        self.assertEqual(ann.dropped, ("str",))

    def test_callable_parameters_are_dropped_and_the_result_is_the_element(self):
        ann = parse.normalize_annotation("Callable[[int, str], Item]")
        self.assertEqual(ann.members, ("Item",))
        self.assertEqual(ann.container, "Callable")
        self.assertEqual(ann.dropped, ("int", "str"))

    def test_a_variadic_tuple_ellipsis_is_not_a_type(self):
        ann = parse.normalize_annotation("tuple[str, ...]")
        self.assertEqual(ann.members, ("str",))

    def test_a_transparent_wrapper_is_seen_through(self):
        for raw, members in (("ClassVar[list[Item]]", ("Item",)),
                             ("Final[Item]", ("Item",)),
                             ("Annotated[Item, 'meta']", ("Item",)),
                             ("type[Item]", ("Item",))):
            with self.subTest(raw=raw):
                self.assertEqual(parse.normalize_annotation(raw).members, members)

    def test_an_unknown_generic_points_at_its_base_and_is_not_descended(self):
        """``MyGeneric[int]`` is evidence about ``MyGeneric``. Guessing that an
        unrecognised subscript is a container would invent an element type."""
        ann = parse.normalize_annotation("MyGeneric[int]")
        self.assertEqual(ann.members, ("MyGeneric",))
        self.assertEqual(ann.containers, ())
        self.assertEqual(parse.split_generic("MyGeneric[int]"),
                         ("", ("MyGeneric[int]",)))

    def test_split_generic_separates_the_hull_from_the_element(self):
        self.assertEqual(parse.split_generic("list[User]"), ("list", ("User",)))
        self.assertEqual(parse.split_generic("dict[str, User]"), ("dict", ("User",)))
        self.assertEqual(parse.split_generic("User"), ("", ("User",)))

    def test_a_dotted_name_is_kept_verbatim(self):
        """W1 from the hub pre-measurement: resolving ``ast.AST`` by its last
        segment asks for a name called ``AST``, which nothing binds -- the module
        ``ast`` is what is bound. 110 annotations in ``daedalus/`` are dotted, so
        the tail rule would mis-handle every one of them."""
        self.assertEqual(parse.normalize_annotation("ast.AST").members, ("ast.AST",))
        self.assertEqual(
            parse.normalize_annotation("collections.abc.Mapping[str, Item]").members,
            ("Item",))


class AnyAndUnresolvable(unittest.TestCase):
    """Pitfall-Policy 6 and invariant I5: never an edge to ``Any``, never an
    edge to a name we could not find, and both counted rather than folded into
    "covered" or "missing"."""

    def test_a_bare_any_is_a_sentinel_with_no_members(self):
        sig = _signatures("unresolvable_annotations.py")["takes_any"]
        for raw in (_param(sig, "payload").annotation, sig.returns):
            with self.subTest(raw=raw):
                self.assertEqual(raw, "Any")
                ann = parse.normalize_annotation(raw)
                self.assertTrue(ann.is_any)
                self.assertEqual(ann.members, ())
                self.assertTrue(parse.is_any_annotation(raw))
        # Refusing to edge is the DEFAULT, not an opt-in: there is nothing in
        # ``members`` a naive consumer could turn into a node.
        self.assertEqual(parse.ANY_SENTINEL, "<any>")
        self.assertFalse(parse.ANY_SENTINEL.isidentifier())

    def test_an_any_inside_a_container_is_a_different_fact(self):
        """``dict[str, Any]`` is not bare Any: it is a dict whose element type is
        unknown. Folding the two together would make one number answer two
        questions."""
        ann = parse.normalize_annotation("dict[str, Any]")
        self.assertFalse(ann.is_any)
        self.assertTrue(ann.has_any)
        self.assertEqual(ann.members, ())
        self.assertEqual(ann.container, "dict")
        self.assertFalse(parse.is_any_annotation("dict[str, Any]"))

    def test_an_unknown_name_survives_as_text_for_stage_two_to_refuse(self):
        """``NoSuchTypeAnywhere`` is declared nowhere and imported from nowhere.
        Stage 1 reports the name it read; stage 2 finds no candidate and counts
        it unresolved. Stage 1 must NOT filter it out (that would hide the gap)
        and must NOT mint a declaration for it (nothing declared it)."""
        sigs = _signatures("unresolvable_annotations.py")
        self.assertEqual(_param(sigs["phantom"], "payload").annotation,
                         "NoSuchTypeAnywhere")
        self.assertEqual(
            parse.normalize_annotation("list[NoSuchTypeAnywhere]").members,
            ("NoSuchTypeAnywhere",))
        self.assertEqual(_types("unresolvable_annotations.py"), {})

    def test_the_three_ways_of_carrying_no_type_are_three_distinct_flags(self):
        rows = {
            # ``has_any`` rides along on a bare Any because it means "an Any
            # appears anywhere inside" -- a bare Any is the degenerate case of
            # that, and a flag that were false here would make
            # ``has_any`` unusable as the coverage predicate.
            "Any": ("is_any", "has_any"),
            "": ("missing",),
            "'not a type at all'": ("unparsed",),
        }
        for raw, expected in rows.items():
            with self.subTest(raw=raw):
                ann = parse.normalize_annotation(raw)
                on = tuple(f.name for f in dataclasses.fields(ann)
                           if f.type == "bool" and getattr(ann, f.name))
                self.assertEqual(on, expected)


# ==========================================================================  #
# Import name bindings (the input stage 2 resolves against)                    #
# ==========================================================================  #
class ImportNameBindings(unittest.TestCase):
    """``_import_records`` discards ``ast.alias.asname``, so annotation
    resolution is impossible from it. ``AliasImport`` carries the binding
    SEPARATELY rather than widening that 4-tuple, which is unpacked positionally
    in ``resolve_python_imports`` and round-tripped through the disk cache."""

    def test_an_asname_binding_is_recoverable(self):
        text = ("from result_alpha import Result as R\n"
                "import pkg.deep as deep\n"
                "import pkg.other\n"
                "from . import sibling\n"
                "from ..up import Thing\n")
        facts = parse.python_type_facts("a/b.py", text)
        self.assertEqual(
            [(a.local, a.kind, a.level, a.module, a.orig) for a in facts.aliases],
            [("R", "from", 0, "result_alpha", "Result"),
             ("deep", "import", 0, "", "pkg.deep"),
             ("pkg", "import", 0, "", "pkg.other"),
             ("sibling", "from", 1, "", "sibling"),
             ("Thing", "from", 2, "up", "Thing")],
        )

    def test_the_import_records_are_unchanged_by_the_new_table(self):
        """The 4-tuple must not grow: ``resolve_python_imports`` unpacks it
        positionally and the disk cache round-trips it."""
        text = "from result_alpha import Result as R\nimport os.path\n"
        _, records, _ = parse.python_units_imports_and_types("m.py", text)
        self.assertEqual(records, [("from", 0, "result_alpha", ("Result",)),
                                   ("import", 0, None, ("os.path",))])
        for record in records:
            self.assertEqual(len(record), 4)

    def test_an_undecidable_try_except_binding_is_reported_as_two_candidates(self):
        """I5a. ``Result`` is bound by a try/except ImportError pair, so WHICH
        ``Result`` the module means is a property of the runtime, not of the
        source. Stage 1's contribution is to report BOTH bindings; taking the
        first sorted one would emit a stably reproduced FALSE edge -- with a
        determinism test protecting it."""
        facts = _facts("ambiguous_result_try_import.py")
        bindings = [a for a in facts.aliases if a.local == "Result"]
        self.assertEqual([a.module for a in bindings],
                         ["result_alpha", "result_beta"])

    def test_a_star_import_is_recorded_as_a_star(self):
        """I5b. There is no ``Result`` token in this file's imports to anchor
        on, so the only recoverable evidence is "two modules were splatted in
        here" -- which is exactly what a resolver needs in order to refuse."""
        facts = _facts("ambiguous_result_star_import.py")
        self.assertEqual([(a.local, a.module, a.orig) for a in facts.aliases],
                         [("*", "result_alpha", "*"), ("*", "result_beta", "*")])

    def test_an_unambiguous_cross_module_binding_is_reported_intact(self):
        """The positive control. I5 forbids GUESSING, not resolving -- a stage
        that refused everything non-local would pass every ambiguity test and
        still be useless."""
        facts = _facts("cross_module_annotation.py")
        bindings = {a.local: a.module for a in facts.aliases}
        self.assertEqual(bindings["User"], "kind_zoo")
        self.assertEqual(bindings["Ticket"], "pkg_nested.inner_types")


# ==========================================================================  #
# Determinism                                                                 #
# ==========================================================================  #
class Determinism(unittest.TestCase):
    """Two processes must produce byte-identical output, so nothing that reaches
    a record may come from set or dict iteration order."""

    def test_repeated_extraction_is_identical(self):
        for rel in CORPUS:
            with self.subTest(rel=rel):
                self.assertEqual(_facts(rel), _facts(rel))

    def test_records_are_sorted_by_a_stable_key(self):
        for rel in CORPUS:
            with self.subTest(rel=rel):
                facts = _facts(rel)
                self.assertEqual(
                    [(t.line, t.qualname, t.kind) for t in facts.types],
                    sorted((t.line, t.qualname, t.kind) for t in facts.types))
                self.assertEqual(
                    [(f.line, f.owner, f.name, f.origin) for f in facts.fields],
                    sorted((f.line, f.owner, f.name, f.origin)
                           for f in facts.fields))
                self.assertEqual(
                    [(s.line, s.qualname) for s in facts.signatures],
                    sorted((s.line, s.qualname) for s in facts.signatures))
                self.assertEqual([(a.line, a.local) for a in facts.aliases],
                                 sorted((a.line, a.local) for a in facts.aliases))

    def test_everything_that_reaches_a_record_is_a_tuple_not_a_set(self):
        """A set has no order, so a set anywhere in a published record is a
        byte-identity failure waiting for a different hash seed."""
        for rel in CORPUS:
            with self.subTest(rel=rel):
                facts = _facts(rel)
                for group in (facts.types, facts.fields, facts.signatures,
                              facts.aliases):
                    self.assertIsInstance(group, tuple)
                    for record in group:
                        for field in dataclasses.fields(record):
                            value = getattr(record, field.name)
                            self.assertNotIsInstance(value, (set, frozenset, dict))

    def test_a_second_interpreter_with_a_different_hash_seed_agrees(self):
        """``PYTHONHASHSEED`` randomises set/dict iteration for str keys. If any
        of it reached an output, this is where it shows."""
        import json
        import os
        import subprocess

        script = (
            "import json,sys;"
            "sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path;"
            "from daedalus.structcore import parse;"
            "root=Path(sys.argv[2]);"
            "out=[[p.relative_to(root).as_posix(),"
            " repr(parse.python_type_facts(p.relative_to(root).as_posix(),"
            "      p.read_text(encoding='utf-8')))]"
            " for p in sorted(root.rglob('*.py'))];"
            "print(json.dumps(out))"
        )
        repo = str(Path(__file__).resolve().parents[1])
        mine = [[rel, repr(_facts(rel))] for rel in CORPUS]
        for seed in ("0", "12345"):
            with self.subTest(seed=seed):
                env = dict(os.environ, PYTHONHASHSEED=seed)
                proc = subprocess.run(
                    [sys.executable, "-c", script, repo, str(FIXTURES)],
                    capture_output=True, text=True, env=env, cwd=repo, timeout=180)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout), mine)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
