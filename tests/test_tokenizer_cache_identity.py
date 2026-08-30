# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tokenizer identity must be part of the per-file cache key and the reported
denominator label.

FileAnalysis.n_tokens rides the on-disk cache, and its value depends on which
tokenizer ``tokens.count_tokens`` picked at runtime (tiktoken cl100k_base when
the optional dep is installed, else the chars/4 fallback). Before this fix
``cache.file_key`` hashed ANALYSIS_VERSION + parse.py digest + rel + spec + text
but NOT the tokenizer, so installing/removing tiktoken -- which changes no source
byte -- left every file a cache HIT: the cached n_tokens (old tokenizer) summed
into ``total_tokens`` (the distill DENOMINATOR) while the slice numerator was
recounted under the NEW tokenizer. That mixed-tokenizer ratio was still stamped
``whole_repo_tokens_exact=True`` and printed "measured". These tests pin:

  * a tokenizer change is a cache MISS, never a mixed denominator;
  * the index carries the tokenizer identity, and the slice surfaces it;
  * the CLI does not call the chars/4 heuristic "measured".

Real tiktoken presence is irrelevant here: the two tokenizers are simulated by
patching ``count_tokens``/``tokenizer_name`` so the test is deterministic on any
machine. Every test pins DAEDALUS_CACHE_DIR at a temp dir it owns, so the real
user cache is never read or written.
"""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from daedalus.structcore import slice as slice_mod
from daedalus.structcore import tokens as tokens_mod
from daedalus.structcore.cache import file_key
from daedalus.structcore.index import build_index
from daedalus.structcore.slice import semantic_slice
from daedalus.structcore.tokens import tokenizer_name

MOD = '''\
"""Module {n} -- prose-heavy so two tokenizers disagree on its size."""


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


@contextlib.contextmanager
def _tokenizer(name: str, per_char_divisor: int):
    """Simulate a tokenizer: a stable identity plus a per-file count that scales
    with the divisor, so two tokenizers produce different totals for the same
    files. Patches the exact references the code under test resolves at runtime:
    perfile binds ``count_tokens`` by name; cache/index call
    ``tokens.tokenizer_name`` module-qualified."""
    def count(text: str) -> int:
        return max(1, len(text) // per_char_divisor)

    with mock.patch("daedalus.structcore.perfile.count_tokens", count), \
         mock.patch.object(tokens_mod, "tokenizer_name", lambda: name):
        yield


@contextlib.contextmanager
def _cache_dir():
    with tempfile.TemporaryDirectory() as d:
        prev = os.environ.get("DAEDALUS_CACHE_DIR")
        os.environ["DAEDALUS_CACHE_DIR"] = d
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop("DAEDALUS_CACHE_DIR", None)
            else:
                os.environ["DAEDALUS_CACHE_DIR"] = prev


class TokenizerCacheIdentityTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        _fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # -------------------------------------------------------------- cache key #
    def test_file_key_folds_tokenizer_identity(self):
        args = ("pkg/mod_0.py", "python", MOD.format(n=0))
        with _tokenizer("tok-A", 4):
            ka = file_key(*args)
        with _tokenizer("tok-B", 4):
            kb = file_key(*args)
        # Same bytes, same path, same spec -- only the tokenizer differs, and
        # that alone must change the key or the mixed-denominator bug returns.
        self.assertNotEqual(ka, kb)

    def test_tokenizer_change_is_a_miss_not_a_mixed_denominator(self):
        """THE defect. A warm cache populated under tokenizer A must NOT serve
        its n_tokens to a build running under tokenizer B: the two totals must
        differ (proving a recompute) and the warm-B total must equal a cold-B
        build (proving no stale A rows leaked into the denominator)."""
        with _cache_dir():
            with _tokenizer("tok-A", 4):
                total_a = build_index(self.root)["total_tokens"]
            # Same cache dir, same root -> same sqlite DB -> every key would HIT
            # if the tokenizer were absent from the key.
            with _tokenizer("tok-B", 2):
                total_b_warm = build_index(self.root)["total_tokens"]

        with _cache_dir():  # fresh dir == cold cache, ground truth for B
            with _tokenizer("tok-B", 2):
                total_b_cold = build_index(self.root)["total_tokens"]

        self.assertNotEqual(total_a, total_b_warm)     # recomputed, not reused
        self.assertEqual(total_b_warm, total_b_cold)   # no stale A denominator

    def test_same_tokenizer_still_hits_the_cache(self):
        """The fix must not defeat the cache for the common case: an unchanged
        tokenizer across two builds still yields a stable, reproducible total."""
        with _cache_dir():
            with _tokenizer("tok-A", 4):
                first = build_index(self.root)["total_tokens"]
                second = build_index(self.root)["total_tokens"]
        self.assertEqual(first, second)

    # ---------------------------------------------------------------- report #
    def test_index_carries_tokenizer_identity(self):
        with _cache_dir():
            idx = build_index(self.root)
        self.assertIn("tokenizer", idx)
        self.assertEqual(idx["tokenizer"], tokenizer_name())

    def test_slice_surfaces_the_denominator_tokenizer(self):
        with _cache_dir():
            idx = build_index(self.root)
        res = semantic_slice(self.root, "pkg/main.py", idx=idx)
        self.assertEqual(res["whole_repo_tokenizer"], idx["tokenizer"])

    def test_cli_does_not_call_the_heuristic_measured(self):
        """Without tiktoken the denominator is a chars/4 sum. It is consistent
        with the numerator (so whole_repo_tokens_exact stays True), but it is a
        heuristic, not a measurement -- the CLI must not print 'measured' for
        it."""
        canned = {
            "target": "pkg/main.py", "focus_file": "pkg/main.py",
            "focus_symbol": None, "included": [], "n_included": 0,
            "slice_tokens": 10, "whole_repo_tokens": 100,
            "whole_repo_tokens_exact": True,
            "whole_repo_tokenizer": "chars/4 (heuristic)",
            "reduction_pct": 90.0, "backend": {"tree_sitter": False},
            "slice_text": "",
        }
        with mock.patch.object(slice_mod, "semantic_slice", return_value=canned):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                slice_mod.main([str(self.root), "pkg/main.py"])
        out = buf.getvalue()
        self.assertNotIn("measured", out)
        self.assertIn("chars/4 (heuristic)", out)

    def test_cli_names_a_real_tokenizer_as_measured(self):
        canned = {
            "target": "pkg/main.py", "focus_file": "pkg/main.py",
            "focus_symbol": None, "included": [], "n_included": 0,
            "slice_tokens": 10, "whole_repo_tokens": 100,
            "whole_repo_tokens_exact": True,
            "whole_repo_tokenizer": "tiktoken/cl100k_base",
            "reduction_pct": 90.0, "backend": {"tree_sitter": False},
            "slice_text": "",
        }
        with mock.patch.object(slice_mod, "semantic_slice", return_value=canned):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                slice_mod.main([str(self.root), "pkg/main.py"])
        out = buf.getvalue()
        self.assertIn("measured: tiktoken/cl100k_base", out)


if __name__ == "__main__":
    unittest.main()
