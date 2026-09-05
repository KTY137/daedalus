"""Real-git evidence for the process-free reader of committed blob bytes.

Every repository in this file is built by the actual ``git`` binary in a
temporary directory. ``git`` is a *test* dependency only: the subject under
test never spawns it, which :func:`test_reader_spawns_no_process` measures
rather than assumes.

The oracle for content is ``git cat-file blob``: the reader is only trusted
where its bytes are identical to what git itself hands out for the same
revision and path.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from daedalus.runtimes.contracts.git_objects import (
    GitBlobObservation,
    GitObjectError,
    GitObjectIntegrityError,
    GitObjectKindError,
    GitObjectLayoutError,
    GitObjectNotFoundError,
    GitObjectRequestError,
    GitObjectSizeError,
    blob_at,
    blob_sha256_at,
    read_blob_at,
)


pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="the fixtures need a real git binary"
)


MAX = 1_048_576


def _git(root: Path, *args: str, config: tuple[str, ...] = ()) -> str:
    result = subprocess.run(
        ["git", *config, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    return result.stdout


def _git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=180,
    )
    return result.stdout


def _init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "lane3@daedalus.test")
    _git(root, "config", "user.name", "Lane Three")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message)
    return _git(root, "rev-parse", "HEAD").strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _revisions(root: Path, count: int) -> list[str]:
    """``count`` revisions of one deltifiable file plus a stable neighbour."""

    lines = [
        f"line {index:04d} original content padding padding padding"
        for index in range(400)
    ]
    _write(root / "pkg" / "data" / "config.txt", "mode = original\n")
    revisions: list[str] = []
    for index in range(count):
        lines[index * 3] = f"line {index:04d} CHANGED at revision {index} xxxxx"
        _write(root / "pkg" / "big.txt", "\n".join(lines) + "\n")
        revisions.append(_commit(root, f"r{index}"))
    return revisions


@pytest.fixture(scope="module")
def loose_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    root = tmp_path_factory.mktemp("loose") / "repo"
    _init(root)
    revisions = _revisions(root, 3)
    assert not sorted((root / ".git" / "objects" / "pack").glob("*.pack"))
    return root, revisions


@pytest.fixture(scope="module")
def packed_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    """One pack whose blob chain is ``OFS_DELTA`` (git's default)."""

    root = tmp_path_factory.mktemp("packed") / "repo"
    _init(root)
    revisions = _revisions(root, 6)
    _git(root, "gc", "-q", "--aggressive")
    assert not _loose_object_ids(root)
    assert _delta_type_codes(root) == {6}
    return root, revisions


@pytest.fixture(scope="module")
def ref_delta_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    """One pack whose blob chain is ``REF_DELTA`` (base addressed by id)."""

    root = tmp_path_factory.mktemp("refdelta") / "repo"
    _init(root)
    revisions = _revisions(root, 6)
    _git(
        root,
        "repack",
        "-a",
        "-d",
        "-f",
        "-q",
        config=("-c", "repack.useDeltaBaseOffset=false"),
    )
    assert _delta_type_codes(root) == {7}
    return root, revisions


@pytest.fixture(scope="module")
def multi_pack_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    root = tmp_path_factory.mktemp("multipack") / "repo"
    _init(root)
    revisions = _revisions(root, 4)
    _git(root, "repack", "-a", "-d", "-q")
    _write(root / "second.txt", "only in the second pack\n")
    revisions.append(_commit(root, "second-pack"))
    _git(root, "repack", "-d", "-q")
    assert len(sorted((root / ".git" / "objects" / "pack").glob("*.idx"))) == 2
    return root, revisions


def _loose_object_ids(root: Path) -> set[str]:
    objects = root / ".git" / "objects"
    found: set[str] = set()
    for directory in objects.iterdir():
        if len(directory.name) != 2 or not directory.is_dir():
            continue
        for entry in directory.iterdir():
            found.add(directory.name + entry.name)
    return found


def _delta_type_codes(root: Path) -> set[int]:
    """The pack type codes of every deltified object, read from the pack itself.

    ``git verify-pack -v`` reports a delta's depth and base id but not whether
    the base is addressed by offset (6) or by id (7), which is exactly the
    distinction the fixtures must guarantee.
    """

    codes: set[int] = set()
    for index in sorted((root / ".git" / "objects" / "pack").glob("*.idx")):
        pack = index.with_suffix(".pack").read_bytes()
        report = _git(root, "verify-pack", "-v", str(index))
        for line in report.splitlines():
            parts = line.split()
            if len(parts) != 7:
                continue
            codes.add((pack[int(parts[4])] >> 4) & 7)
    return codes


def _copy(root: Path, destination: Path) -> Path:
    shutil.copytree(root, destination)
    return destination


def _overwrite(path: Path, data: bytes) -> None:
    """Git marks stored objects read-only; a tamper test has to undo that."""

    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_bytes(data)


# --------------------------------------------------------------------------
# committed bytes, independent of the working tree
# --------------------------------------------------------------------------


def test_loose_blob_matches_git_cat_file_at_every_revision(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = loose_repo
    for revision in revisions:
        expected = _git_bytes(root, "cat-file", "blob", f"{revision}:pkg/big.txt")
        assert blob_at(root, revision, "pkg/big.txt", MAX) == expected


def test_packed_blob_matches_git_cat_file_at_every_revision(
    packed_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = packed_repo
    for revision in revisions:
        expected = _git_bytes(root, "cat-file", "blob", f"{revision}:pkg/big.txt")
        assert blob_at(root, revision, "pkg/big.txt", MAX) == expected


def test_older_revisions_differ_from_head(
    packed_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = packed_repo
    first = blob_at(root, revisions[0], "pkg/big.txt", MAX)
    last = blob_at(root, revisions[-1], "pkg/big.txt", MAX)
    assert first != last
    assert b"CHANGED at revision 5" in last
    assert b"CHANGED at revision 5" not in first


def test_nested_path_walks_subtrees(loose_repo: tuple[Path, list[str]]) -> None:
    root, revisions = loose_repo
    assert blob_at(root, revisions[-1], "pkg/data/config.txt", MAX) == (
        b"mode = original\n"
    )


def test_working_tree_modification_does_not_change_the_committed_bytes(
    tmp_path: Path, loose_repo: tuple[Path, list[str]]
) -> None:
    root = _copy(loose_repo[0], tmp_path / "dirty")
    head = _git(root, "rev-parse", "HEAD").strip()
    committed = blob_at(root, head, "pkg/data/config.txt", MAX)
    (root / "pkg" / "data" / "config.txt").write_bytes(b"mode = LOCAL EDIT\n")
    assert blob_at(root, head, "pkg/data/config.txt", MAX) == committed
    (root / "pkg" / "data" / "config.txt").unlink()
    assert blob_at(root, head, "pkg/data/config.txt", MAX) == committed


def test_committed_bytes_differ_from_the_working_tree_under_eol_filters(
    tmp_path: Path,
) -> None:
    """Why an unequal byte compare is not evidence of a different content.

    With ``text`` filters active the object holds LF and the checkout holds
    CRLF. A reader that returns committed bytes therefore proves equality when
    it matches and proves nothing when it differs.
    """

    root = tmp_path / "eol"
    _init(root)
    _git(root, "config", "core.autocrlf", "true")
    _write(root / ".gitattributes", "*.txt text\n")
    _write(root / "note.txt", "alpha\nbeta\n")
    head = _commit(root, "eol")
    committed = blob_at(root, head, "note.txt", MAX)
    assert committed == b"alpha\nbeta\n"
    (root / "note.txt").unlink()
    _git(root, "checkout", "-q", "--", "note.txt")
    working = (root / "note.txt").read_bytes()
    assert working == b"alpha\r\nbeta\r\n"
    assert committed != working


def test_reader_opens_nothing_outside_the_git_directory(
    monkeypatch: pytest.MonkeyPatch, packed_repo: tuple[Path, list[str]]
) -> None:
    root, revisions = packed_repo
    git_dir = (root / ".git").resolve()
    opened: list[str] = []
    real_open = os.open

    def recording_open(path, flags, mode=0o777, **kwargs):  # type: ignore[no-untyped-def]
        opened.append(os.fspath(path))
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    blob_at(root, revisions[2], "pkg/big.txt", MAX)
    monkeypatch.undo()

    assert opened
    outside = [
        candidate
        for candidate in opened
        if git_dir not in Path(candidate).resolve().parents
    ]
    assert outside == []
    assert not any("big.txt" in candidate for candidate in opened)


def test_reader_spawns_no_process(
    monkeypatch: pytest.MonkeyPatch, packed_repo: tuple[Path, list[str]]
) -> None:
    root, revisions = packed_repo

    def forbidden(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError(f"the reader spawned a process: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(os, "posix_spawn", forbidden, raising=False)
    assert blob_at(root, revisions[0], "pkg/big.txt", MAX)


# --------------------------------------------------------------------------
# pack representations
# --------------------------------------------------------------------------


def test_ofs_delta_chain_is_walked_and_reported(
    packed_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = packed_repo
    observations = [
        read_blob_at(root, revision, "pkg/big.txt", MAX) for revision in revisions
    ]
    assert all(isinstance(item, GitBlobObservation) for item in observations)
    assert {item.source for item in observations} == {"pack"}
    kinds = {kind for item in observations for kind in item.delta_kinds}
    assert kinds == {"ofs_delta"}
    assert max(len(item.delta_kinds) for item in observations) >= 2
    for revision, item in zip(revisions, observations):
        assert item.data == _git_bytes(
            root, "cat-file", "blob", f"{revision}:pkg/big.txt"
        )
        assert item.blob_id == _git(
            root, "rev-parse", f"{revision}:pkg/big.txt"
        ).strip()
        assert item.mode == "100644"
        assert item.pack_name is not None


def test_ref_delta_chain_is_walked_and_reported(
    ref_delta_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = ref_delta_repo
    observations = [
        read_blob_at(root, revision, "pkg/big.txt", MAX) for revision in revisions
    ]
    kinds = {kind for item in observations for kind in item.delta_kinds}
    assert kinds == {"ref_delta"}
    assert max(len(item.delta_kinds) for item in observations) >= 2
    for revision, item in zip(revisions, observations):
        assert item.data == _git_bytes(
            root, "cat-file", "blob", f"{revision}:pkg/big.txt"
        )


def test_several_packs_are_searched(multi_pack_repo: tuple[Path, list[str]]) -> None:
    root, revisions = multi_pack_repo
    head = revisions[-1]
    late = read_blob_at(root, head, "second.txt", MAX)
    early = read_blob_at(root, head, "pkg/big.txt", MAX)
    assert late.data == b"only in the second pack\n"
    assert early.data == _git_bytes(root, "cat-file", "blob", f"{head}:pkg/big.txt")
    assert late.source == early.source == "pack"
    assert late.pack_name != early.pack_name


def test_loose_and_packed_objects_are_both_reachable(
    tmp_path: Path, packed_repo: tuple[Path, list[str]]
) -> None:
    root = _copy(packed_repo[0], tmp_path / "mixed")
    _write(root / "fresh.txt", "written after the pack existed\n")
    head = _commit(root, "loose on top of a pack")
    fresh = read_blob_at(root, head, "fresh.txt", MAX)
    packed = read_blob_at(root, head, "pkg/big.txt", MAX)
    assert fresh.source == "loose"
    assert packed.source == "pack"
    assert fresh.data == b"written after the pack existed\n"


# --------------------------------------------------------------------------
# typed refusals
# --------------------------------------------------------------------------


def test_missing_path_is_a_typed_not_found_refusal(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = loose_repo
    with pytest.raises(GitObjectNotFoundError) as error:
        blob_at(root, revisions[-1], "pkg/absent.txt", MAX)
    assert "pkg/absent.txt" in str(error.value)
    with pytest.raises(GitObjectNotFoundError):
        blob_at(root, revisions[-1], "pkg/data/absent/deep.txt", MAX)


def test_path_that_did_not_exist_yet_is_refused_at_the_older_revision(
    multi_pack_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = multi_pack_repo
    assert blob_at(root, revisions[-1], "second.txt", MAX)
    with pytest.raises(GitObjectNotFoundError):
        blob_at(root, revisions[0], "second.txt", MAX)


def test_unknown_commit_id_is_a_typed_not_found_refusal(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, _ = loose_repo
    with pytest.raises(GitObjectNotFoundError) as error:
        blob_at(root, "0" * 40, "pkg/big.txt", MAX)
    assert "0" * 40 in str(error.value)


def test_a_blob_id_in_place_of_a_commit_is_refused_as_the_wrong_kind(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = loose_repo
    blob_id = _git(root, "rev-parse", f"{revisions[-1]}:pkg/big.txt").strip()
    with pytest.raises(GitObjectKindError) as error:
        blob_at(root, blob_id, "pkg/big.txt", MAX)
    assert "commit" in str(error.value)


def test_a_tree_path_is_refused_as_not_a_blob(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = loose_repo
    with pytest.raises(GitObjectKindError) as error:
        blob_at(root, revisions[-1], "pkg/data", MAX)
    assert "blob" in str(error.value)


def test_a_path_component_that_is_a_blob_is_refused(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = loose_repo
    with pytest.raises(GitObjectKindError):
        blob_at(root, revisions[-1], "pkg/big.txt/inner.txt", MAX)


def test_symlink_entry_is_refused_as_not_a_blob(tmp_path: Path) -> None:
    """A symlink is stored as a blob with mode 120000: the mode decides."""

    root = tmp_path / "symlink"
    _init(root)
    _write(root / "target.txt", "real content\n")
    _commit(root, "target")
    link_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=root,
        input=b"target.txt",
        capture_output=True,
        check=True,
        timeout=180,
    ).stdout.decode("ascii").strip()
    _git(root, "update-index", "--add", "--cacheinfo", f"120000,{link_blob},link.txt")
    _git(root, "commit", "-qm", "symlink")
    head = _git(root, "rev-parse", "HEAD").strip()
    assert _git(root, "ls-tree", head, "link.txt").startswith("120000")
    with pytest.raises(GitObjectKindError) as error:
        blob_at(root, head, "link.txt", MAX)
    assert "symlink" in str(error.value)
    assert blob_at(root, head, "target.txt", MAX) == b"real content\n"


def test_gitlink_entry_is_refused_as_not_a_blob(tmp_path: Path) -> None:
    root = tmp_path / "gitlink"
    _init(root)
    _write(root / "keep.txt", "keep\n")
    first = _commit(root, "keep")
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{first},sub")
    _git(root, "commit", "-qm", "gitlink")
    head = _git(root, "rev-parse", "HEAD").strip()
    assert _git(root, "ls-tree", head, "sub").startswith("160000")
    with pytest.raises(GitObjectKindError) as error:
        blob_at(root, head, "sub", MAX)
    assert "submodule" in str(error.value) or "gitlink" in str(error.value)
    with pytest.raises(GitObjectKindError):
        blob_at(root, head, "sub/inner.txt", MAX)


def test_executable_blob_is_still_a_blob(tmp_path: Path) -> None:
    root = tmp_path / "exec"
    _init(root)
    _write(root / "run.sh", "#!/bin/sh\necho hi\n")
    _commit(root, "run")
    blob_id = _git(root, "rev-parse", "HEAD:run.sh").strip()
    _git(root, "update-index", "--add", "--cacheinfo", f"100755,{blob_id},run.sh")
    _git(root, "commit", "-qm", "exec bit")
    head = _git(root, "rev-parse", "HEAD").strip()
    observation = read_blob_at(root, head, "run.sh", MAX)
    assert observation.mode == "100755"
    assert observation.data == b"#!/bin/sh\necho hi\n"


@pytest.mark.parametrize(
    "path",
    (
        "/absolute.txt",
        "C:/drive.txt",
        "../escape.txt",
        "pkg/../escape.txt",
        "pkg//big.txt",
        "pkg\\big.txt",
        "",
        "pkg/",
        "./big.txt",
    ),
)
def test_unsafe_paths_are_request_refusals(
    loose_repo: tuple[Path, list[str]], path: str
) -> None:
    root, revisions = loose_repo
    with pytest.raises(GitObjectRequestError):
        blob_at(root, revisions[-1], path, MAX)


@pytest.mark.parametrize(
    "commit_id",
    ("", "abc", "A" * 40, "0" * 39, "0" * 41, "g" * 40, " " + "0" * 39),
)
def test_malformed_commit_ids_are_request_refusals(
    loose_repo: tuple[Path, list[str]], commit_id: str
) -> None:
    root, _ = loose_repo
    with pytest.raises(GitObjectRequestError):
        blob_at(root, commit_id, "pkg/big.txt", MAX)


@pytest.mark.parametrize("max_bytes", (0, -1, True, 1.0, None, 1 << 40))
def test_malformed_size_bounds_are_request_refusals(
    loose_repo: tuple[Path, list[str]], max_bytes: object
) -> None:
    root, revisions = loose_repo
    with pytest.raises(GitObjectRequestError):
        blob_at(root, revisions[-1], "pkg/big.txt", max_bytes)  # type: ignore[arg-type]


def test_non_path_root_is_a_request_refusal(loose_repo: tuple[Path, list[str]]) -> None:
    root, revisions = loose_repo
    with pytest.raises(GitObjectRequestError):
        blob_at(str(root), revisions[-1], "pkg/big.txt", MAX)  # type: ignore[arg-type]


def test_blob_above_max_bytes_is_refused_loose(
    loose_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = loose_repo
    size = len(blob_at(root, revisions[-1], "pkg/big.txt", MAX))
    with pytest.raises(GitObjectSizeError) as error:
        blob_at(root, revisions[-1], "pkg/big.txt", size - 1)
    assert str(size - 1) in str(error.value)
    assert blob_at(root, revisions[-1], "pkg/big.txt", size)


def test_blob_above_max_bytes_is_refused_packed(
    packed_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = packed_repo
    size = len(blob_at(root, revisions[-1], "pkg/big.txt", MAX))
    with pytest.raises(GitObjectSizeError):
        blob_at(root, revisions[-1], "pkg/big.txt", size - 1)
    assert len(blob_at(root, revisions[-1], "pkg/big.txt", size)) == size


# --------------------------------------------------------------------------
# integrity
# --------------------------------------------------------------------------


def test_tampered_loose_object_fails_sha1_verification(
    tmp_path: Path, loose_repo: tuple[Path, list[str]]
) -> None:
    root = _copy(loose_repo[0], tmp_path / "tampered-loose")
    head = _git(root, "rev-parse", "HEAD").strip()
    blob_id = _git(root, "rev-parse", "HEAD:pkg/data/config.txt").strip()
    forged = b"mode = FORGED!!\n"
    payload = b"blob " + str(len(forged)).encode("ascii") + b"\x00" + forged
    path = root / ".git" / "objects" / blob_id[:2] / blob_id[2:]
    _overwrite(path, zlib.compress(payload))
    with pytest.raises(GitObjectIntegrityError) as error:
        blob_at(root, head, "pkg/data/config.txt", MAX)
    assert blob_id in str(error.value)


def test_tampered_pack_byte_is_refused(
    tmp_path: Path, packed_repo: tuple[Path, list[str]]
) -> None:
    """Flip one byte inside the record of the blob that is about to be read."""

    root = _copy(packed_repo[0], tmp_path / "tampered-pack")
    head = _git(root, "rev-parse", "HEAD").strip()
    assert blob_at(root, head, "pkg/big.txt", MAX)
    blob_id = _git(root, "rev-parse", "HEAD:pkg/big.txt").strip()
    index_path = sorted((root / ".git" / "objects" / "pack").glob("*.idx"))[0]
    offsets = {
        parts[0]: int(parts[4])
        for parts in (
            line.split() for line in _git(root, "verify-pack", "-v", str(index_path)).splitlines()
        )
        if len(parts) in (5, 7)
    }
    pack = index_path.with_suffix(".pack")
    data = bytearray(pack.read_bytes())
    data[offsets[blob_id] + 8] ^= 0xFF
    _overwrite(pack, bytes(data))
    with pytest.raises(GitObjectError):
        blob_at(root, head, "pkg/big.txt", MAX)


def test_truncated_loose_object_is_refused(
    tmp_path: Path, loose_repo: tuple[Path, list[str]]
) -> None:
    root = _copy(loose_repo[0], tmp_path / "truncated")
    head = _git(root, "rev-parse", "HEAD").strip()
    blob_id = _git(root, "rev-parse", "HEAD:pkg/data/config.txt").strip()
    path = root / ".git" / "objects" / blob_id[:2] / blob_id[2:]
    _overwrite(path, path.read_bytes()[:6])
    with pytest.raises(GitObjectIntegrityError):
        blob_at(root, head, "pkg/data/config.txt", MAX)


# --------------------------------------------------------------------------
# unsupported repository layouts
# --------------------------------------------------------------------------


def test_linked_worktree_pointer_file_is_refused_honestly(
    tmp_path: Path, loose_repo: tuple[Path, list[str]]
) -> None:
    """The same refusal the HEAD verifier gives: name the layout and a remedy."""

    root = _copy(loose_repo[0], tmp_path / "main")
    head = _git(root, "rev-parse", "HEAD").strip()
    linked = tmp_path / "linked"
    _git(root, "worktree", "add", "-q", "-b", "lane", str(linked), "HEAD")
    assert (linked / ".git").is_file()
    assert (linked / ".git").read_bytes().startswith(b"gitdir:")
    with pytest.raises(GitObjectLayoutError) as error:
        blob_at(linked, head, "pkg/big.txt", MAX)
    message = str(error.value)
    assert "worktree" in message
    assert "gitdir" in message
    assert blob_at(root, head, "pkg/big.txt", MAX)


def test_missing_git_directory_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "file.txt").write_bytes(b"content\n")
    with pytest.raises(GitObjectLayoutError):
        blob_at(root, "0" * 40, "file.txt", MAX)


def test_object_alternates_are_refused_instead_of_silently_missing_objects(
    tmp_path: Path, loose_repo: tuple[Path, list[str]]
) -> None:
    root = _copy(loose_repo[0], tmp_path / "alternates")
    head = _git(root, "rev-parse", "HEAD").strip()
    info = root / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_bytes(b"/somewhere/else/objects\n")
    with pytest.raises(GitObjectLayoutError) as error:
        blob_at(root, head, "pkg/big.txt", MAX)
    assert "alternates" in str(error.value)


def test_absent_repository_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(GitObjectError):
        blob_at(tmp_path / "does-not-exist", "0" * 40, "file.txt", MAX)


# --------------------------------------------------------------------------
# pack index parsing that real fixtures cannot reach
# --------------------------------------------------------------------------


def _synthetic_index(object_id: str, offset: int, large: bool) -> bytes:
    raw = bytes.fromhex(object_id)
    fanout = [0] * 256
    for value in range(raw[0], 256):
        fanout[value] = 1
    body = b"\xfftOc" + struct.pack(">I", 2)
    body += b"".join(struct.pack(">I", value) for value in fanout)
    body += raw
    body += struct.pack(">I", 0)
    if large:
        body += struct.pack(">I", 0x80000000)
        body += struct.pack(">Q", offset)
    else:
        body += struct.pack(">I", offset)
    body += b"\x11" * 20
    return body + hashlib.sha1(body).digest()


def test_large_pack_offsets_are_parsed(tmp_path: Path) -> None:
    """A >4 GiB pack offset lives in the 8-byte table, not in the 4-byte one."""

    from daedalus.runtimes.contracts.git_objects import _PackIndex

    object_id = "3" * 40
    offset = (1 << 32) + 4096
    path = tmp_path / "pack-test.idx"
    path.write_bytes(_synthetic_index(object_id, offset, large=True))
    index = _PackIndex.load(path)
    assert index.offset_of(object_id) == offset
    assert index.offset_of("4" * 40) is None
    assert index.id_at_offset(offset) == object_id


def test_small_pack_offsets_are_parsed(tmp_path: Path) -> None:
    from daedalus.runtimes.contracts.git_objects import _PackIndex

    object_id = "5" * 40
    path = tmp_path / "pack-small.idx"
    path.write_bytes(_synthetic_index(object_id, 4096, large=False))
    index = _PackIndex.load(path)
    assert index.offset_of(object_id) == 4096


def test_version_one_pack_index_is_refused(tmp_path: Path) -> None:
    from daedalus.runtimes.contracts.git_objects import _PackIndex

    path = tmp_path / "pack-v1.idx"
    path.write_bytes(b"\x00" * 4 + b"\x00" * 1020)
    with pytest.raises(GitObjectLayoutError):
        _PackIndex.load(path)


# --------------------------------------------------------------------------
# the digest surface the campaign binding would consume
# --------------------------------------------------------------------------


def test_blob_sha256_at_is_the_sha256_of_blob_at(
    packed_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = packed_repo
    for revision in revisions[:3]:
        data = blob_at(root, revision, "pkg/big.txt", MAX)
        assert blob_sha256_at(root, revision, "pkg/big.txt", MAX) == (
            hashlib.sha256(data).hexdigest()
        )


def test_observation_projection_carries_provenance_without_bytes(
    packed_repo: tuple[Path, list[str]],
) -> None:
    root, revisions = packed_repo
    observation = read_blob_at(root, revisions[-1], "pkg/big.txt", MAX)
    payload = observation.to_dict()
    assert payload["schema"] == "daedalus-git-blob-observation/1"
    assert payload["commit_id"] == revisions[-1]
    assert payload["path"] == "pkg/big.txt"
    assert payload["blob_id"] == observation.blob_id
    assert payload["sha256"] == hashlib.sha256(observation.data).hexdigest()
    assert payload["size"] == len(observation.data)
    assert payload["process_spawned"] is False
    assert payload["working_tree_read"] is False
    assert "data" not in payload


# --------------------------------------------------------------------------
# delta-chain bounds (D1, Odysseus 2026-09-05)
#
# Real git will not produce a chain past its own pack.depth and cannot be made
# to write a cycle at all, so these fixtures forge the pack: a PACK header, one
# record per object, an .idx v2 beside it. No git binary is involved.
# --------------------------------------------------------------------------


def _object_id(kind: str, content: bytes) -> str:
    return hashlib.sha1(
        f"{kind} {len(content)}\x00".encode("ascii") + content
    ).hexdigest()


def _pack_object_header(type_code: int, size: int) -> bytes:
    byte = (type_code << 4) | (size & 0x0F)
    size >>= 4
    out = bytearray()
    while size:
        out.append(byte | 0x80)
        byte = size & 0x7F
        size >>= 7
    out.append(byte)
    return bytes(out)


def _offset_distance(distance: int) -> bytes:
    out = bytearray([distance & 0x7F])
    distance >>= 7
    while distance:
        distance -= 1
        out.insert(0, 0x80 | (distance & 0x7F))
        distance >>= 7
    return bytes(out)


def _delta_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
            continue
        out.append(byte)
        return bytes(out)


def _append_delta(base: bytes, suffix: bytes) -> bytes:
    """Copy the whole base, then insert ``suffix``."""

    payload = bytearray()
    payload += _delta_varint(len(base))
    payload += _delta_varint(len(base) + len(suffix))
    opcode = 0x80
    operands = bytearray()
    for index in range(3):
        byte = (len(base) >> (index * 8)) & 0xFF
        if byte:
            opcode |= 0x10 << index
            operands.append(byte)
    payload.append(opcode)
    payload += operands
    payload.append(len(suffix))
    payload += suffix
    return bytes(payload)


def _forge_pack(
    directory: Path,
    records: list[tuple[str, int, bytes, tuple[str, str] | None]],
) -> None:
    """Write one ``.pack``/``.idx`` v2 pair from explicit object records."""

    body = bytearray(b"PACK" + struct.pack(">II", 2, len(records)))
    offsets: dict[str, int] = {}
    crcs: dict[str, int] = {}
    for object_id, type_code, payload, base in records:
        start = len(body)
        offsets[object_id] = start
        body += _pack_object_header(type_code, len(payload))
        if base is not None:
            kind, reference = base
            if kind == "ref":
                body += bytes.fromhex(reference)
            else:
                body += _offset_distance(start - offsets[reference])
        body += zlib.compress(payload)
        crcs[object_id] = zlib.crc32(bytes(body[start:])) & 0xFFFFFFFF
    checksum = hashlib.sha1(bytes(body)).digest()
    body += checksum

    directory.mkdir(parents=True, exist_ok=True)
    name = f"pack-{checksum.hex()}"
    (directory / f"{name}.pack").write_bytes(bytes(body))

    ids = sorted(offsets)
    fanout = [0] * 256
    for object_id in ids:
        fanout[int(object_id[:2], 16)] += 1
    running = 0
    for position in range(256):
        running += fanout[position]
        fanout[position] = running
    index = bytearray(b"\xfftOc" + struct.pack(">I", 2))
    index += b"".join(struct.pack(">I", value) for value in fanout)
    index += b"".join(bytes.fromhex(object_id) for object_id in ids)
    index += b"".join(struct.pack(">I", crcs[object_id]) for object_id in ids)
    index += b"".join(struct.pack(">I", offsets[object_id]) for object_id in ids)
    index += checksum
    index += hashlib.sha1(bytes(index)).digest()
    (directory / f"{name}.idx").write_bytes(bytes(index))


def _forge_commit(
    records: list[tuple[str, int, bytes, tuple[str, str] | None]],
    name: str,
    blob_id: str,
) -> str:
    tree = b"100644 " + name.encode("ascii") + b"\x00" + bytes.fromhex(blob_id)
    tree_id = _object_id("tree", tree)
    commit = (
        f"tree {tree_id}\n".encode("ascii")
        + b"author Lane Three <lane3@daedalus.test> 0 +0000\n"
        + b"committer Lane Three <lane3@daedalus.test> 0 +0000\n\nforged\n"
    )
    commit_id = _object_id("commit", commit)
    records.append((tree_id, 2, tree, None))
    records.append((commit_id, 1, commit, None))
    return commit_id


def _delta_chain_repository(root: Path, links: int, kind: str) -> tuple[str, bytes]:
    """A repository whose ``chain.txt`` sits at the end of ``links`` deltas."""

    contents = [b"forged chain base\n" + b"x" * step for step in range(links + 1)]
    records: list[tuple[str, int, bytes, tuple[str, str] | None]] = []
    previous = _object_id("blob", contents[0])
    records.append((previous, 3, contents[0], None))
    for step in range(1, links + 1):
        object_id = _object_id("blob", contents[step])
        records.append(
            (
                object_id,
                7 if kind == "ref" else 6,
                _append_delta(contents[step - 1], b"x"),
                (kind, previous),
            )
        )
        previous = object_id
    commit_id = _forge_commit(records, "chain.txt", previous)
    _forge_pack(root / ".git" / "objects" / "pack", records)
    return commit_id, contents[links]


def test_a_short_reference_delta_chain_still_resolves(tmp_path: Path) -> None:
    """The forge is only evidence if a legal chain through it reads correctly."""

    root = tmp_path / "short"
    commit_id, expected = _delta_chain_repository(root, 3, "ref")
    observation = read_blob_at(root, commit_id, "chain.txt", MAX)
    assert observation.data == expected
    assert observation.delta_kinds == ("ref_delta", "ref_delta", "ref_delta")
    assert observation.source == "pack"


@pytest.mark.parametrize("kind", ("ref", "ofs"))
def test_delta_chain_at_the_depth_limit_resolves(tmp_path: Path, kind: str) -> None:
    from daedalus.runtimes.contracts.git_objects import _MAX_DELTA_DEPTH

    root = tmp_path / f"limit-{kind}"
    commit_id, expected = _delta_chain_repository(root, _MAX_DELTA_DEPTH, kind)
    observation = read_blob_at(root, commit_id, "chain.txt", MAX)
    assert observation.data == expected
    assert len(observation.delta_kinds) == _MAX_DELTA_DEPTH
    assert set(observation.delta_kinds) == {f"{kind}_delta"}


@pytest.mark.parametrize("kind", ("ref", "ofs"))
def test_delta_chain_beyond_the_depth_limit_is_refused(
    tmp_path: Path, kind: str
) -> None:
    """The bound must hold for both branches; it held only for OFS before."""

    from daedalus.runtimes.contracts.git_objects import _MAX_DELTA_DEPTH

    root = tmp_path / f"beyond-{kind}"
    commit_id, _ = _delta_chain_repository(root, _MAX_DELTA_DEPTH + 1, kind)
    with pytest.raises(GitObjectIntegrityError) as error:
        blob_at(root, commit_id, "chain.txt", MAX)
    assert "delta chain" in str(error.value)


def test_reference_delta_cycle_is_a_typed_refusal(tmp_path: Path) -> None:
    """A <-> B must refuse, not exhaust the interpreter stack."""

    root = tmp_path / "cycle"
    first = _object_id("blob", b"cycle-a")
    second = _object_id("blob", b"cycle-b")
    payload = _append_delta(b"forged chain base\n", b"x")
    records: list[tuple[str, int, bytes, tuple[str, str] | None]] = [
        (first, 7, payload, ("ref", second)),
        (second, 7, payload, ("ref", first)),
    ]
    commit_id = _forge_commit(records, "cycle.txt", first)
    _forge_pack(root / ".git" / "objects" / "pack", records)
    with pytest.raises(GitObjectIntegrityError) as error:
        blob_at(root, commit_id, "cycle.txt", MAX)
    assert "cycle" in str(error.value)
    assert first in str(error.value) or second in str(error.value)


# --------------------------------------------------------------------------
# .git redirection (D2, Odysseus 2026-09-05)
# --------------------------------------------------------------------------


def test_git_directory_junction_is_refused(
    tmp_path: Path, loose_repo: tuple[Path, list[str]]
) -> None:
    """An NTFS junction needs no elevation and is not a symlink to lstat."""

    if os.name != "nt":
        pytest.skip("directory junctions are a Windows layout")
    real = _copy(loose_repo[0], tmp_path / "real")
    head = _git(real, "rev-parse", "HEAD").strip()
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(decoy / ".git"), str(real / ".git")],
        capture_output=True,
        timeout=180,
    )
    if created.returncode != 0 or not (decoy / ".git").exists():
        pytest.skip("mklink /J is unavailable on this host")
    assert not (decoy / ".git").is_symlink()
    assert (decoy / ".git" / "HEAD").is_file()
    with pytest.raises(GitObjectLayoutError) as error:
        blob_at(decoy, head, "pkg/big.txt", MAX)
    message = str(error.value)
    assert "junction" in message or "reparse" in message
    assert blob_at(real, head, "pkg/big.txt", MAX)
