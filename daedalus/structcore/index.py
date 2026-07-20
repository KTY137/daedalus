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

from .languages import LanguageSpec, spec_for
from .parse import CodeUnit, resolve_python_imports, tree_sitter_available
from .metrics import lizard_available
from .clones import (unit_clusters, window_clusters_from_runs, renamed_clusters,
                     near_clusters)
from .perfile import FileAnalysis, analyze_chunk, analyze_file
from .cache import FileCache, file_key
from . import imports as imports_mod
from . import graph
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

    known = {_py_dotted(rel) for rel, spec, _ in records if spec.name == "python"}
    internal_tops = {d.split(".")[0] for d in known}
    rel_by_dotted = {_py_dotted(rel): rel for rel, spec, _ in records if spec.name == "python"}

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
            all_units.extend(a.units)
            modules[rel] = a.metrics
            runs_by_file.append((rel, a.runs))
            lang_summary[spec.name]["files"] += 1
            lang_summary[spec.name]["loc"] += a.loc
        if spec.name == "python":
            # Python resolution stays exactly as-is (precise, relative-aware).
            src_mod = _py_dotted(rel)
            for tgt in resolve_python_imports(a.py_imports, internal_tops, known, src_mod):
                if tgt != src_mod:
                    dep_edges[src_mod].add(tgt)
                    tgt_rel = rel_by_dotted.get(tgt)
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

    fan_in: dict[str, int] = defaultdict(int)
    for targets in dep_edges.values():
        for t in targets:
            fan_in[t] += 1

    unit_cl = unit_clusters(all_units, spec_by_lang, root)
    renamed_cl = renamed_clusters(all_units, spec_by_lang, root)
    near_cl = near_clusters(all_units, spec_by_lang, root)
    window_cl = window_clusters_from_runs(runs_by_file, root=root)

    # Stash the derived symbol resolver so consumers (slice.py) can sharpen call
    # edges without rebuilding; CodeUnits are not JSON-serializable so it lives
    # in a side cache, never in the returned (serializable) index dict.
    _RESOLVER_CACHE[str(root)] = graph.build_resolver(all_units, import_targets_by_rel)

    churn = git_churn(root)
    scored = score_modules(modules, churn)

    return {
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
        },
        "hotspots": scored[:15],
        # Full ranking (same pass as ``hotspots``) so the map can heat-shade
        # every node, not just the top 15.
        "module_heat": scored,
        "total_chars": total_chars,
    }


_RESOLVER_CACHE: dict[str, "graph.SymbolResolver"] = {}


def resolution_context(repo_root) -> "graph.SymbolResolver | None":
    """The symbol resolver derived for a root by the last ``build_index`` call,
    or None if that root has not been indexed this process. Lets ``slice.py``
    reuse Move-4 resolution without recomputing the whole index."""
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
    unscoped = not scope.center and not scope.ignore
    key = str(resolved) if unscoped else f"{resolved}#{scope.fingerprint}"
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
