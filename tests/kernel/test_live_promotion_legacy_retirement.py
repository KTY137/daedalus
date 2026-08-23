from __future__ import annotations

import importlib
from importlib.resources import files

import pytest

import daedalus.kairos.gated_writes as gated_writes
from daedalus.kernel.promotion import PromotionAuthorizationError


# The blob a human-reviewed patch left the sealed source at. History, newest
# first, each a reviewed patch under docs/decisions-taken/:
#   ec2fa2d6  2026-08-23  artifact store from the OS profile (Odysseus APPLY-WITH-FIX)
#   e7acc630  2026-08-23  lease hand-down + governance head (Odysseus APPLY-WITH-FIX)
#   e31d24ec  before       the retained source as sealed
# This pin went stale for one commit (aa5923d4..be7ae675) and was red without
# anybody noticing -- which is why the three-way check below exists.
REVIEWED_LEGACY_BLOB = "ec2fa2d6d01c990f1997a24029c414943d90a2a6"


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
