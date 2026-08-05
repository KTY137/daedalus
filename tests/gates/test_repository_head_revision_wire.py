from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.gates.repository_head_revision import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionReceipt,
    RepositoryHeadRevisionShapeError,
    verify_repository_head_revision,
)


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _symbolic_receipt(tmp_path: Path) -> RepositoryHeadRevisionReceipt:
    git = tmp_path / ".git"
    ref = git / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    (git / "HEAD").write_text(
        "ref: refs/heads/main\n",
        encoding="utf-8",
    )
    ref.write_text(REVISION + "\n", encoding="utf-8")
    return verify_repository_head_revision(tmp_path, REVISION)


def test_malformed_wire_reference_path_stays_inside_error_domain(
    tmp_path: Path,
) -> None:
    payload = _symbolic_receipt(tmp_path).to_dict()
    payload["reference_path"] = "../outside"

    with pytest.raises(
        RepositoryHeadRevisionShapeError,
        match="reference_path is not canonical",
    ):
        RepositoryHeadRevisionReceipt.from_dict(payload)


def test_wire_expected_and_resolved_revision_must_match(tmp_path: Path) -> None:
    payload = _symbolic_receipt(tmp_path).to_dict()
    payload["expected_revision"] = OTHER_REVISION

    with pytest.raises(
        RepositoryHeadRevisionBindingError,
        match="expected revision differs",
    ):
        RepositoryHeadRevisionReceipt.from_dict(payload)


@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/has]bracket",
        "refs/heads/topic.lock/child",
        "refs/heads/delete\x7fcharacter",
    ],
)
def test_conservative_forbidden_ref_forms_refuse(
    tmp_path: Path,
    ref: str,
) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text(f"ref: {ref}\n", encoding="utf-8")

    with pytest.raises(RepositoryHeadRevisionShapeError):
        verify_repository_head_revision(tmp_path, REVISION)
