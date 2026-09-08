"""Entry-time path refusal at the shipped door, before any invocation writer.

The first-writer tripwire makes the red baseline safe even for source overlap.
All seeded files and actual aliases belong to pytest temporary directories.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from daedalus.ignition import gate1
from daedalus.ignition.runner import IgnitionError


class FirstWriteReached(RuntimeError):
    pass


def _inventory(root: Path) -> dict:
    result = {}

    def visit(path):
        info = path.lstat()
        link = stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
        result[path.relative_to(root).as_posix()] = (
            info.st_mode, info.st_dev, info.st_ino, info.st_nlink,
            path.read_bytes() if stat.S_ISREG(info.st_mode) and not link else None,
        )
        if stat.S_ISDIR(info.st_mode) and not link:
            for child in path.iterdir():
                visit(child)

    visit(root)
    return result


@pytest.fixture
def layout(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(gate1.DEFAULT_FIXTURE, source)
    receipts = tmp_path / "receipts"
    mission = receipts / gate1.SESSION_MISSION_ID
    for part in ("store/blobs", "store/locators", "source-trees/objects"):
        directory = mission / part
        directory.mkdir(parents=True)
        (directory / "retained").write_bytes(b"prior evidence, must survive refusal\n")
    (mission / "receipt.json").write_bytes(b'{"prior":true}\n')
    return dict(fixture_root=source, receipt_root=receipts, workspace=tmp_path / "work")


def _trip_writers(monkeypatch):
    def trip(*args, **kwargs):
        raise FirstWriteReached("a refused invocation reached a writer")

    monkeypatch.setattr(gate1, "_reset_evidence_store", trip)
    monkeypatch.setattr(gate1, "SourceTreeStore", trip)
    monkeypatch.setattr(gate1.shutil, "copytree", trip)
    monkeypatch.setattr(gate1.tempfile, "mkdtemp", trip)
    monkeypatch.setattr(gate1.tempfile, "gettempdir", trip)
    monkeypatch.setattr(gate1.subprocess, "run", trip)
    monkeypatch.setattr(Path, "mkdir", trip)


def _refuses_cleanly(tmp_path, layout, monkeypatch, *, match=None):
    before = _inventory(tmp_path)
    with monkeypatch.context() as patcher:
        _trip_writers(patcher)
        with pytest.raises(IgnitionError, match=match):
            gate1.run_gate1_ignition(**layout)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("case", [
    "work-source-equal", "work-source-inside", "work-source-contains",
    "receipts-source-equal", "receipts-source-inside", "receipts-source-contains",
    "cas-source-equal", "cas-source-inside", "cas-source-contains",
    "work-receipts-equal", "work-receipts-inside", "work-receipts-contains",
    "work-cas-equal", "work-cas-inside", "work-cas-contains",
    "cas-receipts-equal", "cas-receipts-contains",
    "cas-store-equal", "cas-store-inside", "cas-store-contains",
    "cas-bundle-equal", "cas-bundle-inside", "cas-bundle-contains",
    "cas-receipt-equal", "cas-receipt-inside",
    "work-installation-equal", "work-installation-inside", "work-installation-contains",
])
def test_forbidden_topology_preserves_all_prior_bytes_and_identities(case, layout, tmp_path, monkeypatch):
    role, other, relation = case.split("-")
    mission = layout["receipt_root"] / gate1.SESSION_MISSION_ID
    roots = {"source": layout["fixture_root"], "receipts": layout["receipt_root"],
             "cas": tmp_path / "external-cas", "store": mission / "store",
             "bundle": mission / "bundle", "receipt": mission / "receipt.json",
             "installation": gate1.ROOT}
    if other == "cas":
        layout["source_tree_store_root"] = roots[other]
    target = roots[other]
    target = target / "nested" if relation == "inside" else target.parent if relation == "contains" else target
    layout[{"work": "workspace", "receipts": "receipt_root", "cas": "source_tree_store_root"}[role]] = target
    _refuses_cleanly(tmp_path, layout, monkeypatch)


@pytest.mark.parametrize("debris", ["target", "candidate", "candidate.tar", "patch-1.diff",
    "spine.sqlite3", "spine.sqlite3-wal", "spine.sqlite3-shm", "controls", "coverage",
    ".hidden", "unrelated.txt"])
def test_every_workspace_child_refuses_before_evidence_reset(debris, layout, tmp_path, monkeypatch):
    layout["workspace"].mkdir()
    (layout["workspace"] / debris).write_bytes(b"interrupted invocation")
    _refuses_cleanly(tmp_path, layout, monkeypatch, match="workspace.*empty")


@pytest.mark.parametrize("pair", ["work-receipts", "work-cas"])
@pytest.mark.parametrize("relation", ["equal", "inside", "contains"])
def test_forbidden_missing_roots_are_compared_without_debris_masking(pair, relation, layout, tmp_path, monkeypatch):
    outer = tmp_path / "not-created"
    inner = outer / "nested"
    layout["workspace"] = inner if relation == "inside" else outer
    other = inner if relation == "contains" else outer
    layout["receipt_root" if pair == "work-receipts" else "source_tree_store_root"] = other
    assert not outer.exists()
    _refuses_cleanly(tmp_path, layout, monkeypatch)


def test_cas_containing_source_refuses_without_other_overlapping_roles(layout, tmp_path, monkeypatch):
    parent = tmp_path / "source-parent"
    parent.mkdir()
    source = parent / "source"
    shutil.move(str(layout["fixture_root"]), source)
    layout["fixture_root"] = source
    layout["source_tree_store_root"] = parent
    _refuses_cleanly(tmp_path, layout, monkeypatch)


def test_uninspectable_workspace_ground_is_not_disjoint(layout, tmp_path, monkeypatch):
    ground = tmp_path / "unknown-ground"
    ground.mkdir()
    layout["workspace"] = ground / "work"
    original = Path.lstat
    def fail_ground(path, *args, **kwargs):
        if path == ground:
            raise PermissionError("uninspectable ground")
        return original(path, *args, **kwargs)
    # Snapshot first; this injected observation failure must not prevent the
    # test's independent post-refusal byte and identity inventory.
    before = _inventory(tmp_path)
    with monkeypatch.context() as patcher:
        _trip_writers(patcher)
        patcher.setattr(Path, "lstat", fail_ground)
        with pytest.raises(IgnitionError):
            gate1.run_gate1_ignition(**layout)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("role", ["fixture_root", "receipt_root", "workspace", "source_tree_store_root"])
def test_empty_explicit_path_is_not_a_default(role, layout, tmp_path, monkeypatch):
    layout[role] = ""
    _refuses_cleanly(tmp_path, layout, monkeypatch)


@pytest.mark.parametrize("relative", ["", "store", "store/blobs", "store/locators", "bundle", "source-trees", "source-trees/objects"])
def test_wrong_derived_directory_type_refuses_before_reset(relative, tmp_path, monkeypatch):
    source = tmp_path / "source"
    shutil.copytree(gate1.DEFAULT_FIXTURE, source)
    receipts = tmp_path / "receipts"
    target = receipts / gate1.SESSION_MISSION_ID / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not a directory")
    _refuses_cleanly(tmp_path, dict(fixture_root=source, receipt_root=receipts,
                                  workspace=tmp_path / "work"), monkeypatch)


def _symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"real filesystem symlink unavailable: {exc}")


@pytest.mark.parametrize("relative", ["", "store", "store/blobs", "store/locators", "bundle", "receipt.json", "source-trees/objects"])
def test_redirected_derived_path_refuses_before_reset(relative, tmp_path, monkeypatch):
    source = tmp_path / "source"
    shutil.copytree(gate1.DEFAULT_FIXTURE, source)
    receipts = tmp_path / "receipts"
    link = receipts / gate1.SESSION_MISSION_ID / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    _symlink(link, source)
    _refuses_cleanly(tmp_path, dict(fixture_root=source, receipt_root=receipts,
                                  workspace=tmp_path / "work"), monkeypatch)


def test_raw_redirect_followed_by_parent_is_still_refused(layout, tmp_path, monkeypatch):
    link = tmp_path / "alias"
    _symlink(link, layout["fixture_root"])
    layout["workspace"] = str(link) + os.sep + ".." + os.sep + "safe"
    _refuses_cleanly(tmp_path, layout, monkeypatch)


@pytest.mark.skipif(os.name != "nt", reason="real Windows junction and DOS spelling contract")
def test_raw_junction_followed_by_parent_is_still_refused(layout, tmp_path, monkeypatch):
    junction = tmp_path / "junction"
    result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(layout["fixture_root"])], capture_output=True)
    if result.returncode:
        pytest.skip(f"real junction unavailable: {result.stderr!r}")
    assert junction.lstat().st_file_attributes & 0x400
    layout["workspace"] = str(junction) + "\\..\\safe"
    _refuses_cleanly(tmp_path, layout, monkeypatch)


@pytest.mark.skipif(os.name != "nt", reason="Windows DOS path spelling contract")
@pytest.mark.parametrize("spelling", ["tail.", "tail ", "NUL", "CON.txt", "COM1", "file:stream", "drive-relative", "unc", "extended"])
def test_windows_alias_spellings_refuse_before_writes(spelling, layout, tmp_path, monkeypatch):
    raw = str(tmp_path / spelling)
    if spelling == "drive-relative":
        raw = tmp_path.drive + "relative"
    elif spelling == "unc":
        raw = "\\\\localhost\\C$\\unsafe"
    elif spelling == "extended":
        raw = "\\\\?\\" + str(tmp_path / "unsafe")
    layout["workspace"] = raw
    _refuses_cleanly(tmp_path, layout, monkeypatch)


def test_hardlinked_receipt_cannot_truncate_source(layout, tmp_path, monkeypatch):
    receipt = layout["receipt_root"] / gate1.SESSION_MISSION_ID / "receipt.json"
    receipt.unlink()
    source_file = next(path for path in layout["fixture_root"].rglob("*") if path.is_file())
    try:
        os.link(source_file, receipt)
    except OSError as exc:
        pytest.skip(f"real filesystem hardlink unavailable: {exc}")
    assert receipt.stat().st_nlink == 2
    _refuses_cleanly(tmp_path, layout, monkeypatch)


@pytest.mark.parametrize("case", ["fresh", "empty", "external-cas", "nested-cas", "all-missing", "missing-siblings", "default-workspace", "default-receipts"])
def test_valid_layouts_reach_first_writer_without_probing_or_allocating(case, layout, tmp_path, monkeypatch):
    if case == "empty":
        layout["workspace"].mkdir()
    elif case == "external-cas":
        layout["source_tree_store_root"] = tmp_path / "new-cas"
    elif case == "nested-cas":
        layout["source_tree_store_root"] = layout["receipt_root"] / "other" / "cas"
    elif case == "all-missing":
        layout["receipt_root"] = tmp_path / "new-receipts"
    elif case == "missing-siblings":
        layout["workspace"] = tmp_path / "missing-parent" / "work"
        layout["receipt_root"] = tmp_path / "missing-parent" / "receipts"
        layout["source_tree_store_root"] = tmp_path / "missing-parent" / "cas"
    elif case == "default-workspace":
        layout.pop("workspace")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
    elif case == "default-receipts":
        # An installation-owned output namespace is legitimate. No real write
        # takes place: the first writer is the tripwire in every positive cell.
        monkeypatch.setattr(gate1, "ROOT", tmp_path / "installation")
        gate1.ROOT.mkdir()
        layout["receipt_root"] = gate1.ROOT / "runs" / "ignition"
    before = _inventory(tmp_path)
    with monkeypatch.context() as patcher:
        _trip_writers(patcher)
        def accepted(root):
            assert root == Path(layout["receipt_root"]).resolve() / gate1.SESSION_MISSION_ID / "store"
            raise FirstWriteReached("admitted reset")
        patcher.setattr(gate1, "_reset_evidence_store", accepted)
        with pytest.raises(FirstWriteReached, match="admitted reset"):
            gate1.run_gate1_ignition(**layout)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("parent", ["source", "absent"])
def test_unsafe_configured_default_temp_parent_refuses_without_fallback(parent, layout, tmp_path, monkeypatch):
    layout.pop("workspace")
    monkeypatch.setenv("TMPDIR", str(layout["fixture_root"] if parent == "source" else tmp_path / "absent-temp"))
    _refuses_cleanly(tmp_path, layout, monkeypatch)


def test_default_workspace_allocates_exactly_the_admitted_leaf(layout, tmp_path, monkeypatch):
    layout.pop("workspace")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    admitted = []
    original = gate1._admit_ignition_layout
    def observe(*args, **kwargs):
        result = original(*args, **kwargs)
        admitted.append(result.workspace)
        assert not result.workspace.exists()
        return result
    monkeypatch.setattr(gate1, "_admit_ignition_layout", observe)
    # Bypass the already-admitted stores only to observe scratch allocation;
    # no attempt, subprocess, or real store write is part of this discriminator.
    monkeypatch.setattr(gate1, "_reset_evidence_store", lambda root: root)
    monkeypatch.setattr(gate1, "SourceTreeStore", lambda root: None)
    monkeypatch.setattr(gate1.ignition_bundle, "evaluator_bundle", lambda *args, **kwargs: {})
    monkeypatch.setattr(gate1.ignition_bundle, "bundle_blockers", lambda bundle: [])
    def allocate(path, *args, **kwargs):
        assert admitted == [path]
        assert kwargs["exist_ok"] is False
        raise FirstWriteReached("exact admitted scratch allocation")
    monkeypatch.setattr(Path, "mkdir", allocate)
    def no_temp_probe(*args, **kwargs):
        raise AssertionError("temporary path was probed or selected again")
    monkeypatch.setattr(gate1.tempfile, "gettempdir", no_temp_probe)
    monkeypatch.setattr(gate1.tempfile, "mkdtemp", no_temp_probe)
    with pytest.raises(FirstWriteReached, match="exact admitted scratch allocation"):
        gate1.run_gate1_ignition(**layout)


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("keep", [False, True])
def test_only_owned_automatic_workspace_is_cleaned_after_preparation_failure(automatic, keep, layout, tmp_path, monkeypatch):
    if automatic:
        layout.pop("workspace")
        monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(gate1, "_reset_evidence_store", lambda root: root)
    monkeypatch.setattr(gate1, "SourceTreeStore", lambda root: None)
    monkeypatch.setattr(gate1.ignition_bundle, "evaluator_bundle", lambda *args, **kwargs: {})
    monkeypatch.setattr(gate1.ignition_bundle, "bundle_blockers", lambda bundle: [])
    observed = []
    def fail_preparation(source, destination):
        observed.append(destination.parent)
        assert destination.parent.is_dir()
        raise FirstWriteReached("stop at preparation")
    monkeypatch.setattr(gate1, "prepare_ignition_repo", fail_preparation)
    with pytest.raises(FirstWriteReached, match="stop at preparation"):
        gate1.run_gate1_ignition(**layout, keep_workspace=keep)
    assert len(observed) == 1
    assert observed[0].exists() is (keep or not automatic)


@pytest.mark.parametrize("relation", ["equal", "inside", "contains", "installation"])
def test_direct_preparation_refuses_before_copy(relation, layout, tmp_path, monkeypatch):
    source = layout["fixture_root"]
    destination = {"equal": source, "inside": source / "target", "contains": source.parent,
                   "installation": gate1.ROOT / "uncreated-ignition-target"}[relation]
    before = _inventory(tmp_path)
    with monkeypatch.context() as patcher:
        _trip_writers(patcher)
        with pytest.raises(IgnitionError):
            gate1.prepare_ignition_repo(source, destination)
    assert _inventory(tmp_path) == before


def test_direct_preparation_accepts_a_fresh_separate_destination(layout, tmp_path):
    before = _inventory(layout["fixture_root"])
    prepared, revision = gate1.prepare_ignition_repo(layout["fixture_root"], tmp_path / "prepared")
    assert prepared == tmp_path / "prepared"
    assert len(revision) == 40
    assert (prepared / gate1.ignition_checks.CONFORMANCE_TEST_PATH).is_file()
    assert _inventory(layout["fixture_root"]) == before
