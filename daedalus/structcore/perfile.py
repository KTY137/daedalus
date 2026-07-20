"""The per-file half of ``build_index`` — pure, picklable, parallelizable.

Roughly half the index build is per-file work that depends on nothing but that
one file's bytes: unit extraction, health metrics, window-run hashing and raw
import extraction. Isolating it here buys two things at once:

  * it can run in a ``ProcessPoolExecutor`` (the work is CPU-bound, so threads
    are useless under the GIL), and
  * it can be memoized on disk, keyed by content, because the result is a pure
    function of (rel, spec, text) plus this module's ``ANALYSIS_VERSION``.

Everything crossing a process boundary is plain data. Nothing here imports
``index`` — workers must not re-enter the single-flight build lock.

Whole-repo work (import RESOLUTION, the clone passes, churn) deliberately stays
in the parent: it needs the full file set, and it is not per-file parallel.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .clones import window_runs
from .languages import LanguageSpec
from .metrics import file_metrics
from .parse import CodeUnit, extract_units, python_units_and_imports
from . import imports as imports_mod

# Bump whenever the MEANING of any field below changes (new metric, different
# unit extraction, changed window hashing). It is part of the disk-cache key, so
# bumping it invalidates every cached entry. A stale cache reporting wrong code
# health is far worse than a slow scan -- when in doubt, bump.
ANALYSIS_VERSION = "2"


@dataclass
class FileAnalysis:
    """Everything the index needs from one file. Plain data only."""
    rel: str
    lang: str
    n_chars: int
    loc: int
    metrics: dict
    units: list[CodeUnit] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    # Python: raw ast import records. Other languages: (raw, kind) pairs.
    py_imports: list = field(default_factory=list)
    raw_imports: list = field(default_factory=list)


def analyze_file(rel: str, text: str, spec: LanguageSpec, ts_on: bool) -> FileAnalysis:
    """Analyze ONE file. Pure: same inputs -> same outputs, no I/O, no globals."""
    if spec.name == "python":
        # One ast.parse feeds both units and imports (it used to be two).
        units, py_imports = python_units_and_imports(rel, text)
        raw_imports: list = []
    else:
        units = extract_units(rel, text, spec)
        py_imports = []
        raw_imports = imports_mod.extract_imports(rel, text, spec, ts_on)

    metrics = file_metrics(rel, text, spec, units)
    return FileAnalysis(
        rel=rel, lang=spec.name, n_chars=len(text), loc=metrics["loc"],
        metrics=metrics, units=units, runs=window_runs(text, spec),
        py_imports=py_imports, raw_imports=raw_imports,
    )


def analyze_chunk(job: tuple) -> list[tuple[int, FileAnalysis]]:
    """Worker entry point: analyze a batch of files, tagging each with its
    ORIGINAL index.

    Batched rather than one-task-per-file because Windows spawns (not forks)
    workers, so per-task overhead is real. The index tag is what lets the parent
    restore exact input order regardless of completion order -- ``all_units``
    order is load-bearing for the clone passes.
    """
    ts_on, items = job
    return [(i, analyze_file(rel, text, spec, ts_on)) for i, rel, text, spec in items]
