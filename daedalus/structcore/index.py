"""build_index — walk a repo, derive the multi-language structural index.

Output (all derived, regenerate-anytime):
  * languages   — files + LOC per language actually found
  * modules     — per-file health metrics
  * dependencies / fan_in — internal import graph (Python precise; other
    languages best-effort via ``imports.py`` — module->file resolution is
    approximated without a real build graph, so unresolved edges are dropped,
    never guessed)
  * duplication — exact (unit) + renamed (Type-2) + near-miss (Type-3) clone
    clusters, plus window-level (universal, parser-free)
  * hotspots    — complexity ranking, multiplied by normalized git churn (the
    CodeScene signal: rot lives where code is complex AND changing)
  * backend     — which optional precision engines were active
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from .languages import LanguageSpec, spec_for
from .parse import CodeUnit, resolve_python_imports, tree_sitter_available
from .metrics import lizard_available
from .clones import (TYPE3_EXCLUDED_LANGUAGES, CloneMemo, unit_clusters,
                     window_clusters_from_runs, renamed_clusters, near_clusters)
from .perfile import FileAnalysis, analyze_chunk, analyze_file
from .cache import FileCache, file_key
from . import imports as imports_mod
from . import graph
from . import tokens
from .churn import git_churn
from .ignore import project_scope

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "out", "coverage", ".next", ".nuxt", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".vs", ".vscode", "vendor", ".cache",
}


def backend_status() -> dict:
    return {"tree_sitter": tree_sitter_available(), "lizard": lizard_available()}


def _collect(root: Path, max_files: int) -> list[tuple[Path, str, LanguageSpec]]:
    out: list[tuple[Path, str, LanguageSpec]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            spec = spec_for(fn)
            if spec is None:
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            out.append((p, rel, spec))
            if len(out) >= max_files:
                return out
    return out


def _py_dotted(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel.rsplit(".", 1)[0]
    return stem.replace("/", ".")


# A ``.pyi`` is a type stub DECLARING the module its ``.py`` sibling defines --
# not a second module. Both strip to one dotted name, which is why the naming
# table has to say which file that name binds to.
_STUB_SUFFIXES = (".pyi",)


def _disambiguate(rels: list[str]) -> str | None:
    """Which file a dotted name binds to, or None when that cannot be known.

    Order-independent by construction: the answer is a function of the SET of
    candidates, never of the order they were walked in. The previous
    ``{_py_dotted(rel): rel for ...}`` dict comprehension was a last-writer-wins
    race decided by ``os.walk`` -- measured at 141 live collisions on
    project_tct, every one a .py/.pyi pair, and it bound the name to the STUB.

    Two rules, in order:
      1. A stub is not a rival. If exactly one candidate is real source, the
         name is that module and the stub is its declaration. This is a
         precedence rule about what a ``.pyi`` MEANS, not a tie-break.
      2. Otherwise refuse. Two genuine modules claiming one dotted name is a
         real ambiguity, and a wrong edge lies about what depends on what --
         strictly worse than a missing one. Callers report the refusal with
         counts rather than binding to whichever file sorted first.
    """
    if len(rels) == 1:
        return rels[0]
    real = [r for r in rels if not r.endswith(_STUB_SUFFIXES)]
    if len(real) == 1:
        return real[0]
    return None


class _View(NamedTuple):
    """One importer's-eye view of the Python dotted namespace.

    ``canon`` maps an accepted ALTERNATE spelling to the file's single
    canonical dotted name, so a target resolved via an alias still lands on one
    identity in ``dep_edges``/``fan_in``.
    """

    tops: set[str]                  # eligibility gate (parse.py membership test)
    known: set[str]                 # every name resolvable from here
    rel_by_dotted: dict[str, str]   # canonical name -> file, when unambiguous
    canon: dict[str, str]           # alias spelling -> canonical name


class _PyNaming:
    """Python dotted-name tables, resolved from the IMPORTER's point of view.

    A declared ``center`` means "this subtree IS the project", so it is also the
    PACKAGE ROOT: ``TCT_app/controller/danger_gate.py`` is run with ``TCT_app``
    on ``sys.path`` and its siblings therefore write ``from controller.
    danger_gate import ...``. Naming it ``TCT_app.controller.danger_gate`` (the
    repo-root form) matched nothing, and ``resolve_python_imports`` dropped the
    edge before it ever reached the ``known`` lookup. 87% of project_tct's map
    was isolated for this one reason.

    WHY VIEWS, AND NOT ONE WIDER GLOBAL TABLE
    -----------------------------------------
    The obvious fix -- strip the prefix and let ``internal_tops`` grow -- is
    unsafe, and the danger is on the *other* side of the membership test.
    ``internal_tops`` is the eligibility gate, and two of its three uses in
    ``parse.py`` (the plain ``import x`` branch, and the fallback) admit a name
    with NO ``known`` check at all. Stripping ``TCT_app/`` globally would inject
    ``controller``, ``devices``, ``gui``, ``data`` -- generic names that collide
    with real PyPI and vendored packages -- into a table consulted by every file
    in the repo. project_tct carries 8516 shell import records today that are
    inert only because no shell file's top segment can equal ``TCT_app``; widen
    the global table and any vendored file writing ``import data`` becomes
    eligible to bind onto a center file. That would manufacture false edges,
    which is the one outcome worse than the missing ones we are fixing.

    So the table is selected by the importer:

      * a file under center C sees C's files by their PACKAGE-RELATIVE name,
        and everything else in the repo by its repo-root name;
      * a file under no center sees the repo-root table, unchanged, which is
        byte-for-byte what every file saw before this change.

    Shell eligibility therefore cannot move, and a repo with no center declared
    gets exactly one view that is identical to the old global one.

    A view strips only its OWN center, which dissolves the multi-center
    collision case rather than having to arbitrate it: with ``center=["a","b"]``
    both containing ``controller/``, inside a's view ``controller.x`` is a's
    file and b's is still ``b.controller.x`` -- which is exactly what the
    runtime does, since ``a`` runs with ``a`` on sys.path and not ``b``. The
    collision that stripping DOES create is against the shell: a center file
    whose stripped name matches a repo-root module (``a/controller/x.py`` vs
    ``controller/x.py``). That one is a genuine ambiguity and is refused, not
    guessed -- see ``_disambiguate``.

    ONE IDENTITY, TWO SPELLINGS
    ---------------------------
    A center can sit at either of two places in a real layout, and the config
    cannot tell us which:

      * the center IS the sys.path root (project_tct: ``TCT_app`` is the cwd,
        so its files write ``from controller.danger_gate import ...``);
      * the center is a PACKAGE on the parent path (the repo root is on
        sys.path, so its files write ``from TCT_app import core``).

    Both spellings name the same file, so accepting both is not a guess and
    costs no precision. What we refuse is two IDENTITIES for one file: the
    repo-root spelling is registered as an ALIAS in this view's lookup tables,
    and every resolved target is canonicalised back to the package-relative
    name before it reaches ``dep_edges``. So ``fan_in`` -- accumulated over
    ``dep_edges`` keys -- still counts each file exactly once, and the top
    fan-in table cannot shift for a bookkeeping reason.

    The alias lives ONLY in its own center's view, and it is that center's own
    path prefix, so it cannot widen what a shell file is eligible to bind. An
    alias also never displaces a real module: if some file genuinely owns that
    spelling in this view, the alias is dropped.
    """

    def __init__(self, py_rels: list[str], scope):
        self._rels = sorted(py_rels)
        # Ownership decides naming; ``center_of`` returns None when no center is
        # declared, so an unconfigured repo takes the repo-root path everywhere
        # by construction rather than by luck. Longest-prefix wins there.
        self._owner = {rel: scope.center_of(rel) for rel in self._rels}
        self._name = {}
        for rel in self._rels:
            c = self._owner[rel]
            self._name[rel] = _py_dotted(rel[len(c) + 1:] if c else rel)

        # EAGER, over a sorted key list. Building views lazily on first use
        # would make ``ambiguous`` depend on which files happened to be visited,
        # so the reported ambiguity set -- and therefore the index -- would vary
        # with walk order. There are at most len(center)+1 views.
        self._ambiguous: dict[str, list[str]] = {}
        self._views: dict[str | None, tuple] = {}
        for key in [None, *sorted(scope.center)]:
            self._views[key] = self._build(key)

    def _build(self, key: str | None) -> "_View":
        by_name: dict[str, list[str]] = defaultdict(list)
        aliases: list[tuple[str, str]] = []
        for rel in self._rels:  # already sorted -> candidate lists are sorted
            stripped = key is not None and self._owner[rel] == key
            canon = self._name[rel] if stripped else _py_dotted(rel)
            by_name[canon].append(rel)
            if stripped and _py_dotted(rel) != canon:
                aliases.append((_py_dotted(rel), canon))

        rel_by_dotted: dict[str, str] = {}
        for name in sorted(by_name):
            pick = _disambiguate(by_name[name])
            if pick is not None:
                rel_by_dotted[name] = pick
            else:
                # The NAME-level edge stays true and is kept in ``known``: the
                # importer really does depend on that module. Only the
                # FILE-level binding is withheld, because which file it is is
                # exactly what we cannot honestly say.
                self._ambiguous.setdefault(name, list(by_name[name]))

        # Sorted, and never over a name a real module already owns in this view.
        canon: dict[str, str] = {}
        for spelling, target in sorted(aliases):
            if spelling not in by_name:
                canon[spelling] = target

        known = set(by_name) | set(canon)
        return _View(tops={n.split(".")[0] for n in known}, known=known,
                     rel_by_dotted=rel_by_dotted, canon=canon)

    def name(self, rel: str) -> str:
        """The dotted module name THIS file is published under."""
        return self._name[rel]

    def tables_for(self, rel: str) -> _View:
        """The dotted namespace as THIS importer sees it."""
        return self._views[self._owner[rel]]

    def describe(self) -> dict:
        """Ambiguity report. Never silent: a name we refused to bind is a
        dependency the map is NOT showing, and an unreported one is
        indistinguishable from a file that genuinely has no dependents."""
        names = sorted(self._ambiguous)
        return {
            "ambiguous_count": len(names),
            "ambiguous_sample": [
                {"dotted": n, "candidates": self._ambiguous[n][:4]} for n in names[:25]
            ],
            "truncated": len(names) > 25,
        }


# Below this many cache-missing files a process pool stops paying for itself:
# Windows SPAWNS workers (no fork), so each one re-imports tree-sitter, lizard
# and the whole package before doing any useful work.
#
# Measured break-even on this 8-core box (cache off, so only the pool varies):
#     72 files -> 1.01x   141 -> 1.14x   467 -> 1.49x   6799 -> 2.75x
# i.e. it is already neutral around 70 files, so 100 is a safe floor that still
# captures the mid-size repos.
_PARALLEL_MIN_FILES = 100
_CHUNK_SIZE = 40


def _worker_count() -> int:
    env = os.environ.get("DAEDALUS_SCAN_WORKERS", "").strip()
    if env.isdigit():
        return max(0, int(env))
    return min(8, os.cpu_count() or 1)


def _parallel_min() -> int:
    """Overridable so tests can force the parallel path on a small fixture --
    otherwise the pool would only ever be exercised on huge repos."""
    env = os.environ.get("DAEDALUS_SCAN_MIN_PARALLEL", "").strip()
    return int(env) if env.isdigit() else _PARALLEL_MIN_FILES


def _per_file_pass(root: Path, records: list[tuple[str, LanguageSpec, str]],
                   ts_on: bool) -> list[FileAnalysis]:
    """Analyze every record, returning results in EXACTLY the input order.

    Two levers, composed: a content-keyed disk cache absorbs unchanged files,
    and whatever is left is spread over a process pool (the work is CPU-bound,
    so threads would do nothing under the GIL).

    ORDER IS LOAD-BEARING and is the whole reason results are index-tagged:
    ``all_units`` is consumed positionally by the clone passes, so cluster
    membership and ordering depend on it. Pool completion order is arbitrary, so
    every result carries its original index and is written back into a
    preallocated slot -- never appended in completion order.
    """
    keys = [file_key(rel, spec.name, text) for rel, spec, text in records]
    out: list[FileAnalysis | None] = [None] * len(records)

    cache = FileCache(root)
    try:
        hits = cache.get_many(keys)
        pending: list[tuple[int, str, str, LanguageSpec]] = []
        for i, (rel, spec, text) in enumerate(records):
            got = hits.get(keys[i])
            if got is not None:
                out[i] = got
            else:
                pending.append((i, rel, text, spec))

        _compute(pending, ts_on, out)

        fresh = [(keys[i], out[i]) for i, _, _, _ in pending if out[i] is not None]
        cache.put_many(fresh)
        cache.prune(set(keys))
    finally:
        cache.close()

    # Any None here means a worker silently dropped a file -- recompute inline
    # rather than shipping a short/misaligned list to the clone passes.
    for i, (rel, spec, text) in enumerate(records):
        if out[i] is None:
            out[i] = analyze_file(rel, text, spec, ts_on)
    return out  # type: ignore[return-value]


def _compute(pending: list[tuple[int, str, str, LanguageSpec]], ts_on: bool,
             out: list) -> None:
    """Fill ``out[i]`` for every pending record, in parallel when it pays."""
    if not pending:
        return

    workers = _worker_count()
    if len(pending) < _parallel_min() or workers < 2:
        for i, rel, text, spec in pending:
            out[i] = analyze_file(rel, text, spec, ts_on)
        return

    chunks = [(ts_on, pending[i:i + _CHUNK_SIZE])
              for i in range(0, len(pending), _CHUNK_SIZE)]
    try:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as ex:
            for batch in ex.map(analyze_chunk, chunks):
                for i, analysis in batch:
                    out[i] = analysis
    except Exception:
        # No usable pool (sandbox, spawn failure, unpicklable payload): the
        # serial path is always correct, just slower.
        for i, rel, text, spec in pending:
            out[i] = analyze_file(rel, text, spec, ts_on)


def build_index(root, max_files: int = 20000, center=None, ignore=None) -> dict:
    root = Path(root).resolve()
    collected = _collect(root, max_files)

    records: list[tuple[str, LanguageSpec, str]] = []
    for path, rel, spec in collected:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        records.append((rel, spec, text))

    # SCOPE: the declared center (what this project IS) plus .daedalusignore
    # (exceptions carved within it). Everything else in the repo is SHELL --
    # real source, but not this project's code: vendored trees, spec copies,
    # generated skeletons.
    #
    # Shell files are deliberately still collected and still parsed: they stay
    # in the file-set indexes below, so a real file importing INTO the shell
    # resolves to a true edge instead of silently degrading to "external". What
    # they are withheld from is every METRIC -- see the aggregation loop. Doing
    # it this way costs ~2% (the per-file parse) and saves ~96% (clone passes).
    scope = project_scope(root, center, ignore)
    ignored: frozenset[str] = frozenset(
        rel for rel, _, _ in records if scope.is_shell(rel))

    # Python dotted-name tables, per importer. A center root is also a PACKAGE
    # root, so files under it are named relative to it; everything else keeps
    # repo-root naming. See ``_PyNaming`` for why this is not one global table.
    py_naming = _PyNaming(
        [rel for rel, spec, _ in records if spec.name == "python"], scope)

    # File-set indexes for best-effort non-Python import resolution (Move 2).
    known_files = {rel for rel, _, _ in records}
    by_basename: dict[str, list[str]] = defaultdict(list)
    by_dir_tail: dict[str, list[str]] = defaultdict(list)
    # SORTED, not raw set order. ``resolve_internal`` takes the FIRST match in
    # these lists, so their order decides which file an ambiguous import binds
    # to -- and iterating the set directly made that depend on PYTHONHASHSEED.
    # On repos with repeated basenames (Marlin ships HAL/AVR/fastio.h,
    # HAL/DUE/fastio.h, ...) the same source resolved to a different header on
    # every process, silently changing dependencies/import_edges/fan_in.
    for rel in sorted(known_files):
        by_basename[rel.rsplit("/", 1)[-1]].append(rel)
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        tail = parent.rsplit("/", 1)[-1] if parent else ""
        if tail:
            by_dir_tail[tail].append(rel)

    ts_on = tree_sitter_available()
    analyses = _per_file_pass(root, records, ts_on)

    modules: dict[str, dict] = {}
    all_units: list[CodeUnit] = []
    runs_by_file: list[tuple[str, list[str]]] = []
    spec_by_lang: dict[str, LanguageSpec] = {}
    lang_summary: dict[str, dict] = defaultdict(lambda: {"files": 0, "loc": 0})
    dep_edges: dict[str, set[str]] = defaultdict(set)
    # Unified rel->rel internal import map (ALL languages) — powers the Move-4
    # symbol resolver; distinct from ``dep_edges`` whose Python keys are dotted.
    import_targets_by_rel: dict[str, set[str]] = defaultdict(set)
    total_chars = 0
    total_tokens = 0

    # Import RESOLUTION stays here in the parent: it needs the whole file set
    # (``known``/``known_files``), which no single-file worker can know. Only
    # the per-file EXTRACTION was moved out.
    for (rel, spec, _text), a in zip(records, analyses):
        spec_by_lang[spec.name] = spec
        # METRIC WITHHOLDING for .daedalusignore files. Everything in this block
        # feeds a metric: units -> all three clone passes AND the symbol
        # resolver, runs -> window clusters, modules -> hotspots/module_heat.
        # Import resolution below is intentionally OUTSIDE the guard.
        if rel not in ignored:
            total_chars += a.n_chars
            # Inside the SAME withholding guard as total_chars on purpose: this
            # is the denominator of the distill ratio, and its numerator only
            # ever contains in-center files. A token total accumulated outside
            # the guard would count ignored files as part of "the repo the slice
            # replaced", inflating the reduction headline.
            total_tokens += a.n_tokens
            all_units.extend(a.units)
            # Per-file token cost is required by budgeted context planners.
            # ``total_tokens`` alone cannot tell DSS whether a candidate fits,
            # and falling back to LOC*8 makes the receipt deterministic but not
            # tokenizer-true.  Additive: existing metric keys keep their meaning.
            modules[rel] = {**a.metrics, "n_tokens": a.n_tokens}
            runs_by_file.append((rel, a.runs))
            lang_summary[spec.name]["files"] += 1
            lang_summary[spec.name]["loc"] += a.loc
        if spec.name == "python":
            # Python resolution: precise, relative-aware, and resolved against
            # the tables THIS file's own package root implies -- a center file
            # against its center-relative view, a shell file against the
            # unchanged repo-root view.
            src_mod = py_naming.name(rel)
            view = py_naming.tables_for(rel)
            for raw_tgt in resolve_python_imports(
                    a.py_imports, view.tops, view.known, src_mod):
                # Fold an alias spelling onto the file's ONE canonical name
                # before it becomes an edge, so fan_in never counts a file twice.
                tgt = view.canon.get(raw_tgt, raw_tgt)
                if tgt != src_mod:
                    dep_edges[src_mod].add(tgt)
                    tgt_rel = view.rel_by_dotted.get(tgt)
                    if tgt_rel and tgt_rel != rel:
                        import_targets_by_rel[rel].add(tgt_rel)
        else:
            # All other languages: best-effort, keyed by rel path (no dotted id).
            for raw, kind in a.raw_imports:
                if kind != "internal":
                    continue
                tgt_rel = imports_mod.resolve_internal(
                    raw, spec.name, rel, known_files, by_basename, by_dir_tail)
                if tgt_rel and tgt_rel != rel:
                    dep_edges[rel].add(tgt_rel)
                    import_targets_by_rel[rel].add(tgt_rel)

    # Reverse of ``import_targets_by_rel``: who imports ME. Built ONCE here
    # because it is index-invariant, and ``semantic_slice`` is called in a loop
    # against a single shared index (eval harness, web API) -- inverting the
    # forward map inside the slicer would redo the same O(E) scan on every
    # target. Sorted at both levels below, same as the forward map.
    import_sources_by_rel: dict[str, set[str]] = defaultdict(set)
    for src, tgts in import_targets_by_rel.items():
        for tgt in tgts:
            import_sources_by_rel[tgt].add(src)

    fan_in: dict[str, int] = defaultdict(int)
    for targets in dep_edges.values():
        for t in targets:
            fan_in[t] += 1

    # ONE memo shared by all three passes. They are independent functions over
    # the SAME unit list and each re-derived what a previous one had already
    # computed: unit_clusters computes the exact fingerprint, renamed_clusters
    # computed it again plus the abstract one, and near_clusters derived the
    # abstract one a third time. Normalization and abstraction are the two most
    # expensive operations in the scan. Scoped to this call and dropped with it
    # -- a module-level cache would leak across scans.
    memo = CloneMemo(spec_by_lang)
    unit_cl = unit_clusters(all_units, spec_by_lang, root, memo=memo)
    renamed_cl = renamed_clusters(all_units, spec_by_lang, root, memo=memo)
    near_cl = near_clusters(all_units, spec_by_lang, root, memo=memo)
    window_cl = window_clusters_from_runs(runs_by_file, root=root)

    # Stash the derived symbol resolver so consumers (slice.py) can sharpen call
    # edges without rebuilding; CodeUnits are not JSON-serializable so it lives
    # in a side cache, never in the returned (serializable) index dict.
    # Keyed by root + SCOPE, exactly like ``_INDEX_CACHE``. Keying it by root
    # alone made the two caches disagree: an unscoped build of the same root
    # overwrote the scoped resolver, and a later scoped slice hit _INDEX_CACHE
    # (so no rebuild repaired it) and resolved callees against a defs_by_file
    # that still contained SHELL units -- pulling a vendored body into a slice
    # the center was supposed to exclude. Reachable from /api/distill, where two
    # projects can share a repo_root under different centers.
    _RESOLVER_CACHE[_scope_key(root, scope)] = graph.build_resolver(
        all_units, import_targets_by_rel)

    churn = git_churn(root)
    scored = score_modules(modules, churn)

    # ADDITIVE AND GATED. An unconfigured repo with nothing to report must
    # produce a byte-identical index to before this change, so the key is
    # present only when there is something to say: a center is declared (naming
    # is center-relative and a reader deserves to know), or a name was refused a
    # binding (a withheld dependency, which must never be silent). A no-center
    # repo with no collisions -- the case every unconfigured repo is in -- gets
    # the dict it always got.
    naming_report = py_naming.describe()
    extra: dict = {}
    if scope.center or naming_report["ambiguous_count"]:
        extra["python_naming"] = {
            "mode": "center-relative" if scope.center else "repo-root",
            "package_roots": list(scope.center),
            **naming_report,
        }

    return {
        **extra,
        "root": str(root),
        "backend": backend_status(),
        "n_files": len(records) - len(ignored),
        # NEVER let exclusion be silent -- a shrunken duplication report that
        # does not say what it dropped reads exactly like a clean bill of health
        # (the same trap as report.truncated / S6's max_files ceiling).
        "ignored": {
            "count": len(ignored),
            "n_files_scanned": len(records),
            **scope.describe(),
            # Bounded sample, sorted for determinism -- the full list can be
            # tens of thousands of paths on a vendored tree.
            "sample": sorted(ignored)[:25],
            "truncated": len(ignored) > 25,
        },
        "languages": {k: v for k, v in sorted(lang_summary.items(),
                                              key=lambda kv: kv[1]["loc"], reverse=True)},
        "modules": modules,
        "dependencies": {m: sorted(t) for m, t in sorted(dep_edges.items())},
        # Same edges, but keyed rel->rel for EVERY language. ``dependencies``
        # mixes namespaces (dotted module names for Python, rel paths for the
        # rest), so it cannot be joined against ``modules``/``hotspots``. The
        # code map needs one consistent node id, and this is it.
        "import_edges": {m: sorted(t) for m, t in sorted(import_targets_by_rel.items())},
        # The same edges inverted (rel -> rels that import it). Additive; the
        # slicer needs caller identities and ``fan_in`` only carries COUNTS.
        "import_edges_reverse": {
            m: sorted(s) for m, s in sorted(import_sources_by_rel.items())},
        # Tie-break on the module name. ``fan_in`` is populated by iterating
        # dep_edges' SETS, so its insertion order varies with PYTHONHASHSEED;
        # since sorted() is stable, equal-count entries used to come out in a
        # different order on every process. Same counts, now a total order.
        "fan_in": dict(sorted(fan_in.items(), key=lambda kv: (-kv[1], kv[0]))),
        "duplication": {
            "unit_clusters": unit_cl,        # exact (Type-1) — key kept for back-compat
            "renamed_clusters": renamed_cl,  # Type-2 (renamed)
            "near_clusters": near_cl,        # Type-3 (near-miss, advisory)
            "window_clusters": window_cl,    # universal, parser-free
            # Type-3 does not cover every language it parsed. Saying so is not
            # optional: a caller who sees C files scanned and zero near-clusters
            # would otherwise read "no near-duplication in C" when the truth is
            # "C was never asked". Sorted for byte-identical output across runs.
            "near_excluded_languages": sorted(
                l for l in TYPE3_EXCLUDED_LANGUAGES if l in lang_summary),
        },
        # The (root, scope) identity of THIS index. Additive. Lets a consumer
        # holding only the index dict ask for the resolver built alongside it
        # (``resolution_context``) instead of guessing at the bare-root key.
        "scope_key": _scope_key(root, scope),
        "hotspots": scored[:15],
        # Full ranking (same pass as ``hotspots``) so the map can heat-shade
        # every node, not just the top 15.
        "module_heat": scored,
        "total_chars": total_chars,
        # Tokenizer-measured size of the same file set total_chars covers.
        # total_chars stays: it is public and other consumers read it. Absent
        # from an index dict produced by an older build or by the Rust engine,
        # which is why every reader must treat it as optional (see slice.py).
        "total_tokens": total_tokens,
        # Identity of the tokenizer that produced total_tokens (and every
        # per-file n_tokens summed into it). Additive; absent from older dumps
        # and the Rust engine. Carried so a consumer can report the denominator
        # HONESTLY: chars/4 is a heuristic, not a measurement, even though it
        # rides the same count_tokens code path, and "measured" is a lie for it.
        "tokenizer": tokens.tokenizer_name(),
    }


_RESOLVER_CACHE: dict[str, "graph.SymbolResolver"] = {}


def _scope_key(resolved: Path, scope) -> str:
    """Cache identity of an index: its root, plus the scope when one is declared.

    SINGLE SOURCE OF TRUTH for both ``_INDEX_CACHE`` and ``_RESOLVER_CACHE``.
    They are two views of one build and MUST agree; when they were keyed by
    different expressions they drifted apart and a scoped index was served with
    an unscoped resolver. An unscoped repo keeps its bare path key, so nothing
    changes for repos that never configure this.
    """
    unscoped = not scope.center and not scope.ignore
    return str(resolved) if unscoped else f"{resolved}#{scope.fingerprint}"


def resolution_context(repo_root, key: str | None = None) -> "graph.SymbolResolver | None":
    """The symbol resolver derived alongside a built index, or None if that
    index has not been built this process. Lets ``slice.py`` reuse Move-4
    resolution without recomputing the whole index.

    ``key`` is an index's ``scope_key``; pass it whenever you hold the index
    dict, so a SCOPED index gets the resolver built under that same scope
    rather than whichever build last touched the bare root. Omitting it keeps
    the historical bare-root lookup for unscoped callers.
    """
    if key is not None:
        return _RESOLVER_CACHE.get(key)
    return _RESOLVER_CACHE.get(str(Path(repo_root).resolve()))


_INDEX_CACHE: dict[str, dict] = {}
_BUILD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _build_lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _BUILD_LOCKS.setdefault(key, threading.Lock())


def cached_index(repo_root, refresh: bool = False, max_files: int = 20000,
                 center=None, ignore=None) -> dict:
    """Process-wide index cache keyed by resolved repo root. build_index is
    expensive on big repos; the first caller warms it and everyone (the web
    endpoints, the Ikarus chat brain) reuses it. ``refresh`` forces a rebuild.

    SINGLE-FLIGHT (load-bearing): the cache is only populated *after* a build
    finishes, so without a per-root lock every concurrent caller saw a cold
    cache and started its OWN full scan. The web server is a ThreadingHTTPServer,
    so switching panels mid-index spawned a second 6.8k-file scan instead of
    reusing the first -- each holding a complete index and its own tree-sitter
    parsers, which exhausted memory and took the page down. Concurrent callers
    now block on the in-flight build and share its result.
    """
    # The scope fingerprint is PART OF THE KEY: the cached index is a function
    # of the center and the ignore rules as well as the root, so changing either
    # must not hand back the index built under the old scope. (It would present
    # as the feature silently not working, and only until the next restart --
    # the worst kind of bug to chase.) An unscoped repo keeps its bare path key,
    # so nothing changes for repos that never configure this.
    resolved = Path(repo_root).resolve()
    scope = project_scope(resolved, center, ignore)
    key = _scope_key(resolved, scope)
    if not refresh and key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    with _build_lock(key):
        if refresh:
            _INDEX_CACHE.pop(key, None)
        # Re-check under the lock: whoever we queued behind may have just built
        # it, and then this call is a cache hit rather than a second scan.
        if key not in _INDEX_CACHE:
            _INDEX_CACHE[key] = build_index(repo_root, max_files=max_files,
                                           center=center, ignore=ignore)
        return _INDEX_CACHE[key]


def _hotspots(modules: dict[str, dict], churn: dict[str, int] | None = None,
              top: int = 15) -> list[dict]:
    """Top-``top`` slice of the full churn x complexity ranking."""
    return score_modules(modules, churn)[:top]


def score_modules(modules: dict[str, dict],
                  churn: dict[str, int] | None = None) -> list[dict]:
    """Complexity ranking for EVERY module, multiplied by a normalized git-churn
    factor (the CodeScene signal: rot lives where code is complex AND churning).

    Base score = long fns * 3 + guard_count + loc/50 (+ cc_max if present).
    Final score = base * (1 + churn/max_churn). If ``churn`` is empty/None the
    factor is exactly 1.0 -> behaves identically to the pre-churn ranking (no
    regression); a ``churn`` field is added to every row regardless.

    Returned whole rather than pre-trimmed so the code map can heat-shade every
    node from the same scoring pass that produces the hotspot list."""
    churn = churn or {}
    max_churn = max(churn.values()) if churn else 0
    scored = []
    for mod, m in modules.items():
        base = len(m.get("long_functions", [])) * 3 + m.get("guard_count", 0) + m["loc"] / 50
        base += m.get("cc_max", 0)
        file_churn = churn.get(mod, 0)
        churn_norm = (file_churn / max_churn) if max_churn else 0.0
        score = base * (1 + churn_norm)
        scored.append({
            "module": mod, "score": round(score, 1), "loc": m["loc"],
            "long_functions": len(m.get("long_functions", [])),
            "guard_count": m.get("guard_count", 0), "cc_max": m.get("cc_max"),
            "churn": file_churn,
        })
    scored.sort(key=lambda h: h["score"], reverse=True)
    return scored
