"""tasks.py -- the labelled task set for the distillation eval.

Each task targets a real symbol/file in a small repo and records the symbols a
*sufficient* distilled slice MUST carry to reason about that target. The labels
below were picked by reading the code and VERIFIED reachable by running
``semantic_slice`` (see ``daedalus.eval.harness``); a label is only listed if a
competent answer about the target genuinely needs it AND it is a real dependency
or caller in the neighborhood.

Task shape::

    {
      "id":               short unique id,
      "repo":             repo label -- "agent_env" | "sunny_garden" | abs path,
      "target":           "path/to/file.py"  or  "path/to/file.py::symbol",
      "must_include":     [symbol_or_substring, ...]   # Tier 1 recall labels
      "question":         natural question about the target (optional, Tier 2),
      "answer_contains":  [substring, ...]              # Tier 2 success labels
      "label_provenance": how ``must_include`` was derived -- see below,
      "tier":             "primary" | "quarantine" -- see below,
      "label_derivation": closed-grammar recipe for "artifact_parsed" tasks
                          (optional; see LABEL DERIVATION below),
    }

Honesty note: ``must_include`` items are matched as substrings against the
slice text. For a symbol target the slice is 1-hop (the focus symbol's direct
callees/callers), so we only label symbols reachable within that hop -- we do
NOT claim transitive callees-of-callees are present when they are not.

Label provenance (the point of this sprint -- read this before trusting a
recall number):

  * "hand_reachable"   -- a human picked the label AND verified it reachable
    by running ``semantic_slice`` (see ``daedalus.eval.harness``). This is
    CIRCULAR: the slicer chose what it is graded on. Every task below is this
    provenance today. Recall computed over ``hand_reachable`` tasks is an
    upper bound / sanity check, NOT independent proof the slicer works --
    ``report.py`` says so on every render, and ``harness.run_tier1`` never
    blends it with the other provenances into one number.
  * "independent_diff" -- labels derived from what an on-disk diff LITERALLY
    changed, with no graph walk involved. Independent of the slicer.
  * "temporal_churn"    -- labels derived from git co-change (files that
    change together), surfacing edges the static import graph doesn't have.
    Independent of the slicer.
  * "artifact_parsed"  -- labels RE-DERIVED by a deterministic parser over the
    artifact itself, under the CLOSED derivation grammar below. Independent of
    the slicer in the strongest sense available here: no human picked the
    strings and no graph walk was consulted, so ``must_include`` is a function
    of the fixture bytes plus the task's own declared parameters. What this
    provenance does NOT claim, stated once so no report can imply it:
      - it is NOT verified reachable by ``semantic_slice``. Nothing checked
        that the product slicer can produce these labels; a test only checks
        that they are plane-exclusive inside the fixture.
      - it is NEVER scored by harness arm A. Every artifact_parsed task below
        targets a file the default structural index does not carry (a .csv/
        .json data artifact, or a document -- documents are opt-in, see
        ``structcore.index.documents_enabled``), so the harness refuses it as
        a PLANE-UNINDEXED row (``harness._plane_unindexed_row``) BEFORE
        slicing, with no recall key at all. A recall number for these labels
        would be a measurement of a retrieval path that does not exist.

``tier``: "primary" tasks count toward any go/no-go recall number WHEN THEY
ARE SCORABLE AT ALL. "quarantine" tasks are minted but not yet confirmed --
``harness.run_tier1`` excludes them from every headline/aggregate and reports
them separately so the labelling flywheel (mint -> quarantine -> confirm ->
primary) stays observable instead of silently inflating (or deflating) the
real number. Two row kinds are primary-tier and still carry NO recall: a
FOCUS-WITHHELD row (the secret floor fail-closed on the task's own focus file)
and the PLANE-UNINDEXED row this module's artifact_parsed tasks produce (the
target's plane is not in the default retrieval universe). Both are counted and
named separately by ``harness.run_tier1``/``run_arms``/``run_gate`` and never
averaged into anything -- "primary" is a statement about label confidence, not
a promise that a number exists.

LABEL DERIVATION (the closed grammar behind "artifact_parsed")
--------------------------------------------------------------
An ``artifact_parsed`` task carries ``label_derivation``: a recipe this module
can re-execute to reproduce ``must_include`` from the fixture bytes. The
grammar is CLOSED -- exactly four kinds, and an unrecognized ``kind`` raises
``ValueError`` rather than degrading to "no labels" (a silent empty tuple
would make ``_recall`` return the vacuous 1.0 the tier machinery exists to
prevent)::

    {"kind": "csv_column_values",    "file": <rel>, "column": <name>}
    {"kind": "json_keys",            "file": <rel>}
    {"kind": "json_string_values",   "file": <rel>}
    {"kind": "markdown_section_lines", "file": <rel>, "section": <heading>,
     "min_chars": <int>, "max_lines": <int>}

After extraction every kind passes through the SAME mechanical filters, in
this order (``derive_labels``):

  1. de-duplicate, keeping first-appearance order (deterministic: the parsers
     are deterministic and the walk is sorted);
  2. drop anything shorter than ``MIN_LABEL_CHARS`` characters -- a 1-3 char
     substring matches by accident;
  3. drop anything spanning more than one line -- ``harness._recall`` matches
     substrings against a slice text whose line breaks it does not control;
  4. drop any candidate that ALSO occurs in a fixture file of a DIFFERENT
     plane than the derivation file's own plane. This is what makes the label
     plane-exclusive, and it is measured over the walked fixture, not
     declared;
  5. drop any candidate that occurs in the task's own TARGET UNIT -- the
     target file, or, when the target names a section (``file.md::Section``),
     that section's text. Without this a retrieval arm could satisfy every
     label by returning the target itself, and the task could not fail.

All comparisons are CASE-SENSITIVE: ``_recall`` is case-sensitive, so a
case-insensitive filter here would admit a label the scorer cannot match.

``must_include`` MUST EQUAL the full derived tuple, and a test asserts it for
every artifact_parsed task (``tests/test_eval_corpus_planes.py``). A
hand-written subset is refused: choosing which mechanically derived labels to
keep is exactly the "hand_reachable" circularity in a new costume.

THE SECOND TASK FORMAT: CORRECTNESS (FAIL_TO_PASS / PASS_TO_PASS)
-----------------------------------------------------------------
Everything above grades the SLICER: ``must_include`` is scored by substring
containment in a distilled context slice (``harness._recall``). That measures
retrieval, and it is honest about it -- but it never looks at a patch, so no
number derived from it can say whether a CHANGE is correct, and an empty
``must_include`` scores 1.0 vacuously.

``daedalus.eval.correctness`` adds a second, disjoint format that grades the
CHANGE, on the SWE-bench pattern, using this repo's own pytest as the oracle::

    {
      "id":                 short unique id,
      "repo":               repo label -- resolved by ``resolve_task_repo``,
      "base_revision":      the revision the change is built ON,
      "reference_revision": the known-good fix (optional; validates the task),
      "test_revision":      revision the test files are taken from,
      "test_overlay":       ["tests/test_x.py", ...]  # SWE-bench's test patch
      "fail_to_pass":       ["tests/test_x.py::test_y", ...]  # RED -> GREEN
      "pass_to_pass":       ["tests/test_z.py::test_w", ...]  # GREEN -> GREEN
      "before_state":       receipt written by --verify (see correctness.py),
      "provenance":         "git_history" | ...,
      "tier":               "primary" | "quarantine",
    }

THE TWO FORMATS MUST NOT BE MIXED IN ONE CORPUS, and that is enforced rather
than asked for: a correctness task carries no ``must_include``, so scoring one
with ``harness._recall`` would return the vacuous 1.0 -- a task that cannot
fail, silently inflating the very number the tier machinery exists to keep
honest. ``is_correctness_task`` below is the single predicate that decides,
and ``harness.eval_task_tier1``/``eval_task_arms`` refuse such a task loudly
(an ERRORED row, which ``run_gate`` reports and fails on for a primary tier)
instead of grading it. Correctness tasks live in their own store
(``correctness.DEFAULT_CORPUS_PATH``) and never enter ``harness.all_tasks()``.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

from daedalus.foundation.projects import list_projects, resolve_repo_root
# The fixture plane walk below needs the same "never source" directory
# blocklist the rest of the stack uses. It is imported from structcore -- the
# ORIGINAL, which ``harness._IGNORE_DIRS`` only mirrors -- and NOT from
# ``daedalus.eval.harness``, deliberately: ``harness`` imports THIS module, so
# a tasks -> harness import would pull ``daedalus.eval.tasks`` into the
# existing (daedalus.eval, harness, report, tier2) import cycle. Measured
# 2026-09-08: that edge alone moves the pinned component digest in
# tests/contracts/test_import_scc_hierarchy.py from
# 841a5a97...c2140a78 to b45b3cc6...bfa9cbdb. A label parser is not worth an
# architecture regression.
from daedalus.structcore.index import _IGNORE_DIRS as _SOURCE_IGNORE_DIRS
from daedalus.structcore.languages import doc_spec_for, spec_for
from daedalus.structcore.markdown import parse_document

# agent_env repo root == parents[2] of this file (daedalus/eval/tasks.py).
AGENT_ENV_ROOT = str(Path(__file__).resolve().parents[2])
SUNNY_GARDEN_FIXTURE = str(
    Path(__file__).resolve().parent / "fixtures" / "sunny_garden"
)
#: The packaged copy of ``examples/fourfold_wiki_app`` -- the four-plane
#: reference project that ``daedalus.twin.reference_compiler`` compiles. It is
#: copied (byte-for-byte, pinned by a test) rather than referenced across
#: ``examples/`` so the eval corpus ships with the ``daedalus.eval`` package
#: exactly like ``sunny_garden`` does, and so eval labels and twin evidence can
#: never drift apart silently.
FOURFOLD_WIKI_FIXTURE = str(
    Path(__file__).resolve().parent / "fixtures" / "fourfold_wiki_app"
)

# --------------------------------------------------------------------------- #
# The data-plane retrieval universe.                                          #
#                                                                             #
# These two tuples are the eval package's OWN decision about which files a
# data-plane retrieval arm may retrieve and which files this module's plane
# walk calls "data". They are NOT a fourth global extension->plane classifier:
# the twin's discovery registry (``daedalus/twin/extractors/registry.py``,
# which classifies ``.json`` as data OR knowledge depending on the extractor),
# the Gate-3 taskset's ``_PLANE_EXTENSIONS`` and ``separate_indices``'s
# ``_DATA_EXTENSIONS`` remain the authorities for their own questions. Nothing
# here overrides them and nothing reads them here.
#
# They live in ``tasks`` rather than in ``harness`` (where they are used by
# ``_repo_chunks``/``_plane_unindexed_reason`` and imported from) for the
# import-cycle reason recorded above the structcore import: ``harness``
# already imports ``tasks``, so this is the only direction that keeps ONE
# definition without enlarging the eval import cycle.
#
# ``fourfold.json`` is excluded BY NAME because it is the reference project's
# declaration manifest -- the thing that says which files are data -- not
# project data itself. Retrieving it would hand a retrieval arm the answer
# key.
_DATA_PLANE_EXTENSIONS = (".csv", ".json")
_DATA_PLANE_EXCLUDED_NAMES = ("fourfold.json",)

#: Shortest label the mechanical filters accept (see LABEL DERIVATION).
MIN_LABEL_CHARS = 4

#: The closed set of ``label_derivation`` kinds. Anything else is a ValueError.
LABEL_DERIVATION_KINDS = (
    "csv_column_values",
    "json_keys",
    "json_string_values",
    "markdown_section_lines",
)


def resolve_task_repo(repo: str) -> str:
    """Map a task's ``repo`` label to an absolute repo root.

    "agent_env"          -> this harness repo (dogfood target)
    "sunny_garden"       -> the packaged code-plane fixture
    "fourfold_wiki_app"  -> the packaged four-plane fixture (same branch shape
                            as sunny_garden: a packaged directory wins over a
                            same-named registered project, and falls through
                            to the registry when the package copy is missing)
    a registered name  -> daedalus.foundation.projects.resolve_repo_root (e.g. sunny_garden)
    an absolute path   -> used as-is (temp fixtures in tests)
    """
    if repo == "agent_env":
        return AGENT_ENV_ROOT
    if repo == "sunny_garden" and Path(SUNNY_GARDEN_FIXTURE).is_dir():
        return SUNNY_GARDEN_FIXTURE
    if repo == "fourfold_wiki_app" and Path(FOURFOLD_WIKI_FIXTURE).is_dir():
        return FOURFOLD_WIKI_FIXTURE
    if os.path.isabs(repo) and Path(repo).exists():
        return repo
    if repo in list_projects():
        return resolve_repo_root(None, repo)
    raise ValueError(f"cannot resolve task repo label: {repo!r}")


# --------------------------------------------------------------------------- #
# The closed label-derivation grammar (label_provenance == "artifact_parsed"). #
# Pure functions: they read fixture files and return strings. Nothing here     #
# imports the slicer, the index, or the harness -- a label that needed the     #
# thing it grades would be circular by construction.                          #
# --------------------------------------------------------------------------- #
def _fixture_text(fixture_root: str, rel: str) -> str:
    """Read one fixture file as text. ``rel`` is POSIX-style and relative."""
    path = Path(fixture_root) / rel
    return path.read_text(encoding="utf-8")


def fixture_plane_map(fixture_root: str) -> dict[str, str]:
    """{rel path -> "code" | "type" | "data" | "knowledge"} for one fixture.

    WALKED, not declared: the fixture's own ``fourfold.json`` manifest lists
    the files it claims, but a manifest is the artifact under test here, not
    the authority over it -- a label that was checked against the manifest
    would be checked against the same declaration a Genesis/twin bug could
    have written. Classification uses the structural stack's existing
    predicates:

      * ``spec_for``      -> "code"       (a parsed source language)
      * ``doc_spec_for``  -> "knowledge"  (a parsed document)
      * ``_DATA_PLANE_EXTENSIONS`` minus ``_DATA_PLANE_EXCLUDED_NAMES``
                          -> "data"

    ``spec_for`` and ``doc_spec_for`` answer non-None for disjoint extension
    sets (``languages.doc_spec_for``'s own docstring: "nothing answers both"),
    and neither answers for ``.csv``/``.json`` -- measured 2026-09-08, so the
    three branches cannot collide. There is deliberately NO "type" branch: no
    extension of the frozen type-plane set (``.pyi``/``.proto``/...) exists in
    this fixture, and inventing one to make a census look four-plane would be
    plane laundering. A file matching none of the three (e.g. the excluded
    manifest) is simply absent from the map.
    """
    planes: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(fixture_root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _SOURCE_IGNORE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            rel = os.path.relpath(
                os.path.join(dirpath, fn), fixture_root).replace("\\", "/")
            if spec_for(fn) is not None:
                planes[rel] = "code"
            elif doc_spec_for(fn) is not None:
                planes[rel] = "knowledge"
            elif (os.path.splitext(fn)[1].lower() in _DATA_PLANE_EXTENSIONS
                    and fn not in _DATA_PLANE_EXCLUDED_NAMES):
                planes[rel] = "data"
    return planes


def _csv_column_values(text: str, column: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or column not in reader.fieldnames:
        raise ValueError(
            f"csv_column_values: no column {column!r} (have {reader.fieldnames!r})")
    return [row[column] for row in reader if row.get(column)]


def _json_keys(text: str) -> list[str]:
    out: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                out.append(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(text))
    return out


def _json_string_values(text: str) -> list[str]:
    out: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            out.append(node)

    walk(json.loads(text))
    return out


def _document_section(fixture_root: str, rel: str, section: str):
    """The ``DocSection`` named ``section`` in document ``rel``.

    Matched on the heading text exactly (the parser's ``name``), never on a
    slug or a prefix: a fuzzy match would silently move a label set when a
    heading is edited, which is the drift this grammar exists to prevent.
    """
    parse = parse_document(rel, _fixture_text(fixture_root, rel))
    for candidate in parse.sections:
        if candidate.name == section:
            return candidate
    raise ValueError(
        f"markdown_section_lines: no section {section!r} in {rel} "
        f"(have {[s.name for s in parse.sections]!r})")


def _markdown_section_lines(fixture_root: str, rel: str, section: str,
                            min_chars: int, max_lines: int) -> list[str]:
    lines = _document_section(fixture_root, rel, section).source.splitlines()
    # The heading line itself is the section's NAME, not its content: keeping
    # it would make the label set partly a restatement of the declared
    # parameter.
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) >= min_chars:
            out.append(stripped)
        if len(out) >= max_lines:
            break
    return out


def _extract_candidates(derivation: dict, fixture_root: str) -> list[str]:
    """Run one ``label_derivation`` recipe. Unknown kind -> ``ValueError``."""
    if not isinstance(derivation, dict):
        raise ValueError(f"label_derivation must be a dict, got {type(derivation)!r}")
    kind = derivation.get("kind")
    if kind not in LABEL_DERIVATION_KINDS:
        raise ValueError(
            f"unknown label_derivation kind {kind!r} -- the grammar is closed: "
            f"{list(LABEL_DERIVATION_KINDS)}")
    rel = derivation.get("file")
    if not isinstance(rel, str) or not rel:
        raise ValueError(f"label_derivation {kind!r} needs a 'file'")
    if kind == "csv_column_values":
        return _csv_column_values(_fixture_text(fixture_root, rel),
                                  derivation["column"])
    if kind == "json_keys":
        return _json_keys(_fixture_text(fixture_root, rel))
    if kind == "json_string_values":
        return _json_string_values(_fixture_text(fixture_root, rel))
    return _markdown_section_lines(
        fixture_root, rel, derivation["section"],
        int(derivation["min_chars"]), int(derivation["max_lines"]))


def _target_unit_text(fixture_root: str, target: str) -> str:
    """The text of the task's target UNIT -- the anti-vacuity denominator.

    For ``path/to/doc.md::Section`` that is the section's own text, not the
    whole document: the retrieval unit a document contributes is one section
    per heading (``harness._repo_chunks`` with ``planes`` including
    "knowledge"), so a sibling section is a genuinely different chunk that a
    retrieval arm has to find. For every other target it is the whole file.
    """
    path, _, section = target.partition("::")
    if section and doc_spec_for(path) is not None:
        return _document_section(fixture_root, path, section).source
    return _fixture_text(fixture_root, path)


def derive_labels(task: dict, fixture_root: str | None = None) -> tuple[str, ...]:
    """Re-derive an ``artifact_parsed`` task's ``must_include`` from the bytes.

    Deterministic and side-effect free. See LABEL DERIVATION in this module's
    docstring for the grammar and the five mechanical filters; this function
    IS that specification, and the tests compare its output to the committed
    ``must_include`` rather than to a second copy of the expected strings.
    """
    derivation = task.get("label_derivation")
    if derivation is None:
        raise ValueError(
            f"task {task.get('id')!r} has no label_derivation to re-execute")
    root = fixture_root if fixture_root is not None else resolve_task_repo(task["repo"])
    planes = fixture_plane_map(root)
    derivation_file = derivation.get("file")
    if derivation_file not in planes:
        raise ValueError(
            f"label_derivation file {derivation_file!r} is not a classified "
            f"plane file of {root!r} -- refusing to derive labels from an "
            "artifact whose plane is unknown")
    own_plane = planes[derivation_file]
    other_plane_texts = {
        rel: _fixture_text(root, rel)
        for rel, plane in sorted(planes.items()) if plane != own_plane
    }
    target_text = _target_unit_text(root, task["target"])

    kept: list[str] = []
    seen: set[str] = set()
    for candidate in _extract_candidates(derivation, root):
        if candidate in seen:
            continue
        seen.add(candidate)
        if len(candidate) < MIN_LABEL_CHARS:
            continue
        if len(candidate.splitlines()) > 1:
            continue
        if any(candidate in text for text in other_plane_texts.values()):
            continue
        if candidate in target_text:
            continue
        kept.append(candidate)
    return tuple(kept)


#: The keys that make a task a CORRECTNESS task rather than a slice-recall one.
#: Either one is enough: a task carrying a test list is claiming its grade comes
#: from running tests, not from substring containment, and half a claim is
#: still a claim.
CORRECTNESS_KEYS = ("fail_to_pass", "pass_to_pass")


def is_correctness_task(task: dict) -> bool:
    """True iff ``task`` uses the FAIL_TO_PASS/PASS_TO_PASS format.

    Deliberately keyed on the PRESENCE of the field, not on its truthiness: a
    task with ``"fail_to_pass": []`` is a correctness task with an empty (and
    therefore invalid, see ``correctness.validate_task``) test list, NOT a
    slice-recall task -- and it must never be handed to ``_recall``, which
    would score its absent ``must_include`` as a vacuous 1.0. That is the exact
    shape of the failure this predicate exists to make impossible.
    """
    return isinstance(task, dict) and any(k in task for k in CORRECTNESS_KEYS)


def task_project_label(task: dict) -> str:
    """The project bucket a task belongs to, for --project filtering.

    A task with NO ``repo`` key labels as ``"<unknown>"`` rather than raising
    ``KeyError``. That is not defensive padding: this function is called from
    ``harness._task_error_row``, i.e. on the REPORTING path for a task that is
    already known to be malformed, so a raise here turned "one bad task is
    reported as a degraded row" into "the whole eval run dies on it" -- the
    exact failure ``_task_error_row`` exists to prevent. Found by a test, not
    by reading."""
    repo = task.get("repo")
    if repo is None:
        return "<unknown>"
    if repo == "agent_env" or repo == AGENT_ENV_ROOT:
        return "agent_env"
    return repo


# --------------------------------------------------------------------------- #
# The task set. Small + fast on purpose: agent_env (dogfood) + sunny_garden.   #
# All Tier-1 labels verified reachable against the current slices -- which is  #
# exactly the circularity documented above. Every task is "hand_reachable" /   #
# "primary" until an "independent_diff" or "temporal_churn" minter (see        #
# daedalus.eval.mint, a separate track) adds tasks with independent labels.    #
# --------------------------------------------------------------------------- #
TASKS: list[dict] = [
    # ----- agent_env: file-level targets ----------------------------------- #
    {
        "id": "web_api_file",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "agent_env",
        "target": "daedalus/interfaces/http/web_api.py",
        "must_include": ["_structure_index", "resolve_repo_root", "cached_index"],
        "question": "In web_api.py, what does _structure_index call to obtain "
                    "the structural index for a project?",
        "answer_contains": ["cached_index"],
    },
    {
        "id": "garden_care_file",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "sunny_garden",
        "target": "garden/care.py",
        "must_include": ["needs_water", "watering_plan", "PLANTS"],
        "question": "How does needs_water decide whether a plant is thirsty?",
        "answer_contains": ["water_every_days"],
    },
    {
        "id": "garden_cli_file",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "sunny_garden",
        "target": "garden/cli.py",
        "must_include": ["watering_plan"],
        "question": "What does the garden cli main() print for each plant?",
        "answer_contains": ["water"],
    },
    {
        "id": "garden_plants_file",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "sunny_garden",
        "target": "garden/plants.py",
        "must_include": ["PLANTS"],
        "question": "How many days between waterings does a cactus need?",
        "answer_contains": ["14"],
    },
    # ----- agent_env: symbol-level targets --------------------------------- #
    {
        "id": "slice_semantic_slice",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "agent_env",
        "target": "daedalus/structcore/slice.py::semantic_slice",
        # Updated when neighborhood expansion moved off the python-only dotted
        # module map onto idx["import_edges"] (S2): ``_py_maps`` no longer
        # exists, and its role -- supplying the lookup semantic_slice expands
        # through -- is now ``_reverse_edges``. Ground truth follows the code;
        # the symbol is still a real callee, verified against the call graph.
        "must_include": ["_reverse_edges", "extract_units", "estimate_tokens"],
        "question": "How does semantic_slice compute the whole-repo token count "
                    "it reports the reduction against?",
        # Updated by the HONEST DENOMINATOR change (slice.py::_whole_repo_tokens):
        # the primary path is now idx["total_tokens"] (tokenizer-measured,
        # carried through by build_index); total_chars // 4 survives only as
        # the fallback for an index dict that predates the field. The label
        # tested total_chars unconditionally and was never updated when the
        # code it grades moved off that formula -- ground truth follows the
        # code (see the comment above this task).
        "answer_contains": ["total_tokens"],
    },
    {
        "id": "index_build_index",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "agent_env",
        "target": "daedalus/structcore/index.py::build_index",
        # Updated when the per-file pass was extracted into perfile.py and
        # parallelized: build_index no longer calls extract_units/file_metrics/
        # python_imports directly -- they moved behind _per_file_pass. These are
        # its real current dependencies, verified against the call graph. The
        # slicer was NOT the thing that changed; the labels were stale.
        "must_include": ["_per_file_pass", "resolve_python_imports", "unit_clusters"],
        "question": "What does build_index use to detect duplicate code units?",
        "answer_contains": ["unit_clusters"],
    },
    {
        "id": "report_structure_summary",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "agent_env",
        "target": "daedalus/structcore/report.py::structure_summary",
        "must_include": ["unit_clusters", "window_clusters", "fan_in"],
        "question": "Which keys does structure_summary place under 'totals'?",
        "answer_contains": ["unit_clusters"],
    },
    {
        "id": "ikarus_distill",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "agent_env",
        "target": "daedalus/orchestration/ikarus/shell.py::_distill",
        "must_include": ["semantic_slice", "resolve_repo_root", "cached_index"],
        "question": "When the user names a file, what does _distill call to "
                    "produce the token-saving figure?",
        "answer_contains": ["semantic_slice"],
    },
    {
        "id": "projects_resolve_repo_root",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "agent_env",
        "target": "daedalus/foundation/projects.py::resolve_repo_root",
        "must_include": ["load_project"],
        "question": "How does resolve_repo_root turn a project name into a "
                    "repo path?",
        "answer_contains": ["load_project", "repo_root"],
    },
    # ----- sunny_garden: symbol-level target ------------------------------- #
    {
        "id": "garden_watering_plan",
        "label_provenance": "hand_reachable",
        "tier": "primary",
        "repo": "sunny_garden",
        "target": "garden/care.py::watering_plan",
        "must_include": ["needs_water", "PLANTS"],
        "question": "What does watering_plan return?",
        "answer_contains": ["needs_water"],
    },
    # ----- fourfold_wiki_app: the cross-plane, artifact_parsed corpus ------ #
    #
    # Four tasks whose gold labels live OUTSIDE the code plane. Read the
    # "artifact_parsed" bullet and LABEL DERIVATION in this module's docstring
    # before touching any of them: ``must_include`` is not editable prose, it
    # is the output of ``derive_labels`` over the fixture bytes, and a test
    # fails the moment the two disagree in either direction.
    #
    # None of them carries a ``question``: a Tier-2 question needs an entry in
    # ``tier2._BUILTIN_VALIDATORS`` (``tier2.builtin_validator_coverage``, and
    # tests/test_eval_tier2_integrity.py asserts the missing list is empty), and
    # an LLM-graded answer about a file the slicer cannot even index would be a
    # claim built on nothing.
    #
    # None of them is scorable by Tier 1 or arm A today: every target is a
    # data artifact or a document, so the harness emits a PLANE-UNINDEXED row
    # (``harness._plane_unindexed_row``) with no recall key. That is the point
    # -- the labels exist and are independent; the retrieval arm that can score
    # them (``harness._repo_chunks(..., planes=("code", "data", "knowledge"))``)
    # is Gate-3 work on another branch.
    {
        # DATA plane target, labels derived from the OTHER data artifact.
        # ``json_keys`` was chosen over ``json_string_values`` after measuring
        # both (2026-09-08): both survive the filters non-empty, but the
        # string-value set is dominated by the two ``$schema``/``$id`` URLs
        # plus the generic words "object"/"string", while the key set is
        # exactly the schema's constraint vocabulary -- what a reader actually
        # needs in context to reason about the CSV's constraints.
        "id": "fourfold_articles_csv",
        "label_provenance": "artifact_parsed",
        "tier": "primary",
        "repo": "fourfold_wiki_app",
        "target": "data/articles.csv",
        "label_derivation": {
            "kind": "json_keys",
            "file": "schemas/article.schema.json",
        },
        "must_include": [
            "$schema", "pattern", "minLength", "enum", "additionalProperties",
        ],
    },
    {
        # DATA plane target (the schema), labels derived from the records the
        # schema constrains. ``fourfold-overview`` is NOT in the list: the
        # exclusivity filter drops it because it also occurs in
        # wiki/CLI.md (knowledge plane). Measured, not chosen.
        "id": "fourfold_article_schema",
        "label_provenance": "artifact_parsed",
        "tier": "primary",
        "repo": "fourfold_wiki_app",
        "target": "schemas/article.schema.json",
        "label_derivation": {
            "kind": "csv_column_values",
            "file": "data/articles.csv",
            "column": "slug",
        },
        "must_include": [
            "revision-atomicity", "evidence-boundaries", "wiki-operations",
            "draft-research",
        ],
    },
    {
        # KNOWLEDGE plane, INTRA-document: the target is one section, the
        # labels are the sibling section of the same file. The anti-vacuity
        # filter is applied at SECTION granularity here (see
        # ``_target_unit_text``) because a document's retrieval unit is a
        # section, so "Decision" is a chunk the arm must actually find --
        # returning the "Consequences" target satisfies none of these labels.
        "id": "fourfold_adr_consequences_section",
        "label_provenance": "artifact_parsed",
        "tier": "primary",
        "repo": "fourfold_wiki_app",
        "target": "wiki/ADR/ADR-001-CSV-Storage.md::Consequences",
        "label_derivation": {
            "kind": "markdown_section_lines",
            "file": "wiki/ADR/ADR-001-CSV-Storage.md",
            "section": "Decision",
            "min_chars": 20,
            "max_lines": 4,
        },
        "must_include": [
            "Use [articles.csv](../../data/articles.csv) as the durable dataset and keep the",
            "reader in [`repository.py`](../../src/knowledge_hub/repository.py). Retain a",
            "parallel [JSON Schema](../../schemas/article.schema.json) so the data plane has",
            "both concrete records and an explicit constraint artifact.",
        ],
    },
    {
        # KNOWLEDGE plane, CROSS-document: the target links to the document the
        # labels come from ("See [Operations](Operations.md)" in Security.md).
        # The twin compiles that link as the edge
        # knowledge:doc:wiki/Security.md -links_to-> knowledge:doc:wiki/Operations.md
        # (measured; tests/test_eval_corpus_planes.py asserts it), so this task
        # asks for exactly one verified cross-document hop.
        "id": "fourfold_security_operations_link",
        "label_provenance": "artifact_parsed",
        "tier": "primary",
        "repo": "fourfold_wiki_app",
        "target": "wiki/Security.md",
        "label_derivation": {
            "kind": "markdown_section_lines",
            "file": "wiki/Operations.md",
            "section": "Operations",
            "min_chars": 20,
            "max_lines": 4,
        },
        "must_include": [
            "The reference application is read-only. Operators update",
            "[articles.csv](../data/articles.csv), validate it against",
            "[article.schema.json](../schemas/article.schema.json), run the application, and",
            "then rebuild the Fourfold snapshot.",
        ],
    },
]
