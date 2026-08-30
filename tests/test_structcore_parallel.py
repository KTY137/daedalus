# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Structural scan: parallel per-file pass + persistent cache.

The bar for this work is DETERMINISM, not speed: the parallel and cached paths
must produce byte-identical indexes to the serial one. ``all_units`` order is
load-bearing (the clone passes consume it positionally), and pool completion
order is arbitrary, so order preservation is asserted explicitly rather than
assumed.

Every test pins DAEDALUS_CACHE_DIR at a temp dir so the real user cache is never
read or written.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from daedalus.structcore.cache import FileCache, file_key
from daedalus.structcore.clones import (window_clusters, window_clusters_from_runs,
                                        window_runs)
from daedalus.structcore.index import build_index
from daedalus.structcore.languages import spec_for
from daedalus.structcore.parse import (extract_units, python_import_records,
                                       python_imports, python_units_and_imports,
                                       resolve_python_imports)

FN = '''\
def handle_{n}(self, payload):
    if payload is None:
        raise ValueError("empty")
    try:
        total = 0
        for item in payload:
            total += item.weight * {n}
        return total
    except KeyError:
        return None
'''

JS = '''\
// module {n}
import {{ helper }} from './helper.js';

export function render{n}(state) {{
  const label = state.label || 'unknown';
  const color = state.ok ? 'green' : 'red';
  const icon = state.busy ? 'spinner' : 'dot';
  return helper(`${{icon}}-${{color}}`, label);
}}
'''


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _corpus(root: Path, n_py: int = 24, n_js: int = 8) -> None:
    """Enough files to make the parallel path meaningful, with real clones,
    imports and cross-file duplication so every index field is populated."""
    for i in range(n_py):
        body = FN.format(n=i % 5)  # repeats -> exact + renamed clone clusters
        _write(root, f"pkg/mod_{i}.py",
               f"from pkg.mod_{(i + 1) % n_py} import handle_{(i + 1) % 5}\n\n"
               f"class C{i}:\n    " + body.replace("\n", "\n    ").rstrip() + "\n")
    for i in range(n_js):
        _write(root, f"web/comp_{i}.js", JS.format(n=i % 3))
    _write(root, "web/helper.js", "export function helper(a, b) { return a + b; }\n")


class _CacheDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cache = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._prev = {k: os.environ.get(k) for k in
                      ("DAEDALUS_CACHE_DIR", "DAEDALUS_NO_CACHE",
                       "DAEDALUS_SCAN_MIN_PARALLEL", "DAEDALUS_SCAN_WORKERS")}
        os.environ["DAEDALUS_CACHE_DIR"] = self._cache.name

    def tearDown(self):
        for k, v in self._prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()
        self._cache.cleanup()

    @staticmethod
    def _canon(idx: dict) -> str:
        """Order-preserving serialization: fan_in/modules/hotspots carry meaning
        in their ORDER, so sort_keys would hide a real ordering regression."""
        return json.dumps(idx, sort_keys=False, default=str)


class ParallelDeterminismTest(_CacheDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        _corpus(self.root)

    def test_parallel_index_is_byte_identical_to_serial(self):
        os.environ["DAEDALUS_NO_CACHE"] = "1"
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "999999"  # force serial
        serial = build_index(self.root)
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "2"       # force the pool
        parallel = build_index(self.root)
        self.assertEqual(self._canon(serial), self._canon(parallel))

    def test_parallel_preserves_all_units_order(self):
        """Cluster membership depends on all_units order, and pool completion
        order is arbitrary -- so results must be reassembled by input index."""
        os.environ["DAEDALUS_NO_CACHE"] = "1"
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "999999"
        serial = build_index(self.root)
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "2"
        parallel = build_index(self.root)
        self.assertEqual(list(serial["modules"]), list(parallel["modules"]))
        for key in ("unit_clusters", "renamed_clusters", "near_clusters",
                    "window_clusters"):
            self.assertEqual(serial["duplication"][key],
                             parallel["duplication"][key], key)

    def test_fan_in_order_is_total(self):
        """fan_in is filled by iterating SETS, so its insertion order varies
        with PYTHONHASHSEED; the final sort must therefore break ties on name."""
        idx = build_index(self.root)
        fan = idx["fan_in"]
        self.assertEqual(list(fan),
                         [k for k, _ in sorted(fan.items(), key=lambda kv: (-kv[1], kv[0]))])


class AmbiguousImportDeterminismTest(_CacheDirMixin, unittest.TestCase):
    """Repeated basenames across directories (Marlin's HAL/AVR/fastio.h vs
    HAL/DUE/fastio.h vs ...) are resolved by "first match in by_basename wins".
    Those lists used to be built by iterating a SET of paths, so the winner --
    and therefore dependencies/import_edges/fan_in -- changed with
    PYTHONHASHSEED. Build order must be lexicographic, not hash order."""

    def setUp(self):
        super().setUp()
        for hal in ("AVR", "DUE", "ESP32", "SAMD21", "STM32"):
            _write(self.root, f"HAL/{hal}/fastio.h",
                   f"#pragma once\n// {hal} fastio\nvoid set_pin_{hal}(int p);\n")
            _write(self.root, f"HAL/{hal}/HAL.cpp",
                   f'#include "fastio.h"\n#include "../shared/Marduino.h"\n'
                   f"void boot_{hal}(void) {{ set_pin_{hal}(1); }}\n")
        _write(self.root, "HAL/shared/Marduino.h", "#pragma once\nint marduino(void);\n")

    def test_resolution_is_stable_across_lookup_table_order(self):
        import daedalus.structcore.index as idxmod

        os.environ["DAEDALUS_NO_CACHE"] = "1"
        first = build_index(self.root)

        # Re-run with the file set enumerated in reverse: a correct build sorts
        # its lookup tables, so the resolved edges must not move.
        real_collect = idxmod._collect
        idxmod._collect = lambda root, mx: list(reversed(real_collect(root, mx)))
        try:
            flipped = build_index(self.root)
        finally:
            idxmod._collect = real_collect

        self.assertEqual(first["dependencies"], flipped["dependencies"])
        self.assertEqual(first["import_edges"], flipped["import_edges"])
        self.assertEqual(first["fan_in"], flipped["fan_in"])
        self.assertEqual(list(first["fan_in"]), list(flipped["fan_in"]))


class PersistentCacheTest(_CacheDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        _corpus(self.root, n_py=6, n_js=3)

    def test_warm_cache_matches_cold(self):
        cold = build_index(self.root)
        warm = build_index(self.root)          # second build: all cache hits
        self.assertEqual(self._canon(cold), self._canon(warm))

    def test_cache_actually_stores_entries(self):
        build_index(self.root)
        files = list(Path(self._cache.name).glob("*.sqlite"))
        self.assertTrue(files, "expected a sqlite cache file to be written")

    def test_edit_invalidates_that_file(self):
        """The nightmare case: a stale cache silently reporting old code health.
        The key is content-addressed, so an edit cannot hit the old entry."""
        before = build_index(self.root)
        self.assertEqual(before["modules"]["pkg/mod_0.py"]["n_functions"], 1)
        _write(self.root, "pkg/mod_0.py",
               "def a():\n    return 1\n\n\ndef b():\n    return 2\n")
        after = build_index(self.root)
        self.assertEqual(after["modules"]["pkg/mod_0.py"]["n_functions"], 2)
        self.assertNotEqual(before["modules"]["pkg/mod_0.py"]["loc"],
                            after["modules"]["pkg/mod_0.py"]["loc"])

    def test_cache_survives_mtime_touch_without_edit(self):
        """Content-keyed, not mtime-keyed: rewriting identical bytes is a hit
        and must not change the result."""
        first = build_index(self.root)
        p = self.root / "pkg/mod_1.py"
        p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(p, (0, 0))
        self.assertEqual(self._canon(first), self._canon(build_index(self.root)))

    def test_disabled_cache_writes_nothing(self):
        os.environ["DAEDALUS_NO_CACHE"] = "1"
        build_index(self.root)
        self.assertEqual(list(Path(self._cache.name).glob("*.sqlite")), [])

    def test_analysis_version_is_part_of_the_key(self):
        """Bumping ANALYSIS_VERSION must invalidate, or a semantics change would
        be masked by entries computed under the old rules."""
        import daedalus.structcore.cache as cache_mod

        k1 = file_key("a.py", "python", "x = 1\n")
        orig = cache_mod.ANALYSIS_VERSION
        try:
            cache_mod.ANALYSIS_VERSION = orig + "-next"
            self.assertNotEqual(k1, file_key("a.py", "python", "x = 1\n"))
        finally:
            cache_mod.ANALYSIS_VERSION = orig

    def test_key_separates_identical_bytes_at_different_paths(self):
        """Analysis embeds the module path (CodeUnit.module), so same bytes at
        two paths are two different results."""
        self.assertNotEqual(file_key("a/x.py", "python", "y = 1\n"),
                            file_key("b/x.py", "python", "y = 1\n"))

    def test_partial_invalidation_matches_a_clean_build(self):
        """The realistic case, and the riskiest one: SOME files changed, so the
        result list is filled from two sources (cache hits and freshly computed
        misses) interleaved. If reassembly were by completion order rather than
        by input index, this is where it would show up."""
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "2"  # force the pool for misses
        build_index(self.root)                          # warm the cache
        for i in (0, 3, 5):                             # scatter the edits
            _write(self.root, f"pkg/mod_{i}.py",
                   f"def changed_{i}(x):\n    return x * {i}\n")
        mixed = build_index(self.root)

        os.environ["DAEDALUS_NO_CACHE"] = "1"
        clean = build_index(self.root)
        self.assertEqual(self._canon(clean), self._canon(mixed))

    def test_cache_directory_is_bounded(self):
        """Cache DBs are named by a hash of the repo root, so vanished roots
        (throwaway test repos, deleted checkouts) leave orphans nothing reopens.
        The directory must stay bounded rather than grow on every run."""
        import daedalus.structcore.cache as cache_mod

        d = Path(self._cache.name)
        d.mkdir(parents=True, exist_ok=True)
        for i in range(40):
            (d / f"idx-{i:016x}.sqlite").write_bytes(b"")
        build_index(self.root)
        self.assertLessEqual(len(list(d.glob("idx-*.sqlite"))),
                             cache_mod._MAX_CACHE_FILES)

    def test_corrupt_cache_degrades_to_recompute(self):
        good = build_index(self.root)
        db = next(Path(self._cache.name).glob("*.sqlite"))
        db.write_bytes(b"not a sqlite database at all")
        self.assertEqual(self._canon(good), self._canon(build_index(self.root)))


class RefactorEquivalenceTest(unittest.TestCase):
    """The optimization split three functions apart; each split must be a
    behaviour-preserving factoring of the original."""

    SRC = ("import os\n"
           "from pkg.util import helper\n"
           "from . import sibling\n"
           "from ..parent import thing\n\n"
           "def outer(a):\n"
           "    def inner(b):\n"
           "        return b + 1\n"
           "    return inner(a)\n\n"
           "async def fetch(u):\n"
           "    return await u\n")

    def test_single_parse_yields_same_units_as_extract_units(self):
        units, _ = python_units_and_imports("pkg/m.py", self.SRC)
        self.assertEqual(units, extract_units("pkg/m.py", self.SRC, spec_for("m.py")))

    def test_split_import_pipeline_matches_original(self):
        tops, known = {"pkg"}, {"pkg.util", "pkg.sibling"}
        for src_dotted in ("pkg.sub.m", "pkg.m", ""):
            self.assertEqual(
                resolve_python_imports(python_import_records(self.SRC), tops, known,
                                       src_dotted),
                python_imports(self.SRC, tops, known, src_dotted), src_dotted)

    def test_single_parse_imports_match_standalone_extraction(self):
        _, recs = python_units_and_imports("pkg/m.py", self.SRC)
        self.assertEqual(recs, python_import_records(self.SRC))

    def test_syntax_error_degrades_like_the_original(self):
        bad = "def broken(:\n  pass\n"
        self.assertEqual(python_units_and_imports("b.py", bad), ([], []))

    def test_window_split_matches_single_pass(self):
        spec = spec_for("a.js")
        files = [(f"w/{i}.js", JS.format(n=i % 2), spec) for i in range(6)]
        self.assertEqual(
            window_clusters(files, root=None),
            window_clusters_from_runs([(rel, window_runs(t, s)) for rel, t, s in files],
                                      root=None))

    def test_window_runs_are_first_encounter_ordered_and_deduped(self):
        spec = spec_for("a.py")
        text = "".join(f"line_{i} = {i}\n" for i in range(10)) * 2
        runs = window_runs(text, spec)
        self.assertEqual(len(runs), len(set(runs)), "runs must be deduped")
        self.assertEqual(runs, window_runs(text, spec), "order must be stable")


class SingleFlightWithPoolTest(_CacheDirMixin, unittest.TestCase):
    """The process pool runs INSIDE cached_index's single-flight lock. Prove the
    two compose: concurrent callers still share one build (no second 6.8k-file
    scan) and the pool cannot deadlock while the lock is held."""

    def setUp(self):
        super().setUp()
        _corpus(self.root, n_py=10, n_js=3)
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "2"  # force the pool

    def test_concurrent_callers_share_one_pooled_build(self):
        import threading

        import daedalus.structcore.index as idxmod

        idxmod._INDEX_CACHE.pop(str(self.root.resolve()), None)
        real, calls = idxmod.build_index, []

        def counting(*a, **kw):
            calls.append(1)
            return real(*a, **kw)

        idxmod.build_index = counting
        results, errors = [], []

        def worker():
            try:
                results.append(idxmod.cached_index(self.root))
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

        try:
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=180)
            self.assertFalse([t for t in threads if t.is_alive()],
                             "build deadlocked under the single-flight lock")
        finally:
            idxmod.build_index = real
            idxmod._INDEX_CACHE.pop(str(self.root.resolve()), None)

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1, "single-flight regressed: >1 build ran")
        self.assertEqual(len(results), 4)
        for r in results[1:]:
            self.assertIs(r, results[0], "callers did not share one index")


class SerialFallbackTest(_CacheDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        _corpus(self.root, n_py=6, n_js=2)

    def test_zero_workers_falls_back_to_serial(self):
        """A pool is an optimization; if it cannot be used the build must still
        produce the identical index, just slower."""
        os.environ["DAEDALUS_NO_CACHE"] = "1"
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "1"
        os.environ["DAEDALUS_SCAN_WORKERS"] = "0"
        forced_serial = build_index(self.root)
        os.environ["DAEDALUS_SCAN_MIN_PARALLEL"] = "999999"
        os.environ.pop("DAEDALUS_SCAN_WORKERS")
        self.assertEqual(self._canon(forced_serial), self._canon(build_index(self.root)))


if __name__ == "__main__":
    unittest.main()
