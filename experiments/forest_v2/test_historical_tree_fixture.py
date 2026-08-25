"""Contract tests for revision-bound Forest-v2 source fixtures."""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest


FOREST_ROOT = Path(__file__).resolve().parent
REPO_ROOT = FOREST_ROOT.parents[1]
sys.path.insert(0, str(FOREST_ROOT))

import _historical_tree_fixture as historical_fixture  # noqa: E402
from _historical_tree_fixture import (  # noqa: E402
    HistoricalTreeError,
    materialize_historical_tree,
)
from s09_eval import gitio  # noqa: E402


SOURCE_REVISION = "dd1a4a2103a9952963e267c0bf5f4f3582d1e2ab"
IRON_GUARD = "tools/iron_plan_guard.py"


def test_materializes_exact_verified_bytes_through_the_read_only_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    real_run = gitio._run

    def spy(repo: Path, args: list[str], stdin: bytes | None = None) -> bytes:
        calls.append(args[0])
        return real_run(repo, args, stdin)

    monkeypatch.setattr(gitio, "_run", spy)
    tree = materialize_historical_tree(
        REPO_ROOT,
        SOURCE_REVISION,
        tmp_path / "tree",
        prefixes=(IRON_GUARD,),
    )

    parent_tree = gitio.list_tree(REPO_ROOT, SOURCE_REVISION)
    blob_sha, _size = parent_tree[IRON_GUARD]
    expected = gitio.read_blobs(REPO_ROOT, [blob_sha])[blob_sha]

    assert tree.source_revision == SOURCE_REVISION
    assert tree.prefixes == (IRON_GUARD,)
    assert tree.blob_count == 1
    assert (tree.root / IRON_GUARD).read_bytes() == expected
    assert set(calls) <= {"rev-list", "rev-parse", "ls-tree", "cat-file"}
    assert {"rev-list", "rev-parse", "ls-tree", "cat-file"} <= set(calls)


@pytest.mark.parametrize(
    "prefix",
    (
        "",
        "../tools",
        "/tools",
        "tools\\iron_plan_guard.py",
        ".",
        "tools/",
        "tools//guard",
        "tools\tguard",
        "C:escape",
        "tools/foo:bar",
        "tools/CON/guard.py",
        "tools/con.txt",
        "tools/CONIN$.txt",
        "tools/CONOUT$",
        "tools/LPT9.py",
        "tools/COM\N{SUPERSCRIPT ONE}.txt",
        "tools/COM\N{SUPERSCRIPT TWO}.txt",
        "tools/COM\N{SUPERSCRIPT THREE}.txt",
        "tools/LPT\N{SUPERSCRIPT ONE}.txt",
        "tools/LPT\N{SUPERSCRIPT TWO}.txt",
        "tools/LPT\N{SUPERSCRIPT THREE}.txt",
        "tools/CON .txt",
        "tools/NUL .x",
        "tools/COM1 .txt",
        "tools/LPT1 .x",
        "tools/trailing.",
        "tools/trailing ",
        "tools/foo*bar",
        "tools/ABCDEF~1/file.py",
        "A" * 256 + "/file.py",
    ),
)
def test_refuses_unsafe_or_noncanonical_prefixes(
    tmp_path: Path, prefix: str
) -> None:
    destination = tmp_path / "tree"
    with pytest.raises(HistoricalTreeError):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            destination,
            prefixes=(prefix,),
        )
    assert not destination.exists()


def test_accepts_the_portable_component_length_boundary() -> None:
    component = "A" * 255
    assert historical_fixture._safe_repo_path(component) == component


def test_refuses_abbreviated_revision_and_missing_prefix(tmp_path: Path) -> None:
    with pytest.raises(HistoricalTreeError, match="full lowercase 40-hex"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION[:12],
            tmp_path / "short",
            prefixes=("tools",),
        )
    with pytest.raises(HistoricalTreeError, match="contain no regular blobs"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            tmp_path / "missing",
            prefixes=("definitely/not/in/the/historical/tree",),
        )
    assert not (tmp_path / "short").exists()
    assert not (tmp_path / "missing").exists()


def test_refuses_unavailable_full_revision_and_mismatched_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unavailable = tmp_path / "unavailable"
    with pytest.raises(HistoricalTreeError):
        materialize_historical_tree(
            REPO_ROOT,
            "0" * 40,
            unavailable,
            prefixes=(IRON_GUARD,),
        )
    assert not unavailable.exists()

    monkeypatch.setattr(gitio, "rev_parse", lambda _repo, _rev: "1" * 40)
    mismatched = tmp_path / "mismatched"
    with pytest.raises(HistoricalTreeError, match="revision mismatch"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            mismatched,
            prefixes=(IRON_GUARD,),
        )
    assert not mismatched.exists()


def test_refuses_a_destination_with_a_missing_parent(tmp_path: Path) -> None:
    destination = tmp_path / "missing-parent" / "tree"
    with pytest.raises(HistoricalTreeError, match="parent is missing"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            destination,
            prefixes=(IRON_GUARD,),
        )
    assert not destination.exists()


def test_refuses_existing_or_source_repository_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("untouched", encoding="utf-8")
    with pytest.raises(HistoricalTreeError, match="already exists"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            existing,
            prefixes=(IRON_GUARD,),
        )
    assert marker.read_text(encoding="utf-8") == "untouched"

    inside_repo = REPO_ROOT / f".forbidden-historical-tree-{tmp_path.name}"
    assert not inside_repo.exists()
    with pytest.raises(HistoricalTreeError, match="repository boundary"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            inside_repo,
            prefixes=(IRON_GUARD,),
        )
    assert not inside_repo.exists()

    common_text = gitio._run(REPO_ROOT, ["rev-parse", "--git-common-dir"])
    common = Path(common_text.decode("utf-8").strip())
    if not common.is_absolute():
        common = (REPO_ROOT / common).resolve()
    inside_common = common / f"forbidden-historical-tree-{tmp_path.name}"
    assert not inside_common.exists()
    with pytest.raises(HistoricalTreeError, match="repository boundary"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            inside_common,
            prefixes=(IRON_GUARD,),
        )
    assert not inside_common.exists()

    trusted_temp = tmp_path / "trusted-temp"
    trusted_temp.mkdir()
    outside_temp = tmp_path / "outside-temp"
    assert not outside_temp.exists()
    monkeypatch.setattr(
        historical_fixture, "_repository_boundaries", lambda _repo: set()
    )
    monkeypatch.setattr(
        historical_fixture.tempfile,
        "gettempdir",
        lambda: str(trusted_temp),
    )
    with pytest.raises(HistoricalTreeError, match="OS temporary root"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            outside_temp,
            prefixes=(IRON_GUARD,),
        )
    assert not outside_temp.exists()


def test_repository_boundaries_include_main_admin_common_and_linked_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "current"
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    source.mkdir()
    main.mkdir()
    linked.mkdir()
    common = main / ".git"
    admin = common / "worktrees" / "current"
    sibling_admin = common / "worktrees" / "linked"
    admin.mkdir(parents=True)
    sibling_admin.mkdir()
    linked_gitdir = linked / ".git"
    linked_gitdir.write_text("gitdir marker", encoding="utf-8")
    (sibling_admin / "gitdir").write_text(str(linked_gitdir), encoding="utf-8")

    answers = {
        "--show-toplevel": source,
        "--absolute-git-dir": admin,
        "--git-common-dir": common,
    }

    def fake_run(repo: Path, args: list[str]) -> bytes:
        if args[-1] == "--show-toplevel" and repo.resolve() == main.resolve():
            return str(main).encode("utf-8")
        return str(answers[args[-1]]).encode("utf-8")

    monkeypatch.setattr(gitio, "_run", fake_run)
    protected = historical_fixture._repository_boundaries(source.resolve())

    assert source.resolve() in protected
    assert main.resolve() in protected
    assert common.resolve() in protected
    assert admin.resolve() in protected
    assert linked.resolve() in protected
    assert linked_gitdir.resolve() in protected


@pytest.mark.parametrize("admin_relative", ("central-admin", "admin-root/.git"))
def test_separate_git_dir_layout_fails_closed_before_main_worktree_write(
    tmp_path: Path,
    admin_relative: str,
) -> None:
    primary = tmp_path / "primary"
    central_admin = tmp_path / admin_relative
    linked = tmp_path / "linked"
    central_admin.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "init",
            "--quiet",
            "--separate-git-dir",
            str(central_admin),
            str(primary),
        ],
        capture_output=True,
        check=True,
    )
    (primary / "seed.txt").write_text("historical evidence\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(primary), "add", "seed.txt"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=historical fixture",
            "commit",
            "--quiet",
            "-m",
            "seed",
        ],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "worktree",
            "add",
            "--quiet",
            "-b",
            "linked-fixture",
            str(linked),
        ],
        capture_output=True,
        check=True,
    )
    revision = (
        subprocess.run(
            ["git", "-C", str(linked), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    destination = primary / "forbidden-tree"
    if admin_relative == "central-admin":
        with pytest.raises(HistoricalTreeError, match="non-conventional"):
            historical_fixture._repository_boundaries(linked.resolve())
        expected = "non-conventional"
    else:
        protected = historical_fixture._repository_boundaries(linked.resolve())
        assert primary.resolve() not in protected
        expected = "Git worktree marker"

    with pytest.raises(HistoricalTreeError, match=expected):
        materialize_historical_tree(
            linked,
            revision,
            destination,
            prefixes=("seed.txt",),
        )
    assert not destination.exists()

    if admin_relative == "admin-root/.git":
        safe_sibling = tmp_path / "safe-sibling-tree"
        result = materialize_historical_tree(
            linked,
            revision,
            safe_sibling,
            prefixes=("seed.txt",),
        )
        assert result.blob_count == 1
        assert (safe_sibling / "seed.txt").read_text(encoding="utf-8") == (
            "historical evidence\n"
        )


def test_truncated_or_missing_batch_blob_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = gitio.read_blobs

    def corrupt(repo: Path, shas) -> dict[str, bytes]:
        blobs = real_read(repo, shas)
        first = next(iter(blobs))
        blobs[first] += b"mutant"
        return blobs

    monkeypatch.setattr(gitio, "read_blobs", corrupt)
    destination = tmp_path / "corrupt"
    with pytest.raises(HistoricalTreeError, match="size mismatch"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            destination,
            prefixes=(IRON_GUARD,),
        )
    assert not destination.exists()

    monkeypatch.setattr(gitio, "read_blobs", lambda _repo, _shas: {})
    missing = tmp_path / "missing-blob"
    with pytest.raises(HistoricalTreeError, match="blob is missing"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            missing,
            prefixes=(IRON_GUARD,),
        )
    assert not missing.exists()


def test_same_length_digest_mutant_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = gitio.read_blobs

    def mutate(repo: Path, shas) -> dict[str, bytes]:
        blobs = real_read(repo, shas)
        first = next(iter(blobs))
        payload = bytearray(blobs[first])
        payload[0] ^= 1
        blobs[first] = bytes(payload)
        return blobs

    monkeypatch.setattr(gitio, "read_blobs", mutate)
    destination = tmp_path / "digest-mutant"
    with pytest.raises(HistoricalTreeError, match="digest mismatch"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            destination,
            prefixes=(IRON_GUARD,),
        )
    assert not destination.exists()


@pytest.mark.parametrize(
    ("raw_tree", "message"),
    (
        (
            b"120000 blob 0000000000000000000000000000000000000000 3\ttools/link\0",
            "non-regular",
        ),
        (
            b"160000 commit 0000000000000000000000000000000000000000 1\ttools/submodule\0",
            "non-regular",
        ),
        (
            b"100644 blob 0000000000000000000000000000000000000000 1\tother/file.py\0",
            "outside the selection",
        ),
    ),
)
def test_refuses_nonregular_or_out_of_selection_tree_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_tree: bytes,
    message: str,
) -> None:
    monkeypatch.setattr(gitio, "rev_parse", lambda _repo, _rev: SOURCE_REVISION)
    monkeypatch.setattr(gitio, "_run", lambda _repo, _args: raw_tree)
    monkeypatch.setattr(
        historical_fixture,
        "_repository_boundaries",
        lambda _repo: {REPO_ROOT},
    )
    monkeypatch.setattr(
        gitio,
        "read_blobs",
        lambda _repo, _shas: pytest.fail("invalid tree reached blob reading"),
    )
    destination = tmp_path / "invalid-tree"
    with pytest.raises(HistoricalTreeError, match=message):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            destination,
            prefixes=("tools",),
        )
    assert not destination.exists()


@pytest.mark.parametrize(
    ("left", "right"),
    (
        ("tools/Foo/a.py", "tools/foo/b.py"),
        (
            "tools/caf\N{LATIN SMALL LETTER E WITH ACUTE}/a.py",
            "tools/cafe\N{COMBINING ACUTE ACCENT}/b.py",
        ),
    ),
)
def test_refuses_case_or_unicode_collisions_before_blob_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    left: str,
    right: str,
) -> None:
    raw_tree = (
        f"100644 blob {'1' * 40} 1\t{left}\0"
        f"100644 blob {'2' * 40} 1\t{right}\0"
    ).encode("utf-8")
    monkeypatch.setattr(gitio, "rev_parse", lambda _repo, _rev: SOURCE_REVISION)
    monkeypatch.setattr(gitio, "_run", lambda _repo, _args: raw_tree)
    monkeypatch.setattr(
        historical_fixture,
        "_repository_boundaries",
        lambda _repo: {REPO_ROOT},
    )
    monkeypatch.setattr(
        gitio,
        "read_blobs",
        lambda _repo, _shas: pytest.fail("collision reached blob reading"),
    )
    destination = tmp_path / "collision"
    with pytest.raises(HistoricalTreeError, match="collide"):
        materialize_historical_tree(
            REPO_ROOT,
            SOURCE_REVISION,
            destination,
            prefixes=("tools",),
        )
    assert not destination.exists()


def _snapshot_files(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(
        candidate for candidate in root.rglob("*") if candidate.is_file()
    ):
        stat = path.stat()
        snapshot[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return snapshot


@pytest.mark.parametrize("filter_spec", ("blob:none", "tree:0"))
def test_promisor_objects_never_trigger_transport_or_source_writes(
    tmp_path: Path, filter_spec: str
) -> None:
    origin = tmp_path / "origin"
    partial = tmp_path / "partial"
    subprocess.run(
        ["git", "init", "--quiet", str(origin)],
        capture_output=True,
        check=True,
    )
    selected = origin / "selected"
    selected.mkdir()
    evidence = selected / "evidence.txt"
    evidence.write_text("promised historical evidence\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(origin), "add", "selected/evidence.txt"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(origin),
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=historical fixture",
            "commit",
            "--quiet",
            "-m",
            "seed promised evidence",
        ],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(origin),
            "config",
            "uploadpack.allowFilter",
            "true",
        ],
        capture_output=True,
        check=True,
    )
    revision = (
        subprocess.run(
            ["git", "-C", str(origin), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    blob_sha = (
        subprocess.run(
            ["git", "-C", str(origin), "rev-parse", "HEAD:selected/evidence.txt"],
            capture_output=True,
            check=True,
        )
        .stdout.decode("ascii")
        .strip()
    )
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            f"--filter={filter_spec}",
            "--no-checkout",
            origin.resolve().as_uri(),
            str(partial),
        ],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(partial),
            "config",
            "protocol.file.allow",
            "always",
        ],
        capture_output=True,
        check=True,
    )
    missing_command = [
        "git",
        "-C",
        str(partial),
        "rev-list",
        "--objects",
        "--missing=print",
        "--no-object-names",
    ]
    if filter_spec == "tree:0":
        missing_command.append(revision)
    else:
        missing_command.extend((revision, "--", "selected"))
    missing_probe = subprocess.run(
        missing_command,
        capture_output=True,
        check=True,
    ).stdout.decode("ascii")
    assert any(line.startswith("?") for line in missing_probe.splitlines())

    before = _snapshot_files(partial)
    destination = tmp_path / f"materialized-{filter_spec.replace(':', '-')}"
    with pytest.raises(HistoricalTreeError):
        materialize_historical_tree(
            partial,
            revision,
            destination,
            prefixes=("selected",),
        )
    assert not destination.exists()
    assert gitio.read_blobs(partial, [blob_sha]) == {}
    assert _snapshot_files(partial) == before

    still_missing = subprocess.run(
        missing_command,
        capture_output=True,
        check=True,
    ).stdout.decode("ascii")
    assert any(line.startswith("?") for line in still_missing.splitlines())
