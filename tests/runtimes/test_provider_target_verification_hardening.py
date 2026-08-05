from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderTargetVerificationBindingError,
    ProviderTargetVerificationSourceError,
    VerifiedPythonTarget,
)


_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_provider_target_verification.py"))
)
_fixture = _HELPERS["_fixture"]
_issue = _HELPERS["_issue"]


def test_loaded_source_tree_manifest_is_rehashed_independently_of_store_method(
    tmp_path,
    monkeypatch,
) -> None:
    expected = _fixture(tmp_path / "expected")
    foreign = _fixture(
        tmp_path / "foreign",
        extra={"README.md": b"foreign manifest identity\n"},
    )
    foreign_manifest = foreign.store.load_tree(foreign.tree_ref)

    def substituted_manifest(self, ref, **kwargs):
        return foreign_manifest

    monkeypatch.setattr(SourceTreeStore, "load_tree", substituted_manifest)
    with pytest.raises(
        ProviderTargetVerificationSourceError,
        match="content address",
    ):
        _issue(expected)


@pytest.mark.parametrize(
    "field,value,match",
    [
        (
            "target",
            "daedalus.runtimes.adapters.other:FixtureAdapter.invoke",
            "repository_path|qualified_name",
        ),
        (
            "qualified_name",
            "FixtureAdapter.output_digests",
            "qualified_name",
        ),
        (
            "repository_path",
            "daedalus/runtimes/adapters/other.py",
            "module",
        ),
        ("source_size", 0, "positive"),
    ],
)
def test_verified_target_wire_binds_target_path_name_and_nonempty_source(
    tmp_path,
    field: str,
    value,
    match: str,
) -> None:
    payload = _issue(_fixture(tmp_path)).invoke.to_dict()
    payload[field] = value
    with pytest.raises(ProviderTargetVerificationBindingError, match=match):
        VerifiedPythonTarget.from_dict(payload)
