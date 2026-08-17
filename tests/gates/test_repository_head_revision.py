from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

import daedalus.gates.repository_head_revision as subject
from daedalus.gates.repository_head_revision import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionRaceError,
    RepositoryHeadRevisionReceipt,
    RepositoryHeadRevisionShapeError,
    verify_repository_head_revision,
    verify_repository_head_revision_receipt,
)


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _git_dir(tmp_path: Path) -> Path:
    git = tmp_path / ".git"
    git.mkdir()
    return git


def _detached(tmp_path: Path, revision: str = REVISION) -> Path:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text(revision + "\n", encoding="utf-8", newline="\n")
    return tmp_path


def _symbolic_loose(tmp_path: Path, revision: str = REVISION) -> Path:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8", newline="\n")
    ref = git / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    ref.write_text(revision + "\n", encoding="utf-8", newline="\n")
    return tmp_path


def _symbolic_packed(tmp_path: Path, revision: str = REVISION) -> Path:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8", newline="\n")
    (git / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{revision} refs/heads/main\n"
        f"{OTHER_REVISION} refs/tags/example\n",
        encoding="utf-8", newline="\n",
    )
    return tmp_path


def test_detached_head_round_trip_is_process_free(tmp_path: Path) -> None:
    root = _detached(tmp_path)

    receipt = verify_repository_head_revision(root, REVISION)
    restored = RepositoryHeadRevisionReceipt.from_dict(receipt.to_dict())

    assert restored == receipt
    assert restored.digest == receipt.digest
    assert receipt.expected_revision == REVISION
    assert receipt.resolved_revision == REVISION
    assert receipt.head_mode == "detached"
    assert receipt.head_ref is None
    assert receipt.resolution_source == "head"
    assert receipt.reference_path is None
    assert receipt.to_dict()["repository_head_verified"] is True
    assert receipt.to_dict()["commit_object_verified"] is False
    assert receipt.to_dict()["worktree_clean_verified"] is False
    assert receipt.to_dict()["process_spawned"] is False
    assert receipt.to_dict()["repository_mutated"] is False
    verify_repository_head_revision_receipt(root, REVISION, restored)


def test_symbolic_loose_ref_round_trip(tmp_path: Path) -> None:
    root = _symbolic_loose(tmp_path)

    receipt = verify_repository_head_revision(root, REVISION)

    assert receipt.head_mode == "symbolic"
    assert receipt.head_ref == "refs/heads/main"
    assert receipt.resolution_source == "loose_ref"
    assert receipt.reference_path == ".git/refs/heads/main"
    assert receipt.reference_sha256 is not None
    assert receipt.reference_size == 41
    verify_repository_head_revision_receipt(root, REVISION, receipt)


def test_symbolic_packed_ref_round_trip(tmp_path: Path) -> None:
    root = _symbolic_packed(tmp_path)

    receipt = verify_repository_head_revision(root, REVISION)

    assert receipt.head_mode == "symbolic"
    assert receipt.head_ref == "refs/heads/main"
    assert receipt.resolution_source == "packed_refs"
    assert receipt.reference_path == ".git/packed-refs"
    verify_repository_head_revision_receipt(root, REVISION, receipt)


def test_stale_expected_revision_refuses(tmp_path: Path) -> None:
    root = _detached(tmp_path)

    with pytest.raises(
        RepositoryHeadRevisionBindingError,
        match="differs from expected revision",
    ):
        verify_repository_head_revision(root, OTHER_REVISION)


@pytest.mark.parametrize(
    "head",
    [
        "",
        "not-a-revision\n",
        REVISION + "\nextra\n",
        "ref: ../outside\n",
        "ref: refs/heads/../main\n",
        "ref: refs/heads/main.lock\n",
        "ref: refs/heads/with space\n",
    ],
)
def test_malformed_head_refuses(tmp_path: Path, head: str) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text(head, encoding="utf-8", newline="\n")

    with pytest.raises(RepositoryHeadRevisionShapeError):
        verify_repository_head_revision(tmp_path, REVISION)


def test_nested_symbolic_ref_refuses_conservatively(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/alias\n", encoding="utf-8", newline="\n")
    ref = git / "refs" / "heads" / "alias"
    ref.parent.mkdir(parents=True)
    ref.write_text("ref: refs/heads/main\n", encoding="utf-8", newline="\n")

    with pytest.raises(
        RepositoryHeadRevisionShapeError,
        match="nested symbolic refs",
    ):
        verify_repository_head_revision(tmp_path, REVISION)


def test_missing_symbolic_ref_and_packed_refs_refuses(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8", newline="\n")

    with pytest.raises(RepositoryHeadRevisionShapeError):
        verify_repository_head_revision(tmp_path, REVISION)


def test_duplicate_packed_ref_refuses(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8", newline="\n")
    (git / "packed-refs").write_text(
        f"{REVISION} refs/heads/main\n"
        f"{REVISION} refs/heads/main\n",
        encoding="utf-8", newline="\n",
    )

    with pytest.raises(
        RepositoryHeadRevisionBindingError,
        match="not present exactly once",
    ):
        verify_repository_head_revision(tmp_path, REVISION)


def test_worktree_gitfile_is_not_misrepresented_as_verified(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text(
        "gitdir: ../metadata/worktrees/example\n",
        encoding="utf-8", newline="\n",
    )

    with pytest.raises(
        RepositoryHeadRevisionShapeError,
        match="must be a real directory",
    ):
        verify_repository_head_revision(tmp_path, REVISION)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation is not portable")
def test_git_directory_symlink_refuses(tmp_path: Path) -> None:
    target = tmp_path / "metadata"
    target.mkdir()
    (target / "HEAD").write_text(REVISION + "\n", encoding="utf-8", newline="\n")
    (tmp_path / ".git").symlink_to(target, target_is_directory=True)

    with pytest.raises(RepositoryHeadRevisionShapeError):
        verify_repository_head_revision(tmp_path, REVISION)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation is not portable")
def test_loose_ref_symlink_cannot_fall_back_to_packed_refs(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8", newline="\n")
    outside = tmp_path / "outside-ref"
    outside.write_text(REVISION + "\n", encoding="utf-8", newline="\n")
    ref = git / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    ref.symlink_to(outside)
    (git / "packed-refs").write_text(
        f"{REVISION} refs/heads/main\n",
        encoding="utf-8", newline="\n",
    )

    with pytest.raises(
        RepositoryHeadRevisionShapeError,
        match="contains a symlink",
    ):
        verify_repository_head_revision(tmp_path, REVISION)


def test_head_change_between_observations_refuses_as_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _detached(tmp_path)
    real_read = subject.read_repository_source
    calls = 0

    def racing_read(repository_root: Path, path: str):
        nonlocal calls
        snapshot = real_read(repository_root, path)
        if path == ".git/HEAD":
            calls += 1
            if calls == 1:
                (root / ".git" / "HEAD").write_text(
                    OTHER_REVISION + "\n",
                    encoding="utf-8", newline="\n",
                )
        return snapshot

    monkeypatch.setattr(subject, "read_repository_source", racing_read)

    with pytest.raises(
        RepositoryHeadRevisionRaceError,
        match="observation changed",
    ):
        verify_repository_head_revision(root, REVISION)


def test_detached_receipt_field_refuses_live_reverification(tmp_path: Path) -> None:
    root = _detached(tmp_path)
    receipt = verify_repository_head_revision(root, REVISION)
    detached = dataclasses.replace(receipt, head_sha256="f" * 64)

    with pytest.raises(RepositoryHeadRevisionBindingError):
        verify_repository_head_revision_receipt(root, REVISION, detached)


def test_wire_claim_escalations_refuse(tmp_path: Path) -> None:
    receipt = verify_repository_head_revision(_detached(tmp_path), REVISION)

    for field, value in (
        ("repository_head_verified", False),
        ("commit_object_verified", True),
        ("worktree_clean_verified", True),
        ("process_spawned", True),
        ("repository_mutated", True),
    ):
        payload = receipt.to_dict()
        payload[field] = value
        with pytest.raises(RepositoryHeadRevisionShapeError):
            RepositoryHeadRevisionReceipt.from_dict(payload)


def test_bool_cannot_substitute_for_strict_size(tmp_path: Path) -> None:
    receipt = verify_repository_head_revision(_detached(tmp_path), REVISION)
    payload = receipt.to_dict()
    payload["head_size"] = True

    with pytest.raises(RepositoryHeadRevisionShapeError):
        RepositoryHeadRevisionReceipt.from_dict(payload)


def test_repository_root_and_receipt_types_are_exactly_bounded(
    tmp_path: Path,
) -> None:
    root = _detached(tmp_path)
    receipt = verify_repository_head_revision(root, REVISION)

    with pytest.raises(RepositoryHeadRevisionShapeError):
        verify_repository_head_revision(
            str(root), REVISION  # type: ignore[arg-type]
        )
    with pytest.raises(RepositoryHeadRevisionShapeError):
        verify_repository_head_revision_receipt(
            root,
            REVISION,
            object(),  # type: ignore[arg-type]
        )
    verify_repository_head_revision_receipt(root, REVISION, receipt)
