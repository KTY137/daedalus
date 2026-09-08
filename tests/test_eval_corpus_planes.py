"""Cross-plane eval corpus: are the labels real, mechanical, and independent?

Packet G1-EVAL-CORPUS-01. Everything here is about the LABELS, not about the
slicer: the four ``artifact_parsed`` tasks in ``daedalus.eval.tasks`` target a
CSV, a JSON schema and two Markdown documents, none of which the harness can
slice at all (they come back as PLANE-UNINDEXED rows -- that contract is
tested in tests/test_eval_oracle.py). What has to be proven here is that the
labels are worth having when a retrieval arm for those planes finally exists:

  V1  the fixture's planes are disjoint under the walked classification, and
      the fixture's own manifest declares nothing outside that walked universe;
  V2  every committed ``must_include`` is EXACTLY what the derivation grammar
      re-derives -- no hand-written subset, no unknown kind;
  V3  no label occurs in its own task's target unit (else a retrieval arm
      could satisfy it by returning the target itself);
  V4  an INDEPENDENT oracle -- the twin's reference compiler, which knows
      nothing about this eval -- sees the same cross-plane structure the
      knowledge-plane tasks assume;
  V5  the corpus's shape rules hold: artifact_parsed <=> label_derivation, and
      no ``hand_reachable`` task targets a non-Python file.

Plus the two fixture-integrity tests: the packaged copy is byte-identical to
``examples/fourfold_wiki_app`` (it is the twin's reference fixture; if the two
diverge, twin evidence and eval labels stop describing the same bytes), and it
sits inside the installable ``daedalus.eval`` package like ``sunny_garden``.
"""
import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from daedalus.eval import tasks as eval_tasks
from daedalus.eval.tasks import (
    FOURFOLD_WIKI_FIXTURE,
    TASKS,
    derive_labels,
    fixture_plane_map,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_COPY = REPO_ROOT / "examples" / "fourfold_wiki_app"

ARTIFACT_PARSED = [t for t in TASKS if t.get("label_provenance") == "artifact_parsed"]


def _digest_tree(root: Path) -> list[tuple[str, str]]:
    """(rel path, sha256) for every file under ``root``, sorted. Bytes, not
    text: a line-ending change is a divergence, and the twin fixture is
    content-addressed."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            rel = str(p.relative_to(root)).replace("\\", "/")
            out.append((rel, hashlib.sha256(p.read_bytes()).hexdigest()))
    return sorted(out)


class PackagedFixtureTest(unittest.TestCase):
    def test_packaged_fixture_is_byte_identical_to_the_examples_copy(self):
        packaged = _digest_tree(Path(FOURFOLD_WIKI_FIXTURE))
        example = _digest_tree(EXAMPLES_COPY)
        self.assertEqual([rel for rel, _ in packaged], [rel for rel, _ in example])
        self.assertEqual(packaged, example)
        # Guard the guard: a comparison of two empty trees passes vacuously.
        self.assertEqual(len(packaged), 19)

    def test_fourfold_fixture_is_part_of_the_installable_eval_package(self):
        # Mirrors the sunny_garden case in tests/test_eval.py.
        root = Path(FOURFOLD_WIKI_FIXTURE).resolve()
        package_root = Path(eval_tasks.__file__).resolve().parent
        self.assertEqual(root.parent, package_root / "fixtures")
        self.assertTrue((root / "fourfold.json").is_file())
        self.assertTrue((root / "data" / "articles.csv").is_file())
        self.assertTrue((root / "schemas" / "article.schema.json").is_file())
        self.assertTrue((root / "wiki" / "Security.md").is_file())
        self.assertTrue((root / "src" / "knowledge_hub" / "app.py").is_file())

    def test_repo_label_resolves_to_the_packaged_fixture(self):
        self.assertEqual(
            eval_tasks.resolve_task_repo("fourfold_wiki_app"), FOURFOLD_WIKI_FIXTURE)


class V1PlaneExclusivityTest(unittest.TestCase):
    """The plane map is WALKED, and the manifest is checked against it."""

    def setUp(self):
        self.planes = fixture_plane_map(FOURFOLD_WIKI_FIXTURE)

    def test_walked_plane_map_is_a_function_and_covers_the_fixture(self):
        # 19 files on disk, 18 classified: fourfold.json is the declaration
        # manifest and is excluded by name (it is not project data).
        on_disk = {rel for rel, _ in _digest_tree(Path(FOURFOLD_WIKI_FIXTURE))}
        self.assertEqual(len(on_disk), 19)
        self.assertNotIn("fourfold.json", self.planes)
        self.assertEqual(set(self.planes) | {"fourfold.json"}, on_disk)
        self.assertEqual(sorted(set(self.planes.values())),
                         ["code", "data", "knowledge"])
        # No type-plane file exists in this fixture, and none was invented to
        # make a census look four-plane.
        self.assertNotIn("type", set(self.planes.values()))

    def test_planes_are_disjoint_per_file(self):
        # A file has exactly one plane by construction (dict), but the three
        # PREDICATES must not both answer for the same file, which is the
        # property that would make the dict order-dependent.
        from daedalus.structcore.languages import doc_spec_for, spec_for
        for rel in self.planes:
            name = rel.rsplit("/", 1)[-1]
            answers = [
                spec_for(name) is not None,
                doc_spec_for(name) is not None,
                os.path.splitext(name)[1].lower() in eval_tasks._DATA_PLANE_EXTENSIONS,
            ]
            self.assertEqual(sum(1 for a in answers if a), 1, rel)

    def test_manifest_declares_nothing_outside_the_walked_universe(self):
        import json
        manifest = json.loads(
            (Path(FOURFOLD_WIKI_FIXTURE) / "fourfold.json").read_text(encoding="utf-8"))
        for key, plane in (("code_files", "code"), ("data_files", "data"),
                           ("knowledge_files", "knowledge")):
            declared = set(manifest[key])
            self.assertTrue(declared)
            self.assertTrue(declared <= set(self.planes), (key, declared - set(self.planes)))
            for rel in declared:
                self.assertEqual(self.planes[rel], plane, rel)


class V2DerivationTest(unittest.TestCase):
    """must_include == derive_labels(task), in both directions."""

    def test_corpus_has_the_four_artifact_parsed_tasks(self):
        self.assertEqual(
            sorted(t["id"] for t in ARTIFACT_PARSED),
            ["fourfold_adr_consequences_section", "fourfold_article_schema",
             "fourfold_articles_csv", "fourfold_security_operations_link"])

    def test_every_committed_label_set_is_exactly_the_derived_one(self):
        for task in ARTIFACT_PARSED:
            with self.subTest(task=task["id"]):
                derived = derive_labels(task)
                self.assertTrue(derived, "an empty label set scores a vacuous 1.0")
                self.assertEqual(tuple(task["must_include"]), derived)

    def test_derivation_is_deterministic(self):
        for task in ARTIFACT_PARSED:
            self.assertEqual(derive_labels(task), derive_labels(task))

    def test_unknown_kind_is_refused(self):
        task = dict(ARTIFACT_PARSED[0])
        task["label_derivation"] = {"kind": "yaml_scalars", "file": "data/articles.csv"}
        with self.assertRaises(ValueError) as ctx:
            derive_labels(task)
        self.assertIn("closed", str(ctx.exception))

    def test_a_hand_written_subset_is_refused(self):
        # The exact failure this packet exists to prevent: someone keeps the
        # derivation but trims must_include to the labels that happen to pass.
        for task in ARTIFACT_PARSED:
            mutated = dict(task)
            mutated["must_include"] = list(task["must_include"])[:1]
            with self.subTest(task=task["id"]):
                self.assertNotEqual(tuple(mutated["must_include"]), derive_labels(mutated))

    def test_a_task_without_a_derivation_cannot_be_derived(self):
        with self.assertRaises(ValueError):
            derive_labels({"id": "x", "repo": "fourfold_wiki_app", "target": "a.md"})

    def test_derivation_file_outside_the_plane_map_is_refused(self):
        task = dict(ARTIFACT_PARSED[0])
        task["label_derivation"] = {"kind": "json_keys", "file": "fourfold.json"}
        with self.assertRaises(ValueError):
            derive_labels(task)


class V3NonVacuityTest(unittest.TestCase):
    def test_no_label_occurs_in_its_own_target_unit(self):
        for task in ARTIFACT_PARSED:
            unit = eval_tasks._target_unit_text(FOURFOLD_WIKI_FIXTURE, task["target"])
            for label in task["must_include"]:
                with self.subTest(task=task["id"], label=label[:40]):
                    self.assertNotIn(label, unit)

    def test_the_section_target_still_lives_in_its_own_file(self):
        # Honest scope of V3 for the intra-document task: its labels DO occur
        # in the target FILE (a sibling section) -- the anti-vacuity unit is
        # the section, because a section is what a retrieval arm returns.
        task = next(t for t in ARTIFACT_PARSED
                    if t["id"] == "fourfold_adr_consequences_section")
        whole_file = (Path(FOURFOLD_WIKI_FIXTURE)
                      / "wiki" / "ADR" / "ADR-001-CSV-Storage.md").read_text(encoding="utf-8")
        for label in task["must_include"]:
            self.assertIn(label, whole_file)

    def test_no_label_is_a_single_bm25_token(self):
        # Recorded, not aspirational: harness._bm25_tokenize splits on
        # non-identifier characters, so a hyphenated slug or a prose line is
        # never one token. A BM25 arm cannot match these labels by luck.
        from daedalus.eval.harness import _bm25_tokenize
        for task in ARTIFACT_PARSED:
            for label in task["must_include"]:
                if "-" in label or " " in label:
                    self.assertNotEqual(_bm25_tokenize(label), [label.lower()])


class V4TwinOracleTest(unittest.TestCase):
    """An independent compiler sees the structure the labels assume."""

    @classmethod
    def setUpClass(cls):
        from daedalus.twin import compile_reference_project
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "fourfold_wiki_app"
        shutil.copytree(FOURFOLD_WIKI_FIXTURE, cls.root)
        cls.result = compile_reference_project(
            cls.root, source_revision="a" * 64, created_at="2026-09-08T00:00:00Z",
            trace_id="g1-eval-corpus-01")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_packaged_fixture_compiles(self):
        self.assertTrue(self.result.snapshot.digest)
        self.assertEqual(len(self.result.file_sha256s), 17)  # manifest-declared

    def test_security_links_to_operations(self):
        # The exact edge fourfold_security_operations_link relies on: the
        # labels live in Operations.md and the target is Security.md.
        edges = {(e.source, e.relation, e.target) for e in self.result.forest.edges}
        self.assertIn(
            ("knowledge:doc:wiki/Security.md", "links_to",
             "knowledge:doc:wiki/Operations.md"), edges)

    def test_the_slug_field_exists_in_both_data_artifacts(self):
        ids = {n.id for n in self.result.forest.nodes}
        self.assertIn("data:field:data/articles.csv#slug", ids)
        self.assertIn("data:schema-field:schemas/article.schema.json#slug", ids)
        self.assertIn("type:src/knowledge_hub/models.py#Article", ids)


class V5CorpusShapeTest(unittest.TestCase):
    def test_artifact_parsed_implies_a_label_derivation(self):
        for task in TASKS:
            if task.get("label_provenance") == "artifact_parsed":
                self.assertIn("label_derivation", task, task["id"])
            else:
                self.assertNotIn("label_derivation", task, task["id"])

    def test_artifact_parsed_tasks_carry_no_tier2_question(self):
        # tier2.builtin_validator_coverage requires a validator for every
        # question-bearing TASKS entry; adding one here without a validator
        # turns tests/test_eval_tier2_integrity.py red.
        for task in ARTIFACT_PARSED:
            self.assertNotIn("question", task)
            self.assertNotIn("answer_contains", task)

    def test_no_hand_reachable_task_targets_a_non_python_file(self):
        # hand_reachable means "verified reachable by running semantic_slice",
        # which is only meaningful for a file the slicer indexes.
        for task in TASKS:
            if task.get("label_provenance", "hand_reachable") != "hand_reachable":
                continue
            path = task["target"].split("::", 1)[0]
            self.assertTrue(path.endswith(".py"), task["id"])

    def test_every_artifact_parsed_task_is_primary_and_in_the_fixture(self):
        for task in ARTIFACT_PARSED:
            self.assertEqual(task["tier"], "primary")
            self.assertEqual(task["repo"], "fourfold_wiki_app")


if __name__ == "__main__":
    unittest.main()
