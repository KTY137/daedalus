# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The type layer's INDEX WIRING — is it additive, and is it gated correctly?

Stage 3 publishes three new keys (``types``, ``type_nodes``, ``type_edges``) out
of ``build_index``. Everything in this file is one of two questions:

  1. IS IT ADDITIVE? Build the fixture repo twice, once with the layer on and
     once with it off, and compare the blocks that already existed. The most
     important assertion in the file is ``duplication``: it is the I1
     thermometer. ``all_units`` feeds ``clones.renamed_clusters``, which is an
     exact match on an ABSTRACTED fingerprint with no threshold and no
     ``max_cluster``, reported in the PRECISE tier -- so if a ``type`` node ever
     became a ``CodeUnit``, the fixture's two four-field dataclasses would
     collapse to one Type-2 fingerprint and be published as renamed clones with
     full confidence. The fixture corpus is deliberately shaped so that
     ``duplication`` is COMPLETELY EMPTY today (every function is <= 3 lines,
     below every clone pass's ``min_loc``), which makes that block the most
     sensitive tripwire available: a single leaked class shows up as a cluster
     appearing out of nothing.

     ``modules`` and ``import_edges`` are the I4 half, and I4 is the expensive
     one: those two keys are the entire input to ``graph._graph_nodes``, whose
     set is the DENOMINATOR of ``graph.fenced_dominance``. Type nodes have no
     forward import edges, so every one of them would land in the denominator
     and none in the numerator, ``fraction`` would fall, ``provider_router``'s
     fence stand-down would stop firing, and every task would stay on the
     premium (paid) lane. Real money, wrong cause. So this file does not only
     compare the two keys -- it asks ``_graph_nodes`` and ``fenced_dominance``
     themselves, the way the fence asks them.

  2. IS THE GATE HONEST? The layer changes the shape of the returned dict, so it
     is part of ``_scope_key`` exactly as ``documents`` is; otherwise the
     in-process ``_INDEX_CACHE`` would serve a build from the wrong
     configuration. And per-file EXTRACTION is deliberately NOT gated, because it
     rides a content-keyed disk cache -- a gate on that side would let a
     layer-off row be served as a HIT to a layer-on build, i.e. an empty type
     block with no error, no exception and no log line.

Every captured literal below was taken from a run of this code, never typed by
hand. The counts are stage 2's published fixture numbers and they matched on the
first wiring, which is the point of having published them.

Companion files: ``test_typegraph_parse.py`` (extraction),
``test_typegraph_resolve.py`` (resolution), ``test_typegraph_fixture.py`` (the
pre-feature baselines this file must not contradict).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import index as index_mod
from daedalus.structcore import graph as graph_mod
from daedalus.structcore import typegraph as typegraph_mod
from daedalus.structcore.cache import _decode, _encode
from daedalus.structcore.index import (build_index, cached_index, resolution_context,
                                       types_enabled, _scope_key)
from daedalus.structcore.ignore import project_scope
from daedalus.structcore.parse import (PyTypeFacts, extract_units,
                                       python_type_facts)
from daedalus.structcore.perfile import ANALYSIS_VERSION, analyze_file
from daedalus.structcore.languages import spec_for

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "typegraph"

# Env keys that can move a build. Pinned for the whole module so a baseline never
# depends on the operator's shell: ``conftest.py`` clears the routing/vendor keys
# but deliberately touches none of these.
_PINNED = ("DAEDALUS_INDEX_TYPES", "DAEDALUS_INDEX_DOCUMENTS",
           "DAEDALUS_CACHE_DIR", "DAEDALUS_NO_CACHE",
           "DAEDALUS_SCAN_MIN_PARALLEL", "DAEDALUS_SCAN_WORKERS")
_SAVED: dict[str, str | None] = {}
_TMP_CACHE: str = ""


def setUpModule() -> None:
    """Pin the environment, and point the disk cache at a temp dir.

    Not optional housekeeping: ``build_index`` writes a sqlite row per file, so
    without this every run of this file would read and write the developer's real
    ``%LOCALAPPDATA%`` cache -- and one of the tests below is specifically about
    what the cache serves.
    """
    global _TMP_CACHE
    for name in _PINNED:
        _SAVED[name] = os.environ.get(name)
        os.environ.pop(name, None)
    _TMP_CACHE = tempfile.mkdtemp(prefix="tgidx-cache-")
    os.environ["DAEDALUS_CACHE_DIR"] = _TMP_CACHE


def tearDownModule() -> None:
    for name, value in _SAVED.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    shutil.rmtree(_TMP_CACHE, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Captured baselines (stage 2's published fixture numbers)                     #
# --------------------------------------------------------------------------- #
COUNTS_BASELINE = {
    "count": 23, "n_fields": 45, "n_nodes": 68, "n_edges": 78, "n_files": 16,
    "hub_cap": 64,
}
EDGES_BY_RELATION_BASELINE = {
    "has_field": 45, "field_type": 4, "inherits": 2,
    "consumes": 19, "produces": 8, "alias_of": 0,
}
OUTCOMES_BASELINE = {
    "resolved": 32, "unresolved": 2, "ambiguous": 4,
    "external": 5, "builtin": 65, "vocabulary": 0, "attempts": 108,
}
# The 14 keys EVERY node row carries, type and field alike. A uniform row is not
# cosmetic: a consumer that has to test for a key's presence before reading it
# ends up inventing a default, and a default here would be a fact about the code.
NODE_KEYS = frozenset({
    "id", "kind", "module", "qualname", "name", "line", "end_line",
    "decl_kind", "owner", "origin", "annotation", "container", "optional",
    "language",
})
TYPES_KEYS = frozenset({
    "enabled", "parse_version", "graph_version", "count", "n_fields", "n_nodes",
    "n_edges", "n_edges_by_relation", "n_files", "hub_cap", "coverage",
    "excluded_from",
})
# Blocks the layer must be able to prove it did not touch. ``scope_key`` is
# excluded on purpose -- it MUST differ, and a separate test says so.
ADDITIVE_KEYS = ("modules", "import_edges", "import_edges_reverse",
                 "dependencies", "fan_in", "duplication", "languages",
                 "n_files", "total_chars", "total_tokens", "hotspots",
                 "module_heat", "ignored", "backend", "root", "tokenizer")


def _build(**kw) -> dict:
    """``documents`` and ``types`` are ALWAYS explicit here: both consult an env
    var when left as None, so a default would make every baseline in this file a
    fact about the caller's shell."""
    kw.setdefault("documents", False)
    kw.setdefault("types", False)
    return build_index(FIXTURE, **kw)


class _OnAndOff(unittest.TestCase):
    """Two builds of one repo, differing in exactly one flag. Built once per
    class: the whole file is comparisons between them."""

    @classmethod
    def setUpClass(cls):
        cls.off = _build(types=False)
        cls.on = _build(types=True)


# --------------------------------------------------------------------------- #
# 1. THE THERMOMETER — the layer is additive or it is a defect                  #
# --------------------------------------------------------------------------- #
class TheLayerIsAdditive(_OnAndOff):
    """Every block that existed before must be byte-identical with the layer on.

    To watch these go red: in ``build_index``, extend ``modules`` with the type
    nodes (I4), or append the extracted ``TypeDecl``s to ``all_units`` (I1).
    """

    def test_duplication_is_byte_identical(self):
        """THE MOST IMPORTANT ASSERTION IN THIS FILE (invariant I1).

        The fixture's ``duplication`` block is empty in every one of its four
        sub-blocks, so any leak of a class into ``all_units`` cannot hide inside
        a pre-existing cluster -- it has to create one. And the fixture holds a
        deliberate pair of four-field dataclasses that abstract to ONE Type-2
        fingerprint, so the leak it would create is the exact one the plan says
        would publish ~176 of this repo's dataclasses as renamed clones.
        """
        self.assertEqual(self.on["duplication"], self.off["duplication"])
        for sub in ("unit_clusters", "renamed_clusters", "near_clusters",
                    "window_clusters"):
            with self.subTest(sub=sub):
                self.assertEqual(self.on["duplication"][sub], [])

    def test_modules_is_byte_identical(self):
        """Invariant I4, first half. ``modules`` keys are the file-node identity
        every other block joins against, and ``code_modules(modules)`` is the
        first term of ``graph._graph_nodes``."""
        self.assertEqual(self.on["modules"], self.off["modules"])

    def test_import_edges_is_byte_identical(self):
        """Invariant I4, second half -- both directions, because
        ``_graph_nodes`` reads the keys of the forward map AND the values of the
        reverse one."""
        self.assertEqual(self.on["import_edges"], self.off["import_edges"])
        self.assertEqual(self.on["import_edges_reverse"],
                         self.off["import_edges_reverse"])

    def test_every_pre_existing_block_is_byte_identical(self):
        for key in ADDITIVE_KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.on[key], self.off[key])

    def test_the_only_new_keys_are_the_three(self):
        """Stated as a SET DIFFERENCE rather than as three membership checks, so
        a fourth key cannot be added without this line going red."""
        self.assertEqual(set(self.on) - set(self.off),
                         {"types", "type_nodes", "type_edges"})
        self.assertEqual(set(self.off) - set(self.on), set())

    def test_the_layer_is_absent_when_off(self):
        for key in ("types", "type_nodes", "type_edges", "fields"):
            with self.subTest(key=key):
                self.assertNotIn(key, self.off)


class TheFenceDenominatorCannotMove(_OnAndOff):
    """Invariant I4, asked the way the FENCE asks it rather than by comparing
    index keys -- because the money bug is downstream of the keys, not in them.

    ``fenced_dominance``'s ``fraction`` is read by ``provider_router`` to decide
    whether to stand the reachability escalation down. A type node has no
    forward import edges, so it lands in the denominator and never in the
    numerator: ``fraction`` falls, the stand-down stops firing, every task stays
    on the premium lane.
    """

    def test_graph_nodes_are_identical(self):
        self.assertEqual(sorted(graph_mod._graph_nodes(self.on)),
                         sorted(graph_mod._graph_nodes(self.off)))

    def test_no_type_node_id_is_a_graph_node(self):
        nodes = graph_mod._graph_nodes(self.on)
        leaked = sorted(n for n in nodes if typegraph_mod.is_type_node_id(n))
        self.assertEqual(leaked, [])

    def test_no_type_node_id_is_a_modules_key(self):
        leaked = sorted(m for m in self.on["modules"]
                        if typegraph_mod.is_type_node_id(m))
        self.assertEqual(leaked, [])

    def test_fenced_dominance_is_identical(self):
        """Every fence spelling the fixture can express, not just one: the
        fraction is a ratio, so a single choice of fenced path could hide a
        change in both terms."""
        for fenced in ([], ["protocol_structural_match.py"],
                       ["cross_module_annotation.py"], ["dataclass"]):
            with self.subTest(fenced=tuple(fenced)):
                self.assertEqual(graph_mod.fenced_dominance(self.on, fenced),
                                 graph_mod.fenced_dominance(self.off, fenced))

    def test_n_files_does_not_count_a_type_as_a_file(self):
        """``types.n_files`` is NESTED and counts the Python files this layer
        scanned. The top-level ``n_files`` counts files. They are allowed to be
        equal here (the fixture is 16 Python files and nothing else) -- what is
        not allowed is the top-level number moving."""
        self.assertEqual(self.on["n_files"], self.off["n_files"])
        self.assertEqual(self.on["n_files"], 16)

    def test_languages_gains_no_type_entry(self):
        self.assertEqual(self.on["languages"], self.off["languages"])
        self.assertNotIn("type", self.on["languages"])
        self.assertNotIn("field", self.on["languages"])


class TheResolverIsUntouched(_OnAndOff):
    """Invariant I2. ``graph.build_resolver`` is called with
    ``all_units + doc_units`` and nothing else, so ``defs_by_file`` holds only
    function and doc-section names.

    Why it matters twice over: ``resolve`` takes the FIRST match on a bare name,
    so a class ``Foo`` would displace a function ``Foo``; and ``graph.callees``
    resolves EVERY identifier token in a body, so field names (``path``,
    ``root``, ``name``, ``line``, ``source`` -- none of them stop-words) would
    become fabricated CALL edges in ``slice_text``. Second-order,
    ``context_plan._symbol_names`` reads ``defs_by_file`` wholesale into the BM25
    corpus, so the leak would re-rank the whole repo.
    """

    def test_defs_by_file_is_byte_identical(self):
        r_off = resolution_context(FIXTURE, self.off["scope_key"])
        r_on = resolution_context(FIXTURE, self.on["scope_key"])
        self.assertIsNotNone(r_off)
        self.assertIsNotNone(r_on)
        self.assertEqual(r_on.defs_by_file, r_off.defs_by_file)

    def test_no_field_name_is_in_defs_by_file(self):
        """Named explicitly rather than left to the equality above, so the test
        still means something if BOTH builds leak.

        Fields are the dangerous half, and the fixture's
        ``field_names_are_common_identifiers.py`` exists for this line: ``path``,
        ``root``, ``name``, ``line``, ``source``, ``module`` are all field names
        in this repo and none of them is a stop-word, so a field in
        ``defs_by_file`` becomes a fabricated CALL edge in every slice that
        mentions one.
        """
        r_on = resolution_context(FIXTURE, self.on["scope_key"])
        fields = {node["name"] for node in self.on["type_nodes"]
                  if node["kind"] == typegraph_mod.FIELD_NODE_KIND}
        self.assertTrue(fields, "fixture declares no fields -- test is vacuous")
        self.assertTrue(fields & {"path", "name", "line", "source"},
                        "the common-identifier fixture is gone -- test is weak")
        for rel, names in sorted(r_on.defs_by_file.items()):
            with self.subTest(rel=rel):
                self.assertEqual(sorted(fields & set(names)), [])

    def test_a_class_name_in_defs_by_file_is_there_for_a_function(self):
        """Classes cannot be checked by NAME alone, because the fixture
        deliberately declares a class ``Foo`` and a function ``Foo`` in one file
        (``name_collision_class_and_function.py``) -- that collision IS the
        hazard. So the assertion is the sharper one: every declared class name
        that appears in ``defs_by_file`` is there because a FUNCTION of that name
        exists in that same file, and its recorded line is the function's."""
        r_on = resolution_context(FIXTURE, self.on["scope_key"])
        declared_by_rel: dict[str, set[str]] = {}
        for node in self.on["type_nodes"]:
            if node["kind"] == typegraph_mod.TYPE_NODE_KIND:
                declared_by_rel.setdefault(node["module"], set()).add(node["name"])
        self.assertTrue(declared_by_rel, "fixture declares no types -- vacuous")
        seen_collision = False
        for rel, names in sorted(r_on.defs_by_file.items()):
            text = (FIXTURE / rel).read_text(encoding="utf-8")
            fn_names = {u.name for u in extract_units(rel, text, spec_for(rel))}
            for name in sorted(declared_by_rel.get(rel, set()) & set(names)):
                seen_collision = True
                with self.subTest(rel=rel, name=name):
                    self.assertIn(name, fn_names)
        self.assertTrue(seen_collision,
                        "no class/function name collision in the corpus -- "
                        "this test no longer proves anything")

    def test_the_type_table_is_a_separate_object(self):
        """``types_by_file`` is the table annotation resolution uses. It is built
        from the raw facts and is never merged into the resolver -- so the two
        must not even be the same shape."""
        r_on = resolution_context(FIXTURE, self.on["scope_key"])
        self.assertFalse(hasattr(r_on, "types_by_file"))


# --------------------------------------------------------------------------- #
# 2. SHAPE — the published blocks say what they claim to say                    #
# --------------------------------------------------------------------------- #
class TheBlocksHaveTheDocumentedShape(_OnAndOff):

    def test_types_block_keys(self):
        self.assertEqual(set(self.on["types"]), TYPES_KEYS)
        self.assertIs(self.on["types"]["enabled"], True)

    def test_counts_are_the_captured_baseline(self):
        for key, want in COUNTS_BASELINE.items():
            with self.subTest(key=key):
                self.assertEqual(self.on["types"][key], want)
        self.assertEqual(self.on["types"]["n_edges_by_relation"],
                         EDGES_BY_RELATION_BASELINE)

    def test_counts_agree_with_the_published_rows(self):
        """The summary numbers are DERIVED, so they must be checkable against the
        rows -- a count that is merely asserted is a claim, not a measurement."""
        types = self.on["types"]
        nodes = self.on["type_nodes"]
        self.assertEqual(types["n_nodes"], len(nodes))
        self.assertEqual(types["count"], sum(
            1 for n in nodes if n["kind"] == typegraph_mod.TYPE_NODE_KIND))
        self.assertEqual(types["n_fields"], sum(
            1 for n in nodes if n["kind"] == typegraph_mod.FIELD_NODE_KIND))
        self.assertEqual(types["count"] + types["n_fields"], len(nodes))
        by_rel = {r: len(rows) for r, rows in self.on["type_edges"].items()}
        self.assertEqual(types["n_edges_by_relation"], by_rel)
        self.assertEqual(types["n_edges"], sum(by_rel.values()))

    def test_every_node_row_carries_the_same_keys(self):
        for node in self.on["type_nodes"]:
            with self.subTest(node=node["id"]):
                self.assertEqual(set(node), NODE_KEYS)

    def test_node_kinds_are_only_type_and_field(self):
        self.assertEqual(sorted({n["kind"] for n in self.on["type_nodes"]}),
                         ["field", "type"])

    def test_node_ids_are_unique_prefixed_and_sorted(self):
        ids = [n["id"] for n in self.on["type_nodes"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        for node_id in ids:
            with self.subTest(node_id=node_id):
                # The prefix is defence in depth, and the ``#`` is the part that
                # actually protects: no filesystem path in an indexed repo
                # carries one, so ``dss._canonical_file_path`` cannot parse a
                # type id as a relative path even if a kind filter ever slipped.
                self.assertTrue(typegraph_mod.is_type_node_id(node_id))
                self.assertIn("#", node_id)

    def test_all_six_relations_are_present_even_when_empty(self):
        """``alias_of`` is empty on this fixture. Publishing the key anyway is the
        difference between "no aliases here" and "this build does not do
        aliases" -- and a consumer that has to ``.get(relation, [])`` cannot tell
        those apart."""
        self.assertEqual(sorted(self.on["type_edges"]),
                         sorted(typegraph_mod.RELATIONS))
        self.assertEqual(self.on["type_edges"]["alias_of"], [])

    def test_instantiates_is_not_published(self):
        """It needs the call graph and the foundation does not build it. Absent,
        not empty: an empty ``instantiates`` would claim we looked."""
        self.assertNotIn("instantiates", self.on["type_edges"])

    def test_every_edge_row_has_source_target_attributes(self):
        for relation, rows in sorted(self.on["type_edges"].items()):
            for row in rows:
                with self.subTest(relation=relation, row=row.get("source")):
                    self.assertEqual(set(row), {"source", "target", "attributes"})
                    self.assertIsInstance(row["attributes"], dict)

    def test_edge_endpoints_obey_the_forest_gate(self):
        """The contract the next stage's membership gate depends on: every target
        is a type node, and every source is either a type node or a ``modules``
        key. Nothing else, so ``(source in module_ids | type_ids) and (target in
        type_ids)`` cannot silently drop rows."""
        type_ids = {n["id"] for n in self.on["type_nodes"]}
        module_ids = set(self.on["modules"])
        for relation, rows in sorted(self.on["type_edges"].items()):
            for row in rows:
                with self.subTest(relation=relation, edge=(row["source"], row["target"])):
                    self.assertIn(row["target"], type_ids)
                    self.assertIn(row["source"], type_ids | module_ids)

    def test_consumes_and_produces_attach_to_a_file_node(self):
        """Functions are not forest nodes today, so the source is the rel path
        and the function identity travels in the attributes. Asserted because the
        alternative -- inventing a function node id -- would put a node with no
        bytes on disk in front of ``dss._estimated_tokens``."""
        module_ids = set(self.on["modules"])
        for relation in ("consumes", "produces"):
            rows = self.on["type_edges"][relation]
            self.assertTrue(rows, f"{relation} is empty -- test is vacuous")
            for row in rows:
                with self.subTest(relation=relation, source=row["source"]):
                    self.assertIn(row["source"], module_ids)
                    self.assertFalse(typegraph_mod.is_type_node_id(row["source"]))
                    self.assertEqual(row["attributes"]["function_ref"],
                                     f"{row['source']}#{row['attributes']['function']}")

    def test_the_blocks_are_json_serialisable_with_no_default_hook(self):
        """The index dict is written to disk by ``--json`` and shipped over HTTP.
        A frozen dataclass or a set that only survives because someone passed
        ``default=str`` is a wire-format bug waiting for a different caller."""
        json.dumps({k: self.on[k] for k in ("types", "type_nodes", "type_edges")})


class ItSaysWhatItRefusedToDo(_OnAndOff):
    """Coverage is the layer reporting its own confidence. Every number here is
    the difference between a small honest map and a small map that looks
    complete."""

    def test_outcome_counts_are_the_captured_baseline(self):
        cov = self.on["types"]["coverage"]
        for key, want in OUTCOMES_BASELINE.items():
            with self.subTest(key=key):
                self.assertEqual(cov[key], want)

    def test_attempts_is_exactly_the_sum_of_the_six_buckets(self):
        """Invariant I5's arithmetic: nothing may fall out of the accounting. A
        refusal that is not counted is indistinguishable from an annotation that
        was never there."""
        cov = self.on["types"]["coverage"]
        self.assertEqual(
            cov["attempts"],
            cov["resolved"] + cov["unresolved"] + cov["ambiguous"]
            + cov["external"] + cov["builtin"] + cov["vocabulary"])

    def test_the_fixture_really_does_exercise_the_refusals(self):
        """Guards the guard: if the corpus stopped containing an ambiguous name,
        every refuse-to-guess assertion above would pass vacuously."""
        cov = self.on["types"]["coverage"]
        self.assertGreater(cov["ambiguous"], 0)
        self.assertGreater(cov["unresolved"], 0)
        self.assertTrue(cov["ambiguous_sample"])
        for row in cov["ambiguous_sample"]:
            with self.subTest(row=row["name"]):
                self.assertGreaterEqual(len(row["candidates"]), 2)

    def test_no_refused_site_produced_an_edge(self):
        """The refusal is only real if the edge is actually missing. Checked
        against the published rows, not against the counter.

        PER SITE, not per NAME, and that distinction is the whole point:
        ``Result`` is AMBIGUOUS in ``ambiguous_result_star_import.py`` (two star
        imports could each provide it) and RESOLVED inside ``result_alpha.py``
        (which declares it). A name-level check would either pass vacuously or
        demand that a legitimate edge be dropped. What must be true is that the
        refusing SITE -- one file, one line, one nominal -- emitted nothing.
        """
        cov = self.on["types"]["coverage"]
        module_by_node = {n["id"]: n["module"] for n in self.on["type_nodes"]}
        emitted: set[tuple[str, int, str]] = set()
        for rows in self.on["type_edges"].values():
            for row in rows:
                attrs = row["attributes"]
                member = attrs.get("member")
                if not member:
                    continue
                module = module_by_node.get(row["source"], row["source"])
                emitted.add((module, attrs["line"], member))
        refused = {(r["module"], r["line"], r["name"])
                   for r in cov["unresolved_sample"]}
        refused |= {(r["module"], r["line"], r["name"])
                    for r in cov["ambiguous_sample"]}
        self.assertTrue(refused, "nothing was refused -- test is vacuous")
        self.assertEqual(sorted(refused & emitted), [])

    def test_languages_report_not_supported_never_a_zero(self):
        """Stufe 1 is Python only. A numeric 0 for a language the tree-sitter
        path has no class vocabulary for would claim "we looked and found none"
        where the truth is "we did not look"."""
        langs = self.on["types"]["coverage"]["languages"]
        self.assertEqual(langs["python"], "supported")
        for lang, value in sorted(langs.items()):
            with self.subTest(lang=lang):
                self.assertIsInstance(value, str)
                self.assertNotIsInstance(value, (int, float))
                if lang != "python":
                    self.assertEqual(value, "not_supported")

    def test_a_non_python_language_is_reported_not_counted(self):
        """Built against ``daedalus/`` rather than the fixture, because the
        fixture is deliberately Python-only (a ``.ts`` file in it would also move
        ``near_excluded_languages``). ``daedalus/`` ships JavaScript."""
        idx = build_index(REPO_ROOT / "daedalus", documents=False, types=True)
        langs = idx["types"]["coverage"]["languages"]
        others = sorted(set(idx["languages"]) - {"python"})
        self.assertTrue(others, "daedalus/ is python-only -- test is vacuous")
        for lang in others:
            with self.subTest(lang=lang):
                self.assertEqual(langs[lang], "not_supported")

    def test_the_hub_cap_is_published_even_when_it_did_nothing(self):
        """Measured 2026-07-29: max fan-in on this repo is 33 against a cap of
        64, so the cap suppresses nothing HERE. Publishing it anyway is what lets
        a reader tell "nothing was dropped" from "85% was dropped" -- and 85% is
        the measured figure for an uncapped run of the same corpus."""
        cov = self.on["types"]["coverage"]
        self.assertEqual(cov["hub_cap"], typegraph_mod.DEFAULT_HUB_CAP)
        self.assertEqual(cov["hub_suppressed_edges"], 0)
        self.assertEqual(cov["hub_suppressed_types"], [])
        self.assertEqual(cov["edges_before_hub_cap"], EDGES_BY_RELATION_BASELINE)

    def test_the_exclusions_are_stated_out_loud(self):
        """The documents block's precedent: a consumer who sees a type layer in
        the index and zero type nodes in ``hotspots`` must be able to read WHY
        here instead of inferring a clean bill of health."""
        excluded = self.on["types"]["excluded_from"]
        for name in ("modules", "import_edges", "duplication", "fan_in",
                     "hotspots", "n_files", "safety_graph_nodes",
                     "defs_by_file", "dss_diffusion", "all_units"):
            with self.subTest(name=name):
                self.assertIn(name, excluded)

    def test_shell_files_are_withheld_from_the_layer(self):
        """Same withholding boundary as ``all_units``: a file outside the
        declared center contributes no node, no edge and no coverage number of
        its own. Otherwise the layer would report metrics about code every other
        block agreed not to measure."""
        scoped = build_index(FIXTURE, documents=False, types=True,
                             ignore=["cross_module_annotation.py"])
        self.assertIn("cross_module_annotation.py", scoped["ignored"]["sample"])
        owners = {n["module"] for n in scoped["type_nodes"]}
        self.assertNotIn("cross_module_annotation.py", owners)
        self.assertLess(scoped["types"]["count"], COUNTS_BASELINE["count"])


# --------------------------------------------------------------------------- #
# 3. THE GATE                                                                  #
# --------------------------------------------------------------------------- #
class TheGateIsHonest(unittest.TestCase):
    """Default OFF, env-readable, explicit-argument-wins -- the ``documents``
    contract, because two gates that behave differently is one gate too many."""

    def tearDown(self):
        os.environ.pop("DAEDALUS_INDEX_TYPES", None)

    def test_off_by_default(self):
        self.assertFalse(types_enabled())
        self.assertFalse(types_enabled(None))

    def test_the_env_var_turns_it_on(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                os.environ["DAEDALUS_INDEX_TYPES"] = value
                self.assertTrue(types_enabled())

    def test_a_non_truthy_env_value_leaves_it_off(self):
        for value in ("", "0", "false", "no", "off", "maybe"):
            with self.subTest(value=value):
                os.environ["DAEDALUS_INDEX_TYPES"] = value
                self.assertFalse(types_enabled())

    def test_the_explicit_argument_wins_both_ways(self):
        os.environ["DAEDALUS_INDEX_TYPES"] = "1"
        self.assertFalse(types_enabled(False))
        os.environ.pop("DAEDALUS_INDEX_TYPES")
        self.assertTrue(types_enabled(True))

    def test_an_unconfigured_build_carries_no_type_layer(self):
        """The default is the safe one, asserted end to end rather than only on
        the predicate."""
        idx = build_index(FIXTURE, documents=False)
        for key in ("types", "type_nodes", "type_edges"):
            with self.subTest(key=key):
                self.assertNotIn(key, idx)

    def test_the_env_var_reaches_build_index(self):
        os.environ["DAEDALUS_INDEX_TYPES"] = "1"
        idx = build_index(FIXTURE, documents=False)
        self.assertIn("types", idx)
        self.assertIs(idx["types"]["enabled"], True)


class TheCacheCannotServeTheWrongConfiguration(unittest.TestCase):
    """``_scope_key`` is the identity of a BUILD, and the type layer changes what
    a build returns -- so it has to be in the key. Without it the in-process
    ``_INDEX_CACHE`` presents as the feature silently not working in one process
    and silently working in the next, which is the worst kind of bug to chase and
    the exact failure the scope fingerprint was added to close."""

    def setUp(self):
        self.scope = project_scope(FIXTURE, None, None)

    def test_the_four_flag_combinations_are_four_distinct_keys(self):
        keys = {
            (docs, types): _scope_key(FIXTURE, self.scope, docs, types)
            for docs in (False, True) for types in (False, True)
        }
        self.assertEqual(len(set(keys.values())), 4, keys)

    def test_the_suffix_order_is_fixed(self):
        """``base+docs+types``, never ``base+types+docs``. A free order would let
        two configurations collide on one key the moment a third flag appears."""
        self.assertTrue(
            _scope_key(FIXTURE, self.scope, True, True).endswith("+docs+types"))
        self.assertTrue(
            _scope_key(FIXTURE, self.scope, False, True).endswith("+types"))
        self.assertFalse(
            _scope_key(FIXTURE, self.scope, True, False).endswith("+types"))

    def test_a_type_free_key_is_unchanged_from_before(self):
        """The pre-feature spelling has to survive exactly, or every cache in
        every running process is invalidated for nothing."""
        self.assertEqual(_scope_key(FIXTURE, self.scope), str(FIXTURE))
        self.assertEqual(_scope_key(FIXTURE, self.scope, False, False),
                         str(FIXTURE))

    def test_the_published_scope_key_differs(self):
        off = _build(types=False)
        on = _build(types=True)
        self.assertNotEqual(on["scope_key"], off["scope_key"])
        self.assertTrue(on["scope_key"].endswith("+types"))

    def test_cached_index_does_not_serve_one_for_the_other(self):
        off = cached_index(FIXTURE, documents=False, types=False)
        on = cached_index(FIXTURE, documents=False, types=True)
        self.assertNotIn("types", off)
        self.assertIn("types", on)
        # And again, so the second call is a genuine cache HIT rather than a
        # rebuild that happens to be right.
        self.assertNotIn("types", cached_index(FIXTURE, documents=False, types=False))
        self.assertIn("types", cached_index(FIXTURE, documents=False, types=True))

    def test_the_resolver_cache_is_keyed_the_same_way(self):
        off = _build(types=False)
        on = _build(types=True)
        self.assertIsNotNone(resolution_context(FIXTURE, off["scope_key"]))
        self.assertIsNotNone(resolution_context(FIXTURE, on["scope_key"]))


class ExtractionIsNotGated(unittest.TestCase):
    """The one place the ``documents`` template must NOT be copied.

    Documents are not on the disk cache at all, so their gate can never poison a
    row. Type facts ARE on it -- they ride ``FileAnalysis`` -- so if the gate
    reached ``analyze_file``, a row written with the layer OFF would hold empty
    facts and a later layer-ON build would be a cache HIT serving empty type
    blocks with no error, no exception and no log line. So extraction is
    unconditional and only resolution/publication are gated.
    """

    def test_analyze_file_extracts_regardless_of_the_env_var(self):
        rel = "dataclass_field_count_collision.py"
        text = (FIXTURE / rel).read_text(encoding="utf-8")
        spec = spec_for(rel)
        saved = os.environ.get("DAEDALUS_INDEX_TYPES")
        try:
            for value in (None, "0", "1"):
                with self.subTest(value=value):
                    if value is None:
                        os.environ.pop("DAEDALUS_INDEX_TYPES", None)
                    else:
                        os.environ["DAEDALUS_INDEX_TYPES"] = value
                    facts = analyze_file(rel, text, spec, False).type_facts
                    self.assertTrue(facts.types)
        finally:
            os.environ.pop("DAEDALUS_INDEX_TYPES", None)
            if saved is not None:
                os.environ["DAEDALUS_INDEX_TYPES"] = saved

    def test_file_key_carries_no_types_segment(self):
        """The corollary: because extraction is unconditional, the per-file key
        needs no gate segment. If a future change gates extraction, THIS test is
        the one that must go red first."""
        from daedalus.structcore import cache as cache_mod
        import inspect

        source = inspect.getsource(cache_mod.file_key)
        self.assertNotIn("DAEDALUS_INDEX_TYPES", source)
        self.assertNotIn("types_enabled", source)

    def test_a_non_python_file_gets_empty_facts_not_a_fabricated_zero(self):
        facts = analyze_file("x.js", "class A { }\n", spec_for("x.js"), False).type_facts
        self.assertEqual(facts.types, ())
        self.assertEqual(facts.fields, ())
        self.assertEqual(facts.signatures, ())


class TheCacheRoundTripsTypeFacts(unittest.TestCase):
    """A cache HIT must equal a cache MISS, exactly. JSON has no tuple, so a
    decoder that forgot to re-tuple would hand back lists where extraction gave
    tuples -- same contents, different ``repr`` and different dataclass equality,
    which is enough to make a warm build differ from a cold one byte for byte."""

    def test_analysis_version_was_bumped(self):
        """Verified, not assumed: the constant is part of every ``file_key``, and
        a row from the generation before ``type_facts`` existed must not be
        served to this one."""
        self.assertEqual(ANALYSIS_VERSION, "5")

    def test_type_facts_survive_the_round_trip_exactly(self):
        """Dataclass EQUALITY, over every file in the corpus -- which is stricter
        than it looks, because a frozen dataclass compares its tuple fields by
        type as well as by contents, so a list that should have been a tuple is a
        failure here rather than a difference nobody notices.

        Deliberately NOT ``assertEqual(back, analysis)`` on the whole
        ``FileAnalysis``: the PRE-EXISTING ``py_imports`` codec turns the nested
        ``tuple`` of imported names into a ``list`` on the way back
        (cache.py's own comment says so and calls it shape-compatible, because
        ``resolve_python_imports`` only unpacks positionally and iterates). That
        asymmetry is inert -- ``test_a_warm_cache_equals_a_cold_one`` proves the
        whole index is byte-identical across it -- but it is not this layer's,
        and asserting it away here would either fail for someone else's reason or
        quietly bless it. The new field does not inherit it: that is what this
        test is for.
        """
        for rel in sorted(p.name for p in FIXTURE.glob("*.py")):
            text = (FIXTURE / rel).read_text(encoding="utf-8")
            analysis = analyze_file(rel, text, spec_for(rel), False)
            with self.subTest(rel=rel):
                back = _decode(_encode(analysis))
                self.assertEqual(back.type_facts, analysis.type_facts)
                # Everything except the two pre-existing import lists.
                for name in ("rel", "lang", "n_chars", "n_tokens", "loc",
                             "metrics", "units", "runs"):
                    self.assertEqual(getattr(back, name), getattr(analysis, name),
                                     name)

    def test_tuple_fields_come_back_as_tuples(self):
        rel = "generic_containers.py"
        text = (FIXTURE / rel).read_text(encoding="utf-8")
        back = _decode(_encode(analyze_file(rel, text, spec_for(rel), False)))
        facts = back.type_facts
        for name in ("types", "fields", "signatures", "aliases"):
            with self.subTest(name=name):
                self.assertIsInstance(getattr(facts, name), tuple)
        for decl in facts.types:
            with self.subTest(decl=decl.qualname):
                self.assertIsInstance(decl.bases, tuple)
                self.assertIsInstance(decl.decorators, tuple)
        for sig in facts.signatures:
            with self.subTest(sig=sig.qualname):
                self.assertIsInstance(sig.params, tuple)
                self.assertIsInstance(sig.decorators, tuple)

    def test_an_old_row_without_type_facts_is_a_miss_not_a_default(self):
        """The second lock on the door: ``_decode`` reads by subscript, so a
        pre-type payload raises rather than decoding into an analysis that claims
        the file has no types."""
        import zlib

        rel = "dataclass_field_count_collision.py"
        text = (FIXTURE / rel).read_text(encoding="utf-8")
        blob = _encode(analyze_file(rel, text, spec_for(rel), False))
        doc = json.loads(zlib.decompress(blob).decode("utf-8"))
        del doc["type_facts"]
        stale = zlib.compress(json.dumps(doc).encode("utf-8"), 1)
        with self.assertRaises(KeyError):
            _decode(stale)

    def test_the_facts_survive_a_pickle(self):
        """``FileAnalysis`` crosses a process boundary in the parallel path, so
        the new field has to be picklable and equality-stable."""
        import pickle

        rel = "protocol_structural_match.py"
        text = (FIXTURE / rel).read_text(encoding="utf-8")
        analysis = analyze_file(rel, text, spec_for(rel), False)
        self.assertEqual(pickle.loads(pickle.dumps(analysis)), analysis)

    def test_extraction_matches_the_standalone_entry_point(self):
        """``analyze_file`` must not be a second, drifting extractor: it has to
        produce exactly what ``python_type_facts`` produces from the same bytes."""
        for rel in sorted(p.name for p in FIXTURE.glob("*.py")):
            text = (FIXTURE / rel).read_text(encoding="utf-8")
            with self.subTest(rel=rel):
                self.assertEqual(analyze_file(rel, text, spec_for(rel), False).type_facts,
                                 python_type_facts(rel, text))

    def test_an_empty_facts_default_is_immutable_and_shared(self):
        """A frozen dataclass of tuples is safe as a plain dataclass default. If
        someone makes it mutable, two ``FileAnalysis`` objects start sharing
        state across the whole build."""
        from dataclasses import FrozenInstanceError

        with self.assertRaises(FrozenInstanceError):
            PyTypeFacts().types = ()  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 4. DETERMINISM                                                               #
# --------------------------------------------------------------------------- #
def _canon(idx: dict) -> str:
    """Serialize WITHOUT sorting keys, on purpose: ``fan_in``, ``modules`` and
    ``hotspots`` carry meaning in their ORDER, so sorting here would hide exactly
    the class of non-determinism worth catching."""
    return json.dumps({k: v for k, v in idx.items() if k != "root"},
                      sort_keys=False, default=str)


class TheBuildIsDeterministic(unittest.TestCase):
    """Two processes must produce byte-identical output, so every iteration over
    a set or a dict whose order can reach the output is sorted. The type layer
    iterates a lot of dicts."""

    def test_a_rebuild_is_byte_identical(self):
        self.assertEqual(_canon(_build(types=True)), _canon(_build(types=True)))

    def test_a_warm_cache_equals_a_cold_one(self):
        """The disk cache is the likeliest place for a list-vs-tuple divergence
        to hide, because it is the only path where the facts are reconstructed
        rather than extracted."""
        cold_dir = tempfile.mkdtemp(prefix="tgidx-cold-")
        saved = os.environ["DAEDALUS_CACHE_DIR"]
        try:
            os.environ["DAEDALUS_CACHE_DIR"] = cold_dir
            cold = _build(types=True)      # populates the empty cache
            warm = _build(types=True)      # every file a hit
            self.assertEqual(_canon(cold), _canon(warm))
        finally:
            os.environ["DAEDALUS_CACHE_DIR"] = saved
            shutil.rmtree(cold_dir, ignore_errors=True)

    def test_the_process_pool_equals_the_serial_path(self):
        """``PyTypeFacts`` crosses a pickle boundary in the pool. Forced with
        ``DAEDALUS_SCAN_MIN_PARALLEL`` because the fixture is far below the
        real threshold, so the pool would otherwise never be exercised."""
        saved = {k: os.environ.get(k) for k in
                 ("DAEDALUS_SCAN_MIN_PARALLEL", "DAEDALUS_SCAN_WORKERS",
                  "DAEDALUS_NO_CACHE")}
        try:
            os.environ["DAEDALUS_NO_CACHE"] = "1"
            os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "999999"
            serial = _build(types=True)
            os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "2"
            os.environ["DAEDALUS_SCAN_WORKERS"] = "2"
            parallel = _build(types=True)
            self.assertEqual(_canon(serial), _canon(parallel))
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_nodes_and_every_relation_are_sorted(self):
        idx = _build(types=True)
        ids = [n["id"] for n in idx["type_nodes"]]
        self.assertEqual(ids, sorted(ids))
        for relation, rows in sorted(idx["type_edges"].items()):
            pairs = [(r["source"], r["target"]) for r in rows]
            with self.subTest(relation=relation):
                self.assertEqual(pairs, sorted(pairs))

    def test_a_subprocess_agrees_with_this_process(self):
        """A fresh interpreter, i.e. a fresh ``PYTHONHASHSEED``. Set-iteration
        order is the classic way a "deterministic" index turns out to be
        deterministic only within one process."""
        import subprocess
        import sys

        script = (
            "import json,os,sys\n"
            "sys.path.insert(0, r'%s')\n"
            "from daedalus.structcore.index import build_index\n"
            "idx = build_index(r'%s', documents=False, types=True)\n"
            "print(json.dumps({k: v for k, v in idx.items() if k != 'root'},"
            " sort_keys=False, default=str))\n"
        ) % (REPO_ROOT, FIXTURE)
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "12345"
        out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                             text=True, env=env, cwd=str(REPO_ROOT))
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip(), _canon(_build(types=True)))


if __name__ == "__main__":
    unittest.main()
