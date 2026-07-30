"""The type layer's DETERMINISM and REFUSE-TO-GUESS contract.

Two processes must produce byte-identical output, and every name the layer
could not pin down must produce NO edge and a COUNTER.  Those two properties
are one subject, not two, which is why they share a file: determinism is what
makes a wrong answer permanent.  The plan says it in one line -- "deterministic
is not the same as correct: taking the first sorted import when two modules both
define ``Result`` yields a stably reproduced FALSE edge" -- so a determinism
suite that did not also assert the refusals would be certifying the bug.

WHY SUBPROCESSES AND NOT A SECOND CALL IN THIS ONE
--------------------------------------------------
``PYTHONHASHSEED`` is fixed for the lifetime of an interpreter.  A second call
inside this process re-uses the same salt, so it cannot see the failure this
file exists to catch: a ``set`` or an unsorted ``dict`` whose iteration order
reaches output.  ``test_typegraph_resolve.py`` already re-resolves in-process
(that catches accumulated state); this file runs the WHOLE pipeline -- scan,
extract, resolve, publish, forest -- in six fresh interpreters at six different
salts, including ``PYTHONHASHSEED=random``, which is the only setting that
varies the salt on every single run and therefore the only one that can fail
intermittently rather than never.  The precedent is not theoretical: this
package has MEASURED non-determinism before (``test_typegraph_fixture.py``
records 3 distinct slice hashes over 5 seeds for the distilled slice).

WHAT THE DIGEST COVERS
----------------------
One digest over one payload, so a drift anywhere fails here rather than in
whichever consumer notices first.  The payload names each ordered thing
separately -- ``type_edge_order``, ``field_child_order``, ``union_ids``,
``forest_content_sha256``, ``forest_node_order``, ``forest_edge_order``, plus
the whole ``types`` block with its coverage samples -- so a failure reports a
PATH (``$.type_edge_order.consumes[3].2``) instead of "the hashes differ", and
``_ORDER_SOURCE`` turns that path into the line of code whose iteration leaked.
A single opaque hash would prove the bug exists and tell you nothing about
where, which in a suite whose whole job is diagnosis is not good enough.

WHAT ``union_id`` HAS TO BE
---------------------------
Content-derived, never counted.  A counter is deterministic within one run and
still wrong: it renumbers when a file is added, when the corpus is filtered, or
when the members of a union are visited in a different order, so two runs over
overlapping inputs disagree about which edges belong to one annotation.  The
strongest available refutation is here: resolving ``union_shapes.py`` ALONE
yields the same three ids as resolving all sixteen files, which no counter can
do.

RED-VERIFIED, ONE BREAK AT A TIME
---------------------------------
Every guard below was broken deliberately and the suite watched go red, then the
file was restored byte-for-byte (sha256 checked).  Eleven breaks, eleven
failures: edge rows ordered out of a set; ``union_id`` replaced by a counter;
node rows ordered out of a set; the ambiguous branch taking ``candidates[0]``;
``unresolved`` silently not counted; the ambiguous ``candidates`` list and the
``unresolved_sample`` list left unsorted; ``Any`` admitted to
``Annotation.members`` as ``"Any"`` and again as ``ANY_SENTINEL``; the dropped
mapping key left uncounted; ``not_supported`` replaced by a numeric ``0``; and
the language report built from ``set(languages)`` instead of ``sorted``.

TWO BREAKS DID NOT FIRE, and both are findings rather than gaps -- recorded here
because a future reader will otherwise assume the tests missed them:

  * Deleting the ``return`` after ``site_counts["sites_any"] += 1`` in
    ``resolve_type_graph.emit`` changes NOTHING.  A bare ``Any`` has EMPTY
    ``members`` (parse.py never puts ``Any`` in), so the ``if not ann.members``
    branch two lines down already refuses.  The early return is defence in
    depth; the operative guard is the empty member tuple, which is why the two
    ``Any``-as-a-member breaks above are the ones that matter and are tested.
  * Iterating ``set(ann.members)`` instead of ``ann.members`` when emitting a
    union changes NOTHING either, because the final
    ``sorted(edges[relation], key=_edge_key)`` re-orders the rows by
    ``(source, target, attributes)`` and the members of one union have distinct
    targets.  Member ORDER is screened off from output by that sort; what is
    NOT screened off is the sort itself, which is break #1.

Companion files: ``test_typegraph_parse.py`` (extraction),
``test_typegraph_resolve.py`` (resolution), ``test_typegraph_index.py`` (the
index blocks), ``test_typegraph_forest.py`` (the forest wiring),
``test_typegraph_fixture.py`` (the pre-feature baselines).

Nothing here touches the network, a model or a vendor CLI, and nothing here
imports a fixture file as a module -- they are read as TEXT.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore import build_index
from daedalus.structcore import typegraph as tg
from daedalus.structcore.forest import build_knowledge_forest
from daedalus.structcore.parse import ANY_SENTINEL, python_type_facts

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "typegraph"

# Every env var that can move a number here.  Popped for the whole module (and
# for every subprocess) because ``documents``/``types``/cache/parallelism all
# consult the environment when left at their default, and a baseline that
# depends on the caller's shell is not a baseline.
_PINNED = ("DAEDALUS_INDEX_DOCUMENTS", "DAEDALUS_INDEX_TYPES",
           "DAEDALUS_CACHE_DIR", "DAEDALUS_NO_CACHE",
           "DAEDALUS_SCAN_MIN_PARALLEL", "DAEDALUS_SCAN_WORKERS")
_SAVED: dict[str, str | None] = {}
_TMP_DIRS: list[str] = []


def setUpModule() -> None:
    for name in _PINNED:
        _SAVED[name] = os.environ.get(name)
        os.environ.pop(name, None)
    os.environ["DAEDALUS_CACHE_DIR"] = _mktmp("tgdet-cache-")


def tearDownModule() -> None:
    for name, value in _SAVED.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    for path in _TMP_DIRS:
        shutil.rmtree(path, ignore_errors=True)


def _mktmp(prefix: str) -> str:
    path = tempfile.mkdtemp(prefix=prefix)
    _TMP_DIRS.append(path)
    return path


# --------------------------------------------------------------------------- #
# Captured fixture facts.  CAPTURED by running the code, never typed by hand.   #
# The fixture repo is frozen by construction (see its README), so a red line    #
# below means the CODE changed -- never re-capture one to make a test pass.     #
# --------------------------------------------------------------------------- #
# D3: the only bare ``Any`` in the corpus is unresolvable_annotations.py's
# ``takes_any(payload: Any) -> Any`` -- one param slot and one return slot.
ANY_SITES = 2
ANY_INSIDE_SITES = 2
# D4: ``Result`` is undecidable in TWO files (try/except import and star
# import), each at a param slot and a return slot.  4 = 2 files x 2 slots.
AMBIGUOUS_ATTEMPTS = 4
# D4: ``NoSuchTypeAnywhere`` appears bare and inside ``list[...]``.  The two
# RETURN slots of those functions are ``None`` and ``int``, which are not
# unresolved -- they are counted as ``sites_none`` and ``builtin``.
UNRESOLVED_ATTEMPTS = 2
# D2: three union sites, each contributing two member edges.
UNION_IDS = (
    "union_shapes.py#produce_union:return:",
    "union_shapes.py#take_nested:param:value",
    "union_shapes.py#take_union:param:value",
)
UNION_EDGES = 6

# PYTHONHASHSEED settings.  Six, one of them ``random``: 0 disables hashing
# randomisation entirely, the four integers pick fixed distinct salts, and
# ``random`` re-salts on every run and is therefore the only value that can
# catch an order leak that happens to be stable at fixed salts.
SEEDS = ("0", "1", "2", "12345", "98765", "random")

# Which iteration a differing payload path implicates.  The point of naming the
# ordered things separately in the payload is that the failure message can say
# WHICH set or dict reached output instead of "the digests differ".
_ORDER_SOURCE = {
    "type_edge_order":
        "typegraph.resolve_type_graph's final `sorted(edges[relation], "
        "key=_edge_key)` (or an unsorted dict feeding the append loop above it)",
    "field_child_order":
        "the has_field append loop over `_dedupe_fields(facts[rel].fields)` "
        "in typegraph.resolve_type_graph, i.e. parse.PyTypeFacts.fields order",
    "union_ids":
        "typegraph.union_id / `ann.members` -- member order must be SOURCE "
        "order out of parse.flatten_union, never a set",
    "forest_content_sha256":
        "forest.build_knowledge_forest's node/edge row sort (or a set reaching "
        "the type/field layers)",
    "language_key_order":
        "typegraph.resolve_type_graph's `for lang in sorted(languages or {})` "
        "loop building `lang_report`",
    "forest_node_order": "forest.build_knowledge_forest's node sort",
    "forest_edge_order": "forest.build_knowledge_forest's edge sort",
    "type_nodes":
        "typegraph.resolve_type_graph's `tuple(nodes[node_id] for node_id in "
        "sorted(nodes))`",
    "types":
        "a coverage aggregate -- most likely `sorted(set(unresolved_sample))` / "
        "`sorted(set(ambiguous_sample))`, the hub table, or `languages`",
}


# --------------------------------------------------------------------------- #
# The subprocess probe                                                         #
# --------------------------------------------------------------------------- #
# Runs the WHOLE pipeline and prints ONE json document.  Everything whose ORDER
# is load-bearing is named as its own key so a diff points at a line of code.
_PROBE = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from daedalus.structcore import build_index
from daedalus.structcore import typegraph as tg
from daedalus.structcore.forest import build_knowledge_forest

idx = build_index(Path(sys.argv[2]), documents=False, types=True)
forest = build_knowledge_forest(idx)

order, union_ids, field_children = {}, [], []
for relation in tg.RELATIONS:
    rows = idx["type_edges"].get(relation, [])
    order[relation] = [
        [row["source"], row["target"],
         json.dumps(row["attributes"], sort_keys=True)] for row in rows]
    for row in rows:
        group = row["attributes"].get("union_id", "")
        if group:
            union_ids.append([relation, row["source"], row["target"], group])
    if relation == tg.REL_HAS_FIELD:
        field_children = [[row["source"], row["target"]] for row in rows]

payload = {
    "types": idx["types"],
    "type_nodes": idx["type_nodes"],
    "type_edge_order": order,
    "field_child_order": field_children,
    "union_ids": union_ids,
    "forest_content_sha256": forest.content_sha256,
    # A LIST, because the payload is serialised with sort_keys=True and that
    # normalises every dict KEY order away.  The language report's key order is
    # a real output and has to be carried as a sequence to be seen at all.
    "language_key_order": list(idx["types"]["coverage"]["languages"]),
    "forest_node_order": [[n.kind, n.id] for n in forest.nodes],
    "forest_edge_order": [
        [e.relation, e.source, e.target,
         json.dumps(e.to_dict()["attributes"], sort_keys=True)]
        for e in forest.edges],
}
sys.stdout.write(json.dumps(payload, sort_keys=True))
'''

_PROBES: dict[str, str] = {}


def _run_probe(label: str, seed: str, extra: dict | None = None) -> str:
    env = dict(os.environ)
    for name in _PINNED:
        env.pop(name, None)
    env["PYTHONHASHSEED"] = seed
    # A private cache dir per run: a shared one would let run N read run N-1's
    # rows, which is the one arrangement in which a non-deterministic EXTRACTOR
    # cannot fail.  Cold every time is the honest test.
    env["DAEDALUS_CACHE_DIR"] = _mktmp("tgdet-%s-" % label)
    env.update(extra or {})
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT), str(FIXTURE)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        env=env, timeout=600)
    if proc.returncode != 0:                       # pragma: no cover - diagnosis
        raise AssertionError(
            "probe %s (PYTHONHASHSEED=%s) exited %d:\n%s"
            % (label, seed, proc.returncode, proc.stderr[-4000:]))
    return proc.stdout


def _first_difference(left, right, path: str = "$") -> str:
    """The first path at which two json documents disagree, or ""."""
    if type(left) is not type(right):
        return "%s: type %s vs %s" % (path, type(left).__name__,
                                      type(right).__name__)
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return "%s.%s: absent on the left" % (path, key)
            if key not in right:
                return "%s.%s: absent on the right" % (path, key)
            found = _first_difference(left[key], right[key],
                                      "%s.%s" % (path, key))
            if found:
                return found
        return ""
    if isinstance(left, list):
        if len(left) != len(right):
            return "%s: length %d vs %d" % (path, len(left), len(right))
        for position, (one, two) in enumerate(zip(left, right)):
            found = _first_difference(one, two, "%s[%d]" % (path, position))
            if found:
                return found
        return ""
    if left != right:
        return "%s: %r vs %r" % (path, left, right)
    return ""


def _diagnose(left_label: str, right_label: str, left: str, right: str) -> str:
    """A failure message that names the leaking iteration, not just the hash."""
    where = _first_difference(json.loads(left), json.loads(right)) \
        or "(the digests differ but the parsed documents compare equal -- " \
           "suspect key ORDER in a json.dumps that lost sort_keys)"
    top = where.lstrip("$").lstrip(".").split(".")[0].split("[")[0]
    return (
        "%s and %s disagree.\n"
        "  first difference: %s\n"
        "  suspect: %s"
        % (left_label, right_label, where,
           _ORDER_SOURCE.get(top, "unknown -- follow the path above")))


# --------------------------------------------------------------------------- #
# In-process state, built once                                                 #
# --------------------------------------------------------------------------- #
_STATE: dict = {}


def _state() -> dict:
    """The fixture index with the type layer ON, plus its forest.

    ``documents`` and ``types`` are ALWAYS explicit: both consult an env var
    when left as None.
    """
    if not _STATE:
        index = build_index(FIXTURE, documents=False, types=True)
        _STATE["index"] = index
        _STATE["types"] = index["types"]
        _STATE["coverage"] = index["types"]["coverage"]
        _STATE["nodes"] = index["type_nodes"]
        _STATE["edges"] = index["type_edges"]
        _STATE["forest"] = build_knowledge_forest(index)
        _STATE["all_edges"] = [
            (relation, row)
            for relation in tg.RELATIONS
            for row in index["type_edges"].get(relation, [])
        ]
    return _STATE


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        state = _state()
        cls.index = state["index"]
        cls.types = state["types"]
        cls.coverage = state["coverage"]
        cls.nodes = state["nodes"]
        cls.edges = state["edges"]
        cls.forest = state["forest"]
        cls.all_edges = state["all_edges"]


# --------------------------------------------------------------------------- #
# D1. BYTE-IDENTITY ACROSS PYTHONHASHSEEDS                                     #
# --------------------------------------------------------------------------- #
class ByteIdentityAcrossHashSeeds(unittest.TestCase):
    """Six fresh interpreters, six salts, one digest.

    The salt changes ``set`` and ``dict`` iteration order for str keys, which is
    every key this layer has: rels, qualnames, node ids, candidate sets, the
    fan-in table.  If any of them reaches output unsorted, at least one of these
    six runs disagrees -- and ``PYTHONHASHSEED=random`` means the disagreement
    is found eventually even if the fixed salts happen to collide.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not _PROBES:
            for seed in SEEDS:
                _PROBES["seed=%s" % seed] = _run_probe("seed%s" % seed, seed)
            # The same question asked of the PARALLEL scan path, where worker
            # completion order is a second, independent source of disorder that
            # the serial default cannot exercise.
            _PROBES["parallel"] = _run_probe(
                "par", "random",
                {"DAEDALUS_SCAN_MIN_PARALLEL": "1",
                 "DAEDALUS_SCAN_WORKERS": "4"})
        cls.probes = dict(_PROBES)

    def _digest(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_at_least_five_distinct_hash_seeds_were_actually_run(self):
        """Guards the guard: a suite that quietly ran one seed proves nothing,
        and the plan asks for at least five."""
        self.assertGreaterEqual(len(SEEDS), 5)
        self.assertEqual(len(set(SEEDS)), len(SEEDS))
        self.assertIn("random", SEEDS)
        self.assertEqual(len(self.probes), len(SEEDS) + 1)
        for label, output in self.probes.items():
            self.assertTrue(output.strip(), "%s produced no output" % label)

    def test_one_digest_over_every_seed(self):
        """The headline assertion: ONE digest, all runs."""
        digests = {label: self._digest(text)
                   for label, text in self.probes.items()}
        if len(set(digests.values())) != 1:
            labels = sorted(self.probes)
            reference = labels[0]
            messages = [
                _diagnose(reference, other,
                          self.probes[reference], self.probes[other])
                for other in labels[1:]
                if digests[other] != digests[reference]
            ]
            self.fail("the type layer is NOT deterministic across "
                      "PYTHONHASHSEED.\n" + "\n".join(messages))
        self.assertEqual(len(set(digests.values())), 1, digests)

    def test_this_process_agrees_with_the_subprocesses(self):
        """The in-process build -- the one every other test in this file reads
        -- must be the same artefact the subprocesses produced, or those tests
        are asserting about a different object."""
        state = _state()
        sample = json.loads(self.probes["seed=0"])
        self.assertEqual(
            json.dumps(sample["types"], sort_keys=True),
            json.dumps(state["types"], sort_keys=True))
        self.assertEqual(
            json.dumps(sample["type_nodes"], sort_keys=True),
            json.dumps(state["nodes"], sort_keys=True))
        self.assertEqual(sample["forest_content_sha256"],
                         state["forest"].content_sha256)

    # -- the four things the digest is REQUIRED to cover ------------------- #
    def test_the_type_edge_order_is_covered_and_identical(self):
        orders = {label: json.loads(text)["type_edge_order"]
                  for label, text in self.probes.items()}
        reference = orders["seed=0"]
        self.assertEqual(sorted(reference), sorted(tg.RELATIONS))
        self.assertTrue(any(reference[r] for r in reference),
                        "no type edges at all -- the payload is vacuous")
        for label, order in sorted(orders.items()):
            self.assertEqual(order, reference, label)

    def test_the_field_child_order_is_covered_and_identical(self):
        """Field children are the one order NOT produced by a sort over ids:
        they follow ``PyTypeFacts.fields`` through ``_dedupe_fields``, so a set
        anywhere in extraction lands here first."""
        orders = {label: json.loads(text)["field_child_order"]
                  for label, text in self.probes.items()}
        reference = orders["seed=0"]
        self.assertTrue(reference, "no has_field rows -- the payload is vacuous")
        owners = {}
        for source, target in reference:
            owners.setdefault(source, []).append(target)
        self.assertTrue(any(len(children) > 1 for children in owners.values()),
                        "no type has two fields -- ORDER cannot be tested")
        for label, order in sorted(orders.items()):
            self.assertEqual(order, reference, label)

    def test_the_union_ids_are_covered_and_identical(self):
        groups = {label: json.loads(text)["union_ids"]
                  for label, text in self.probes.items()}
        reference = groups["seed=0"]
        self.assertEqual(len(reference), UNION_EDGES)
        for label, rows in sorted(groups.items()):
            self.assertEqual(rows, reference, label)

    def test_the_forest_content_sha256_is_covered_and_identical(self):
        hashes = {label: json.loads(text)["forest_content_sha256"]
                  for label, text in self.probes.items()}
        self.assertEqual(len(set(hashes.values())), 1, hashes)
        self.assertEqual(len(next(iter(hashes.values()))), 64)

    def test_the_forest_row_order_is_covered_and_identical(self):
        for key in ("forest_node_order", "forest_edge_order"):
            rows = {label: json.loads(text)[key]
                    for label, text in self.probes.items()}
            reference = rows["seed=0"]
            self.assertTrue(reference, "%s is empty" % key)
            for label, value in sorted(rows.items()):
                self.assertEqual(value, reference, "%s / %s" % (key, label))

    def test_the_parallel_scan_path_agrees_with_the_serial_one(self):
        """Named separately from the seed sweep so a failure reads as "the
        worker pool leaked" rather than "a hash seed leaked"."""
        self.assertEqual(
            self._digest(self.probes["parallel"]),
            self._digest(self.probes["seed=0"]),
            _diagnose("the serial scan", "the parallel scan",
                      self.probes["seed=0"], self.probes["parallel"]))

    def test_the_input_order_of_the_facts_cannot_reach_the_output(self):
        """The same claim asked without a subprocess: hand the resolver its
        files in reverse and the published blocks must not move.  This is the
        cheap regression that runs even when subprocesses are unavailable."""
        facts = {
            path.relative_to(FIXTURE).as_posix():
                python_type_facts(path.relative_to(FIXTURE).as_posix(),
                                  path.read_text(encoding="utf-8"))
            for path in sorted(FIXTURE.rglob("*.py"))
        }
        forward = tg.resolve_type_graph(
            facts_by_rel=facts,
            imports_by_file=_state()["index"]["import_edges"],
            languages=_state()["index"]["languages"])
        backward = tg.resolve_type_graph(
            facts_by_rel=dict(reversed(list(facts.items()))),
            imports_by_file=dict(reversed(list(
                _state()["index"]["import_edges"].items()))),
            languages=_state()["index"]["languages"])
        self.assertEqual(
            json.dumps(forward.to_index_blocks(), sort_keys=True),
            json.dumps(backward.to_index_blocks(), sort_keys=True))


# --------------------------------------------------------------------------- #
# D2. union_id IS CONTENT-DERIVED, NOT A COUNTER                               #
# --------------------------------------------------------------------------- #
class UnionIdIsContentDerived(_Fixture):
    """A counter is deterministic and still wrong.

    ``union_id`` exists so a consumer can tell "this function takes an Alpha OR
    a Beta" (one annotation, two edges) from "it takes an Alpha and, elsewhere,
    a Beta".  A counter satisfies a single-run determinism test and then
    renumbers the moment the corpus changes shape, so two runs over overlapping
    inputs disagree about which edges belong together.  Every assertion below
    is one a counter fails.
    """

    def _union_rows(self):
        return [(relation, row) for relation, row in self.all_edges
                if row["attributes"].get("union_id")]

    def test_the_id_is_exactly_the_site_it_names(self):
        """The definition, asked of the helper: no state, no counter, no clock
        -- four strings in, one string out."""
        self.assertEqual(tg.union_id("m.py", "f", "param", "x"),
                         "m.py#f:param:x")
        self.assertEqual(tg.union_id("m.py", "f", "return", ""),
                         "m.py#f:return:")
        self.assertEqual(tg.union_id("m.py", "f", "param", "x"),
                         tg.union_id("m.py", "f", "param", "x"))

    def test_every_published_id_recomputes_from_its_own_attributes(self):
        """The strongest in-repo form: take the edge's OWN description of where
        it came from, recompute the id from it, and require a match.  A counter
        cannot be recomputed from the site at all."""
        rows = self._union_rows()
        self.assertEqual(len(rows), UNION_EDGES)
        for relation, row in rows:
            # CAPTURED: every union site in this corpus is a function slot, so
            # ``source`` is the rel and the owner is in ``function``.  Asserted
            # rather than assumed, because a union FIELD would make the
            # recomputation below read the wrong attributes and pass anyway.
            self.assertIn(relation, (tg.REL_CONSUMES, tg.REL_PRODUCES))
            attributes = row["attributes"]
            recomputed = tg.union_id(row["source"], attributes["function"],
                                     attributes["role"], attributes["param"])
            self.assertEqual(attributes["union_id"], recomputed,
                             "%s %s -> %s" % (relation, row["source"],
                                              row["target"]))

    def test_the_same_annotation_in_the_same_place_agrees_across_processes(self):
        """D2's cross-process half.  The subprocess payload carries the ids in
        publication order, so this compares values AND pairing."""
        if not _PROBES:                              # pragma: no cover - order
            ByteIdentityAcrossHashSeeds.setUpClass()
        published = [
            [relation, row["source"], row["target"],
             row["attributes"]["union_id"]]
            for relation, row in self._union_rows()
        ]
        for label, text in sorted(_PROBES.items()):
            self.assertEqual(json.loads(text)["union_ids"], published, label)

    def test_two_different_params_never_share_an_id(self):
        """Injectivity.  Asked two ways: over the published edges (each id must
        name exactly one site) and over the helper (distinct sites must produce
        distinct ids), because the first alone passes vacuously on a corpus with
        one union per function."""
        sites_by_id: dict[str, set] = {}
        for _relation, row in self._union_rows():
            attributes = row["attributes"]
            sites_by_id.setdefault(attributes["union_id"], set()).add(
                (row["source"], attributes["function"],
                 attributes["role"], attributes["param"]))
        self.assertEqual(sorted(sites_by_id), sorted(UNION_IDS))
        for group, sites in sorted(sites_by_id.items()):
            self.assertEqual(len(sites), 1,
                             "%s names %d sites: %r" % (group, len(sites),
                                                        sorted(sites)))

        distinct_sites = [
            ("m.py", "f", "param", "x"), ("m.py", "f", "param", "y"),
            ("m.py", "f", "return", ""), ("m.py", "g", "param", "x"),
            ("n.py", "f", "param", "x"), ("m.py", "C.f", "param", "x"),
            ("m.py", "C.f", "field", ""),
        ]
        produced = [tg.union_id(*site) for site in distinct_sites]
        self.assertEqual(len(set(produced)), len(distinct_sites), produced)

    def test_the_members_of_one_union_share_one_id_and_two_unions_do_not(self):
        """The property the id exists for.  ``take_union(value: Union[Alpha,
        Beta])`` must publish two edges under ONE id; ``take_nested`` is a
        different site and must not borrow it."""
        by_id: dict[str, list[str]] = {}
        for _relation, row in self._union_rows():
            by_id.setdefault(row["attributes"]["union_id"], []).append(
                row["target"])
        for group, targets in sorted(by_id.items()):
            self.assertEqual(len(targets), 2, group)
            self.assertEqual(len(set(targets)), 2, group)
        self.assertEqual(len(by_id), len(UNION_IDS))

    def test_resolving_one_file_alone_yields_the_same_ids_as_the_whole_corpus(self):
        """THE counter-refutation.  A counter numbers by arrival, so a corpus of
        one file renumbers everything; a content-derived id cannot notice that
        the other fifteen files are missing."""
        rel = "union_shapes.py"
        alone = tg.resolve_type_graph(facts_by_rel={
            rel: python_type_facts(rel, (FIXTURE / rel).read_text(
                encoding="utf-8"))})
        subset_ids = sorted({
            row["attributes"]["union_id"]
            for relation in tg.RELATIONS
            for row in alone.edges[relation]
            if row["attributes"].get("union_id")})
        self.assertEqual(tuple(subset_ids), UNION_IDS)
        self.assertEqual(
            subset_ids,
            sorted({row["attributes"]["union_id"]
                    for _relation, row in self._union_rows()}))

    def test_a_non_union_annotation_carries_an_empty_id_not_a_number(self):
        """``union_id`` is minted for union sites only.  A blank is honest; a
        counter that numbered every site would be indistinguishable from one
        that grouped them wrongly."""
        for relation, row in self.all_edges:
            attributes = row["attributes"]
            if "union_id" not in attributes:
                continue
            if attributes.get("union"):
                self.assertTrue(attributes["union_id"], (relation, row))
            else:
                self.assertEqual(attributes["union_id"], "", (relation, row))


# --------------------------------------------------------------------------- #
# D3. NO EDGE TO ``Any``                                                       #
# --------------------------------------------------------------------------- #
class AnyProducesNoEdgeAndIsCounted(_Fixture):
    """``Any`` is annotated, resolvable and says nothing.

    Folding it into "covered" claims a type we do not have; folding it into
    "unresolved" claims a gap we could close by looking harder.  It gets its own
    bucket, and it gets no edge and no node -- a ``type`` node called ``Any``
    would be a hub by construction (it is one of the eight measured hubs behind
    the hub cap).
    """

    def test_no_node_is_named_any(self):
        for node in self.nodes:
            self.assertNotEqual(node["name"], "Any", node)
            self.assertNotEqual(node["qualname"], "Any", node)
        # ``parse.ANY_SENTINEL`` is a documented LABEL ("<any>") that is
        # deliberately never put into ``Annotation.members``.  If it ever
        # reaches a node id, refusing to edge stopped being the default.
        ids = [node["id"] for node in self.nodes]
        self.assertNotIn(ANY_SENTINEL, ids)
        for node_id in ids:
            self.assertNotIn(ANY_SENTINEL, node_id)

    def test_no_edge_points_at_any(self):
        for relation, row in self.all_edges:
            self.assertNotIn("#Any", row["target"], (relation, row))
            self.assertNotEqual(row["attributes"].get("member"), "Any",
                                (relation, row))
            self.assertNotEqual(row["attributes"].get("annotation"), "Any",
                                (relation, row))

    def test_the_any_annotated_function_produced_no_edge_at_all(self):
        """``takes_any`` is annotated on both slots, so an implementation that
        skipped only UNANNOTATED slots would still emit two edges here."""
        refs = {row["attributes"].get("function_ref")
                for relation, row in self.all_edges
                if relation in (tg.REL_CONSUMES, tg.REL_PRODUCES)}
        self.assertNotIn("unresolvable_annotations.py#takes_any", refs)
        self.assertIn("union_shapes.py#take_union", refs)   # positive control

    def test_any_is_counted_in_its_own_bucket(self):
        self.assertEqual(self.coverage["sites_any"], ANY_SITES)
        self.assertEqual(self.coverage["sites_any_inside"], ANY_INSIDE_SITES)

    def test_any_is_not_smuggled_into_unresolved_or_ambiguous(self):
        """The counter must not double-count: an ``Any`` that also raised
        ``unresolved`` would make the gap look worse and the fix look
        possible."""
        names = {row["name"] for row in self.coverage["unresolved_sample"]}
        names |= {row["name"] for row in self.coverage["ambiguous_sample"]}
        self.assertNotIn("Any", names)
        self.assertEqual(self.coverage["vocabulary"], 0)

    def test_a_bare_any_never_even_reaches_the_resolver(self):
        """Measured on an inline module rather than inferred: with ``Any`` the
        only vocabulary present, ``attempts`` is ZERO.  Refusing to edge is the
        default, not a filter applied afterwards."""
        source = ("from typing import Any\n\n"
                  "class Box:\n    payload: Any\n\n"
                  "def use(value: Any) -> Any:\n    return value\n")
        graph = tg.resolve_type_graph(
            facts_by_rel={"m.py": python_type_facts("m.py", source)})
        self.assertEqual(graph.coverage["attempts"], 0)
        self.assertEqual(graph.coverage["sites_any"], 3)
        self.assertEqual(
            {relation: len(rows) for relation, rows in graph.edges.items()
             if relation != tg.REL_HAS_FIELD},
            {tg.REL_FIELD_TYPE: 0, tg.REL_INHERITS: 0, tg.REL_CONSUMES: 0,
             tg.REL_PRODUCES: 0, tg.REL_ALIAS_OF: 0})

    def test_any_inside_a_container_drops_the_element_and_says_so(self):
        """``dict[str, Any]`` has no usable element.  It must not become an
        edge to ``dict``, to ``str`` or to ``Any``, and the drop is COUNTED --
        otherwise the container numbers are a lower bound sold as a total."""
        source = ("from typing import Any\n\n"
                  "def use(value: dict[str, Any]) -> list[Any]:\n"
                  "    return list(value)\n")
        graph = tg.resolve_type_graph(
            facts_by_rel={"m.py": python_type_facts("m.py", source)})
        self.assertEqual(graph.coverage["attempts"], 0)
        self.assertEqual(graph.coverage["sites_any"], 0)
        self.assertEqual(graph.coverage["sites_any_inside"], 2)
        self.assertEqual(graph.coverage["sites_no_member"], 2)
        self.assertEqual(graph.coverage["dropped_keys"], 1)
        self.assertEqual(graph.edges[tg.REL_CONSUMES], ())
        self.assertEqual(graph.edges[tg.REL_PRODUCES], ())


# --------------------------------------------------------------------------- #
# D4. REFUSE TO GUESS (I5)                                                     #
# --------------------------------------------------------------------------- #
class RefuseToGuess(_Fixture):
    """No edge AND a counter -- both halves, every time.

    An absence with no count is indistinguishable from "we did not look", and a
    count with no absence check passes an implementation that counts the
    ambiguity and emits the edge anyway.  That second failure is the one the
    plan predicts by name, because it is the one a determinism suite would then
    protect: "a stably reproduced FALSE edge".
    """

    AMBIGUOUS_FILES = ("ambiguous_result_star_import.py",
                       "ambiguous_result_try_import.py")
    RESULT_NODES = ("type:result_alpha.py#Result", "type:result_beta.py#Result")

    def test_the_ambiguous_result_produced_no_edge_to_either_candidate(self):
        for relation, row in self.all_edges:
            if row["source"] in self.AMBIGUOUS_FILES:
                self.assertNotIn(row["target"], self.RESULT_NODES,
                                 (relation, row))

    def test_the_ambiguous_files_produced_no_type_edge_whatsoever(self):
        """Stronger and non-vacuous: those two files annotate NOTHING else, so
        any edge sourced there is a guess."""
        sourced = [(relation, row) for relation, row in self.all_edges
                   if row["source"] in self.AMBIGUOUS_FILES]
        self.assertEqual(sourced, [])

    def test_the_ambiguous_counter_was_incremented(self):
        self.assertEqual(self.coverage["ambiguous"], AMBIGUOUS_ATTEMPTS)

    def test_the_ambiguous_sample_names_the_site_and_both_candidates(self):
        """The count alone is not actionable.  A reader has to be able to go to
        the line and see WHICH two declarations collided."""
        sample = self.coverage["ambiguous_sample"]
        self.assertEqual(len(sample), AMBIGUOUS_ATTEMPTS)
        self.assertEqual(sorted({row["module"] for row in sample}),
                         sorted(self.AMBIGUOUS_FILES))
        for row in sample:
            self.assertEqual(row["name"], "Result")
            self.assertEqual(sorted(row["candidates"]),
                             sorted(self.RESULT_NODES))
            self.assertGreater(row["line"], 0)

    def test_the_nonexistent_annotation_produced_no_edge(self):
        for relation, row in self.all_edges:
            self.assertNotIn("NoSuchTypeAnywhere", row["target"],
                             (relation, row))
            self.assertNotEqual(row["attributes"].get("member"),
                                "NoSuchTypeAnywhere", (relation, row))

    def test_the_nonexistent_annotation_was_not_minted_as_a_node(self):
        """Being MENTIONED is not a declaration.  A node here would make the
        type count a count of names seen rather than of types declared."""
        for node in self.nodes:
            self.assertNotEqual(node["name"], "NoSuchTypeAnywhere", node)
            self.assertNotIn("NoSuchTypeAnywhere", node["id"], node)

    def test_the_unresolved_counter_was_incremented(self):
        self.assertEqual(self.coverage["unresolved"], UNRESOLVED_ATTEMPTS)
        sample = self.coverage["unresolved_sample"]
        self.assertEqual(len(sample), UNRESOLVED_ATTEMPTS)
        self.assertEqual({row["name"] for row in sample},
                         {"NoSuchTypeAnywhere"})
        self.assertEqual({row["module"] for row in sample},
                         {"unresolvable_annotations.py"})
        # One bare and one inside ``list[...]`` -- the container spelling must
        # not resolve away the element.
        self.assertEqual(sorted(row["annotation"] for row in sample),
                         ["NoSuchTypeAnywhere", "list[NoSuchTypeAnywhere]"])

    def test_no_refused_site_produced_an_edge_anywhere(self):
        """The general form, checked PER SITE rather than per name: ``Result``
        is legitimately resolved in ``cross_module_annotation.py``'s neighbours
        elsewhere, so a name-level check would be wrong as well as vacuous."""
        refused = {
            (row["module"], row["line"])
            for row in list(self.coverage["unresolved_sample"])
                     + list(self.coverage["ambiguous_sample"])
        }
        self.assertTrue(refused)
        for relation, row in self.all_edges:
            if relation not in (tg.REL_CONSUMES, tg.REL_PRODUCES):
                continue
            site = (row["source"], row["attributes"].get("function_line"))
            if site in refused:
                self.assertNotIn(
                    row["attributes"].get("member"),
                    {"Result", "NoSuchTypeAnywhere"}, (relation, row))

    def test_the_counters_add_up_to_the_attempts(self):
        """Bookkeeping honesty: every attempt lands in exactly one of the six
        buckets, so ``unresolved`` cannot be quietly reduced by moving a name
        into ``external`` or ``builtin``."""
        buckets = ("resolved", "unresolved", "ambiguous",
                   "external", "builtin", "vocabulary")
        self.assertEqual(sum(self.coverage[name] for name in buckets),
                         self.coverage["attempts"])
        for name in buckets:
            self.assertIsInstance(self.coverage[name], int)

    def test_the_positive_control_still_resolves(self):
        """An implementation that refuses EVERYTHING passes every test above.
        ``cross_module_annotation.py`` imports across a flat sibling and a
        nested package and must produce real edges."""
        targets = {row["target"] for relation, row in self.all_edges
                   if row["source"] == "cross_module_annotation.py"}
        self.assertTrue(targets, "the positive control resolved nothing")
        self.assertGreater(self.coverage["resolved"], 0)

    def test_a_refusal_is_stable_across_processes(self):
        """The refusals themselves must be deterministic, or the coverage
        record is a different document on every run and no consumer can diff
        two scans."""
        if not _PROBES:                              # pragma: no cover - order
            ByteIdentityAcrossHashSeeds.setUpClass()
        reference = json.dumps(
            {"ambiguous": self.coverage["ambiguous"],
             "unresolved": self.coverage["unresolved"],
             "ambiguous_sample": self.coverage["ambiguous_sample"],
             "unresolved_sample": self.coverage["unresolved_sample"]},
            sort_keys=True)
        for label, text in sorted(_PROBES.items()):
            coverage = json.loads(text)["types"]["coverage"]
            self.assertEqual(
                json.dumps({"ambiguous": coverage["ambiguous"],
                            "unresolved": coverage["unresolved"],
                            "ambiguous_sample": coverage["ambiguous_sample"],
                            "unresolved_sample": coverage["unresolved_sample"]},
                           sort_keys=True),
                reference, label)


# --------------------------------------------------------------------------- #
# D5. COVERAGE HONESTY ACROSS LANGUAGES                                        #
# --------------------------------------------------------------------------- #
class CoverageIsHonestAboutWhatItDidNotLook(_Fixture):
    """Stufe 1 is Python only, and the report has to SAY so.

    A numeric 0 for JavaScript claims "we looked and found none".  The truth is
    "the tree-sitter path has no class/field vocabulary and we did not look",
    and the difference decides whether a reader files a bug or waits for
    Stufe 2.  The type is the guard: a string cannot be summed, averaged or
    plotted next to a real count by accident.
    """

    OTHER_LANGUAGES = {
        "a.py": "class A:\n    x: int\n",
        "b.js": "function f(a) { return a; }\n",
        "c.ts": "export const x: number = 1;\n",
        "d.go": "package main\n\nfunc f() int { return 1 }\n",
    }

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.mixed_root = Path(_mktmp("tgdet-langs-"))
        for name, body in sorted(cls.OTHER_LANGUAGES.items()):
            (cls.mixed_root / name).write_text(body, encoding="utf-8")
        cls.mixed = build_index(cls.mixed_root, documents=False, types=True)

    def test_python_is_reported_as_supported(self):
        self.assertEqual(self.coverage["languages"]["python"], "supported")
        self.assertEqual(
            self.mixed["types"]["coverage"]["languages"]["python"], "supported")

    def test_every_language_the_index_saw_is_reported(self):
        """A report that only lists what it supports is not a report."""
        seen = set(self.mixed["languages"])
        self.assertGreater(len(seen), 1, "the mixed tree is not mixed")
        reported = set(self.mixed["types"]["coverage"]["languages"])
        self.assertEqual(reported, seen | {"python"})

    def test_every_non_python_language_says_not_supported(self):
        languages = self.mixed["types"]["coverage"]["languages"]
        others = sorted(name for name in languages if name != "python")
        self.assertTrue(others, "no non-Python language in the mixed tree")
        for name in others:
            self.assertEqual(languages[name], "not_supported", name)

    def test_no_language_value_is_a_number(self):
        """The literal invariant: NEVER a numeric 0.  Checked by TYPE, and
        separately against every spelling of zero, because ``0 == False`` and
        ``"0"`` would each read as a count to a careless consumer."""
        for source, languages in (
            ("fixture", self.coverage["languages"]),
            ("mixed", self.mixed["types"]["coverage"]["languages"]),
        ):
            for name, value in sorted(languages.items()):
                self.assertIsInstance(value, str, "%s/%s" % (source, name))
                self.assertNotIsInstance(value, (int, float))
                self.assertNotIn(value, ("0", "0.0", ""), "%s/%s" % (source, name))
                self.assertNotEqual(value, 0, "%s/%s" % (source, name))

    def test_the_report_is_only_ever_one_of_two_words(self):
        """An open vocabulary would let a later stage publish "partial" and
        mean anything at all."""
        for languages in (self.coverage["languages"],
                          self.mixed["types"]["coverage"]["languages"]):
            self.assertLessEqual(set(languages.values()),
                                 {"supported", "not_supported"})

    def test_a_non_python_file_contributed_no_node_and_no_edge(self):
        """The report's claim, checked against the artefact: ``not_supported``
        must mean zero rows, not "we published some and called it partial"."""
        for node in self.mixed["type_nodes"]:
            self.assertEqual(node["language"], "python", node)
            self.assertTrue(node["module"].endswith(".py"), node)
        for relation in tg.RELATIONS:
            for row in self.mixed["type_edges"].get(relation, []):
                for endpoint in (row["source"], row["target"]):
                    self.assertNotIn(".js", endpoint, (relation, row))
                    self.assertNotIn(".ts", endpoint, (relation, row))
                    self.assertNotIn(".go", endpoint, (relation, row))

    def test_the_language_report_has_a_fixed_key_order(self):
        """The one order the D1 digest CANNOT see.

        The subprocess probe serialises with ``sort_keys=True``, which normalises
        every dict key order away -- so a report built by iterating an unsorted
        ``index["languages"]`` would pass the whole determinism sweep and still
        differ between two scans for any consumer that compares the raw dict or
        writes it out unsorted.  The contract is ``python`` first (it is the one
        supported language, so it leads) and every other language sorted after
        it, which is what ``resolve_type_graph`` builds.
        """
        for source, languages in (
            ("fixture", self.coverage["languages"]),
            ("mixed", self.mixed["types"]["coverage"]["languages"]),
        ):
            keys = list(languages)
            self.assertEqual(keys[0], "python", source)
            self.assertEqual(keys[1:], sorted(keys[1:]), source)
            self.assertEqual(len(set(keys)), len(keys), source)
        # Non-vacuous: the mixed tree really does carry more than one key, so
        # "sorted after the first" is an assertion and not a tautology.
        self.assertGreater(
            len(self.mixed["types"]["coverage"]["languages"]), 1)

    def test_the_language_key_order_is_identical_across_processes(self):
        """The probe carries the key order as a LIST for exactly this test --
        reading it back out of the serialised dict would only re-measure
        ``sort_keys``."""
        if not _PROBES:                              # pragma: no cover - order
            ByteIdentityAcrossHashSeeds.setUpClass()
        reference = list(self.coverage["languages"])
        self.assertEqual(reference, ["python"])      # the fixture is Python-only
        for label, text in sorted(_PROBES.items()):
            self.assertEqual(json.loads(text)["language_key_order"],
                             reference, label)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
