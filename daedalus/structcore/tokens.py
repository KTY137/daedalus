"""tokens.py — token counting for the distill benchmark.

Uses ``tiktoken`` (optional ``tokenizer`` extra) for a real BPE count when it
is installed **and** its ``cl100k_base`` BPE file is already cached on this
host; otherwise a ``chars/4`` heuristic. Degrades visibly: the reduction
*ratio* is meaningful either way, and becomes tokenizer-exact when tiktoken is
present. This is what makes the "92.8% smaller" claim rigorous rather than a
hand-wave.

Status contract (packet G1-TOKENIZER-01):

* ``tokenizer_status()`` reports *measured* exactness. ``exact`` is ``True``
  only after the loaded encoder reproduced the pinned probe ids
  (``PROBE_IDS``) for ``PROBE_TEXT``; every other outcome is the heuristic
  with a ``degrade_reason``.
* Daedalus never downloads the BPE file. ``tiktoken.get_encoding`` performs an
  HTTP GET without a timeout when its cache misses (and deletes plus re-fetches
  a cached file whose hash mismatches), so this module resolves the cache path
  exactly like ``tiktoken.load.read_file_cached`` (env precedence
  ``TIKTOKEN_CACHE_DIR`` > ``DATA_GYM_CACHE_DIR`` > ``<tempdir>/data-gym-cache``,
  key ``sha1(url)``), checks the file and its SHA-256 itself, and only then
  calls ``get_encoding``. A missing or mismatching file yields the heuristic
  plus one ``TokenizerDegradedWarning`` naming the path and the one-shot fetch
  command ``FETCH_COMMAND`` (which the owner runs, not Daedalus).
* ``tiktoken`` not installed is a documented optional dependency: heuristic
  status, ``degrade_reason == "tiktoken not installed"``, no warning.
* ``count_tokens`` never raises. When an encoder exists but ``encode`` raises,
  the call falls back to ``chars/4`` and increments a module-level monotone
  counter that ``TokenizerStatus.heuristic_fallback_calls`` reads live (it is
  a property, not a frozen field, so a consumer can snapshot it before and
  after a run through the same cached status object).
* ``tokenizer_status`` is ``lru_cache(1)`` and computed lazily; importing this
  module does no work and emits no warning. ``_reset_tokenizer_cache()`` is a
  test-only helper; after a reset the warning fires again by design.

Honest limits: ``chars/4`` is never comparable to a BPE count, and
``cl100k_base`` is an OpenAI tokenizer, not the tokenizer of the Claude or
Ollama models this repository drives. Nothing here opens Gate 3.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

TIKTOKEN_ENCODING = "cl100k_base"
TIKTOKEN_NAME = "tiktoken/cl100k_base"
HEURISTIC_NAME = "chars/4 (heuristic)"

# Mirrors tiktoken_ext.openai_public.cl100k_base (tiktoken 0.14.0).
BPE_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
BPE_CACHE_KEY = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"  # sha1(BPE_URL), tiktoken's cache key
BPE_FILE_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
FETCH_COMMAND = "python -c \"import tiktoken; tiktoken.get_encoding('cl100k_base')\""

# Exactness probe. Measured 2026-09-08 with tiktoken 0.14.0:
#   enc.encode(PROBE_TEXT, disallowed_special=()) == list(PROBE_IDS)
PROBE_TEXT = "Daedalus counts tokens: 4 planes, 11 arms, 9 measures.\n"
PROBE_IDS = (
    31516, 291, 87227, 14921, 11460, 25, 220, 19, 25761, 11, 220, 806, 11977,
    11, 220, 24, 11193, 627,
)


class TokenizerDegradedWarning(RuntimeWarning):
    """tiktoken is installed but the exact counter is not usable."""


_HEURISTIC_FALLBACK_CALLS = 0
_ENCODER: Any = None


@dataclass(frozen=True)
class TokenizerStatus:
    """Measured state of the canonical token counter.

    ``exact`` is ``True`` iff ``degrade_reason`` is ``None`` iff
    ``probe_digest`` is set. ``bpe_cache_path`` is the resolved cache file
    that was checked (also when absent); it is ``None`` only when tiktoken is
    not installed or its cache is disabled by an empty cache-dir variable.
    """

    name: str
    exact: bool
    library: str | None
    degrade_reason: str | None
    probe_digest: str | None
    bpe_cache_path: str | None

    @property
    def heuristic_fallback_calls(self) -> int:
        """Live read of the process-wide ``chars/4`` fallback counter.

        Counts ``count_tokens`` calls that fell back although an encoder was
        loaded (``encode`` raised). Monotone for the process lifetime; a cache
        reset does not zero it. Advisory: the increment is not thread-atomic.
        """
        return _HEURISTIC_FALLBACK_CALLS

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "exact": self.exact,
            "library": self.library,
            "degrade_reason": self.degrade_reason,
            "probe_digest": self.probe_digest,
            "bpe_cache_path": self.bpe_cache_path,
            "heuristic_fallback_calls": self.heuristic_fallback_calls,
        }


def _probe_digest() -> str:
    canonical = json.dumps(list(PROBE_IDS), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bpe_cache_path() -> str | None:
    """Resolve the cl100k_base cache file exactly like tiktoken, without importing it."""
    if "TIKTOKEN_CACHE_DIR" in os.environ:
        cache_dir = os.environ["TIKTOKEN_CACHE_DIR"]
    elif "DATA_GYM_CACHE_DIR" in os.environ:
        cache_dir = os.environ["DATA_GYM_CACHE_DIR"]
    else:
        cache_dir = os.path.join(tempfile.gettempdir(), "data-gym-cache")
    if cache_dir == "":
        return None  # tiktoken: "disable caching" -> every load would fetch
    return os.path.join(cache_dir, BPE_CACHE_KEY)


def _sha256_of_file(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _library_version(module: Any) -> str:
    version = getattr(module, "__version__", None)
    if not version:
        try:
            from importlib.metadata import version as dist_version

            version = dist_version("tiktoken")
        except Exception:
            version = "unknown"
    return f"tiktoken {version}"


def _heuristic(library: str | None, reason: str, path: str | None) -> TokenizerStatus:
    return TokenizerStatus(
        name=HEURISTIC_NAME,
        exact=False,
        library=library,
        degrade_reason=reason,
        probe_digest=None,
        bpe_cache_path=path,
    )


def _probe_tokenizer() -> tuple[TokenizerStatus, Any]:
    try:
        import tiktoken
    except ImportError:
        return _heuristic(None, "tiktoken not installed", None), None

    library = _library_version(tiktoken)
    path = _bpe_cache_path()
    if path is None:
        reason = (
            "tiktoken BPE cache disabled (TIKTOKEN_CACHE_DIR or DATA_GYM_CACHE_DIR is "
            "empty); every get_encoding call would download, and daedalus never "
            "fetches the BPE file"
        )
        return _heuristic(library, reason, None), None
    if not os.path.isfile(path):
        reason = (
            f"cl100k_base BPE file not cached at {path}; daedalus never downloads "
            f"it -- fetch it once with: {FETCH_COMMAND}"
        )
        return _heuristic(library, reason, path), None
    try:
        digest = _sha256_of_file(path)
    except OSError as exc:
        return _heuristic(library, f"{type(exc).__name__}: {exc}", path), None
    if digest != BPE_FILE_SHA256:
        reason = (
            f"cached BPE file {path} has sha256 {digest}, expected {BPE_FILE_SHA256}; "
            "tiktoken would delete and re-download it, so daedalus refuses to load "
            f"it -- remove the file and fetch it once with: {FETCH_COMMAND}"
        )
        return _heuristic(library, reason, path), None
    try:
        encoder = tiktoken.get_encoding(TIKTOKEN_ENCODING)
    except Exception as exc:
        return _heuristic(library, f"{type(exc).__name__}: {exc}", path), None
    try:
        ids = tuple(int(i) for i in encoder.encode(PROBE_TEXT, disallowed_special=()))
    except Exception as exc:
        reason = f"probe encode failed: {type(exc).__name__}: {exc}"
        return _heuristic(library, reason, path), None
    if ids != PROBE_IDS:
        reason = f"probe mismatch: got {list(ids)}, expected {list(PROBE_IDS)}"
        return _heuristic(library, reason, path), None
    status = TokenizerStatus(
        name=TIKTOKEN_NAME,
        exact=True,
        library=library,
        degrade_reason=None,
        probe_digest=_probe_digest(),
        bpe_cache_path=path,
    )
    return status, encoder


@lru_cache(maxsize=1)
def tokenizer_status() -> TokenizerStatus:
    """Measure the canonical counter once per process (or per cache reset).

    Emits exactly one ``TokenizerDegradedWarning`` when tiktoken is installed
    but unusable; a missing library is silent.
    """
    global _ENCODER
    status, encoder = _probe_tokenizer()
    _ENCODER = encoder
    if status.library is not None and status.degrade_reason is not None:
        warnings.warn(
            f"token counting degraded to {status.name}: {status.degrade_reason}",
            TokenizerDegradedWarning,
            stacklevel=2,
        )
    return status


def _reset_tokenizer_cache() -> None:
    """Test-only: forget the measured status and encoder. The warning re-fires."""
    global _ENCODER
    tokenizer_status.cache_clear()
    _ENCODER = None


def _encoder():
    tokenizer_status()
    return _ENCODER


def count_tokens(text: str) -> int:
    global _HEURISTIC_FALLBACK_CALLS
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            _HEURISTIC_FALLBACK_CALLS += 1
    return max(1, len(text) // 4)


def tokenizer_name() -> str:
    return tokenizer_status().name
