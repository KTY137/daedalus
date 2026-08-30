# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Stage 2 of the type-graph lane: RESOLUTION and edge construction.

What is under test is ``daedalus/structcore/typegraph.py``: the whole-repo half
that turns the raw annotation STRINGS ``parse.py`` extracted into resolved
edges, and that reports every name it refused to resolve.

The suite is organised around the two invariants this stage owns, because those
are the two ways it can be wrong in a way no user would notice:

  I2  ``graph.SymbolResolver.defs_by_file`` must be UNTOUCHED. Resolution uses a
      separate ``types_by_file`` table. This is checked three ways, not one:
      the table is snapshotted before and after a resolve; the module's own AST
      is inspected for any import of ``graph``, any reference to
      ``build_resolver`` and any attribute access named ``defs_by_file``; and no
      class or field name is allowed to appear in the resolver's table. A
      by-eye reading of the module is not evidence, and neither is a grep that a
      docstring can satisfy.
  I5  REFUSE TO GUESS. The fixture corpus carries the undecidable case twice
      (``ambiguous_result_try_import.py`` via try/except, and
      ``ambiguous_result_star_import.py`` via star imports) precisely because
      the two fail an implementation at different points. Required behaviour is
      NO EDGE plus a counter, and the test asserts BOTH -- a counter with no
      edge assertion would pass an implementation that counted the ambiguity and
      emitted the edge anyway, which is exactly the failure the plan predicts
      ("a stably reproduced FALSE edge, with a determinism test to protect it").
      The positive control (``cross_module_annotation.py``) is asserted in the
      same class, because an implementation that refuses EVERYTHING passes every
      ambiguity test and is useless.

Everything is measured over ``tests/fixtures/typegraph/`` (frozen by
construction; see its README) plus a handful of inline sources for shapes the
corpus deliberately does not contain -- ``TypeAlias``/``NewType`` (there is no
alias hazard file, and adding one would change the corpus's captured
baselines), a metaclass keyword, and a nested class.

Nothing here touches the network, a model or a vendor CLI, and nothing here
imports the fixture files as modules: they are read as TEXT, which is what keeps
``typing.get_type_hints`` (it executes imports) permanently unnecessary.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from daedalus.structcore import build_index, typegraph as tg
from daedalus.structcore.index import _PyNaming, project_scope, resolution_context
from daedalus.structcore.parse import python_type_facts

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "typegraph"
MODULE_PATH = REPO_ROOT / "daedalus" / "structcore" / "typegraph.py"


def _fixture_files() -> list[tuple[str, str]]:
    return [(p.relative_to(FIXTURE).as_posix(), p.read_text(encoding="utf-8"))
            for p in sorted(FIXTURE.rglob("*.py"))]


_STATE: dict = {}


def _state() -> dict:
    """The fixture index + facts + resolved graph, computed once.

    ``build_index`` is the expensive part and every class here wants the same
    answer from it, so it is shared rather than rebuilt per TestCase.
    ``documents=False`` is passed EXPLICITLY: ``documents_enabled(None)``
    consults DAEDALUS_INDEX_DOCUMENTS, so leaving it to the default would make
    these numbers depend on the caller's environment.
    """
    if not _STATE:
        idx = build_index(FIXTURE, documents=False)
        facts = {rel: python_type_facts(rel, text) for rel, text in _fixture_files()}
        graph = tg.resolve_type_graph(
            facts_by_rel=facts,
            imports_by_file=idx["import_edges"],
            languages=idx["languages"],
        )
        _STATE.update(idx=idx, facts=facts, graph=graph)
    return _STATE


def _edges(relation: str, *, source: str | None = None,
           target: str | None = None) -> list[dict]:
    rows = _state()["graph"].edges[relation]
    return [e for e in rows
            if (source is None or e["source"] == source)
            and (target is None or e["target"] == target)]


def _resolve(sources: dict[str, str], **kwargs) -> tg.TypeGraph:
    """Resolve an inline corpus. ``imports_by_file`` defaults to "no imports",
    which is the honest degradation: without import edges only same-file
    resolution can succeed."""
    facts = {rel: python_type_facts(rel, text)
             for rel, text in sorted(sources.items())}
    kwargs.setdefault("imports_by_file", {rel: () for rel in facts})
    return tg.resolve_type_graph(facts_by_rel=facts, **kwargs)


# --------------------------------------------------------------------------- #
# I5 — the whole point of the stage                                            #
# --------------------------------------------------------------------------- #
ALPHA = tg.type_node_id("result_alpha.py", "Result")
BETA = tg.type_node_id("result_beta.py", "Result")


class AmbiguityIsRefusedAndCounted(unittest.TestCase):
    """I5. Two modules declare ``Result``; nothing in the importing text picks
    one. Required: NO EDGE, and a counter.

    To watch this go red: make ``_Resolver._resolve`` return ``unique[0]``
    instead of refusing when ``len(unique) > 1``. Every assertion in this class
    fails, and the naive implementation is the one that binds to
    ``result_alpha`` (it sorts first) deterministically, in every process."""

    TRY = "ambiguous_result_try_import.py"
    STAR = "ambiguous_result_star_import.py"

    def test_the_try_except_case_produces_no_edge(self):
        for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
            with self.subTest(relation=relation):
                self.assertEqual(_edges(relation, source=self.TRY), [])

    def test_the_star_import_case_produces_no_edge(self):
        for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
            with self.subTest(relation=relation):
                self.assertEqual(_edges(relation, source=self.STAR), [])

    def test_neither_result_is_reachable_from_either_ambiguous_file(self):
        """The specific false edge the plan names: ``result_alpha`` wins a
        sorted-first tie-break, so its absence is the assertion that matters."""
        for target in (ALPHA, BETA):
            for source in (self.TRY, self.STAR):
                for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
                    with self.subTest(target=target, source=source,
                                      relation=relation):
                        self.assertEqual(
                            _edges(relation, source=source, target=target), [])

    def test_the_ambiguous_counter_moved(self):
        cov = _state()["graph"].coverage
        # Four sites: one param + one return in each of the two files.
        self.assertEqual(cov["ambiguous"], 4)

    def test_the_ambiguity_is_reported_with_both_candidates(self):
        cov = _state()["graph"].coverage
        rows = [r for r in cov["ambiguous_sample"] if r["name"] == "Result"]
        self.assertEqual(len(rows), 4)
        for row in rows:
            with self.subTest(module=row["module"], line=row["line"]):
                self.assertEqual(row["candidates"], [ALPHA, BETA])
        self.assertEqual(
            sorted({r["module"] for r in rows}), [self.STAR, self.TRY])

    def test_the_two_mechanisms_are_both_covered(self):
        """The corpus carries the ambiguity twice on purpose: the try/except
        case fails an import-BINDING reader, the star case fails a
        graph-WALKING resolver. A suite that only had one would pass an
        implementation that is broken in the other direction."""
        cov = _state()["graph"].coverage
        modules = sorted({r["module"] for r in cov["ambiguous_sample"]})
        self.assertIn(self.TRY, modules)
        self.assertIn(self.STAR, modules)

    def test_disagreeing_bindings_are_refused_even_when_only_one_is_visible(self):
        """The nastier half of the try/except case: one branch imports from a
        module we CAN see and the other from a module we cannot.

        Python binds whichever import executes LAST, so resolving to the visible
        one is a guess dressed as a resolution -- and it is the guess an
        implementation makes by accident, because the invisible branch simply
        produces no candidate to conflict with."""
        sources = {
            "vis.py": "class Result:\n    ok: bool\n",
            "user.py": ("try:\n"
                        "    from third_party import Result\n"
                        "except ImportError:\n"
                        "    from vis import Result\n"
                        "\n"
                        "def use(x: Result) -> None:\n"
                        "    del x\n"),
        }
        graph = _resolve(sources, imports_by_file={"user.py": ["vis.py"]})
        self.assertEqual(graph.edges[tg.REL_CONSUMES], ())
        self.assertEqual(graph.coverage["ambiguous"], 1)
        self.assertEqual(graph.coverage["ambiguous_sample"][0]["candidates"],
                         [tg.type_node_id("vis.py", "Result")])

    def test_agreeing_bindings_still_resolve(self):
        """``if TYPE_CHECKING`` duplicates are the common shape, and they are
        not a disagreement. Refusing them would trade a false edge for a missing
        one across a large part of a typed codebase."""
        sources = {
            "vis.py": "class Result:\n    ok: bool\n",
            "user.py": ("from typing import TYPE_CHECKING\n"
                        "\n"
                        "if TYPE_CHECKING:\n"
                        "    from vis import Result\n"
                        "from vis import Result\n"
                        "\n"
                        "def use(x: Result) -> None:\n"
                        "    del x\n"),
        }
        graph = _resolve(sources, imports_by_file={"user.py": ["vis.py"]})
        self.assertEqual([e["target"] for e in graph.edges[tg.REL_CONSUMES]],
                         [tg.type_node_id("vis.py", "Result")])
        self.assertEqual(graph.coverage["ambiguous"], 0)

    def test_result_alpha_still_resolves_inside_its_own_file(self):
        """Refusal is per SITE, not per NAME. ``result_alpha.make_alpha``
        returns its OWN ``Result`` unambiguously, and a resolver that
        blacklisted the name globally would silently drop that."""
        rows = _edges(tg.REL_PRODUCES, source="result_alpha.py", target=ALPHA)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attributes"]["function"], "make_alpha")


class ResolvingIsStillRequired(unittest.TestCase):
    """The positive control for I5: it forbids GUESSING, not resolving.

    An implementation that refuses everything it did not find in the same file
    passes every assertion in ``AmbiguityIsRefusedAndCounted`` and is useless.
    This is the class that catches it."""

    REL = "cross_module_annotation.py"

    def test_a_flat_sibling_import_resolves(self):
        rows = _edges(tg.REL_PRODUCES, source=self.REL,
                      target=tg.type_node_id("kind_zoo.py", "User"))
        self.assertEqual([r["attributes"]["function"] for r in rows], ["owner"])

    def test_a_nested_package_import_resolves(self):
        rows = _edges(tg.REL_PRODUCES, source=self.REL,
                      target=tg.type_node_id("pkg_nested/inner_types.py",
                                             "Ticket"))
        self.assertEqual([r["attributes"]["function"] for r in rows],
                         ["ticket_of"])

    def test_a_cross_module_field_annotation_resolves(self):
        rows = _edges(tg.REL_FIELD_TYPE,
                      source=tg.field_node_id(self.REL, "Assignment", "user"),
                      target=tg.type_node_id("kind_zoo.py", "User"))
        self.assertEqual(len(rows), 1)

    def test_a_type_edge_never_contradicts_the_import_graph(self):
        """Module -> file resolution FILTERS the import edges index.py already
        published rather than re-resolving imports, so a resolved cross-file
        edge always sits on top of an import edge. If that ever stops being
        true, the two graphs disagree about what depends on what."""
        state = _state()
        imports = state["idx"]["import_edges"]
        for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
            for edge in state["graph"].edges[relation]:
                src = edge["source"]
                tgt_rel = edge["target"].split(":", 1)[1].split("#", 1)[0]
                if tgt_rel == src:
                    continue
                with self.subTest(edge=f"{src}->{edge['target']}"):
                    self.assertIn(tgt_rel, imports.get(src, ()))


class UnresolvedIsCountedNotGuessed(unittest.TestCase):
    """A name declared nowhere is never minted into a node for being mentioned."""

    REL = "unresolvable_annotations.py"

    def test_the_phantom_type_has_no_node(self):
        ids = {node["id"] for node in _state()["graph"].nodes}
        for node_id in (tg.type_node_id(self.REL, "NoSuchTypeAnywhere"),
                        tg.type_node_id("", "NoSuchTypeAnywhere")):
            with self.subTest(node_id=node_id):
                self.assertNotIn(node_id, ids)
        self.assertEqual(
            [i for i in ids if "NoSuchTypeAnywhere" in i], [])

    def test_the_phantom_type_has_no_edge(self):
        for relation in tg.RELATIONS:
            with self.subTest(relation=relation):
                self.assertEqual(
                    [e for e in _state()["graph"].edges[relation]
                     if "NoSuchTypeAnywhere" in e["target"]], [])

    def test_it_is_counted_and_sampled(self):
        cov = _state()["graph"].coverage
        self.assertEqual(cov["unresolved"], 2)   # bare + inside list[...]
        names = {r["name"] for r in cov["unresolved_sample"]}
        self.assertEqual(names, {"NoSuchTypeAnywhere"})
        annotations = sorted(r["annotation"] for r in cov["unresolved_sample"])
        self.assertEqual(annotations,
                         ["NoSuchTypeAnywhere", "list[NoSuchTypeAnywhere]"])

    def test_any_is_counted_separately_from_unresolved(self):
        """``Any`` is annotated, resolvable, and says nothing. Folding it into
        either bucket makes the coverage number a lie in one direction."""
        cov = _state()["graph"].coverage
        self.assertEqual(cov["sites_any"], 2)      # takes_any: param + return
        self.assertNotIn("<any>", {n["id"] for n in _state()["graph"].nodes})
        for relation in tg.RELATIONS:
            with self.subTest(relation=relation):
                self.assertEqual(
                    [e for e in _state()["graph"].edges[relation]
                     if e["target"].endswith("#Any")], [])

    def test_the_any_refusal_rests_on_two_independent_mechanisms(self):
        """Stated out loud because it is the one guard here that a single
        adversarial edit cannot turn red, and a reviewer is entitled to know
        which: (1) ``normalize_annotation`` gives a bare ``Any`` an EMPTY member
        list, so there is nothing to edge to; (2) a name is only ever a target
        if it is DECLARED, and ``Any`` is declared in ``typing``. Deleting
        either one leaves the other standing. That is deliberate -- ``Any`` as a
        node would be a hub that poisons every ranking -- and it is why the
        ``is_any`` early return in ``emit`` is belt-and-braces rather than dead
        code."""
        from daedalus.structcore.parse import is_any_annotation, normalize_annotation

        self.assertEqual(normalize_annotation("Any").members, ())
        self.assertEqual(normalize_annotation("typing.Any").members, ())
        self.assertTrue(is_any_annotation("Any"))
        graph = _resolve({"m.py": (
            "from typing import Any\n"
            "\n"
            "def f(x: Any) -> Any:\n"
            "    return x\n"
        )})
        self.assertEqual(graph.coverage["sites_any"], 2)
        self.assertEqual(graph.counts["n_nodes"], 0)
        self.assertEqual(graph.counts["n_edges"], 0)

    def test_a_dict_with_an_any_value_is_a_different_fact(self):
        """``dict[str, Any]`` is not a bare ``Any``: it is a dict whose element
        type is unknown, which is a different number. Counting it as ``Any``
        would understate how much shape the layer actually failed to see."""
        graph = _resolve({"m.py": (
            "from typing import Any\n"
            "\n"
            "def f(x: dict[str, Any]) -> None:\n"
            "    del x\n"
        )})
        self.assertEqual(graph.coverage["sites_any"], 0)
        self.assertEqual(graph.coverage["sites_any_inside"], 1)
        self.assertEqual(graph.coverage["sites_no_member"], 1)
        self.assertEqual(graph.coverage["dropped_keys"], 1)

    def test_an_unannotated_parameter_is_a_counted_gap(self):
        cov = _state()["graph"].coverage
        self.assertEqual(cov["total_params"] - cov["annotated_params"], 1)
        self.assertGreater(cov["sites_missing"], 0)

    def test_a_builtin_is_not_a_failure(self):
        """1722 mentions of ``str`` in daedalus/ are not 1722 gaps. Counting
        them as unresolved would make the coverage headline unusable."""
        cov = _state()["graph"].coverage
        self.assertGreater(cov["builtin"], 0)
        self.assertEqual(
            [n["id"] for n in _state()["graph"].nodes
             if n["name"] in ("str", "int", "bool", "float")], [])

    def test_an_external_declaration_is_not_a_failure_either(self):
        """``from typing import Protocol`` is 'declared somewhere else', which
        is a different fact from 'declared nowhere' and a different number."""
        cov = _state()["graph"].coverage
        self.assertGreater(cov["external"], 0)

    def test_every_attempt_lands_in_exactly_one_bucket(self):
        cov = _state()["graph"].coverage
        total = sum(cov[name] for name in
                    ("resolved", "unresolved", "ambiguous", "external",
                     "builtin", "vocabulary"))
        self.assertEqual(total, cov["attempts"])


# --------------------------------------------------------------------------- #
# I2 — the separate table                                                      #
# --------------------------------------------------------------------------- #
class TheResolverTableIsSeparate(unittest.TestCase):
    """I2. Annotation resolution uses ``types_by_file``, never
    ``graph.SymbolResolver.defs_by_file``.

    The reason is not tidiness. ``resolve`` takes the FIRST match on a bare
    name, so a class ``Foo`` displaces a function ``Foo``; and ``graph.callees``
    resolves EVERY identifier token in a body, so field names (``path``,
    ``root``, ``name``, ``line``, ``source``, ``module`` -- not one of them is a
    stop-word) become fabricated CALL edges in every slice."""

    @classmethod
    def setUpClass(cls):
        idx = build_index(FIXTURE, documents=False)
        cls.resolver = resolution_context(FIXTURE, idx["scope_key"])
        cls.before = {rel: sorted(defs) for rel, defs
                      in cls.resolver.defs_by_file.items()}
        cls.graph = _state()["graph"]
        cls.tbf = tg.types_by_file(_state()["facts"])
        cls.tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))

    def test_defs_by_file_is_unchanged_by_a_resolve(self):
        after = {rel: sorted(defs)
                 for rel, defs in self.resolver.defs_by_file.items()}
        self.assertEqual(after, self.before)

    def test_a_second_resolve_still_does_not_touch_it(self):
        tg.resolve_type_graph(
            facts_by_rel=_state()["facts"],
            imports_by_file=_state()["idx"]["import_edges"])
        after = {rel: sorted(defs)
                 for rel, defs in self.resolver.defs_by_file.items()}
        self.assertEqual(after, self.before)

    def test_no_declared_type_is_a_resolvable_symbol(self):
        for rel, bucket in sorted(self.tbf.items()):
            for qualname, decl in sorted(bucket.items()):
                if decl.name == "Foo":
                    continue     # the fixture declares BOTH a class and a
                    #              function called Foo; the name alone cannot
                    #              tell them apart (see the fixture suite).
                with self.subTest(rel=rel, qualname=qualname):
                    self.assertNotIn(decl.name,
                                     self.resolver.defs_by_file.get(rel, {}))

    def test_no_field_name_is_a_resolvable_symbol(self):
        for node in self.graph.nodes:
            if node["kind"] != tg.FIELD_NODE_KIND:
                continue
            with self.subTest(node=node["id"]):
                self.assertNotIn(
                    node["name"],
                    self.resolver.defs_by_file.get(node["module"], {}))

    def test_the_module_does_not_import_graph(self):
        """Asked of the AST, not of a grep: this file's own docstrings name
        ``defs_by_file`` and ``build_resolver`` on purpose, so a text search
        would be satisfied by prose."""
        imported: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported.extend(f"{node.module or ''}.{a.name}"
                                for a in node.names)
        self.assertNotIn("graph", imported)
        self.assertNotIn(".graph", imported)
        for name in imported:
            with self.subTest(name=name):
                self.assertFalse(name.endswith("graph"), name)

    def test_the_module_never_names_the_forbidden_members(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "defs_by_file")
                self.assertNotEqual(node.attr, "imports_by_file_")
            if isinstance(node, ast.Name):
                self.assertNotIn(
                    node.id, ("build_resolver", "SymbolResolver", "CodeUnit"))

    def test_the_table_holds_type_declarations_keyed_by_qualname(self):
        decl = self.tbf["kind_zoo.py"]["User"]
        self.assertEqual((decl.module, decl.qualname, decl.kind),
                         ("kind_zoo.py", "User", "dataclass"))
        self.assertFalse(hasattr(decl, "source"),
                         "a TypeDecl with .source could enter all_units")
        self.assertFalse(hasattr(decl, "loc"))

    def test_a_nested_class_is_keyed_by_its_full_qualname(self):
        """A leaf-name key would make two nested classes with the same leaf
        collide and force a tie-break -- which is the guess I5 forbids."""
        graph = _resolve({"m.py": (
            "class Outer:\n"
            "    class Inner:\n"
            "        tag: str\n"
            "\n"
            "def take(x: Outer.Inner) -> None:\n"
            "    del x\n"
            "\n"
            "def bare(x: Inner) -> None:\n"
            "    del x\n"
        )})
        ids = {n["id"] for n in graph.nodes}
        self.assertIn(tg.type_node_id("m.py", "Outer.Inner"), ids)
        self.assertNotIn(tg.type_node_id("m.py", "Inner"), ids)
        qualified = _edge_targets(graph, tg.REL_CONSUMES)
        self.assertIn(tg.type_node_id("m.py", "Outer.Inner"), qualified)
        # The bare ``Inner`` is a gap, not a lucky hit.
        self.assertEqual(graph.coverage["unresolved"], 1)
        self.assertEqual(len(graph.edges[tg.REL_CONSUMES]), 1)


def _edge_targets(graph: tg.TypeGraph, relation: str) -> list[str]:
    return [e["target"] for e in graph.edges[relation]]


# --------------------------------------------------------------------------- #
# Relations                                                                    #
# --------------------------------------------------------------------------- #
class HasFieldAndFieldType(unittest.TestCase):
    """``has_field`` (type -> field) plus the edge onward to the field's own
    type (CPG calls that EVAL_TYPE; here ``field_type``). Two relations rather
    than one because the directions are opposite."""

    def test_every_field_hangs_off_its_declaring_type(self):
        nodes = {n["id"]: n for n in _state()["graph"].nodes}
        for edge in _state()["graph"].edges[tg.REL_HAS_FIELD]:
            with self.subTest(edge=f"{edge['source']}->{edge['target']}"):
                self.assertEqual(nodes[edge["source"]]["kind"],
                                 tg.TYPE_NODE_KIND)
                self.assertEqual(nodes[edge["target"]]["kind"],
                                 tg.FIELD_NODE_KIND)
                self.assertEqual(nodes[edge["target"]]["owner"],
                                 nodes[edge["source"]]["qualname"])

    def test_the_field_carries_its_raw_annotation(self):
        rows = _edges(tg.REL_HAS_FIELD,
                      target=tg.field_node_id("future_annotations_forward_ref.py",
                                              "Node", "parent"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attributes"]["annotation"], "Node | None")
        self.assertTrue(rows[0]["attributes"]["optional"])

    def test_an_enum_member_never_points_at_a_type(self):
        """Enum members are VALUES. parse.py forces their annotation to "" so
        no member->type edge can be fabricated; here that has to stay true."""
        for name in ("FAST", "SLOW"):
            member = tg.field_node_id("kind_zoo.py", "Mode", name)
            with self.subTest(member=name):
                self.assertEqual(len(_edges(tg.REL_HAS_FIELD, target=member)), 1)
                self.assertEqual(_edges(tg.REL_FIELD_TYPE, source=member), [])

    def test_one_member_written_twice_is_one_field_node(self):
        """``limit: int = 10`` in the body AND ``self.limit = limit`` in
        ``__init__`` are two FACTS about one member (parse.py emits both). Two
        nodes for one member would be a fabrication; the annotated origin wins.
        """
        limit = tg.field_node_id("kind_zoo.py", "PlainHolder", "limit")
        nodes = [n for n in _state()["graph"].nodes if n["id"] == limit]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["origin"], "annassign")
        self.assertEqual(nodes[0]["annotation"], "int")
        self.assertEqual(len(_edges(tg.REL_HAS_FIELD, target=limit)), 1)

    def test_an_unannotated_self_field_is_a_node_with_no_type_edge(self):
        tag = tg.field_node_id("kind_zoo.py", "PlainHolder", "tag")
        nodes = [n for n in _state()["graph"].nodes if n["id"] == tag]
        self.assertEqual([n["origin"] for n in nodes], ["self"])
        self.assertEqual(_edges(tg.REL_FIELD_TYPE, source=tag), [])


class Inherits(unittest.TestCase):
    def test_a_declared_base_is_a_nominal_edge(self):
        rows = _edges(tg.REL_INHERITS,
                      source=tg.type_node_id("protocol_structural_match.py",
                                             "DeclaredEmitter"),
                      target=tg.type_node_id("protocol_structural_match.py",
                                             "Emitter"))
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["attributes"]["structural"])
        self.assertEqual(rows[0]["attributes"]["base"], "Emitter")

    def test_an_external_base_produces_no_edge(self):
        """``class Sink(Protocol)`` -- ``Protocol`` is declared in ``typing``,
        not here. No edge, and it is counted as external rather than as a gap."""
        self.assertEqual(
            _edges(tg.REL_INHERITS,
                   source=tg.type_node_id("kind_zoo.py", "Sink")), [])

    def test_a_metaclass_keyword_is_not_a_base(self):
        """parse.py keeps ``metaclass=M`` in ``bases`` as written so a consumer
        can see it without re-parsing. A metaclass is not a base class.

        The EDGE set alone does not prove this: ``metaclass=Meta`` is not a
        Python expression, so it would fall out as ``unparsed`` even with no
        guard at all. The numbers are what catch it -- the base denominator must
        not count it and the unparsed counter must not move -- because a
        coverage report that calls a keyword argument an unreadable annotation
        is reporting a defect that does not exist."""
        graph = _resolve({"m.py": (
            "class Meta(type):\n"
            "    pass\n"
            "\n"
            "class Base:\n"
            "    pass\n"
            "\n"
            "class C(Base, metaclass=Meta):\n"
            "    pass\n"
        )})
        rows = [e for e in graph.edges[tg.REL_INHERITS]
                if e["source"] == tg.type_node_id("m.py", "C")]
        self.assertEqual([e["target"] for e in rows],
                         [tg.type_node_id("m.py", "Base")])
        self.assertEqual(graph.coverage["total_bases"], 2)  # type, Base
        self.assertEqual(graph.coverage["sites_unparsed"], 0)


class StructuralProtocolMatching(unittest.TestCase):
    """A FLAGGED heuristic. ``structural=True`` is the flag, and it is the whole
    difference between a declared contract and a coincidence of names -- which
    ``emit``/``flush`` make the normal case, not a rarity."""

    PROTO = tg.type_node_id("protocol_structural_match.py", "Emitter")

    def test_a_structural_match_is_marked_structural(self):
        rows = _edges(tg.REL_INHERITS,
                      source=tg.type_node_id("protocol_structural_match.py",
                                             "FileEmitter"),
                      target=self.PROTO)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["attributes"]["structural"])
        self.assertEqual(rows[0]["attributes"]["heuristic"],
                         "protocol_member_names")

    def test_a_declared_implementation_is_not_re_emitted_structurally(self):
        rows = _edges(tg.REL_INHERITS,
                      source=tg.type_node_id("protocol_structural_match.py",
                                             "DeclaredEmitter"),
                      target=self.PROTO)
        self.assertEqual([r["attributes"]["structural"] for r in rows], [False])

    def test_a_one_member_protocol_matches_nothing(self):
        """One common method name is a coincidence, not evidence, so the
        heuristic refuses below ``STRUCTURAL_MIN_MEMBERS`` -- and publishes the
        threshold so the choice is falsifiable rather than buried.

        The fixture's own one-member protocol (``kind_zoo.Sink``) cannot prove
        this on its own: nothing else in the corpus happens to define
        ``accept``, so the match set would be empty either way. The inline case
        supplies the coincidence the corpus lacks."""
        self.assertEqual(
            _edges(tg.REL_INHERITS, target=tg.type_node_id("kind_zoo.py", "Sink")),
            [])
        self.assertEqual(_state()["graph"].coverage["structural_min_members"], 2)
        graph = _resolve({"m.py": (
            "from typing import Protocol\n"
            "\n"
            "class Runnable(Protocol):\n"
            "    def run(self) -> None: ...\n"
            "\n"
            "class Coincidence:\n"
            "    def run(self) -> None: ...\n"
        )})
        self.assertEqual(graph.coverage["structural_matches"], 0)
        self.assertEqual(graph.edges[tg.REL_INHERITS], ())

    def test_an_overmatching_protocol_is_dropped_whole(self):
        """The first N of an arbitrary match set is a guess wearing a number, so
        a protocol matching more than the cap emits NOTHING and says so."""
        body = ["from typing import Protocol", "",
                "class P(Protocol):",
                "    def a(self) -> None: ...",
                "    def b(self) -> None: ..."]
        for i in range(tg.STRUCTURAL_MAX_MATCHES + 1):
            body += [f"class C{i}:",
                     "    def a(self) -> None: ...",
                     "    def b(self) -> None: ..."]
        graph = _resolve({"m.py": "\n".join(body) + "\n"})
        self.assertEqual(graph.coverage["structural_matches"], 0)
        self.assertEqual(graph.coverage["structural_overmatched"],
                         [tg.type_node_id("m.py", "P")])
        self.assertEqual(
            [e for e in graph.edges[tg.REL_INHERITS]
             if e["attributes"]["structural"]], [])


class ConsumesAndProduces(unittest.TestCase):
    """function -> type, one edge per parameter; and the return."""

    def test_one_edge_per_parameter_with_name_and_position(self):
        graph = _resolve({"m.py": (
            "class A:\n    tag: str\n\n"
            "class B:\n    tag: str\n\n"
            "def take(first: A, second: B) -> A:\n"
            "    return first\n"
        )})
        rows = graph.edges[tg.REL_CONSUMES]
        self.assertEqual(
            [(e["attributes"]["param"], e["attributes"]["position"],
              e["target"]) for e in rows],
            [("first", 0, tg.type_node_id("m.py", "A")),
             ("second", 1, tg.type_node_id("m.py", "B"))])
        self.assertEqual(_edge_targets(graph, tg.REL_PRODUCES),
                         [tg.type_node_id("m.py", "A")])

    def test_the_implicit_receiver_is_not_a_parameter(self):
        """A consumer that filters on the literal string ``self`` both misses a
        renamed receiver and wrongly drops a staticmethod's first argument, so
        parse.py carries the receiver NAME and this stage reads it."""
        graph = _resolve({"m.py": (
            "class A:\n    tag: str\n\n"
            "class Holder:\n"
            "    def method(this, value: A) -> None:\n"
            "        del value\n"
            "\n"
            "    @staticmethod\n"
            "    def static(value: A) -> None:\n"
            "        del value\n"
        )})
        rows = graph.edges[tg.REL_CONSUMES]
        self.assertEqual(sorted(e["attributes"]["param"] for e in rows),
                         ["value", "value"])
        self.assertEqual(graph.coverage["total_params"], 2)

    def test_the_source_is_the_file_and_the_function_is_an_attribute(self):
        """Functions are not forest nodes today (the forest's nodes are files
        and documents), so the edge attaches to the FILE node and carries the
        function identity in its attributes. Stage 3 needs both."""
        rows = _edges(tg.REL_CONSUMES, source="generic_containers.py")
        self.assertTrue(rows)
        modules = _state()["idx"]["modules"]
        for edge in rows:
            with self.subTest(function=edge["attributes"]["function"]):
                self.assertIn(edge["source"], modules)
                self.assertEqual(
                    edge["attributes"]["function_ref"],
                    f"generic_containers.py#{edge['attributes']['function']}")

    def test_a_none_return_is_not_a_type(self):
        """``-> None`` is the ABSENCE of a return type. ``None`` reaching the
        vocabulary is rank 2 by fan-in in daedalus/ (883 edges) if a plain union
        treatment lets it through."""
        self.assertEqual(
            [e for e in _state()["graph"].edges[tg.REL_PRODUCES]
             if e["target"].endswith("#None")], [])
        self.assertGreater(_state()["graph"].coverage["sites_none"], 0)


class UnionsAndOptional(unittest.TestCase):
    """Pitfall-Policy 1: ``Optional`` stripped, one edge per union member, all
    members of ONE site sharing a ``union_id``."""

    REL = "union_shapes.py"
    ALPHA = tg.type_node_id("union_shapes.py", "Alpha")
    BETA = tg.type_node_id("union_shapes.py", "Beta")

    def test_optional_is_stripped_to_one_edge(self):
        for function in ("take_optional", "take_pep604"):
            rows = [e for e in _edges(tg.REL_CONSUMES, source=self.REL)
                    if e["attributes"]["function"] == function]
            with self.subTest(function=function):
                self.assertEqual([e["target"] for e in rows], [self.ALPHA])
                self.assertTrue(rows[0]["attributes"]["optional"])
                self.assertFalse(rows[0]["attributes"]["union"])
                self.assertEqual(rows[0]["attributes"]["union_id"], "")

    def test_a_union_shares_one_union_id_across_its_members(self):
        rows = sorted(
            (e for e in _edges(tg.REL_CONSUMES, source=self.REL)
             if e["attributes"]["function"] == "take_union"),
            key=lambda e: e["target"])
        self.assertEqual([e["target"] for e in rows], [self.ALPHA, self.BETA])
        ids = {e["attributes"]["union_id"] for e in rows}
        self.assertEqual(ids, {"union_shapes.py#take_union:param:value"})

    def test_nesting_does_not_multiply_the_members(self):
        rows = [e for e in _edges(tg.REL_CONSUMES, source=self.REL)
                if e["attributes"]["function"] == "take_nested"]
        self.assertEqual(sorted(e["target"] for e in rows),
                         [self.ALPHA, self.BETA])
        self.assertEqual(
            {e["attributes"]["union_id"] for e in rows},
            {"union_shapes.py#take_nested:param:value"})
        self.assertTrue(all(e["attributes"]["optional"] for e in rows))

    def test_a_union_id_is_derived_from_the_site_not_from_a_counter(self):
        """A counter over a set would renumber whenever iteration order shifted
        and two processes would disagree about which edges are alternatives."""
        rows = [e for e in _edges(tg.REL_PRODUCES, source=self.REL)
                if e["attributes"]["function"] == "produce_union"]
        self.assertEqual(
            {e["attributes"]["union_id"] for e in rows},
            {"union_shapes.py#produce_union:return:"})

    def test_none_is_never_a_union_member(self):
        self.assertEqual(
            [n["id"] for n in _state()["graph"].nodes
             if n["name"] in ("None", "NoneType")], [])


class Generics(unittest.TestCase):
    """Pitfall-Policy 2 / the TYGAR lesson: NO node per instantiation."""

    ITEM = tg.type_node_id("generic_containers.py", "Item")

    def test_four_annotations_share_one_element_type(self):
        rows = _edges(tg.REL_CONSUMES, source="generic_containers.py",
                      target=self.ITEM)
        self.assertEqual(
            sorted((e["attributes"]["function"], e["attributes"]["container"])
                   for e in rows),
            [("by_sku", "dict"), ("first_item", "list"),
             ("grouped", "Mapping"), ("nested_tuple", "list")])

    def test_no_node_is_an_instantiation(self):
        for node in _state()["graph"].nodes:
            with self.subTest(node=node["id"]):
                self.assertNotIn("[", node["id"])
                self.assertNotIn("]", node["id"])

    def test_the_container_hull_is_an_attribute_and_the_chain_is_kept(self):
        rows = [e for e in _edges(tg.REL_CONSUMES, target=self.ITEM)
                if e["attributes"]["function"] == "grouped"]
        self.assertEqual(rows[0]["attributes"]["containers"],
                         ["Mapping", "list"])

    def test_a_dropped_mapping_key_is_counted_not_hidden(self):
        """``dict[str, User]`` -> ``User``; the KEY type is dropped. Publishing
        the count is what keeps every str-related number from being a lower
        bound presented as a total."""
        self.assertGreater(_state()["graph"].coverage["dropped_keys"], 0)


class AliasOf(unittest.TestCase):
    """``alias_of`` (type -> type). Tested inline: the fixture corpus has no
    alias hazard file, and adding one would move its captured baselines."""

    SRC = (
        "from typing import NewType, TypeAlias\n"
        "\n"
        "class Base:\n"
        "    tag: str\n"
        "\n"
        "Vec: TypeAlias = list[Base]\n"
        "Ident = NewType('Ident', Base)\n"
        "NotAnAlias = 3\n"
    )

    @classmethod
    def setUpClass(cls):
        cls.graph = _resolve({"m.py": cls.SRC})

    def test_a_typealias_and_a_newtype_both_produce_an_edge(self):
        base = tg.type_node_id("m.py", "Base")
        self.assertEqual(
            sorted((e["source"], e["target"])
                   for e in self.graph.edges[tg.REL_ALIAS_OF]),
            [(tg.type_node_id("m.py", "Ident"), base),
             (tg.type_node_id("m.py", "Vec"), base)])

    def test_the_container_hull_survives_the_alias(self):
        rows = [e for e in self.graph.edges[tg.REL_ALIAS_OF]
                if e["source"] == tg.type_node_id("m.py", "Vec")]
        self.assertEqual(rows[0]["attributes"]["container"], "list")
        self.assertEqual(rows[0]["attributes"]["alias_target"], "list[Base]")

    def test_a_bare_constant_assignment_is_not_an_alias(self):
        """``X = 3`` at module level is a constant far more often than a type,
        and minting a node for it fabricates a declaration."""
        ids = {n["id"] for n in self.graph.nodes}
        self.assertNotIn(tg.type_node_id("m.py", "NotAnAlias"), ids)


class ForwardRefsAndPep563(unittest.TestCase):
    """Two-pass resolution: register every declaration, THEN resolve.

    An implementation that resolves incrementally while walking reports the
    forward reference as unresolved, and reports it as a NUMBER rather than as
    an error -- which is the failure mode that looks like a working feature."""

    REL = "future_annotations_forward_ref.py"

    def test_a_forward_reference_resolves(self):
        rows = _edges(tg.REL_CONSUMES, source=self.REL,
                      target=tg.type_node_id(self.REL, "Later"))
        self.assertEqual(sorted(e["attributes"]["function"] for e in rows),
                         ["link", "take_quoted"])

    def test_a_quoted_forward_reference_resolves(self):
        rows = [e for e in _edges(tg.REL_CONSUMES, source=self.REL)
                if e["attributes"]["function"] == "take_quoted"]
        self.assertEqual([e["target"] for e in rows],
                         [tg.type_node_id(self.REL, "Later")])

    def test_a_self_reference_resolves(self):
        rows = _edges(tg.REL_FIELD_TYPE,
                      source=tg.field_node_id(self.REL, "Node", "parent"),
                      target=tg.type_node_id(self.REL, "Node"))
        self.assertEqual(len(rows), 1)

    def test_definition_order_cannot_change_the_answer(self):
        """The same two declarations in both orders must resolve identically."""
        first = _resolve({"m.py": (
            "class A:\n    other: 'B'\n\nclass B:\n    other: 'A'\n")})
        second = _resolve({"m.py": (
            "class B:\n    other: 'A'\n\nclass A:\n    other: 'B'\n")})
        self.assertEqual(
            sorted((e["source"].split("#")[1], e["target"].split("#")[1])
                   for e in first.edges[tg.REL_FIELD_TYPE]),
            sorted((e["source"].split("#")[1], e["target"].split("#")[1])
                   for e in second.edges[tg.REL_FIELD_TYPE]))
        self.assertEqual(first.coverage["unresolved"], 0)
        self.assertEqual(second.coverage["unresolved"], 0)

    def test_the_future_import_is_reported(self):
        self.assertEqual(_state()["graph"].coverage["future_annotations_files"], 2)


# --------------------------------------------------------------------------- #
# I6 — the hub cap                                                             #
# --------------------------------------------------------------------------- #
class HubCap(unittest.TestCase):
    """I6. The cap was MEASURED on daedalus/ before this code existed (2-hop
    blow-up 53.6% of the complete graph uncapped; an empty band in the fan-in
    distribution between rank 8 at 175 and rank 9 at 33, so every cap in
    [34, 174] excludes the same eight universal-vocabulary types). What is
    tested here is that it is APPLIED and PUBLISHED, not that 64 is pretty."""

    def test_nothing_is_suppressed_on_the_fixture_at_the_default(self):
        cov = _state()["graph"].coverage
        self.assertEqual(cov["hub_cap"], tg.DEFAULT_HUB_CAP)
        self.assertEqual(cov["hub_suppressed_edges"], 0)
        self.assertEqual(cov["hub_suppressed_types"], [])

    def test_a_low_cap_suppresses_the_hub_and_says_which(self):
        state = _state()
        graph = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"],
            hub_cap=2)
        item = tg.type_node_id("generic_containers.py", "Item")
        suppressed = {row["id"] for row in graph.coverage["hub_suppressed_types"]}
        self.assertIn(item, suppressed)
        for relation in (tg.REL_CONSUMES, tg.REL_PRODUCES):
            with self.subTest(relation=relation):
                self.assertEqual(
                    [e for e in graph.edges[relation] if e["target"] == item], [])
        self.assertGreater(graph.coverage["hub_suppressed_edges"], 0)

    def test_the_cap_never_touches_declaration_structure(self):
        """``has_field``/``inherits``/``alias_of`` are bounded by the number of
        declarations, not by call sites, so they are not the 2-hop hazard."""
        state = _state()
        capped = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"], hub_cap=1)
        for relation in (tg.REL_HAS_FIELD, tg.REL_INHERITS, tg.REL_ALIAS_OF):
            with self.subTest(relation=relation):
                self.assertEqual(capped.edges[relation],
                                 state["graph"].edges[relation])

    def test_both_numbers_are_published(self):
        """Publish the kept AND the dropped count, so nobody mistakes the kept
        set for the whole truth (on daedalus/ the cap drops ~85% of the
        nominal edges, and that IS the finding: most type edges are the word
        ``str``)."""
        state = _state()
        graph = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"], hub_cap=2)
        before = graph.coverage["edges_before_hub_cap"]
        self.assertGreater(before[tg.REL_CONSUMES],
                           len(graph.edges[tg.REL_CONSUMES]))

    def test_zero_disables_the_cap(self):
        state = _state()
        graph = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"], hub_cap=0)
        self.assertEqual(graph.coverage["hub_suppressed_edges"], 0)
        self.assertEqual(graph.edges[tg.REL_CONSUMES],
                         state["graph"].edges[tg.REL_CONSUMES])

    def test_the_layer_registers_no_dss_relation(self):
        """The foundation ships a LENS, not a diffusion channel: two functions
        that both take a hub type must not become two hops apart."""
        from daedalus.structcore import dss

        for relation in tg.RELATIONS:
            with self.subTest(relation=relation):
                self.assertNotIn(relation, dss.DEFAULT_RELATION_WEIGHTS)

    def test_no_type_kind_joined_the_file_node_kinds(self):
        from daedalus.structcore import dss

        self.assertEqual(dss.FILE_NODE_KINDS,
                         frozenset({"source_file", "file", "document"}))
        for kind in (tg.TYPE_NODE_KIND, tg.FIELD_NODE_KIND):
            with self.subTest(kind=kind):
                self.assertNotIn(kind, dss.FILE_NODE_KINDS)


# --------------------------------------------------------------------------- #
# Node identity and structural shape (what stage 3 consumes)                   #
# --------------------------------------------------------------------------- #
class NodeNamespace(unittest.TestCase):
    def test_every_node_id_is_in_its_own_namespace(self):
        modules = set(_state()["idx"]["modules"])
        for node in _state()["graph"].nodes:
            with self.subTest(node=node["id"]):
                self.assertTrue(tg.is_type_node_id(node["id"]))
                self.assertIn("#", node["id"])
                self.assertNotIn(node["id"], modules)

    def test_no_module_rel_is_mistaken_for_a_type_node(self):
        for rel in sorted(_state()["idx"]["modules"]):
            with self.subTest(rel=rel):
                self.assertFalse(tg.is_type_node_id(rel))

    def test_nodes_are_sorted_by_id_and_unique(self):
        ids = [n["id"] for n in _state()["graph"].nodes]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_node_carries_the_same_key_set(self):
        expected = {"id", "kind", "module", "qualname", "name", "line",
                    "end_line", "decl_kind", "owner", "origin", "annotation",
                    "container", "optional", "language"}
        for node in _state()["graph"].nodes:
            with self.subTest(node=node["id"]):
                self.assertEqual(set(node), expected)

    def test_every_edge_endpoint_exists(self):
        """Stage 3 gates forest edges on membership. A dangling endpoint would
        either vanish silently or raise there instead of here."""
        node_ids = {n["id"] for n in _state()["graph"].nodes}
        modules = set(_state()["idx"]["modules"])
        for relation in tg.RELATIONS:
            for edge in _state()["graph"].edges[relation]:
                with self.subTest(relation=relation, edge=edge["source"]):
                    self.assertIn(edge["target"], node_ids)
                    self.assertIn(edge["source"], node_ids | modules)

    def test_a_field_node_id_cannot_collide_with_a_type_node_id(self):
        self.assertNotEqual(tg.type_node_id("m.py", "A.b"),
                            tg.field_node_id("m.py", "A", "b"))

    def test_edges_are_sorted_within_every_relation(self):
        for relation in tg.RELATIONS:
            rows = _state()["graph"].edges[relation]
            keys = [(e["source"], e["target"]) for e in rows]
            with self.subTest(relation=relation):
                self.assertEqual(keys, sorted(keys))

    def test_the_index_blocks_have_the_shape_stage_three_publishes(self):
        blocks = _state()["graph"].to_index_blocks()
        self.assertEqual(sorted(blocks), ["type_edges", "type_nodes", "types"])
        self.assertEqual(sorted(blocks["type_edges"]), sorted(tg.RELATIONS))
        self.assertTrue(blocks["types"]["enabled"])
        self.assertEqual(blocks["types"]["count"], 23)
        self.assertIn("coverage", blocks["types"])
        for key in ("modules", "import_edges", "duplication", "defs_by_file",
                    "dss_diffusion", "all_units"):
            with self.subTest(key=key):
                self.assertIn(key, blocks["types"]["excluded_from"])
        # JSON-serialisable without a default= hook: it goes into the index.
        json.dumps(blocks, sort_keys=True)

    def test_instantiates_is_not_built(self):
        """Deferred on purpose: it needs the call graph."""
        self.assertNotIn("instantiates", tg.RELATIONS)
        self.assertNotIn("instantiates", _state()["graph"].edges)


class CoverageIsHonest(unittest.TestCase):
    def test_non_python_languages_are_not_supported_never_zero(self):
        """A numeric 0 would claim 'we looked and found none' where the truth is
        'we did not look': the tree-sitter path has no class/field vocabulary."""
        graph = tg.resolve_type_graph(
            facts_by_rel=_state()["facts"],
            imports_by_file=_state()["idx"]["import_edges"],
            languages={"python": {"files": 16}, "c": {"files": 3},
                       "typescript": {"files": 9}})
        langs = graph.coverage["languages"]
        self.assertEqual(langs["python"], "supported")
        self.assertEqual(langs["c"], "not_supported")
        self.assertEqual(langs["typescript"], "not_supported")
        for lang, value in sorted(langs.items()):
            with self.subTest(lang=lang):
                self.assertIsInstance(value, str)
                self.assertNotEqual(value, 0)

    def test_the_denominators_are_present_and_consistent(self):
        cov = _state()["graph"].coverage
        self.assertEqual(cov["total_returns"], cov["n_functions"])
        self.assertGreaterEqual(cov["total_params"], cov["annotated_params"])
        self.assertGreaterEqual(cov["total_fields"], cov["annotated_fields"])
        self.assertEqual(cov["total_fields"],
                         sum(1 for n in _state()["graph"].nodes
                             if n["kind"] == tg.FIELD_NODE_KIND))

    def test_the_samples_are_bounded_and_flagged(self):
        cov = _state()["graph"].coverage
        self.assertLessEqual(len(cov["unresolved_sample"]), 25)
        self.assertLessEqual(len(cov["ambiguous_sample"]), 25)
        self.assertIn("truncated", cov)

    def test_a_withheld_file_contributes_nothing(self):
        """Out-of-scope files are withheld exactly as ``all_units`` withholds
        their units, so a shell file cannot move a published number."""
        state = _state()
        graph = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"],
            ignored=("result_alpha.py", "result_beta.py"))
        self.assertEqual(
            [n["id"] for n in graph.nodes if n["module"].startswith("result_")],
            [])
        # With both declarations withheld the ambiguity has nothing to be
        # ambiguous between, so it becomes an honest gap rather than a guess.
        self.assertEqual(graph.coverage["ambiguous"], 0)
        self.assertGreater(graph.coverage["unresolved"], 0)

    def test_no_import_data_degrades_to_same_file_only(self):
        """Without import edges only same-file resolution can succeed, and the
        loss shows up as a COUNT rather than as silence. The same edge with the
        import edges present is asserted first, so this cannot pass by the
        edge having never existed."""
        state = _state()
        user = tg.type_node_id("kind_zoo.py", "User")
        self.assertNotEqual(
            _edges(tg.REL_PRODUCES, source="cross_module_annotation.py",
                   target=user), [])
        graph = tg.resolve_type_graph(facts_by_rel=state["facts"])
        self.assertEqual(
            [e for e in graph.edges[tg.REL_PRODUCES]
             if e["source"] == "cross_module_annotation.py"
             and e["target"] == user], [])
        self.assertEqual(graph.coverage["ambiguous"], 0)
        # The loss lands in ``external``, not in ``unresolved``: a binding was
        # read (``from kind_zoo import User``) and the module could not be shown
        # to be internal, which is exactly "declared somewhere we cannot see".
        self.assertLess(graph.coverage["resolved"],
                        state["graph"].coverage["resolved"])
        self.assertGreater(graph.coverage["external"],
                           state["graph"].coverage["external"])


class NamingAgreesWithTheIndex(unittest.TestCase):
    """``PlainNaming`` exists so this module never imports ``index`` (``index``
    imports IT). It must give the same answer as the real table on a repo with
    no declared center -- which is the case every unconfigured repo is in."""

    def test_plain_naming_matches_pynaming_on_the_fixture(self):
        rels = sorted(rel for rel, _ in _fixture_files())
        plain = tg.PlainNaming.from_rels(rels)
        real = _PyNaming(rels, project_scope(FIXTURE.resolve(), None, None))
        for rel in rels:
            with self.subTest(rel=rel):
                self.assertEqual(plain.name(rel), real.name(rel))
                self.assertEqual(plain.tables_for(rel).rel_by_dotted,
                                 real.tables_for(rel).rel_by_dotted)

    def test_the_real_naming_object_is_accepted(self):
        state = _state()
        rels = sorted(state["facts"])
        real = _PyNaming(rels, project_scope(FIXTURE.resolve(), None, None))
        graph = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"],
            naming=real)
        self.assertEqual(graph.edges, state["graph"].edges)

    def test_a_relative_import_is_anchored_the_same_way_as_import_resolution(self):
        sources = {
            "pkg/__init__.py": "",
            "pkg/a.py": "class Thing:\n    tag: str\n",
            "pkg/b.py": ("from .a import Thing\n\n"
                         "def use(x: Thing) -> None:\n    del x\n"),
        }
        graph = _resolve(sources,
                         imports_by_file={"pkg/b.py": ["pkg/a.py"]})
        self.assertEqual(_edge_targets(graph, tg.REL_CONSUMES),
                         [tg.type_node_id("pkg/a.py", "Thing")])

    def test_a_package_spelling_resolves_to_its_init_file(self):
        sources = {
            "pkg/__init__.py": "class Thing:\n    tag: str\n",
            "user.py": ("from pkg import Thing\n\n"
                        "def use(x: Thing) -> None:\n    del x\n"),
        }
        graph = _resolve(sources,
                         imports_by_file={"user.py": ["pkg/__init__.py"]})
        self.assertEqual(_edge_targets(graph, tg.REL_CONSUMES),
                         [tg.type_node_id("pkg/__init__.py", "Thing")])

    def test_an_aliased_import_resolves(self):
        """``_import_records`` throws ``asname`` away, which is why parse.py
        emits a separate ``AliasImport``. Without it this edge is impossible."""
        sources = {
            "a.py": "class Thing:\n    tag: str\n",
            "b.py": ("from a import Thing as Renamed\n\n"
                     "def use(x: Renamed) -> None:\n    del x\n"),
        }
        graph = _resolve(sources, imports_by_file={"b.py": ["a.py"]})
        self.assertEqual(_edge_targets(graph, tg.REL_CONSUMES),
                         [tg.type_node_id("a.py", "Thing")])

    def test_a_dotted_annotation_is_never_reduced_to_its_tail(self):
        """``ast.AST`` -> ``AST`` asks for a name nothing binds (the MODULE
        ``ast`` is what is bound). 110 annotations in daedalus/ are dotted."""
        sources = {
            "a.py": "class Thing:\n    tag: str\n",
            "b.py": ("import a\n\n"
                     "def use(x: a.Thing) -> None:\n    del x\n"
                     "def bad(x: nowhere.Thing) -> None:\n    del x\n"),
        }
        graph = _resolve(sources, imports_by_file={"b.py": ["a.py"]})
        self.assertEqual(_edge_targets(graph, tg.REL_CONSUMES),
                         [tg.type_node_id("a.py", "Thing")])
        self.assertEqual(graph.coverage["unresolved"], 1)

    def test_a_stdlib_dotted_annotation_is_external_not_unresolved(self):
        graph = _resolve({"b.py": (
            "import ast\n\n"
            "def use(x: ast.AST) -> None:\n    del x\n")})
        self.assertEqual(graph.edges[tg.REL_CONSUMES], ())
        self.assertEqual(graph.coverage["external"], 1)
        self.assertEqual(graph.coverage["unresolved"], 0)


# --------------------------------------------------------------------------- #
# Determinism                                                                  #
# --------------------------------------------------------------------------- #
class Determinism(unittest.TestCase):
    """Two processes must produce byte-identical output. Not a style point: this
    stage iterates dicts of facts, sets of candidates and a fan-in table, and
    every one of those orders used to be a function of PYTHONHASHSEED
    elsewhere in this package (measured: 3 distinct slice hashes over 5 seeds).
    """

    SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from daedalus.structcore import build_index, typegraph as tg
from daedalus.structcore.parse import python_type_facts
fixture = Path(sys.argv[2])
idx = build_index(fixture, documents=False)
facts = {p.relative_to(fixture).as_posix():
         python_type_facts(p.relative_to(fixture).as_posix(),
                           p.read_text(encoding="utf-8"))
         for p in sorted(fixture.rglob("*.py"))}
g = tg.resolve_type_graph(facts_by_rel=facts,
                          imports_by_file=idx["import_edges"],
                          languages=idx["languages"])
print(json.dumps(g.to_index_blocks(), sort_keys=True))
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
        self.assertEqual(first, second)

    def test_a_repeated_resolve_in_one_process_is_identical(self):
        state = _state()
        again = tg.resolve_type_graph(
            facts_by_rel=state["facts"],
            imports_by_file=state["idx"]["import_edges"],
            languages=state["idx"]["languages"])
        self.assertEqual(json.dumps(again.to_index_blocks(), sort_keys=True),
                         json.dumps(state["graph"].to_index_blocks(),
                                    sort_keys=True))

    def test_the_input_order_of_the_facts_cannot_change_the_output(self):
        state = _state()
        reversed_facts = dict(reversed(list(state["facts"].items())))
        graph = tg.resolve_type_graph(
            facts_by_rel=reversed_facts,
            imports_by_file=state["idx"]["import_edges"],
            languages=state["idx"]["languages"])
        self.assertEqual(json.dumps(graph.to_index_blocks(), sort_keys=True),
                         json.dumps(state["graph"].to_index_blocks(),
                                    sort_keys=True))


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
