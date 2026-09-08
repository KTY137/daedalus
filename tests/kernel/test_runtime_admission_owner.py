"""Runtime admission has one canonical production owner.

The old kernel import remains a lazy compatibility facade only. This pins the
ownership boundary so future Claude/Ikarus composition cannot grow a second
runtime-authority minter in the kernel.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import daedalus.kernel.runtime_authorization_issuer as legacy_issuer
import daedalus.runtimes.admission as runtime_admission
import daedalus.runtimes.admission.authorization as runtime_authorization


_PUBLIC = (
    "RUNTIME_AUTHORITY_KEY_ID",
    "RUNTIME_LEASE_KEY_ID",
    "acquire_runtime_bound_authorization",
    "runtime_trust_ledger",
    "runtime_trust_ledger_path",
)


@pytest.mark.parametrize("name", _PUBLIC)
def test_legacy_runtime_authorization_import_delegates_to_runtime_owner(name: str) -> None:
    assert getattr(legacy_issuer, name) is getattr(runtime_admission, name)


def test_runtime_authorization_implementation_has_one_owner() -> None:
    legacy_source = Path(legacy_issuer.__file__).read_text(encoding="utf-8")
    owner_source = Path(runtime_authorization.__file__).read_text(encoding="utf-8")

    assert "def acquire_runtime_bound_authorization(" not in legacy_source
    assert "def acquire_runtime_bound_authorization(" in owner_source
    assert "RuntimeBoundEffectAuthorization(" not in legacy_source
    assert owner_source.count("RuntimeBoundEffectAuthorization(") == 1
