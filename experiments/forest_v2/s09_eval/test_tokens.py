"""Tests for the shared tokenizer -- the other module that had no test file.

Sharing one tokenizer between the scrubber and every retriever is a fairness
property: if they disagreed about what a token is, leakage scrubbing would be
cosmetic.  That makes each of its three rules load-bearing, and all three
were uncaught by mutation testing -- lowercasing, the camelCase split, and
the length-1 filter could each be removed with the suite still green.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval.tokens import TokenCache, path_tokens, word_tokens  # noqa: E402


def test_tokens_are_lowercased():
    """Without this, ``Event`` in a message never matches ``event`` in a file."""
    assert word_tokens("Event VOLTAGE Bias") == ["event", "voltage", "bias"]
    assert word_tokens("HELLO") == ["hello"]


def test_case_folding_makes_query_and_document_agree():
    assert set(word_tokens("BiasVoltage")) == set(word_tokens("bias voltage"))


def test_camel_case_is_split_at_the_boundary():
    """``bias_voltage -> biasVoltage`` renames must still match either spelling."""
    assert word_tokens("biasVoltage") == ["bias", "voltage"]
    assert word_tokens("HTTPServerHandler") == ["httpserver", "handler"]
    assert word_tokens("effect2Boundary") == ["effect2", "boundary"]


def test_camel_split_survives_a_digit_boundary():
    assert word_tokens("gate0Kernel") == ["gate0", "kernel"]


def test_single_character_tokens_are_dropped():
    """A one-letter token matches nearly every document and carries no signal."""
    assert word_tokens("a b c ab") == ["ab"]
    assert word_tokens("x/y/z.py") == ["py"]


def test_splitting_is_on_non_alphanumerics():
    assert word_tokens("daedalus/spine/effect_boundary.py") == [
        "daedalus", "spine", "effect", "boundary", "py",
    ]
    assert word_tokens("a-b_c.d,e;f") == []


def test_word_tokens_preserves_document_order_and_repeats():
    """BM25 needs term frequency, so this must not de-duplicate."""
    assert word_tokens("alpha beta alpha") == ["alpha", "beta", "alpha"]


def test_path_tokens_is_a_set_of_directories_stem_and_extension():
    assert path_tokens("daedalus/spine/effect_boundary.py") == {
        "daedalus", "spine", "effect", "boundary", "py",
    }


def test_path_tokens_of_a_bare_basename_has_no_directory():
    assert path_tokens("effect_boundary.py") == {"effect", "boundary", "py"}


def test_empty_text_yields_no_tokens():
    assert word_tokens("") == []
    assert word_tokens("   ") == []


def test_token_cache_is_keyed_by_blob_and_counts_once():
    cache = TokenCache()
    calls = []

    def body():
        calls.append(1)
        return "alpha beta alpha"

    first = cache.counts("blob1", body)
    second = cache.counts("blob1", body)
    assert first is second
    assert len(calls) == 1
    assert first["alpha"] == 2
    assert cache.hits == 1 and cache.misses == 1


def test_token_cache_separates_distinct_blobs():
    cache = TokenCache()
    a = cache.counts("blob1", lambda: "alpha")
    b = cache.counts("blob2", lambda: "beta")
    assert a != b
    assert cache.misses == 2
