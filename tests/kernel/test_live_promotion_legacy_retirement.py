from __future__ import annotations

import importlib
from importlib.resources import files

import pytest

import daedalus.kairos.gated_writes as gated_writes
from daedalus.kernel.promotion import PromotionAuthorizationError


REVIEWED_LEGACY_BLOB = "e31d24ec67f7c208ace34f5dd2e9fefe4e654a86"


def test_retained_source_is_package_data_not_a_second_python_entrypoint() -> None:
    resource = files("daedalus.kairos").joinpath("_gated_writes_legacy.py.src")
    assert resource.is_file()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("daedalus.kairos._gated_writes_legacy")


def test_retained_source_is_bound_to_its_exact_reviewed_git_blob() -> None:
    resource = files("daedalus.kairos").joinpath("_gated_writes_legacy.py.src")
    original = resource.read_bytes()
    assert gated_writes._RETAINED_SOURCE_GIT_BLOB_SHA1 == REVIEWED_LEGACY_BLOB
    assert gated_writes._verify_retained_source(original) is original
    assert gated_writes._git_blob_sha1(original) == REVIEWED_LEGACY_BLOB

    mutated = original.replace(b"PHASE 1", b"PHASE X", 1)
    assert mutated != original
    with pytest.raises(RuntimeError, match="integrity mismatch"):
        gated_writes._verify_retained_source(mutated)


def test_private_facade_has_legacy_promotion_poisoned() -> None:
    with pytest.raises(PromotionAuthorizationError, match="retired"):
        gated_writes._legacy.promote_candidates()


def test_wildcard_exports_do_not_publish_strangler_internals() -> None:
    assert "promote_candidates" in gated_writes.__all__
    assert "gate_candidates" in gated_writes.__all__
    assert "_legacy" not in gated_writes.__all__
    assert "_verify_retained_source" not in gated_writes.__all__
