"""G1-TOKENIZER-01 -- the canonical token counter reports its own status.

Every branch of ``daedalus.structcore.tokens.tokenizer_status`` is driven by a
stub ``tiktoken`` module installed with ``monkeypatch.setitem(sys.modules, ...)``
so the suite runs without the ``tokenizer`` extra. The one real-library test
uses ``pytest.importorskip`` and only runs under
``uv run --frozen --with tiktoken==0.14.0``.

Cache-only invariant: daedalus code never calls ``get_encoding`` unless the
BPE file is present with the pinned SHA-256, because ``get_encoding`` performs
an HTTP GET without a timeout on a cache miss.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
import tomllib
import types
import warnings
from pathlib import Path

import pytest

from daedalus.structcore import tokens

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_status():
    tokens._reset_tokenizer_cache()
    yield
    tokens._reset_tokenizer_cache()


def _stub_tiktoken(get_encoding):
    module = types.ModuleType("tiktoken")
    module.__version__ = "stub"
    module.get_encoding = get_encoding
    return module


class _Encoder:
    def __init__(self, ids=None, raise_exc=None):
        self._ids = ids
        self._raise = raise_exc
        self.calls = 0

    def encode(self, text, disallowed_special=()):
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        return list(self._ids)


def _must_not_fetch(name):
    raise AssertionError("must not fetch")


def _cached_bpe(monkeypatch, tmp_path: Path, *, content: bytes = b"stub-bpe") -> str:
    """Point tiktoken's cache dir at tmp_path with a file whose digest is pinned."""
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    path = tmp_path / tokens.BPE_CACHE_FILENAME
    path.write_bytes(content)
    monkeypatch.setattr(tokens, "_sha256_of_file", lambda p: tokens.BPE_FILE_SHA256)
    return str(path)


def _status_with_warnings():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        status = tokens.tokenizer_status()
    degraded = [w for w in caught if issubclass(w.category, tokens.TokenizerDegradedWarning)]
    return status, degraded


# --- not installed ---------------------------------------------------------

def test_not_installed_is_heuristic_without_warning(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    status, degraded = _status_with_warnings()
    assert status == tokens.TokenizerStatus(
        name="chars/4 (heuristic)",
        exact=False,
        library=None,
        degrade_reason="tiktoken not installed",
        probe_digest=None,
        bpe_cache_path=None,
    )
    assert degraded == []
    assert tokens.tokenizer_name() == "chars/4 (heuristic)"
    assert tokens._encoder() is None
    assert tokens.count_tokens("hello world") == max(1, len("hello world") // 4)


# --- installed, BPE not cached: never fetch -------------------------------

def test_installed_but_uncached_warns_names_path_and_never_fetches(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(_must_not_fetch))
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    expected_path = os.path.join(str(tmp_path), tokens.BPE_CACHE_FILENAME)
    status, degraded = _status_with_warnings()
    assert status.exact is False
    assert status.name == "chars/4 (heuristic)"
    assert status.library == "tiktoken stub"
    assert status.bpe_cache_path == expected_path
    assert status.probe_digest is None
    assert expected_path in status.degrade_reason
    assert tokens.FETCH_COMMAND in status.degrade_reason
    assert "import tiktoken; tiktoken.get_encoding('cl100k_base')" in status.degrade_reason
    assert len(degraded) == 1
    assert status.degrade_reason in str(degraded[0].message)
    assert tokens.count_tokens("abcdefgh") == 2


def test_cache_dir_precedence_matches_tiktoken(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(_must_not_fetch))
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "primary"))
    monkeypatch.setenv("DATA_GYM_CACHE_DIR", str(tmp_path / "secondary"))
    assert tokens._bpe_cache_path() == os.path.join(str(tmp_path / "primary"), tokens.BPE_CACHE_FILENAME)
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR")
    assert tokens._bpe_cache_path() == os.path.join(str(tmp_path / "secondary"), tokens.BPE_CACHE_FILENAME)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR")
    import tempfile

    assert tokens._bpe_cache_path() == os.path.join(
        tempfile.gettempdir(), "data-gym-cache", tokens.BPE_CACHE_FILENAME
    )
    assert tokens.BPE_CACHE_FILENAME == hashlib.sha1(tokens.BPE_URL.encode(), usedforsecurity=False).hexdigest()


def test_empty_cache_dir_means_every_load_would_fetch_so_refuse(monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(_must_not_fetch))
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "")
    status, degraded = _status_with_warnings()
    assert status.exact is False
    assert status.bpe_cache_path is None
    assert "cache disabled" in status.degrade_reason
    assert len(degraded) == 1


def test_cached_file_with_wrong_hash_is_refused_without_fetch(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(_must_not_fetch))
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    path = tmp_path / tokens.BPE_CACHE_FILENAME
    path.write_bytes(b"not the real bpe file")
    status, degraded = _status_with_warnings()
    assert status.exact is False
    assert status.bpe_cache_path == str(path)
    assert hashlib.sha256(b"not the real bpe file").hexdigest() in status.degrade_reason
    assert tokens.BPE_FILE_SHA256 in status.degrade_reason
    assert tokens.FETCH_COMMAND in status.degrade_reason
    assert len(degraded) == 1


# --- installed and cached, but the encoder is unusable --------------------

def test_get_encoding_raising_yields_heuristic_with_exception_type(monkeypatch, tmp_path):
    def boom(name):
        raise ValueError("Hash mismatch for data downloaded")

    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(boom))
    path = _cached_bpe(monkeypatch, tmp_path)
    status, degraded = _status_with_warnings()
    assert status.exact is False
    assert status.bpe_cache_path == path
    assert status.degrade_reason == "ValueError: Hash mismatch for data downloaded"
    assert len(degraded) == 1
    assert tokens._encoder() is None
    assert tokens.count_tokens("x" * 40) == 10


def test_probe_mismatch_yields_heuristic_and_warning(monkeypatch, tmp_path):
    wrong = _Encoder(ids=[1, 2, 3])
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(lambda name: wrong))
    _cached_bpe(monkeypatch, tmp_path)
    status, degraded = _status_with_warnings()
    assert status.exact is False
    assert status.name == "chars/4 (heuristic)"
    assert status.probe_digest is None
    assert status.degrade_reason.startswith("probe mismatch")
    assert "[1, 2, 3]" in status.degrade_reason
    assert len(degraded) == 1
    assert tokens._encoder() is None
    assert wrong.calls == 1
    # the mismatching encoder is never used for counting
    assert tokens.count_tokens("abcdefgh") == 2
    assert wrong.calls == 1


def test_probe_encode_raising_yields_heuristic(monkeypatch, tmp_path):
    broken = _Encoder(raise_exc=RuntimeError("regex engine missing"))
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(lambda name: broken))
    _cached_bpe(monkeypatch, tmp_path)
    status, degraded = _status_with_warnings()
    assert status.exact is False
    assert status.degrade_reason == "probe encode failed: RuntimeError: regex engine missing"
    assert len(degraded) == 1


# --- exact -----------------------------------------------------------------

def test_probe_match_is_exact_with_probe_digest(monkeypatch, tmp_path):
    good = _Encoder(ids=tokens.PROBE_IDS)
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(lambda name: good))
    path = _cached_bpe(monkeypatch, tmp_path)
    status, degraded = _status_with_warnings()
    expected_digest = hashlib.sha256(
        json.dumps(list(tokens.PROBE_IDS), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert status == tokens.TokenizerStatus(
        name="tiktoken/cl100k_base",
        exact=True,
        library="tiktoken stub",
        degrade_reason=None,
        probe_digest=expected_digest,
        bpe_cache_path=path,
    )
    assert degraded == []
    assert tokens.tokenizer_name() == "tiktoken/cl100k_base"
    assert tokens._encoder() is good
    assert tokens.count_tokens("anything") == len(tokens.PROBE_IDS)
    assert tokens.tokenizer_status() is status  # cached object
    assert status.as_dict()["exact"] is True
    assert status.as_dict()["heuristic_fallback_calls"] == status.heuristic_fallback_calls


def test_heuristic_fallback_counter_is_live_and_monotone(monkeypatch, tmp_path):
    good = _Encoder(ids=tokens.PROBE_IDS)
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(lambda name: good))
    _cached_bpe(monkeypatch, tmp_path)
    status = tokens.tokenizer_status()
    assert status.exact is True
    before = status.heuristic_fallback_calls
    assert tokens.count_tokens("ok") == len(tokens.PROBE_IDS)
    assert status.heuristic_fallback_calls == before
    good._raise = RuntimeError("encode exploded mid-run")
    assert tokens.count_tokens("abcdefgh") == 2  # never raises
    assert tokens.count_tokens("abcdefgh") == 2
    assert status.heuristic_fallback_calls == before + 2
    assert tokens.tokenizer_status().heuristic_fallback_calls == before + 2
    assert tokens.tokenizer_status().exact is True  # status is measured, not re-derived per call
    tokens._reset_tokenizer_cache()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", tokens.TokenizerDegradedWarning)  # re-probe sees the broken encoder
        assert tokens.tokenizer_status().heuristic_fallback_calls == before + 2  # reset keeps the count


def test_warning_fires_once_per_cache_state(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(_must_not_fetch))
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tokens.tokenizer_status()
        tokens.tokenizer_status()
        tokens.count_tokens("abc")
        tokens.tokenizer_name()
    assert len([w for w in caught if issubclass(w.category, tokens.TokenizerDegradedWarning)]) == 1
    tokens._reset_tokenizer_cache()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tokens.tokenizer_status()
    assert len([w for w in caught if issubclass(w.category, tokens.TokenizerDegradedWarning)]) == 1


@pytest.mark.parametrize(
    "scenario",
    ["not_installed", "uncached", "get_encoding_raises", "probe_mismatch", "encode_raises"],
)
def test_count_tokens_never_raises(monkeypatch, tmp_path, scenario):
    if scenario == "not_installed":
        monkeypatch.setitem(sys.modules, "tiktoken", None)
    elif scenario == "uncached":
        monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(_must_not_fetch))
        monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    elif scenario == "get_encoding_raises":
        def boom(name):
            raise OSError("cache unreadable")

        monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(boom))
        _cached_bpe(monkeypatch, tmp_path)
    elif scenario == "probe_mismatch":
        monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(lambda n: _Encoder(ids=[9])))
        _cached_bpe(monkeypatch, tmp_path)
    else:
        enc = _Encoder(ids=tokens.PROBE_IDS)
        monkeypatch.setitem(sys.modules, "tiktoken", _stub_tiktoken(lambda n: enc))
        _cached_bpe(monkeypatch, tmp_path)
        tokens.tokenizer_status()
        enc._raise = RuntimeError("encode raised")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", tokens.TokenizerDegradedWarning)
        assert tokens.count_tokens("") == 1
        assert tokens.count_tokens("abcdefgh") == 2
        assert tokens.count_tokens("x" * 4000) == 1000


# --- real library (only under the tokenizer extra) -------------------------

def test_real_tiktoken_is_exact_when_bpe_is_cached_on_this_host(monkeypatch):
    tiktoken = pytest.importorskip("tiktoken")
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    path = tokens._bpe_cache_path()
    if not os.path.isfile(path):
        pytest.skip(f"cl100k_base BPE file not cached at {path}; run {tokens.FETCH_COMMAND} once")
    status, degraded = _status_with_warnings()
    assert status.exact is True, status.degrade_reason
    assert status.library == f"tiktoken {tiktoken.__version__}"
    assert status.bpe_cache_path == path
    assert degraded == []
    assert tokens.count_tokens("hello world") == 2
    assert tokens._encoder().encode("hello world", disallowed_special=()) == [15339, 1917]
    assert tokens.count_tokens(tokens.PROBE_TEXT) == len(tokens.PROBE_IDS)


# --- wiring ----------------------------------------------------------------

def test_harness_reexports_the_canonical_status():
    from daedalus.eval import harness

    assert harness.count_tokens is tokens.count_tokens
    assert harness.tokenizer_name is tokens.tokenizer_name
    assert harness.tokenizer_status is tokens.tokenizer_status


def test_tokenizer_extra_is_pinned_and_test_extra_stays_bpe_free():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    assert extras["tokenizer"] == ["tiktoken==0.14.0"]
    assert not any("tiktoken" in dep for dep in extras["test"])
    assert not any("tiktoken" in dep for dep in pyproject["project"]["dependencies"])


def test_import_emits_no_warning_and_does_no_work():
    code = (
        "import warnings, sys\n"
        "warnings.simplefilter('error')\n"
        "sys.modules['tiktoken'] = None\n"
        "import daedalus.structcore.tokens as t\n"
        "assert t.tokenizer_status.cache_info().currsize == 0\n"
        "assert t._ENCODER is None\n"
        "print('clean-import')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "clean-import"


def test_module_is_a_leaf_without_daedalus_imports():
    source = (ROOT / "daedalus" / "structcore" / "tokens.py").read_text(encoding="utf-8")
    assert "from daedalus" not in source and "from ." not in source
    assert "import tiktoken" in source  # lazy, inside the probe only
    module = importlib.import_module("daedalus.structcore.tokens")
    assert "tiktoken" not in vars(module)
