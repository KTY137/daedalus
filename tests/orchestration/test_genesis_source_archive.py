from __future__ import annotations

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

import pytest

from daedalus.orchestration.genesis import read_genesis_source_archive
from daedalus.orchestration.genesis import service
from daedalus.spine.killswitch import KillSwitch


@pytest.fixture(scope="module")
def candidates(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("genesis-source-archive")
    authority = root / "authority"
    authority.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DAEDALUS_KILLSWITCH", str(root / "control" / "killswitch"))
        results = {}
        for profile, prompt, target in (
            ("collection", "Build a local task board with search", "web"),
            ("kanban", "Build a local kanban board with search", "web"),
            ("cli", "Create a command-line task tracker", "cli"),
        ):
            result = service.run_genesis(
                prompt, target=target, request_key=f"genesis:archive:{profile}",
                repo_root=authority,
            )
            assert result["status"] == ("succeeded" if target == "cli" else "preview-ready")
            results[profile] = result
        yield authority, results


def _store(authority: Path) -> service.SourceTreeStore:
    return service.SourceTreeStore.open_existing(
        service.control_root(authority) / "genesis" / "source-cas"
    )


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("profile", ["collection", "kanban", "cli"])
def test_archive_contains_exact_candidate_and_canonical_provenance(candidates, profile: str) -> None:
    authority, results = candidates
    result = results[profile]
    digest = result["candidate"]["sha256"]
    before = _snapshot(authority)
    payload = read_genesis_source_archive(result["run_id"], digest, repo_root=authority)
    assert payload == read_genesis_source_archive(result["run_id"], digest, repo_root=authority)
    assert _snapshot(authority) == before

    store = _store(authority)
    ref = service.ArtifactRef.from_sha256(digest)
    manifest = store.load_tree(ref)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = ["genesis-run.json", "source-tree.json", *(f"source/{row.path}" for row in manifest.entries)]
        assert archive.namelist() == sorted(names)
        assert archive.testzip() is None
        assert archive.read("source-tree.json") == store.read_bytes(ref, max_bytes=service.MAX_REPORT_BYTES)
        assert hashlib.sha256(archive.read("source-tree.json")).hexdigest() == digest
        assert archive.read("genesis-run.json") == service.canonical_json(result).encode("ascii")
        for row in manifest.entries:
            expected = store.read_bytes(service.ArtifactRef.from_sha256(row.blob_sha256), max_bytes=row.size)
            assert archive.read(f"source/{row.path}") == expected
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.create_system == 3
            assert stat.S_ISREG(info.external_attr >> 16)
            assert not info.extra and not info.comment and not info.is_dir()
    if profile == "cli":
        with pytest.raises(service.GenesisPreviewError, match="no green preview"):
            service.read_genesis_preview(result["run_id"], "app.py", repo_root=authority)


def test_archive_works_with_stopped_switch_without_execution_or_writes(candidates, monkeypatch: pytest.MonkeyPatch) -> None:
    authority, results = candidates
    result = results["kanban"]
    switch = KillSwitch(repo_root=authority)
    switch.stop("archive remains read-only")

    def forbidden(*args, **kwargs):
        pytest.fail("source download attempted to start an effect")

    monkeypatch.setattr(service, "acquire_effect_lease", forbidden)
    monkeypatch.setattr(service, "_ensure_genesis_switch", forbidden)
    monkeypatch.setattr(service, "_run_command", forbidden)
    before = _snapshot(authority.parent)
    assert read_genesis_source_archive(result["run_id"], result["candidate"]["sha256"], repo_root=authority)
    assert _snapshot(authority.parent) == before
    assert switch.read_state().running is False


@pytest.mark.parametrize("run_id,digest", [
    ("genesis-" + "A" * 24, "a" * 64),
    ("../genesis-" + "a" * 24, "a" * 64),
    (None, "a" * 64),
    ("genesis-" + "a" * 24, "A" * 64),
    ("genesis-" + "a" * 24, "a" * 63),
    ("genesis-" + "a" * 24, "a" * 64 + "\n"),
    ("genesis-" + "a" * 24, None),
])
def test_invalid_identity_refuses_before_resolving_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_id, digest) -> None:
    monkeypatch.setattr(service, "_state_paths", lambda *args: pytest.fail("invalid identity reached state reader"))
    with pytest.raises(service.GenesisPreviewError, match="invalid Genesis"):
        read_genesis_source_archive(run_id, digest, repo_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_missing_run_does_not_create_state(tmp_path: Path) -> None:
    with pytest.raises(service.GenesisPreviewError, match="does not exist"):
        read_genesis_source_archive("genesis-" + "a" * 24, "b" * 64, repo_root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_digest_from_another_successful_candidate_refuses(candidates) -> None:
    authority, results = candidates
    with pytest.raises(service.GenesisPreviewError, match="does not match its terminal Attempt receipt"):
        read_genesis_source_archive(
            results["collection"]["run_id"], results["kanban"]["candidate"]["sha256"],
            repo_root=authority,
        )


@pytest.mark.parametrize("artifact", ["candidate", "evidence", "roundtrip", "run_record", "attempt", "report", "source_blob"])
def test_archive_refuses_missing_or_corrupt_authoritative_bytes(candidates, artifact: str) -> None:
    authority, results = candidates
    result = results["kanban"]
    store = _store(authority)
    digest = result["candidate"]["sha256"]
    if artifact == "report":
        ref = service.ArtifactRef.from_sha256(service.canonical_sha(result))
    elif artifact == "source_blob":
        row = next(row for row in store.load_tree(service.ArtifactRef.from_sha256(digest)).entries if row.path == "app.js")
        ref = service.ArtifactRef.from_sha256(row.blob_sha256)
    else:
        ref = service.ArtifactRef.from_sha256(digest if artifact == "candidate" else result["artifacts"][artifact]["sha256"])
    path = store.objects / ref.sha256[:2] / ref.sha256[2:]
    original = path.read_bytes()
    try:
        path.unlink()
        with pytest.raises(service.GenesisPreviewError):
            read_genesis_source_archive(result["run_id"], digest, repo_root=authority)
        path.write_bytes(b"corrupt retained artifact")
        with pytest.raises(service.GenesisPreviewError):
            read_genesis_source_archive(result["run_id"], digest, repo_root=authority)
    finally:
        path.write_bytes(original)


def test_archive_requires_retained_outer_effect_terminal(candidates) -> None:
    authority, results = candidates
    result = results["collection"]
    terminal_root = service.control_root(authority) / "genesis" / "effect-evidence" / result["run_id"] / "lease-terminal"
    records = {path: path.read_bytes() for path in terminal_root.glob("*.json")}
    assert records
    try:
        for path in records:
            path.unlink()
        with pytest.raises(service.GenesisPreviewError, match="terminal evidence is missing"):
            read_genesis_source_archive(result["run_id"], result["candidate"]["sha256"], repo_root=authority)
    finally:
        for path, payload in records.items():
            path.write_bytes(payload)


@pytest.mark.parametrize("state", ["missing", "pending", "failed", "corrupt"])
def test_archive_refuses_non_successful_attempts(candidates, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    authority, results = candidates
    result = results["collection"]

    def lookup(*args, **kwargs):
        if state == "corrupt":
            raise service.AttemptStateError("corrupt terminal Attempt")
        if state == "missing":
            return None
        if state == "pending":
            return SimpleNamespace(completion=None)
        return SimpleNamespace(completion=SimpleNamespace(receipt=SimpleNamespace(outcome="failed", candidate_tree=None)))

    monkeypatch.setattr(service.AttemptLedger, "lookup_read_only", lookup)
    with pytest.raises(service.GenesisPreviewError):
        read_genesis_source_archive(result["run_id"], result["candidate"]["sha256"], repo_root=authority)


def test_archive_preserves_executable_modes_and_refuses_reread_mutation(candidates, monkeypatch: pytest.MonkeyPatch) -> None:
    authority, results = candidates
    result = results["cli"]
    verified = service._read_verified_genesis_candidate(result["run_id"], repo_root=authority, preview_only=False)
    rows = tuple(replace(row, executable=row.path == "app.py") for row in verified.manifest.entries)
    manifest = replace(verified.manifest, entries=rows)
    modified = replace(verified, manifest=manifest, manifest_bytes=manifest.to_json().encode("ascii"))
    monkeypatch.setattr(service, "_read_verified_genesis_candidate", lambda *args, **kwargs: modified)
    payload = read_genesis_source_archive(result["run_id"], manifest.digest, repo_root=authority)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert stat.S_IMODE(archive.getinfo("source/app.py").external_attr >> 16) == 0o755
        assert stat.S_IMODE(archive.getinfo("source/README.md").external_attr >> 16) == 0o644
        assert stat.S_IMODE(archive.getinfo("source-tree.json").external_attr >> 16) == 0o644

    row = next(row for row in rows if row.path == "app.py")
    original_read = service.SourceTreeStore.read_bytes

    def changed_blob(self, ref, *, max_bytes):
        if ref.sha256 == row.blob_sha256:
            return b"!" * row.size
        return original_read(self, ref, max_bytes=max_bytes)

    monkeypatch.setattr(service.SourceTreeStore, "read_bytes", changed_blob)
    with pytest.raises(service.GenesisPreviewError, match="size or digest changed"):
        read_genesis_source_archive(result["run_id"], manifest.digest, repo_root=authority)


def test_archive_refuses_unsafe_path_and_transport_overflow(candidates, monkeypatch: pytest.MonkeyPatch) -> None:
    authority, results = candidates
    result = results["cli"]
    verified = service._read_verified_genesis_candidate(result["run_id"], repo_root=authority, preview_only=False)
    row = verified.manifest.entries[0]
    manifest = replace(verified.manifest, entries=(replace(row, path="nested/stream:alternate"),))
    monkeypatch.setattr(service, "_read_verified_genesis_candidate", lambda *args, **kwargs: replace(verified, manifest=manifest))
    with pytest.raises(service.GenesisPreviewError, match="path is not safe"):
        read_genesis_source_archive(result["run_id"], manifest.digest, repo_root=authority)
    manifest = replace(verified.manifest, entries=(replace(row, size=service.GENESIS_MAX_BYTES + 1),))
    monkeypatch.setattr(service, "_read_verified_genesis_candidate", lambda *args, **kwargs: replace(verified, manifest=manifest))
    with pytest.raises(service.GenesisPreviewError, match="transport bound"):
        read_genesis_source_archive(result["run_id"], manifest.digest, repo_root=authority)
