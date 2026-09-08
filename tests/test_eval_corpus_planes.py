"""Cross-plane eval corpus: are the labels real, mechanical, and independent?

Packet G1-EVAL-CORPUS-01. Everything here is about the LABELS, not about the
slicer: the four ``artifact_parsed`` tasks in ``daedalus.eval.tasks`` target a
CSV, a JSON schema and two Markdown documents, none of which the harness can
slice at all (they come back as PLANE-UNINDEXED rows -- that contract is
tested in tests/test_eval_oracle.py). What has to be proven here is that the
labels are worth having when a retrieval arm for those planes finally exists:

  V1  the fixture's planes are disjoint under the walked classification, the
      fixture's own manifest declares nothing outside that walked universe,
      and every committed label is PLANE-EXCLUSIVE inside the fixture -- the
      last one asserted from the fixture bytes without calling
      ``derive_labels``, so the derivation cannot vouch for itself;
  V2  every committed ``must_include`` is EXACTLY what the derivation grammar
      re-derives -- no hand-written subset, no unknown kind;
  V3  no label occurs in its own task's target unit (else a retrieval arm
      could satisfy it by returning the target itself), and the filter that
      enforces that is tested DIRECTLY on a synthetic fixture built to make it
      fire, not only on a corpus where it happens never to fire;
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

    def test_every_committed_label_is_plane_exclusive_in_the_fixture(self):
        """The claim `report._PROVENANCE_NOTE["artifact_parsed"]` prints on
        every render -- "verified plane-exclusive by test" -- asserted here,
        and asserted INDEPENDENTLY of ``derive_labels``.

        Until 2026-09-08 nothing asserted it: this class only checked the plane
        MAP, and `V2DerivationTest` only checked `must_include ==
        derive_labels(task)`, which is the derivation agreeing with itself. So
        the mutation "delete filter 4 from ``derive_labels`` AND regenerate
        ``must_include`` to match" (M1b) left the whole suite green while the
        rendered report kept advertising a property the corpus no longer had.

        This test never calls ``derive_labels``. It reads the committed
        ``must_include`` and the fixture bytes, and asserts the property from
        first principles: every fixture file whose TEXT contains a label lies
        in the SAME plane as that task's own target. That is what a
        cross-plane label would have to violate.
        """
        texts = {rel: (Path(FOURFOLD_WIKI_FIXTURE) / rel).read_text(encoding="utf-8")
                 for rel in self.planes}
        self.assertEqual(len(texts), 18)   # guard the guard: no empty walk
        checked = 0
        for task in ARTIFACT_PARSED:
            target_file = task["target"].split("::", 1)[0]
            self.assertIn(target_file, self.planes, task["id"])
            target_plane = self.planes[target_file]
            for label in task["must_include"]:
                holders = sorted(rel for rel, text in texts.items() if label in text)
                with self.subTest(task=task["id"], label=label[:40]):
                    # Non-vacuous: the label must occur SOMEWHERE, else the
                    # "same plane" check below would pass over an empty set.
                    self.assertTrue(holders, "label occurs in no fixture file")
                    off_plane = [rel for rel in holders
                                 if self.planes[rel] != target_plane]
                    self.assertEqual(off_plane, [], (task["id"], label[:60]))
                checked += 1
        self.assertEqual(checked, 17)   # 5 + 4 + 4 + 4 committed labels

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

    # DELETED 2026-09-08: `test_a_hand_written_subset_is_refused` was a
    # tautology. `derive_labels` never reads `must_include` (it re-executes
    # `label_derivation`), so trimming a COPY of the committed list and
    # comparing it to `derive_labels(copy)` asserted nothing about the corpus
    # -- only that every derived label set has >= 2 entries. The refusal it
    # claimed is really pinned by
    # `test_every_committed_label_set_is_exactly_the_derived_one` above, which
    # compares the COMMITTED `must_include` to the derivation and therefore
    # fails on any subset, superset or reordering. The acceptance matrix cites
    # that test now.

    def test_a_task_without_a_derivation_cannot_be_derived(self):
        with self.assertRaises(ValueError):
            derive_labels({"id": "x", "repo": "fourfold_wiki_app", "target": "a.md"})

    def test_derivation_file_outside_the_plane_map_is_refused(self):
        task = dict(ARTIFACT_PARSED[0])
        task["label_derivation"] = {"kind": "json_keys", "file": "fourfold.json"}
        with self.assertRaises(ValueError):
            derive_labels(task)


class V3NonVacuityTest(unittest.TestCase):
    def test_the_anti_vacuity_filter_drops_a_candidate_found_in_the_target(self):
        """Filter 5 (``if candidate in target_text: continue``) tested DIRECTLY,
        on a synthetic fixture built to make it fire.

        Why this exists (independent verification, 2026-09-08): on the
        committed corpus filter 5 removes ZERO candidates, so deleting the two
        lines changed nothing and no test noticed (mutation M9 survived). The
        corpus is evidence that the filter did not need to fire, not evidence
        that it works. This fixture makes it need to fire.

        The fixture isolates filter 5 on purpose: both files are `.csv`, so
        they share a plane and filter 4 (cross-plane) has an EMPTY other-plane
        set; both candidates are >= MIN_LABEL_CHARS and single-line, so filters
        2 and 3 are inert; the two values are distinct, so filter 1 is inert.
        The only difference between them is that one occurs in the target unit.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "rows.csv").write_text(
                "slug\nalpha-shared-token\nbeta-unique-token\n", encoding="utf-8")
            # The TARGET quotes the first slug -- a retrieval arm that returned
            # the target itself would satisfy that label for free.
            (root / "data" / "target.csv").write_text(
                "id,note\n1,see alpha-shared-token\n", encoding="utf-8")
            task = {
                "id": "synthetic_anti_vacuity",
                "label_provenance": "artifact_parsed",
                "tier": "primary",
                "repo": str(root),
                "target": "data/target.csv",
                "label_derivation": {"kind": "csv_column_values",
                                     "file": "data/rows.csv", "column": "slug"},
            }
            planes = fixture_plane_map(str(root))
            self.assertEqual(planes, {"data/rows.csv": "data",
                                      "data/target.csv": "data"})
            # The candidate really is produced by the grammar -- so its absence
            # below is the filter removing it, not an extraction that never
            # made it.
            self.assertEqual(
                eval_tasks._extract_candidates(task["label_derivation"], str(root)),
                ["alpha-shared-token", "beta-unique-token"])
            self.assertIn(
                "alpha-shared-token",
                eval_tasks._target_unit_text(str(root), task["target"]))

            derived = derive_labels(task, fixture_root=str(root))

            self.assertNotIn("alpha-shared-token", derived)   # the bite
            # Non-vacuous: the derivation is not simply empty.
            self.assertEqual(derived, ("beta-unique-token",))

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

    def test_no_hyphenated_or_multiword_label_is_a_single_bm25_token(self):
        """Recorded, not aspirational: ``harness._bm25_tokenize`` splits on
        non-identifier characters, so a hyphenated slug or a prose line is
        never one token. A BM25 arm cannot match THOSE labels by luck.

        The claim is deliberately narrower than the old test name suggested,
        and the guard's precondition is now asserted. Previously the assertion
        sat behind ``if "-" in label or " " in label`` with nothing checking
        that the branch was ever entered -- and unconditionally the assertion
        would FAIL: four of the five ``json_keys`` labels
        (``pattern``/``enum``/``minLength``/``additionalProperties``) ARE
        single BM25 tokens that match themselves. (``$schema`` is not, because
        ``_bm25_tokenize`` strips the ``$``; it is still outside the claim,
        being neither hyphenated nor multi-word.) Asserting the exact split
        records that honestly instead of letting a silent skip read as a
        stronger property.
        """
        from daedalus.eval.harness import _bm25_tokenize
        multi, single = [], []
        for task in ARTIFACT_PARSED:
            for label in task["must_include"]:
                if "-" in label or " " in label:
                    multi.append(label)
                    with self.subTest(label=label[:40]):
                        self.assertNotEqual(_bm25_tokenize(label), [label.lower()])
                else:
                    single.append(label)
        # The guard fired, and on exactly the labels it is claimed for.
        self.assertEqual((len(multi), len(single)), (12, 5))
        self.assertEqual(sorted(single), ["$schema", "additionalProperties",
                                          "enum", "minLength", "pattern"])


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
