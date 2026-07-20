"""tasks.py -- the labelled task set for the distillation eval.

Each task targets a real symbol/file in a small repo and records the symbols a
*sufficient* distilled slice MUST carry to reason about that target. The labels
below were picked by reading the code and VERIFIED reachable by running
``semantic_slice`` (see ``daedalus.eval.harness``); a label is only listed if a
competent answer about the target genuinely needs it AND it is a real dependency
or caller in the neighborhood.

Task shape::

    {
      "id":              short unique id,
      "repo":            repo label -- "agent_env" | "sunny_garden" | abs path,
      "target":          "path/to/file.py"  or  "path/to/file.py::symbol",
      "must_include":    [symbol_or_substring, ...]   # Tier 1 recall labels
      "question":        natural question about the target (optional, Tier 2),
      "answer_contains": [substring, ...]              # Tier 2 success labels
    }

Honesty note: ``must_include`` items are matched as substrings against the
slice text. For a symbol target the slice is 1-hop (the focus symbol's direct
callees/callers), so we only label symbols reachable within that hop -- we do
NOT claim transitive callees-of-callees are present when they are not.
"""
from __future__ import annotations

import os
from pathlib import Path

from daedalus.projects import list_projects, resolve_repo_root

# agent_env repo root == parents[2] of this file (daedalus/eval/tasks.py).
AGENT_ENV_ROOT = str(Path(__file__).resolve().parents[2])


def resolve_task_repo(repo: str) -> str:
    """Map a task's ``repo`` label to an absolute repo root.

    "agent_env"        -> this harness repo (dogfood target)
    a registered name  -> daedalus.projects.resolve_repo_root (e.g. sunny_garden)
    an absolute path   -> used as-is (temp fixtures in tests)
    """
    if repo == "agent_env":
        return AGENT_ENV_ROOT
    if os.path.isabs(repo) and Path(repo).exists():
        return repo
    if repo in list_projects():
        return resolve_repo_root(None, repo)
    raise ValueError(f"cannot resolve task repo label: {repo!r}")


def task_project_label(task: dict) -> str:
    """The project bucket a task belongs to, for --project filtering."""
    repo = task["repo"]
    if repo == "agent_env" or repo == AGENT_ENV_ROOT:
        return "agent_env"
    return repo


# --------------------------------------------------------------------------- #
# The task set. Small + fast on purpose: agent_env (dogfood) + sunny_garden.   #
# All Tier-1 labels verified reachable against the current slices.             #
# --------------------------------------------------------------------------- #
TASKS: list[dict] = [
    # ----- agent_env: file-level targets ----------------------------------- #
    {
        "id": "web_api_file",
        "repo": "agent_env",
        "target": "daedalus/web_api.py",
        "must_include": ["_structure_index", "resolve_repo_root", "cached_index"],
        "question": "In web_api.py, what does _structure_index call to obtain "
                    "the structural index for a project?",
        "answer_contains": ["cached_index"],
    },
    {
        "id": "garden_care_file",
        "repo": "sunny_garden",
        "target": "garden/care.py",
        "must_include": ["needs_water", "watering_plan", "PLANTS"],
        "question": "How does needs_water decide whether a plant is thirsty?",
        "answer_contains": ["water_every_days"],
    },
    {
        "id": "garden_cli_file",
        "repo": "sunny_garden",
        "target": "garden/cli.py",
        "must_include": ["watering_plan"],
        "question": "What does the garden cli main() print for each plant?",
        "answer_contains": ["water"],
    },
    {
        "id": "garden_plants_file",
        "repo": "sunny_garden",
        "target": "garden/plants.py",
        "must_include": ["PLANTS"],
        "question": "How many days between waterings does a cactus need?",
        "answer_contains": ["14"],
    },
    # ----- agent_env: symbol-level targets --------------------------------- #
    {
        "id": "slice_semantic_slice",
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
        "answer_contains": ["total_chars"],
    },
    {
        "id": "index_build_index",
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
        "repo": "agent_env",
        "target": "daedalus/structcore/report.py::structure_summary",
        "must_include": ["unit_clusters", "window_clusters", "fan_in"],
        "question": "Which keys does structure_summary place under 'totals'?",
        "answer_contains": ["unit_clusters"],
    },
    {
        "id": "ikarus_distill",
        "repo": "agent_env",
        "target": "daedalus/ikarus_os.py::_distill",
        "must_include": ["semantic_slice", "resolve_repo_root", "cached_index"],
        "question": "When the user names a file, what does _distill call to "
                    "produce the token-saving figure?",
        "answer_contains": ["semantic_slice"],
    },
    {
        "id": "projects_resolve_repo_root",
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
        "repo": "sunny_garden",
        "target": "garden/care.py::watering_plan",
        "must_include": ["needs_water", "PLANTS"],
        "question": "What does watering_plan return?",
        "answer_contains": ["needs_water"],
    },
]
