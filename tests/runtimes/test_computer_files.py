"""Focused acceptance for the handle-anchored workspace file adapter.

Every case uses a disposable workspace below pytest's temporary directory. No
canonical lease, ledger, kill switch or model is involved: the adapter is the
private seam behind the trusted computer service, and this suite measures the
write-root boundary that the v0.1.6 release fence names as its prerequisite.
Directory links use junctions on Windows so no privilege is required.
On POSIX, the autouse fixture lifts only the adapter's private test gate so the
backend keeps producing negative evidence; a dedicated case verifies that the
public release entrypoint refuses every POSIX effect.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from daedalus.kernel.policy import computer as policy_module
from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, FILE_TOOLS
from daedalus.runtimes import computer_files as subject
from daedalus.runtimes.computer_files import WorkspaceFiles


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def link_directory(target: Path, link: Path) -> None:
    """Create a directory reparse point without elevated privileges."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def link_file(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlink creation unavailable on host: {exc}")


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture(autouse=True)
def lowered_fence(monkeypatch):
    """The adapter admits through ``ComputerPolicy.admit``, which applies the v0.1.6 fence.

    These cases exercise the adapter as the fence-lifting packet will see it:
    file tools admitted, path-based vision still fenced. ``test_fence_and_grants``
    restores the full fence explicitly.
    """
    monkeypatch.setattr(policy_module, "RELEASE_DISABLED_TOOLS", frozenset({"vision.match", "vision.changes"}))
    if os.name != "nt":
        # The public host gate stays covered below. Existing cross-platform
        # cases deliberately exercise the private POSIX backend as a bounded
        # experiment; they do not claim that POSIX effects are enabled.
        monkeypatch.setattr(subject, "_effect_host_available", lambda: True)


@pytest.fixture(params=["policy-and-handles", "handles-only"])
def layer(request, monkeypatch):
    """Run link cases twice: with the lexical policy pre-check and without it.

    The second variant replaces the policy's link/resolve pre-check with a pure
    lexical join so the refusal must come from the handle traversal itself.
    """
    if request.param == "handles-only":
        def lexical_only(self, value, *, must_exist=False):
            return self.workspace.joinpath(*[p for p in value.replace("\\", "/").split("/") if p not in ("", ".")])
        monkeypatch.setattr(ComputerPolicy, "path", lexical_only)
    return request.param


def adapter(workspace, checkpoint=lambda: None, **policy_fields):
    policy = ComputerPolicy(workspace=workspace, tools=FILE_TOOLS, **policy_fields)
    return WorkspaceFiles(policy, checkpoint)


def test_fence_and_grants_are_enforced_inside_the_adapter(workspace, monkeypatch):
    monkeypatch.setattr(policy_module, "RELEASE_DISABLED_TOOLS",
                        frozenset(FILE_TOOLS + ("vision.match", "vision.changes")))
    with pytest.raises(ComputerRefused, match="handle-relative"):
        adapter(workspace).execute("file.write", {"path": "x.txt", "text": "y"})
    monkeypatch.setattr(policy_module, "RELEASE_DISABLED_TOOLS", frozenset({"vision.match", "vision.changes"}))
    ungranted = WorkspaceFiles(ComputerPolicy(workspace=workspace, tools=()), lambda: None)
    with pytest.raises(ComputerRefused, match="not enabled"):
        ungranted.execute("file.write", {"path": "x.txt", "text": "y"})
    with pytest.raises(ComputerRefused, match="not enabled"):
        ungranted.execute("file.list", {})
    read_only = WorkspaceFiles(ComputerPolicy(workspace=workspace, tools=("file.read",)), lambda: None)
    with pytest.raises(ComputerRefused, match="not enabled"):
        read_only.execute("file.write", {"path": "x.txt", "text": "y"})
    assert list(workspace.iterdir()) == []


def test_release_host_gate_refuses_every_effect_before_checkpoint_or_backend_handle(workspace, monkeypatch):
    monkeypatch.setattr(subject, "_effect_host_available", lambda: False)

    def checkpoint():
        pytest.fail("checkpoint reached for a release-disabled host effect")

    files = adapter(workspace, checkpoint=checkpoint)
    cases = [("file.write", {"path": "x.txt", "text": "x"}),
             ("file.mkdir", {"path": "dir"}),
             ("file.move", {"source": "a.txt", "destination": "b.txt",
                            "expected_sha256": "0" * 64})]
    for tool, args in cases:
        with pytest.raises(ComputerRefused, match="Windows release target"):
            files.execute(tool, args)
    assert adapter(workspace).execute("file.list", {})["entries"] == []
    assert list(workspace.iterdir()) == []


def test_secret_floor_applies_inside_the_adapter(workspace):
    files = adapter(workspace)
    leaked = "AKIA" + "ABCDEFGHIJKLMNOP"
    with pytest.raises(ComputerRefused, match="secret"):
        files.execute("file.write", {"path": "creds.txt", "text": f"aws {leaked}\n"})
    assert not (workspace / "creds.txt").exists()
    (workspace / "leaked.txt").write_text(f"key {leaked}\n", encoding="utf-8")
    with pytest.raises(ComputerRefused, match="secret") as refusal:
        files.execute("file.read", {"path": "leaked.txt"})
    assert leaked not in str(refusal.value)
    # Cerberus NEW-1: a rename must not launder the floor's path channel
    # (.env -> ok.txt -> readable) nor its content channel.
    (workspace / ".env").write_bytes(b"DB_HOST=prod.internal\n")
    with pytest.raises(ComputerRefused, match="secret"):
        files.execute("file.move", {"source": ".env", "destination": "ok.txt",
                                    "expected_sha256": sha(b"DB_HOST=prod.internal\n")})
    leaked_bytes = (workspace / "leaked.txt").read_bytes()
    with pytest.raises(ComputerRefused, match="secret"):
        files.execute("file.move", {"source": "leaked.txt", "destination": "plain.txt",
                                    "expected_sha256": sha(leaked_bytes)})
    (workspace / "plain.txt").write_bytes(b"plain\n")
    with pytest.raises(ComputerRefused, match="secret"):
        files.execute("file.move", {"source": "plain.txt", "destination": "id_rsa",
                                    "expected_sha256": sha(b"plain\n")})
    assert sorted(p.name for p in workspace.iterdir()) == [".env", "leaked.txt", "plain.txt"]
    assert (workspace / ".env").read_bytes() == b"DB_HOST=prod.internal\n"


def test_read_and_list_admit_through_the_checkpoint_and_verify_the_parent(workspace):
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    (workspace / "sub" / "f.txt").write_text("f", encoding="utf-8")
    outcome: list[str] = []

    def move_out():
        if outcome:
            return
        try:
            (workspace / "sub").rename(outside / "sub")
            outcome.append("moved")
        except PermissionError:
            outcome.append("pinned")

    files = adapter(workspace, checkpoint=move_out)
    for tool, args in (("file.read", {"path": "sub/f.txt"}), ("file.list", {"path": "sub"})):
        outcome.clear()
        try:
            result = files.execute(tool, args)
        except ComputerRefused as exc:
            assert outcome == ["moved"] and "changed during" in str(exc)
            (outside / "sub").rename(workspace / "sub")
        else:
            assert outcome == ["pinned"] and result["postcondition_verified"] is True
        assert list(outside.iterdir()) == []


def test_read_and_list_withhold_content_when_the_parent_drifts_after_the_read(workspace, monkeypatch):
    (workspace / "sub").mkdir()
    (workspace / "sub" / "f.txt").write_text("f", encoding="utf-8")
    files = adapter(workspace)
    real = files._in_place
    calls: list[int] = []

    def drifting(directory, expected):
        calls.append(1)
        return real(directory, expected) if len(calls) == 1 else False

    monkeypatch.setattr(files, "_in_place", drifting)
    # A read or listing whose directory drifted after the data was taken is a
    # refusal with no effect: the data is withheld, never returned.
    with pytest.raises(ComputerRefused, match="withheld") as refusal:
        files.execute("file.read", {"path": "sub/f.txt"})
    assert "f\n" not in str(refusal.value)
    calls.clear()
    with pytest.raises(ComputerRefused, match="withheld"):
        files.execute("file.list", {"path": "sub"})


def test_identity_drift_refuses_before_the_effect_and_is_reported_after_it(workspace, monkeypatch):
    """On Windows the pinned chain makes real drift impossible, so the identity
    check is exercised directly: it must still refuse before an effect and must
    still turn a success into an unverified observation after one."""
    (workspace / "sub").mkdir()
    files = adapter(workspace)
    monkeypatch.setattr(files, "_in_place", lambda directory, expected: False)
    for tool, args in (("file.write", {"path": "sub/x.txt", "text": "x"}), ("file.mkdir", {"path": "sub/d"})):
        with pytest.raises(ComputerRefused, match="changed during"):
            files.execute(tool, args)
    assert list((workspace / "sub").iterdir()) == []
    calls: list[int] = []

    def drift_after_the_effect(directory, expected):
        calls.append(1)
        return len(calls) == 1

    monkeypatch.setattr(files, "_in_place", drift_after_the_effect)
    written = files.execute("file.write", {"path": "sub/x.txt", "text": "x"})
    assert (workspace / "sub" / "x.txt").read_bytes() == b"x"
    assert written["postcondition_verified"] is False and "no longer resolves" in written["detail"]
    calls.clear()
    made = files.execute("file.mkdir", {"path": "sub/d"})
    assert (workspace / "sub" / "d").is_dir()
    assert made["postcondition_verified"] is False and "no longer resolves" in made["detail"]


def test_post_effect_verification_failures_are_reported_not_raised(workspace, monkeypatch):
    files = adapter(workspace)
    real_current = files._current
    calls: list[str] = []

    def flaky(parent, name, shown):
        calls.append(name)
        if calls.count(name) >= 2:
            raise ComputerRefused(f"'{shown}' is hard-linked and refused")
        return real_current(parent, name, shown)

    monkeypatch.setattr(files, "_current", flaky)
    result = files.execute("file.write", {"path": "new.txt", "text": "WRITTEN"})
    assert (workspace / "new.txt").read_bytes() == b"WRITTEN"
    assert result["postcondition_verified"] is False and "hard-linked" in result["detail"]
    calls.clear()
    moved = files.execute("file.move", {"source": "new.txt", "destination": "moved.txt",
                                        "expected_sha256": sha(b"WRITTEN")})
    assert (workspace / "moved.txt").read_bytes() == b"WRITTEN" and not (workspace / "new.txt").exists()
    assert moved["postcondition_verified"] is False and "detail" in moved


def test_keyboard_interrupt_is_not_swallowed_and_leaves_no_temporary(workspace, monkeypatch):
    files = adapter(workspace)
    files.execute("file.write", {"path": "a.txt", "text": "one"})

    def interrupt(fd, data):
        raise KeyboardInterrupt()

    monkeypatch.setattr(subject, "_write_all", interrupt)
    with pytest.raises(subject.ComputerFileInterrupted) as replacement:
        files.execute("file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"one")})
    assert replacement.value.effect_state == "none"
    assert replacement.value.recovery_paths == ()
    with pytest.raises(subject.ComputerFileInterrupted) as creation:
        files.execute("file.write", {"path": "fresh.txt", "text": "x"})
    assert creation.value.effect_state == "none"
    assert creation.value.recovery_paths == ()
    assert (workspace / "a.txt").read_bytes() == b"one"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.txt"]


def test_create_interrupt_reports_uncertain_when_partial_cleanup_cannot_be_verified(workspace, monkeypatch):
    files = adapter(workspace)

    def interrupt(fd, data):
        raise KeyboardInterrupt()

    def refuse_cleanup(parent, name, fd):
        raise subject._HostRefusal("injected cleanup failure")

    monkeypatch.setattr(subject, "_write_all", interrupt)
    monkeypatch.setattr(files._backend, "unlink", refuse_cleanup)
    with pytest.raises(subject.ComputerFileInterrupted) as interruption:
        files.execute("file.write", {"path": "partial.txt", "text": "x"})
    assert interruption.value.effect_state == "uncertain"
    assert interruption.value.recovery_paths == ("partial.txt",)
    assert (workspace / "partial.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="share-mode hold is a Windows property")
def test_replace_holds_the_target_against_writers_until_the_rename(workspace, monkeypatch):
    files = adapter(workspace)
    files.execute("file.write", {"path": "a.txt", "text": "one"})
    backend = files._backend
    real_rename = backend.rename
    attempts: list[str] = []
    calls = 0

    def write_then_rename(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            try:
                with open(workspace / "a.txt", "ab") as stream:
                    stream.write(b"!")
                attempts.append("written")
            except PermissionError:
                attempts.append("held")
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(backend, "rename", write_then_rename)
    result = files.execute("file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"one")})
    assert attempts == ["held"]
    assert calls == 2
    assert result["postcondition_verified"] is True
    assert (workspace / "a.txt").read_bytes() == b"two"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.txt"]


@pytest.mark.skipif(os.name != "nt", reason="Windows replacement share semantics")
def test_replace_does_not_overwrite_a_target_substituted_at_the_final_rename(workspace, monkeypatch):
    files = adapter(workspace)
    files.execute("file.write", {"path": "target.txt", "text": "old"})
    backend = files._backend
    real_rename = backend.rename
    calls = 0

    def substitute_then_rename(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            # The first handle-bound rename has moved the verified original to
            # its reserved backup. Occupy the now-free public name immediately
            # before installation; the second rename must be no-replace.
            (workspace / "target.txt").write_bytes(b"UNOBSERVED")
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(backend, "rename", substitute_then_rename)
    with pytest.raises(subject.ComputerFileEffectUncertain) as uncertain:
        files.execute(
            "file.write", {"path": "target.txt", "text": "new", "expected_sha256": sha(b"old")}
        )
    assert (workspace / "target.txt").read_bytes() == b"UNOBSERVED"
    backups = [path for path in workspace.iterdir() if path.name.endswith(subject._BACKUP_SUFFIX)]
    assert len(backups) == 1 and backups[0].read_bytes() == b"old"
    assert not any(path.name.endswith(subject._TEMPORARY_SUFFIX) for path in workspace.iterdir())
    assert uncertain.value.effect_state == "uncertain"
    assert uncertain.value.recovery_paths == ("target.txt", backups[0].name)
    # Recovery artifacts are service-only: ordinary model-facing paths cannot
    # observe or address them.
    assert files.execute("file.list", {})["entries"] == [{"path": "target.txt", "kind": "file"}]
    with pytest.raises(ComputerRefused, match="recovery paths"):
        files.execute("file.read", {"path": backups[0].name})


@pytest.mark.skipif(os.name != "nt", reason="Windows replacement share semantics")
@pytest.mark.parametrize("after_install", [False, True], ids=["before-install", "after-install"])
def test_replace_interrupt_reports_restored_or_uncertain_state(workspace, monkeypatch, after_install):
    files = adapter(workspace)
    files.execute("file.write", {"path": "target.txt", "text": "old"})
    backend = files._backend
    real_rename = backend.rename
    calls = 0

    def interrupt_install(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if after_install:
                real_rename(*args, **kwargs)
            raise KeyboardInterrupt()
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(backend, "rename", interrupt_install)
    with pytest.raises(subject.ComputerFileInterrupted) as interruption:
        files.execute(
            "file.write", {"path": "target.txt", "text": "new", "expected_sha256": sha(b"old")}
        )
    if after_install:
        assert interruption.value.effect_state == "uncertain"
        assert (workspace / "target.txt").read_bytes() == b"new"
        backups = [path for path in workspace.iterdir() if path.name.endswith(subject._BACKUP_SUFFIX)]
        assert len(backups) == 1 and backups[0].read_bytes() == b"old"
        assert interruption.value.recovery_paths == ("target.txt", backups[0].name)
    else:
        assert interruption.value.effect_state == "none"
        assert interruption.value.recovery_paths == ()
        assert (workspace / "target.txt").read_bytes() == b"old"
        assert sorted(path.name for path in workspace.iterdir()) == ["target.txt"]


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-location evidence")
@pytest.mark.parametrize("after_rename", [False, True], ids=["before-rename", "after-rename"])
def test_move_interrupt_reports_none_or_uncertain_from_the_held_source(workspace, monkeypatch, after_rename):
    files = adapter(workspace)
    files.execute("file.write", {"path": "source.txt", "text": "payload"})
    backend = files._backend
    real_rename = backend.rename

    def interrupt(*args, **kwargs):
        if after_rename:
            real_rename(*args, **kwargs)
        raise KeyboardInterrupt()

    monkeypatch.setattr(backend, "rename", interrupt)
    with pytest.raises(subject.ComputerFileInterrupted) as interruption:
        files.execute(
            "file.move", {"source": "source.txt", "destination": "destination.txt",
                          "expected_sha256": sha(b"payload")}
        )
    if after_rename:
        assert interruption.value.effect_state == "uncertain"
        assert interruption.value.recovery_paths == ("source.txt", "destination.txt")
        assert not (workspace / "source.txt").exists()
        assert (workspace / "destination.txt").read_bytes() == b"payload"
    else:
        assert interruption.value.effect_state == "none"
        assert interruption.value.recovery_paths == ()
        assert (workspace / "source.txt").read_bytes() == b"payload"
        assert not (workspace / "destination.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="share-mode hold is a Windows property")
@pytest.mark.parametrize("replace", [False, True], ids=["new-file", "replacement-temporary"])
def test_created_effect_file_excludes_competing_writers_and_renames(workspace, monkeypatch, replace):
    files = adapter(workspace)
    if replace:
        files.execute("file.write", {"path": "target.txt", "text": "old"})
    real_write_all = subject._write_all
    attempts: list[str] = []

    def write_then_interfere(fd, data):
        real_write_all(fd, data)
        if replace:
            candidates = [p for p in workspace.iterdir() if p.name.endswith(subject._TEMPORARY_SUFFIX)]
            assert len(candidates) == 1
            target = candidates[0]
        else:
            target = workspace / "new.txt"
        try:
            with open(target, "ab") as stream:
                stream.write(b"!")
            attempts.append("written")
        except PermissionError:
            attempts.append("write-held")
        try:
            target.rename(workspace / "stolen.txt")
            attempts.append("renamed")
        except PermissionError:
            attempts.append("rename-held")

    monkeypatch.setattr(subject, "_write_all", write_then_interfere)
    if replace:
        result = files.execute(
            "file.write", {"path": "target.txt", "text": "new", "expected_sha256": sha(b"old")}
        )
        destination = workspace / "target.txt"
    else:
        result = files.execute("file.write", {"path": "new.txt", "text": "new"})
        destination = workspace / "new.txt"
    assert attempts == ["write-held", "rename-held"]
    assert result["postcondition_verified"] is True
    assert destination.read_bytes() == b"new"
    assert not (workspace / "stolen.txt").exists()
    assert not any(p.name.endswith(subject._TEMPORARY_SUFFIX) for p in workspace.iterdir())


@pytest.mark.skipif(os.name != "nt", reason="share-mode hold is a Windows property")
def test_move_holds_the_source_against_writers_and_renames_until_rename(workspace, monkeypatch):
    files = adapter(workspace)
    files.execute("file.write", {"path": "a.txt", "text": "one"})
    backend = files._backend
    real_rename = backend.rename
    attempts: list[str] = []

    def interfere_then_rename(*args, **kwargs):
        try:
            with open(workspace / "a.txt", "ab") as stream:
                stream.write(b"!")
            attempts.append("written")
        except PermissionError:
            attempts.append("write-held")
        try:
            (workspace / "a.txt").rename(workspace / "stolen.txt")
            attempts.append("renamed")
        except PermissionError:
            attempts.append("rename-held")
        return real_rename(*args, **kwargs)

    monkeypatch.setattr(backend, "rename", interfere_then_rename)
    result = files.execute(
        "file.move", {"source": "a.txt", "destination": "b.txt", "expected_sha256": sha(b"one")}
    )
    assert attempts == ["write-held", "rename-held"]
    assert result["postcondition_verified"] is True
    assert not (workspace / "a.txt").exists() and not (workspace / "stolen.txt").exists()
    assert (workspace / "b.txt").read_bytes() == b"one"


@pytest.mark.skipif(os.name != "nt", reason="Windows NT backend")
def test_nt_checked_refuses_type_confusion_independently_of_create_options(workspace):
    backend = subject._NTBackend()
    (workspace / "dir").mkdir()
    (workspace / "f.txt").write_text("f", encoding="utf-8")
    root = backend.open_root(workspace)
    try:
        cases = (("dir", backend._FILE_DIRECTORY_FILE, False), ("f.txt", backend._FILE_NON_DIRECTORY_FILE, True))
        for name, options, directory in cases:
            handle = backend._open(root.raw, name, backend._FILE_READ_ATTRIBUTES, backend._FILE_OPEN, options)
            with pytest.raises(subject._HostRefusal, match="directory"):
                backend._checked(handle, directory=directory)
    finally:
        backend.close_directory(root)


def test_write_then_read_round_trip_verifies_through_handles(workspace):
    files = adapter(workspace)
    written = files.execute("file.write", {"path": "hello.txt", "text": "Hello Ikarus\n"})
    assert written == {"path": "hello.txt", "sha256": sha(b"Hello Ikarus\n"), "bytes": 13,
                       "postcondition_verified": True}
    assert (workspace / "hello.txt").read_bytes() == b"Hello Ikarus\n"
    read = files.execute("file.read", {"path": "hello.txt"})
    assert read == {"path": "hello.txt", "text": "Hello Ikarus\n", "sha256": sha(b"Hello Ikarus\n"),
                    "bytes": 13, "postcondition_verified": True}
    json.dumps(written, allow_nan=False)
    json.dumps(read, allow_nan=False)


def test_unicode_names_and_content_round_trip(workspace):
    files = adapter(workspace)
    files.execute("file.mkdir", {"path": "Ünïcödé"})
    files.execute("file.write", {"path": "Ünïcödé/名前.txt", "text": "grüß 🙂"})
    assert files.execute("file.read", {"path": "Ünïcödé/名前.txt"})["text"] == "grüß 🙂"
    assert files.execute("file.list", {"path": "Ünïcödé"})["entries"] == [
        {"path": "Ünïcödé/名前.txt", "kind": "file"}]


def test_astral_unicode_filename_is_not_truncated_on_windows(workspace):
    files = adapter(workspace)
    name = "\U0001f642-名前.txt"
    result = files.execute("file.write", {"path": name, "text": "hello"})
    assert result["postcondition_verified"] is True
    assert files.execute("file.read", {"path": name})["text"] == "hello"
    assert [entry.name for entry in workspace.iterdir()] == [name]


def test_replacing_requires_the_current_hash_and_leaves_no_temporary_file(workspace):
    files = adapter(workspace)
    files.execute("file.write", {"path": "a.txt", "text": "one"})
    with pytest.raises(ComputerRefused, match="expected_sha256"):
        files.execute("file.write", {"path": "a.txt", "text": "two"})
    with pytest.raises(ComputerRefused, match="expected_sha256"):
        files.execute("file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"stale")})
    assert (workspace / "a.txt").read_bytes() == b"one"
    result = files.execute("file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"one")})
    assert result == {"path": "a.txt", "sha256": sha(b"two"), "bytes": 3, "postcondition_verified": True}
    assert (workspace / "a.txt").read_bytes() == b"two"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.txt"]
    with pytest.raises(ComputerRefused, match="no longer exists"):
        files.execute("file.write", {"path": "b.txt", "text": "x", "expected_sha256": sha(b"one")})
    assert not (workspace / "b.txt").exists()


def test_failed_temporary_write_leaves_the_original_and_no_temporary(workspace, monkeypatch):
    files = adapter(workspace)
    files.execute("file.write", {"path": "a.txt", "text": "one"})

    def failing(fd, data):
        raise OSError("injected disk failure")

    monkeypatch.setattr(subject, "_write_all", failing)
    with pytest.raises(ComputerRefused, match="injected disk failure"):
        files.execute("file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"one")})
    with pytest.raises(ComputerRefused, match="injected disk failure"):
        files.execute("file.write", {"path": "fresh.txt", "text": "two"})
    assert (workspace / "a.txt").read_bytes() == b"one"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.txt"]


def test_ancestor_swap_attempt_at_the_checkpoint_remains_confined(workspace):
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    outcome = []

    def swap_checked_ancestor():
        if outcome:
            return
        try:
            (workspace / "sub").rename(workspace / "sub-original")
        except PermissionError:
            outcome.append("pinned")
            return
        link_directory(outside, workspace / "sub")
        outcome.append("moved")

    files = adapter(workspace, checkpoint=swap_checked_ancestor)
    try:
        result = files.execute("file.write", {"path": "sub/escaped.txt", "text": "escaped"})
    except ComputerRefused as exc:
        assert outcome == ["moved"] and "changed during" in str(exc)
    else:
        assert outcome == ["pinned"] and result["postcondition_verified"] is True
    assert list(outside.iterdir()) == []
    if outcome == ["moved"]:
        assert not (workspace / "sub-original" / "escaped.txt").exists()
        (workspace / "sub").unlink() if os.name != "nt" else os.rmdir(workspace / "sub")
        (workspace / "sub-original").rename(workspace / "sub")
    else:
        assert (workspace / "sub" / "escaped.txt").read_bytes() == b"escaped"
        (workspace / "sub" / "escaped.txt").unlink()

    outcome.clear()
    try:
        result = files.execute("file.mkdir", {"path": "sub/child"})
    except ComputerRefused as exc:
        assert outcome == ["moved"] and "changed during" in str(exc)
    else:
        assert outcome == ["pinned"] and result["postcondition_verified"] is True
    assert list(outside.iterdir()) == []
    if outcome == ["moved"]:
        assert not (workspace / "sub-original" / "child").exists()
    else:
        assert (workspace / "sub" / "child").is_dir()


def test_ancestor_swapped_after_the_final_check_still_lands_inside_the_workspace(workspace, monkeypatch):
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    files = adapter(workspace)
    backend = files._backend
    real_open_file = backend.open_file
    outcome = []

    def swap_then_open(parent, name, mode):
        if mode == "create" and not (workspace / "sub-original").exists():
            try:
                (workspace / "sub").rename(workspace / "sub-original")
                link_directory(outside, workspace / "sub")
                outcome.append("moved")
            except PermissionError:
                outcome.append("pinned")
        return real_open_file(parent, name, mode)

    monkeypatch.setattr(backend, "open_file", swap_then_open)
    result = files.execute("file.write", {"path": "sub/escaped.txt", "text": "escaped"})
    assert list(outside.iterdir()) == []
    assert outcome in (["moved"], ["pinned"])
    destination = (workspace / "sub-original" / "escaped.txt" if outcome == ["moved"]
                   else workspace / "sub" / "escaped.txt")
    assert destination.read_bytes() == b"escaped"
    assert result["postcondition_verified"] is (outcome == ["pinned"])
    assert result["sha256"] == sha(b"escaped")
    if outcome == ["moved"]:
        assert "moved" in result["detail"]


@pytest.mark.skipif(os.name != "nt", reason="v0.1.6 file effects are Windows-only")
@pytest.mark.parametrize("move_target", ["effect-parent", "workspace-root"])
def test_effect_ancestry_cannot_move_outside_after_the_final_check(workspace, monkeypatch, move_target):
    outside = workspace.parent / "outside"
    outside.mkdir()
    (workspace / "sub").mkdir()
    files = adapter(workspace)
    backend = files._backend
    real_open_file = backend.open_file
    attempts = []

    def move_out_then_open(parent, name, mode):
        if mode == "create" and not attempts:
            source = workspace / "sub" if move_target == "effect-parent" else workspace
            destination = outside / "sub" if move_target == "effect-parent" else outside / "workspace"
            try:
                source.rename(destination)
                attempts.append("moved")
            except PermissionError:
                attempts.append("pinned")
        return real_open_file(parent, name, mode)

    monkeypatch.setattr(backend, "open_file", move_out_then_open)
    result = files.execute("file.write", {"path": "sub/escaped.txt", "text": "MODEL BYTES"})
    assert attempts == ["pinned"]
    assert not list(outside.rglob("*"))
    assert (workspace / "sub" / "escaped.txt").read_bytes() == b"MODEL BYTES"
    assert result["postcondition_verified"] is True


@pytest.mark.skipif(os.name != "nt", reason="v0.1.6 file effects are Windows-only")
def test_open_effect_parent_pins_an_ancestor_above_the_workspace(workspace, monkeypatch):
    holder = workspace / "holder"
    authorized = holder / "authorized"
    (authorized / "sub").mkdir(parents=True)
    outside = workspace / "outside"
    outside.mkdir()
    files = adapter(authorized)
    backend = files._backend
    real_open_file = backend.open_file
    attempts = []

    def move_out_then_open(parent, name, mode):
        if mode == "create" and not attempts:
            try:
                holder.rename(outside / "holder")
                attempts.append("moved")
            except PermissionError:
                attempts.append("pinned")
        return real_open_file(parent, name, mode)

    monkeypatch.setattr(backend, "open_file", move_out_then_open)
    result = files.execute("file.write", {"path": "sub/file.txt", "text": "x"})
    assert attempts == ["pinned"]
    assert not list(outside.rglob("*"))
    assert (authorized / "sub" / "file.txt").read_bytes() == b"x"
    assert result["postcondition_verified"] is True


def test_link_component_present_before_the_operation_is_refused_without_effect(workspace, layer):
    outside = workspace.parent / "outside"
    outside.mkdir()
    (outside / "peek.txt").write_text("secret", encoding="utf-8")
    link_directory(outside, workspace / "sub")
    files = adapter(workspace)
    cases = [("file.write", {"path": "sub/x.txt", "text": "x"}),
             ("file.mkdir", {"path": "sub/dir"}),
             ("file.list", {"path": "sub"}),
             ("file.read", {"path": "sub/peek.txt"}),
             ("file.move", {"source": "sub/peek.txt", "destination": "moved.txt", "expected_sha256": sha(b"secret")}),
             ("file.mkdir", {"path": "sub"})]
    for tool, args in cases:
        with pytest.raises(ComputerRefused, match="link"):
            files.execute(tool, args)
    assert sorted(p.name for p in outside.iterdir()) == ["peek.txt"]
    assert sorted(p.name for p in workspace.iterdir()) == ["sub"]


def test_workspace_root_replaced_by_a_link_is_refused(workspace, layer):
    files = adapter(workspace)
    outside = workspace.parent / "outside"
    outside.mkdir()
    workspace.rename(workspace.parent / "workspace-original")
    link_directory(outside, workspace)
    for tool, args in [("file.write", {"path": "x.txt", "text": "x"}), ("file.list", {}), ("file.mkdir", {"path": "d"})]:
        with pytest.raises(ComputerRefused, match="link"):
            files.execute(tool, args)
    assert list(outside.iterdir()) == []


def test_workspace_ancestor_replaced_by_a_link_is_refused(workspace, layer):
    holder = workspace / "holder"
    authorized = holder / "authorized"
    authorized.mkdir(parents=True)
    files = adapter(authorized)
    outside = workspace / "outside"
    redirected = outside / "authorized"
    redirected.mkdir(parents=True)
    holder.rename(workspace / "holder-original")
    link_directory(outside, holder)

    with pytest.raises(ComputerRefused):
        files.execute("file.write", {"path": "escaped.txt", "text": "escaped"})

    assert not (redirected / "escaped.txt").exists()
    assert not (workspace / "holder-original" / "authorized" / "escaped.txt").exists()


def test_file_link_as_final_component_never_reaches_its_target(workspace, layer):
    outside = workspace.parent / "outside"
    outside.mkdir()
    target = outside / "target.txt"
    target.write_bytes(b"outside")
    link_file(target, workspace / "alias.txt")
    files = adapter(workspace)
    with pytest.raises(ComputerRefused):
        files.execute("file.read", {"path": "alias.txt"})
    with pytest.raises(ComputerRefused):
        files.execute("file.write", {"path": "alias.txt", "text": "clobber", "expected_sha256": sha(b"outside")})
    with pytest.raises(ComputerRefused):
        files.execute("file.write", {"path": "alias.txt", "text": "clobber"})
    with pytest.raises(ComputerRefused):
        files.execute("file.move", {"source": "alias.txt", "destination": "taken.txt", "expected_sha256": sha(b"outside")})
    assert target.read_bytes() == b"outside"
    assert sorted(p.name for p in outside.iterdir()) == ["target.txt"]
    listed = files.execute("file.list", {})["entries"]
    assert all(entry["kind"] == "link" for entry in listed)
    if layer == "policy-and-handles":
        assert listed == []


def test_hard_linked_files_are_refused_for_read_replace_and_move(workspace, layer):
    files = adapter(workspace)
    files.execute("file.write", {"path": "one.txt", "text": "one"})
    try:
        os.link(workspace / "one.txt", workspace / "two.txt")
    except OSError as exc:
        pytest.skip(f"hard links unavailable on host: {exc}")
    cases = [("file.read", {"path": "one.txt"}),
             ("file.write", {"path": "one.txt", "text": "x", "expected_sha256": sha(b"one")}),
             ("file.move", {"source": "one.txt", "destination": "three.txt", "expected_sha256": sha(b"one")})]
    for tool, args in cases:
        with pytest.raises(ComputerRefused, match="hard"):
            files.execute(tool, args)
    assert (workspace / "one.txt").read_bytes() == b"one" and (workspace / "two.txt").read_bytes() == b"one"


def test_file_created_at_the_checkpoint_is_not_overwritten_by_a_new_write(workspace):
    def create_late():
        (workspace / "late.txt").write_bytes(b"late")

    files = adapter(workspace, checkpoint=create_late)
    with pytest.raises(ComputerRefused, match="already exists"):
        files.execute("file.write", {"path": "late.txt", "text": "mine"})
    assert (workspace / "late.txt").read_bytes() == b"late"
    assert sorted(p.name for p in workspace.iterdir()) == ["late.txt"]


def test_file_changed_at_the_checkpoint_is_not_replaced(workspace):
    adapter(workspace).execute("file.write", {"path": "a.txt", "text": "one"})

    def change_late():
        (workspace / "a.txt").write_bytes(b"changed")

    files = adapter(workspace, checkpoint=change_late)
    with pytest.raises(ComputerRefused, match="changed before replacement"):
        files.execute("file.write", {"path": "a.txt", "text": "two", "expected_sha256": sha(b"one")})
    assert (workspace / "a.txt").read_bytes() == b"changed"
    assert sorted(p.name for p in workspace.iterdir()) == ["a.txt"]


def test_destination_created_at_the_checkpoint_is_not_overwritten_by_move(workspace):
    adapter(workspace).execute("file.write", {"path": "source.txt", "text": "payload"})

    def occupy_late():
        (workspace / "target.txt").write_bytes(b"late")

    files = adapter(workspace, checkpoint=occupy_late)
    with pytest.raises(ComputerRefused, match="exists"):
        files.execute("file.move", {"source": "source.txt", "destination": "target.txt",
                                    "expected_sha256": sha(b"payload")})
    assert (workspace / "target.txt").read_bytes() == b"late"
    assert (workspace / "source.txt").read_bytes() == b"payload"


def test_move_requires_hash_and_free_destination_and_relinks_by_handle(workspace):
    files = adapter(workspace)
    (workspace / "a").mkdir()
    (workspace / "b").mkdir()
    files.execute("file.write", {"path": "a/source.txt", "text": "payload"})
    digest = sha(b"payload")
    with pytest.raises(ComputerRefused, match="expected_sha256"):
        files.execute("file.move", {"source": "a/source.txt", "destination": "b/target.txt", "expected_sha256": sha(b"other")})
    (workspace / "b" / "taken.txt").write_bytes(b"t")
    with pytest.raises(ComputerRefused, match="exists"):
        files.execute("file.move", {"source": "a/source.txt", "destination": "b/taken.txt", "expected_sha256": digest})
    assert (workspace / "b" / "taken.txt").read_bytes() == b"t"
    assert (workspace / "a" / "source.txt").read_bytes() == b"payload"
    result = files.execute("file.move", {"source": "a/source.txt", "destination": "b/target.txt", "expected_sha256": digest})
    assert result == {"path": "b/target.txt", "sha256": digest, "bytes": 7, "postcondition_verified": True}
    assert not (workspace / "a" / "source.txt").exists()
    assert (workspace / "b" / "target.txt").read_bytes() == b"payload"
    with pytest.raises(ComputerRefused, match="does not exist"):
        files.execute("file.move", {"source": "a/source.txt", "destination": "b/again.txt", "expected_sha256": digest})
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.move", {"source": "a", "destination": "c", "expected_sha256": digest})
    assert (workspace / "a").is_dir() and not (workspace / "c").exists()


def test_one_character_names_can_be_replaced_and_moved(workspace):
    files = adapter(workspace)
    files.execute("file.write", {"path": "a", "text": "one"})
    replaced = files.execute(
        "file.write", {"path": "a", "text": "two", "expected_sha256": sha(b"one")}
    )
    assert replaced["postcondition_verified"] is True
    moved = files.execute(
        "file.move", {"source": "a", "destination": "b", "expected_sha256": sha(b"two")}
    )
    assert moved["postcondition_verified"] is True
    assert not (workspace / "a").exists()
    assert (workspace / "b").read_bytes() == b"two"


def test_list_reports_kinds_without_following_links_and_bounds_entries(workspace):
    files = adapter(workspace)
    (workspace / "dir").mkdir()
    (workspace / "dir" / "inner.txt").write_text("i", encoding="utf-8")
    (workspace / "file.txt").write_text("f", encoding="utf-8")
    outside = workspace.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    link_directory(outside, workspace / "link")
    (workspace / ".git").mkdir()
    (workspace / "AGENTS.md").write_text("protected", encoding="utf-8")
    (workspace / "computer-policy.json").write_text("{}", encoding="utf-8")
    result = files.execute("file.list", {})
    # Links and policy-protected names are omitted, as the fenced service did:
    # a listing shows only entries the policy would admit for a later read,
    # and says how many it withheld (Cerberus NEW-4).
    assert result == {"entries": [{"path": "dir", "kind": "directory"}, {"path": "file.txt", "kind": "file"}],
                      "limit": 200, "truncated": False, "withheld": 4, "postcondition_verified": True}
    assert files.execute("file.list", {"path": "."})["entries"] == result["entries"]
    assert files.execute("file.list", {"path": "dir"})["entries"] == [{"path": "dir/inner.txt", "kind": "file"}]
    with pytest.raises(ComputerRefused, match="link"):
        files.execute("file.list", {"path": "link"})
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.list", {"path": "file.txt"})
    with pytest.raises(ComputerRefused, match="does not exist"):
        files.execute("file.list", {"path": "missing"})
    for index in range(205):
        (workspace / "dir" / f"entry-{index:03d}.txt").write_text("x", encoding="utf-8")
    bounded = files.execute("file.list", {"path": "dir"})
    assert len(bounded["entries"]) == 200 and bounded["truncated"] is True
    assert bounded["entries"][0] == {"path": "dir/entry-000.txt", "kind": "file"}


def test_mkdir_creates_one_level_and_tolerates_an_existing_real_directory(workspace):
    files = adapter(workspace)
    assert files.execute("file.mkdir", {"path": "docs"}) == {"path": "docs", "created": True, "postcondition_verified": True}
    assert files.execute("file.mkdir", {"path": "docs"}) == {"path": "docs", "created": False, "postcondition_verified": True}
    assert files.execute("file.mkdir", {"path": "docs/nested"})["created"] is True
    (workspace / "plain.txt").write_text("p", encoding="utf-8")
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.mkdir", {"path": "plain.txt"})
    with pytest.raises(ComputerRefused, match="does not exist"):
        files.execute("file.mkdir", {"path": "missing/deep"})
    assert sorted(p.name for p in workspace.iterdir()) == ["docs", "plain.txt"]


def test_missing_parent_directories_are_never_created(workspace):
    files = adapter(workspace)
    with pytest.raises(ComputerRefused, match="does not exist"):
        files.execute("file.write", {"path": "missing/x.txt", "text": "x"})
    with pytest.raises(ComputerRefused, match="does not exist"):
        files.execute("file.read", {"path": "missing/x.txt"})
    assert list(workspace.iterdir()) == []


def test_directories_and_files_are_not_interchangeable(workspace):
    files = adapter(workspace)
    (workspace / "dir").mkdir()
    (workspace / "f.txt").write_text("f", encoding="utf-8")
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.read", {"path": "dir"})
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.write", {"path": "dir", "text": "x"})
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.write", {"path": "dir", "text": "x", "expected_sha256": "0" * 64})
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.read", {"path": "f.txt/child"})
    with pytest.raises(ComputerRefused, match="directory"):
        files.execute("file.write", {"path": "f.txt/child", "text": "x"})
    assert (workspace / "f.txt").read_text(encoding="utf-8") == "f" and list((workspace / "dir").iterdir()) == []


@pytest.mark.parametrize("tool,args", [
    ("file.write", {"path": "../escape.txt", "text": "x"}),
    ("file.write", {"path": "sub/../../escape.txt", "text": "x"}),
    ("file.write", {"path": "/abs.txt", "text": "x"}),
    ("file.write", {"path": "C:/abs.txt", "text": "x"}),
    ("file.write", {"path": "a:stream.txt", "text": "x"}),
    ("file.mkdir", {"path": ".git"}),
    ("file.read", {"path": "CON"}),
    ("file.write", {"path": "trailing. ", "text": "x"}),
    ("file.write", {"path": "", "text": "x"}),
    ("file.write", {"path": ".", "text": "x"}),
    ("file.mkdir", {"path": "."}),
    ("file.read", {"path": "."}),
    ("file.move", {"source": ".", "destination": "x", "expected_sha256": "0" * 64}),
    ("file.write", {"path": "nul\x00byte", "text": "x"}),
    ("file.write", {"path": "bad*name.txt", "text": "x"}),
    ("file.write", {"path": "bad?.txt", "text": "x"}),
    ("file.write", {"path": "a<b.txt", "text": "x"}),
    ("file.write", {"path": "a|b.txt", "text": "x"}),
    ("file.write", {"path": "q\"uote.txt", "text": "x"}),
    ("file.write", {"path": "ctrl\x01.txt", "text": "x"}),
    ("file.write", {"path": "tab\t.txt", "text": "x"}),
    ("file.write", {"path": "café.txt", "text": "x"}),
    ("file.write", {"path": 7, "text": "x"}),
    ("file.write", {"path": "typed.txt", "text": 7}),
    ("file.write", {"path": "typed.txt", "text": "x", "expected_sha256": "ABC"}),
    ("file.move", {"source": "a", "destination": "b"}),
    ("vision.inspect", {"path": "x"}),
])
def test_invalid_requests_refuse_before_any_checkpoint_or_handle(workspace, tool, args):
    def checkpoint():
        pytest.fail("checkpoint reached for an invalid request")

    files = adapter(workspace, checkpoint=checkpoint)
    with pytest.raises(ComputerRefused):
        files.execute(tool, args)
    assert list(workspace.iterdir()) == []
    assert not (workspace.parent / "escape.txt").exists()


def test_cancellation_at_the_checkpoint_performs_no_effect(workspace):
    adapter(workspace).execute("file.write", {"path": "keep.txt", "text": "keep"})

    def cancel():
        raise ComputerRefused("computer task cancellation requested")

    cancelled = adapter(workspace, checkpoint=cancel)
    cases = [("file.write", {"path": "new.txt", "text": "x"}),
             ("file.write", {"path": "keep.txt", "text": "x", "expected_sha256": sha(b"keep")}),
             ("file.mkdir", {"path": "dir"}),
             ("file.move", {"source": "keep.txt", "destination": "moved.txt", "expected_sha256": sha(b"keep")})]
    for tool, args in cases:
        with pytest.raises(ComputerRefused, match="cancellation"):
            cancelled.execute(tool, args)
    assert sorted(p.name for p in workspace.iterdir()) == ["keep.txt"]
    assert (workspace / "keep.txt").read_bytes() == b"keep"
    with pytest.raises(ComputerRefused, match="cancellation"):
        cancelled.execute("file.read", {"path": "keep.txt"})
    with pytest.raises(ComputerRefused, match="cancellation"):
        cancelled.execute("file.list", {})


def test_size_bounds_apply_to_reads_and_writes(workspace):
    # 128 bytes keeps every JSON argument envelope (a move carries a 64-hex
    # digest) inside the policy's 2x bound, so the adapter's own content limit
    # is the refusal under test.
    files = adapter(workspace, max_file_bytes=128)
    with pytest.raises(ComputerRefused, match="size"):
        files.execute("file.write", {"path": "big.txt", "text": "x" * 129})
    assert not (workspace / "big.txt").exists()
    (workspace / "large.txt").write_bytes(b"x" * 129)
    with pytest.raises(ComputerRefused, match="size"):
        files.execute("file.read", {"path": "large.txt"})
    with pytest.raises(ComputerRefused, match="size"):
        files.execute("file.move", {"source": "large.txt", "destination": "moved.txt", "expected_sha256": sha(b"x" * 129)})
    assert (workspace / "large.txt").exists() and not (workspace / "moved.txt").exists()
    assert files.execute("file.write", {"path": "ok.txt", "text": "x" * 128})["bytes"] == 128


def test_non_utf8_bytes_are_refused_as_text(workspace):
    (workspace / "bin.dat").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ComputerRefused, match="UTF-8"):
        adapter(workspace).execute("file.read", {"path": "bin.dat"})


def test_adapter_is_unavailable_when_the_workspace_is_missing(workspace):
    files = adapter(workspace)
    workspace.rename(workspace.parent / "gone")
    with pytest.raises(ComputerRefused, match="does not exist"):
        files.execute("file.list", {})


@pytest.mark.skipif(os.name != "nt", reason="Windows 8.3 short names")
def test_short_name_aliases_cannot_address_workspace_entries(workspace):
    import ctypes
    long_dir = workspace / "protected-long-directory-name"
    long_dir.mkdir()
    long_file = long_dir / "inner-file-with-a-long-name.txt"
    long_file.write_text("i", encoding="utf-8")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
    kernel32.GetShortPathNameW.restype = ctypes.c_ulong

    def short_name(path: Path) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        if not kernel32.GetShortPathNameW(str(path), buffer, 32768):
            pytest.skip("short names unavailable on this volume")
        alias = Path(buffer.value).name
        if alias.casefold() == path.name.casefold():
            pytest.skip("8.3 names are disabled on this volume")
        return alias

    short_dir, short_file = short_name(long_dir), short_name(long_file)
    files = adapter(workspace)
    with pytest.raises(ComputerRefused, match="full name"):
        files.execute("file.list", {"path": short_dir})
    with pytest.raises(ComputerRefused, match="full name"):
        files.execute("file.read", {"path": f"{short_dir}/{long_file.name}"})
    with pytest.raises(ComputerRefused, match="full name"):
        files.execute("file.read", {"path": f"{long_dir.name}/{short_file}"})
    with pytest.raises(ComputerRefused, match="full name"):
        files.execute("file.write", {"path": f"{long_dir.name}/{short_file}", "text": "x", "expected_sha256": sha(b"i")})
    assert long_file.read_text(encoding="utf-8") == "i"
    assert files.execute("file.list", {"path": long_dir.name})["entries"] == [
        {"path": f"{long_dir.name}/{long_file.name}", "kind": "file"}]
    assert files.execute("file.read", {"path": f"{long_dir.name}/{long_file.name}"})["text"] == "i"


@pytest.mark.skipif(os.name != "nt", reason="Windows NT backend")
def test_nt_backend_refuses_names_that_could_traverse(workspace):
    backend = subject._NTBackend()
    root = backend.open_root(workspace)
    try:
        for name in ("a\\b", "a/b", "..", ".", "", "x" * 256, "a:b"):
            with pytest.raises(ComputerRefused):
                backend.open_child_directory(root, name)
    finally:
        backend.close_directory(root)
    assert list(workspace.iterdir()) == []
