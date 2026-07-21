"""The honest denominator: reduction_pct must not divide a real token count by
a fake one.

``slice_tokens`` has always been tokenizer-exact (tiktoken cl100k_base when
installed). ``whole_repo_tokens`` was ``total_chars // 4`` -- a heuristic -- so
the flagship distillation headline was a measured numerator over an estimated
denominator. These tests pin the fix: the index carries a real ``total_tokens``,
slice uses it, and it says so via ``whole_repo_tokens_exact``.

The staleness test is the important one. A per-file field that rides the disk
cache can be reintroduced as zero by a row written before the field existed --
which would read as "these files contribute nothing to the repo", i.e. a
silently inflated reduction %. This is the failure class the cache's own
docstring was written about, so it gets an explicit test rather than trust in a
remembered version bump.

Every test pins DAEDALUS_CACHE_DIR at a temp dir so the real user cache is never
read or written.
"""
import os
import tempfile
import unittest
import zlib
import json
from pathlib import Path

from daedalus.structcore.cache import FileCache, _encode, file_key
from daedalus.structcore.index import build_index
from daedalus.structcore.perfile import analyze_file
from daedalus.structcore.languages import spec_for
from daedalus.structcore.slice import _whole_repo_tokens, semantic_slice
from daedalus.structcore.tokens import _encoder

HAS_TIKTOKEN = _encoder() is not None

MOD = '''\
"""Module {n} -- deliberately prose-heavy, because chars/4 and a real BPE
tokenizer disagree most on English text and identifiers, which is exactly the
gap this measurement was hiding."""


def compute_{n}(payload):
    total = 0
    for item in payload:
        total += item.weight * {n}
    return total
'''

MAIN = '''\
from pkg.mod_0 import compute_0
from pkg.mod_1 import compute_1


def run(payload):
    return compute_0(payload) + compute_1(payload)
'''


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> None:
    _write(root, "pkg/__init__.py", "")
    for n in range(3):
        _write(root, f"pkg/mod_{n}.py", MOD.format(n=n))
    _write(root, "pkg/main.py", MAIN)


class HonestDenominatorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._cache = tempfile.TemporaryDirectory()
        cls._prev_cache = os.environ.get("DAEDALUS_CACHE_DIR")
        os.environ["DAEDALUS_CACHE_DIR"] = cls._cache.name
        cls.root = Path(cls._tmp.name)
        _fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        if cls._prev_cache is None:
            os.environ.pop("DAEDALUS_CACHE_DIR", None)
        else:
            os.environ["DAEDALUS_CACHE_DIR"] = cls._prev_cache
        cls._cache.cleanup()
        cls._tmp.cleanup()

    # ------------------------------------------------------------------ index #
    def test_index_carries_total_tokens(self):
        idx = build_index(self.root)
        self.assertIn("total_tokens", idx)
        self.assertGreater(idx["total_tokens"], 0)
        # total_chars stays: it is public and other consumers read it.
        self.assertIn("total_chars", idx)
        self.assertGreater(idx["total_chars"], 0)

    @unittest.skipUnless(HAS_TIKTOKEN, "tiktoken not installed")
    def test_measured_denominator_differs_from_the_heuristic(self):
        """The size of the lie. If these were equal the fix would be cosmetic."""
        idx = build_index(self.root)
        self.assertNotEqual(idx["total_tokens"], idx["total_chars"] // 4)

    def test_total_tokens_is_the_sum_of_per_file_counts(self):
        """Derived, not maintained: the index total must be reproducible by
        re-analyzing the same files, or the two can drift apart unnoticed."""
        idx = build_index(self.root)
        expect = 0
        for rel in sorted(idx["modules"]):
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            expect += analyze_file(rel, text, spec_for(rel), False).n_tokens
        self.assertEqual(idx["total_tokens"], expect)

    # ------------------------------------------------------------------ slice #
    def test_slice_uses_the_measured_denominator(self):
        idx = build_index(self.root)
        res = semantic_slice(self.root, "pkg/main.py", idx=idx)
        self.assertEqual(res["whole_repo_tokens"], idx["total_tokens"])
        self.assertTrue(res["whole_repo_tokens_exact"])
        self.assertLess(res["slice_tokens"], res["whole_repo_tokens"])

    def test_falls_back_when_the_index_predates_the_field(self):
        """An older JSON dump, or the Rust engine (structcore-rs emits
        total_chars only). Degraded is allowed; degraded-and-silent is not."""
        idx = build_index(self.root)
        legacy = dict(idx)
        legacy.pop("total_tokens")
        res = semantic_slice(self.root, "pkg/main.py", idx=legacy)
        self.assertEqual(res["whole_repo_tokens"], max(1, idx["total_chars"] // 4))
        self.assertFalse(res["whole_repo_tokens_exact"])

    def test_exactness_flag_is_truthful_both_ways(self):
        idx = build_index(self.root)
        self.assertEqual(_whole_repo_tokens(idx), (idx["total_tokens"], True))
        legacy = {"total_chars": idx["total_chars"]}
        self.assertEqual(_whole_repo_tokens(legacy),
                         (max(1, idx["total_chars"] // 4), False))
        # No size information at all still yields a usable (never zero) divisor.
        self.assertEqual(_whole_repo_tokens({}), (1, False))

    def test_heuristic_path_still_behaves(self):
        """Without tiktoken the ratio is still meaningful -- both sides are then
        chars/4 and the reduction stays a real comparison, just coarser. Asserted
        unconditionally so a tiktoken-less machine is covered too."""
        idx = build_index(self.root)
        whole, exact = _whole_repo_tokens({"total_chars": idx["total_chars"]})
        self.assertGreater(whole, 0)
        self.assertFalse(exact)

    # ------------------------------------------------------------------ cache #
    def test_cached_rebuild_reports_the_same_total_tokens(self):
        """THE staleness test. The second build is served from the disk cache; if
        the cached row did not carry n_tokens the denominator would silently
        collapse and every reduction % would jump."""
        first = build_index(self.root)
        second = build_index(self.root)
        self.assertGreater(second["total_tokens"], 0)
        self.assertEqual(first["total_tokens"], second["total_tokens"])
        self.assertEqual(first["total_chars"], second["total_chars"])

    def test_cache_roundtrips_the_token_count(self):
        rel = "pkg/mod_0.py"
        text = (self.root / rel).read_text(encoding="utf-8")
        a = analyze_file(rel, text, spec_for(rel), False)
        self.assertGreater(a.n_tokens, 0)
        with FileCache(self.root) as fc:
            k = file_key(rel, "python", text)
            fc.put_many([(k, a)])
            got = fc.get_many([k])
        self.assertEqual(got[k].n_tokens, a.n_tokens)

    def test_a_row_without_the_field_is_a_miss_not_a_zero(self):
        """Belt and braces behind ANALYSIS_VERSION: even if a pre-fix row were
        reachable under a current key, decoding must FAIL (-> recompute) rather
        than default the token count to something plausible-looking."""
        rel = "pkg/mod_1.py"
        text = (self.root / rel).read_text(encoding="utf-8")
        a = analyze_file(rel, text, spec_for(rel), False)
        doc = json.loads(zlib.decompress(_encode(a)).decode("utf-8"))
        doc.pop("n_tokens")
        legacy_blob = zlib.compress(json.dumps(doc).encode("utf-8"), 1)
        k = "legacy-shaped-row"
        with FileCache(self.root) as fc:
            if fc.conn is None:
                self.skipTest("sqlite cache unavailable")
            fc.conn.execute(
                "INSERT OR REPLACE INTO files (key, schema, payload) VALUES (?,?,?)",
                (k, 1, legacy_blob))
            fc.conn.commit()
            self.assertEqual(fc.get_many([k]), {})


if __name__ == "__main__":
    unittest.main()
