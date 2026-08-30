# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
from .parse import (CodeUnit, PyTypeFacts, extract_units,
                    python_units_imports_and_types)
from .tokens import count_tokens
from . import imports as imports_mod

# Bump whenever the MEANING of any field below changes (new metric, different
# unit extraction, changed window hashing). It is part of the disk-cache key, so
# bumping it invalidates every cached entry. A stale cache reporting wrong code
# health is far worse than a slow scan -- when in doubt, bump.
#
# "3": added n_tokens. A row cached under "2" has no token count, and an index
# built from such rows would report a denominator of zero for part of the repo
# -- i.e. an inflated distillation headline, silently. Bumping makes that
# unrepresentable.
#
# "4": ``parse.py`` gained the type/field/signature extractor (``PyTypeFacts``).
# The digest of parse.py is already part of every key, so this bump is belt to
# that braces -- but the two locks fail differently and only one of them is
# under our control. The digest catches an EDIT to the extractor; this constant
# is what a reader greps for to answer "which generation of rows is in this
# cache", and the convention above says to bump when the meaning of a row
# changes. It does: a row now describes a file that has type facts, even in the
# generation where ``FileAnalysis`` does not yet carry them.
#
# "5": ``FileAnalysis`` now actually CARRIES them (``type_facts``). "4" rows were
# written by the generation that had the extractor but not the field, so they
# have no ``type_facts`` key at all. Those rows would decode (``_decode`` reads
# by subscript, so in fact they raise KeyError and become a miss) -- but relying
# on a KeyError being raised and swallowed is an accidental lock, not a stated
# one, and ``_SCHEMA`` was bumped to 2 in the same commit so they are DELETEd on
# open anyway. This constant is the one a reader greps to answer "which
# generation of rows is in this cache", and the answer changed.
ANALYSIS_VERSION = "5"


@dataclass
class FileAnalysis:
    """Everything the index needs from one file. Plain data only."""
    rel: str
    lang: str
    n_chars: int
    # Real tokenizer count of the file's text (tiktoken cl100k_base when
    # installed, else tokens.count_tokens' chars/4 fallback). Carried per-file
    # rather than recomputed at report time so it rides the disk cache: the
    # distill ratio's DENOMINATOR then comes from the same tokenizer as its
    # numerator, instead of a chars/4 guess. Computed in the pass that already
    # holds the text, so it costs one encode per cache miss.
    n_tokens: int
    loc: int
    metrics: dict
    units: list[CodeUnit] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    # Python: raw ast import records. Other languages: (raw, kind) pairs.
    py_imports: list = field(default_factory=list)
    raw_imports: list = field(default_factory=list)
    # RAW, UNRESOLVED type/field/signature records for the type-graph layer
    # (Python only -- Stufe 1; ``PyTypeFacts()`` for every other language, which
    # is why the layer reports ``not_supported`` per language rather than a zero).
    #
    # EXTRACTED UNCONDITIONALLY, even when the layer is switched off. The gate is
    # in ``index.build_index`` (resolution + publication) and deliberately NOT
    # here: this dataclass rides a CONTENT-KEYED disk cache, so a gate on this
    # side would let a row written with the layer off (empty facts) be served as
    # a HIT to a later build with the layer on -- an empty type block with no
    # error, no exception and no log line, which is the exact silent failure the
    # plan's Cache-Kopplung note describes. Making it unconditional costs one
    # more walk of a tree that is already parsed (~3ms/file, and only on a cache
    # MISS) and makes the cache correct by construction instead of by a
    # correctly-composed key.
    #
    # A frozen dataclass with only tuple fields is hashable and immutable, so it
    # is safe as a PLAIN default (no default_factory) and safe to ship across a
    # process boundary.
    type_facts: PyTypeFacts = PyTypeFacts()


def analyze_file(rel: str, text: str, spec: LanguageSpec, ts_on: bool) -> FileAnalysis:
    """Analyze ONE file. Pure: same inputs -> same outputs, no I/O, no globals."""
    type_facts = PyTypeFacts(module=rel)
    if spec.name == "python":
        # ONE ast.parse feeds units, imports AND type facts (it used to be two
        # walks of one parse; it is now three walks of the same one). The units
        # and the import records are produced by the SAME functions as before --
        # ``python_units_imports_and_types`` adds a third walk, it does not
        # change the first two (invariant I1).
        units, py_imports, type_facts = python_units_imports_and_types(rel, text)
        raw_imports: list = []
    else:
        units = extract_units(rel, text, spec)
        py_imports = []
        raw_imports = imports_mod.extract_imports(rel, text, spec, ts_on)

    metrics = file_metrics(rel, text, spec, units)
    return FileAnalysis(
        rel=rel, lang=spec.name, n_chars=len(text), n_tokens=count_tokens(text),
        loc=metrics["loc"],
        metrics=metrics, units=units, runs=window_runs(text, spec),
        py_imports=py_imports, raw_imports=raw_imports,
        type_facts=type_facts,
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
