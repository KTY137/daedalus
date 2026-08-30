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

``tier``: "primary" tasks count toward any go/no-go recall number.
"quarantine" tasks are minted but not yet confirmed -- ``harness.run_tier1``
excludes them from every headline/aggregate and reports them separately so
the labelling flywheel (mint -> quarantine -> confirm -> primary) stays
observable instead of silently inflating (or deflating) the real number.

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

import os
from pathlib import Path

from daedalus.projects import list_projects, resolve_repo_root

# agent_env repo root == parents[2] of this file (daedalus/eval/tasks.py).
AGENT_ENV_ROOT = str(Path(__file__).resolve().parents[2])
SUNNY_GARDEN_FIXTURE = str(
    Path(__file__).resolve().parent / "fixtures" / "sunny_garden"
)


def resolve_task_repo(repo: str) -> str:
    """Map a task's ``repo`` label to an absolute repo root.

    "agent_env"        -> this harness repo (dogfood target)
    a registered name  -> daedalus.projects.resolve_repo_root (e.g. sunny_garden)
    an absolute path   -> used as-is (temp fixtures in tests)
    """
    if repo == "agent_env":
        return AGENT_ENV_ROOT
    if repo == "sunny_garden" and Path(SUNNY_GARDEN_FIXTURE).is_dir():
        return SUNNY_GARDEN_FIXTURE
    if os.path.isabs(repo) and Path(repo).exists():
        return repo
    if repo in list_projects():
        return resolve_repo_root(None, repo)
    raise ValueError(f"cannot resolve task repo label: {repo!r}")


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
        "target": "daedalus/web_api.py",
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
        "target": "daedalus/ikarus_os.py::_distill",
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
        "target": "daedalus/projects.py::resolve_repo_root",
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
]
