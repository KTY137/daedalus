"""Canonical owner for the packaged desktop sidecar bootstrap.

The frozen launcher delegates here before creating writable runtime state. The
HTTP server and desktop service owners retain their own narrower nested effect
boundaries; this module owns only the bootstrap that necessarily precedes them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable
import uuid

DESKTOP_PROJECT_SCHEMA = "daedalus-desktop-self-project/1"
DESKTOP_INITIAL_ARM_CLAIM_ENV = "DAEDALUS_DESKTOP_INITIAL_ARM_CLAIM"
DESKTOP_PROJECT_COMMENT = (
    "Generated once by the Tauri desktop sidecar. The repository root is "
    "the writable packaged runtime, not the source checkout."
)

_INITIAL_ARM_CLAIM_SUFFIX = ".desktop-initial-arm.claim"
_INITIAL_ARM_CLAIM_HEADER = b"daedalus-desktop-initial-arm/1\n"
_INITIAL_ARM_CLAIM_PENDING = _INITIAL_ARM_CLAIM_HEADER + b"state=PENDING\n"
_INITIAL_ARM_CLAIM_COMPLETE = _INITIAL_ARM_CLAIM_HEADER + b"state=COMPLETE\n"
_MAX_INITIAL_ARM_ENTRY_BYTES = 64 * 1024


class DesktopSwitchInitializationRefused(RuntimeError):
    """The one-shot desktop permit bootstrap could not be proven safe."""


class DesktopSwitchRevocationUnproven(RuntimeError):
    """A post-arm failure left the permit running or unreadable.

    This is deliberately distinct from a safely stopped initialization
    refusal. The packaged process must terminate before constructing the
    manager or HTTP server when revocation cannot be proven.
    """


def bundled_root() -> Path:
    """Return the root that mirrors the repository inside the frozen app."""

    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen).resolve()
    return Path(__file__).resolve().parents[3]


def _desktop_project(root: Path) -> dict[str, Any]:
    return {
        "name": "daedalus",
        "repo_root": str(root),
        "center": ["daedalus", "apps/web/src"],
        "ignore": ["@tests"],
        "default_branch": "main",
        "policy": {
            "deny": [".env", "configs/secrets", "runs/", "inbox/", "outbox/"],
            "allow": ["daedalus/", "apps/web/src/", "docs/", ".md"],
        },
        "_desktop_schema": DESKTOP_PROJECT_SCHEMA,
        "_desktop_comment": DESKTOP_PROJECT_COMMENT,
    }


def _prepare_desktop_project(project_file: Path, runtime: Path) -> None:
    """Seed or relocate only the sidecar-owned self-project record."""

    from daedalus.atomic import write_text_atomic

    if not project_file.exists():
        payload = _desktop_project(runtime)
    else:
        try:
            existing = json.loads(project_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(existing, dict) or not (
            existing.get("_desktop_schema") == DESKTOP_PROJECT_SCHEMA
            or existing.get("_desktop_comment") == DESKTOP_PROJECT_COMMENT
        ):
            return
        payload = dict(existing)
        payload["repo_root"] = str(runtime)
        payload["_desktop_schema"] = DESKTOP_PROJECT_SCHEMA
        payload["_desktop_comment"] = DESKTOP_PROJECT_COMMENT
        if payload == existing:
            return

    write_text_atomic(
        project_file,
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def prepare_runtime(root: Path | None = None) -> Path:
    """Create desktop-owned runtime dirs and a self-project seed, without overwrite."""

    runtime = (root or bundled_root()).resolve()
    for relative in ("projects", "runs", "inbox", "outbox", "memory", "config"):
        (runtime / relative).mkdir(parents=True, exist_ok=True)

    project_file = runtime / "projects" / "daedalus.json"
    _prepare_desktop_project(project_file, runtime)
    return runtime


def _single_link_regular(state: os.stat_result) -> bool:
    attributes = int(getattr(state, "st_file_attributes", 0))
    return bool(
        stat.S_ISREG(state.st_mode)
        and state.st_nlink == 1
        and not stat.S_ISLNK(state.st_mode)
        and not attributes
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        and not getattr(state, "st_reparse_tag", 0)
    )


def _entry_state(parent: Path, name: str, directory_fd: int | None):
    """Inspect one sibling without following a final-component link."""

    try:
        if directory_fd is None:
            return os.lstat(parent / name)
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise DesktopSwitchInitializationRefused(
            f"desktop initial-arm entry cannot be inspected: {name}: {exc}"
        ) from exc


def _checked_existing_entry(
    parent: Path,
    name: str,
    directory_fd: int | None,
) -> os.stat_result | None:
    state = _entry_state(parent, name, directory_fd)
    if state is not None and not _single_link_regular(state):
        raise DesktopSwitchInitializationRefused(
            f"desktop initial-arm entry is redirected or hard-linked: {name}"
        )
    return state


def _write_all(file_fd: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(file_fd, remaining)
        if written <= 0:
            raise OSError("short desktop initial-arm claim write")
        remaining = remaining[written:]


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_revision(left: os.stat_result, right: os.stat_result) -> bool:
    """Identity plus the metadata that changes on an in-place rewrite."""

    return bool(
        _same_identity(left, right)
        and left.st_size == right.st_size
        and getattr(left, "st_mtime_ns", None)
        == getattr(right, "st_mtime_ns", None)
        and getattr(left, "st_ctime_ns", None)
        == getattr(right, "st_ctime_ns", None)
    )


def _read_checked_entry(
    parent: Path,
    name: str,
    directory_fd: int | None,
) -> tuple[bytes, os.stat_result] | None:
    """Read one bounded regular/single-link sibling without path substitution.

    POSIX opens descriptor-relative to the pinned directory. Windows keeps the
    no-share-delete parent handle open and proves that the name before, opened
    descriptor, and name after the read all identify one unchanged inode. A
    transient/unreadable result is an exception, never evidence of STOP.
    """

    named_before = _checked_existing_entry(parent, name, directory_fd)
    if named_before is None:
        return None
    if named_before.st_size > _MAX_INITIAL_ARM_ENTRY_BYTES:
        raise DesktopSwitchInitializationRefused(
            f"desktop initial-arm entry is implausibly large: {name}"
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    file_fd = -1
    try:
        if directory_fd is None:
            file_fd = os.open(parent / name, flags)
        else:
            file_fd = os.open(name, flags, dir_fd=directory_fd)
        opened_before = os.fstat(file_fd)
        if (
            not _single_link_regular(opened_before)
            or not _same_identity(named_before, opened_before)
        ):
            raise DesktopSwitchInitializationRefused(
                f"desktop initial-arm entry identity changed while opening: {name}"
            )

        chunks: list[bytes] = []
        remaining = _MAX_INITIAL_ARM_ENTRY_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(8192, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > _MAX_INITIAL_ARM_ENTRY_BYTES:
            raise DesktopSwitchInitializationRefused(
                f"desktop initial-arm entry is implausibly large: {name}"
            )
        opened_after = os.fstat(file_fd)
        named_after = _checked_existing_entry(parent, name, directory_fd)
        if (
            named_after is None
            or not _same_revision(opened_before, opened_after)
            or not _same_revision(named_before, named_after)
            # NTFS/CPython can report slightly different ctime precision for
            # fstat(handle) and lstat(path) on the same unchanged file. Cross-
            # API comparison is identity-only; each API family independently
            # proves its own revision did not change during the read.
            or not _same_identity(opened_after, named_after)
            or opened_after.st_size != len(payload)
        ):
            raise DesktopSwitchInitializationRefused(
                f"desktop initial-arm entry changed while reading: {name}"
            )
        return payload, opened_after
    except DesktopSwitchInitializationRefused:
        raise
    except OSError as exc:
        raise DesktopSwitchInitializationRefused(
            f"desktop initial-arm entry cannot be read: {name}: {exc}"
        ) from exc
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _first_token(payload: bytes) -> bytes | None:
    for line in payload.splitlines():
        token = line.strip()
        if token:
            return token
    return None


def _create_posix_claim_new(
    parent: Path,
    name: str,
    directory_fd: int,
    payload: bytes = _INITIAL_ARM_CLAIM_PENDING,
) -> os.stat_result | None:
    """Descriptor-relative CREATE_NEW plus file and directory durability."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        file_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError:
        return None
    try:
        _write_all(file_fd, payload)
        os.fsync(file_fd)
        identity = os.fstat(file_fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not _single_link_regular(named)
            or (named.st_dev, named.st_ino) != (identity.st_dev, identity.st_ino)
        ):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim identity changed during creation"
            )
        # The claim must survive a crash before arm(). If this flush fails the
        # claim deliberately remains visible and suppresses every later retry.
        os.fsync(directory_fd)
        return identity
    finally:
        try:
            os.close(file_fd)
        except OSError:
            pass


def _create_windows_claim_new(
    path: Path,
    payload: bytes = _INITIAL_ARM_CLAIM_PENDING,
) -> os.stat_result | None:
    """Win32 CREATE_NEW with write-through data and metadata semantics."""

    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    generic_write = 0x40000000
    create_new = 1
    file_attribute_normal = 0x00000080
    file_flag_write_through = 0x80000000
    file_flag_open_reparse_point = 0x00200000
    handle = create_file(
        str(path),
        generic_write,
        0,
        None,
        create_new,
        file_attribute_normal
        | file_flag_write_through
        | file_flag_open_reparse_point,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        error = ctypes.get_last_error()
        if error in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
            return None
        raise OSError(error, "cannot CREATE_NEW desktop initial-arm claim", str(path))

    file_fd = -1
    try:
        flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOINHERIT", 0)
        file_fd = msvcrt.open_osfhandle(int(handle), flags)
        # The CRT descriptor now owns the Win32 handle.
        handle = None
        _write_all(file_fd, payload)
        os.fsync(file_fd)
        identity = os.fstat(file_fd)
    finally:
        if file_fd >= 0:
            try:
                os.close(file_fd)
            except OSError:
                pass
        elif handle not in (None, invalid):
            close_handle(handle)

    named = os.lstat(path)
    if (
        not _single_link_regular(named)
        or (named.st_dev, named.st_ino) != (identity.st_dev, identity.st_ino)
    ):
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm claim identity changed during creation"
        )
    return identity


def _initial_arm_paths() -> tuple[Path, Path] | None:
    """Return the exact Tauri-supplied stable sibling paths, if enabled."""

    from daedalus.spine.killswitch import ENV_SWITCH_PATH

    raw_switch = os.environ.get(ENV_SWITCH_PATH)
    raw_claim = os.environ.get(DESKTOP_INITIAL_ARM_CLAIM_ENV)
    if not raw_claim:
        return None
    if not raw_switch:
        raise DesktopSwitchInitializationRefused(
            f"{DESKTOP_INITIAL_ARM_CLAIM_ENV} requires {ENV_SWITCH_PATH}"
        )
    if not Path(raw_switch).is_absolute() or not Path(raw_claim).is_absolute():
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm paths must be absolute"
        )
    switch_path = Path(os.path.abspath(raw_switch))
    claim_path = Path(os.path.abspath(raw_claim))
    expected_claim = switch_path.with_name(
        switch_path.name + _INITIAL_ARM_CLAIM_SUFFIX
    )
    if os.path.normcase(str(claim_path)) != os.path.normcase(str(expected_claim)):
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm claim must be the fixed sibling of the kill switch"
        )
    return switch_path, claim_path


def _parent_identity(path: Path) -> tuple[int, int]:
    state = os.lstat(path)
    attributes = int(getattr(state, "st_file_attributes", 0))
    if (
        not stat.S_ISDIR(state.st_mode)
        or stat.S_ISLNK(state.st_mode)
        or attributes
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        or getattr(state, "st_reparse_tag", 0)
    ):
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm parent is redirected or not a directory"
        )
    return state.st_dev, state.st_ino


def _claim_publish_failure(message: str, exc: BaseException) -> None:
    raise DesktopSwitchInitializationRefused(message) from exc


def _publish_posix_claim_body(
    parent: Path,
    name: str,
    directory_fd: int,
    payload: bytes,
    *,
    expected_identity: os.stat_result,
    expected_body: bytes,
) -> os.stat_result:
    """Atomically replace one pinned claim and fsync its directory entry."""

    scratch_name = f".{name}.{uuid.uuid4().hex}.tmp"
    scratch_identity: os.stat_result | None = None
    replaced = False
    try:
        scratch_identity = _create_posix_claim_new(
            parent,
            scratch_name,
            directory_fd,
            payload,
        )
        if scratch_identity is None:  # UUID collision is still not a safe retry.
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim scratch unexpectedly existed"
            )
        current = _read_checked_entry(parent, name, directory_fd)
        if (
            current is None
            or current[0] != expected_body
            or not _same_identity(current[1], expected_identity)
        ):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim changed before state publication"
            )
        os.replace(
            scratch_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        replaced = True
        os.fsync(directory_fd)
        published = _read_checked_entry(parent, name, directory_fd)
        if (
            published is None
            or published[0] != payload
            or not _same_identity(published[1], scratch_identity)
        ):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim state publication changed identity"
            )
        return published[1]
    finally:
        if not replaced and scratch_identity is not None:
            try:
                leftover = _checked_existing_entry(
                    parent, scratch_name, directory_fd
                )
                if leftover is not None and _same_identity(
                    leftover, scratch_identity
                ):
                    os.unlink(scratch_name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
            except OSError:
                pass


def _publish_windows_claim_body(
    parent: Path,
    name: str,
    payload: bytes,
    *,
    expected_identity: os.stat_result,
    expected_body: bytes,
) -> os.stat_result:
    """Publish a claim with Win32 WRITE_THROUGH under the pinned parent."""

    from daedalus.atomic import REPLACE_RETRY_S
    from .effects import _move_file_ex_windows_write_through

    target = parent / name
    scratch = parent / f".{name}.{uuid.uuid4().hex}.tmp"
    scratch_identity = _create_windows_claim_new(scratch, payload)
    if scratch_identity is None:
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm claim scratch unexpectedly existed"
        )
    replaced = False
    try:
        current = _read_checked_entry(parent, name, None)
        if (
            current is None
            or current[0] != expected_body
            or not _same_identity(current[1], expected_identity)
        ):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim changed before state publication"
            )

        deadline = time.monotonic() + REPLACE_RETRY_S
        last_error: OSError | None = None
        while True:
            try:
                _move_file_ex_windows_write_through(scratch, target)
                replaced = True
                break
            except OSError as exc:
                last_error = exc
                # A native move can have made the new name visible before an
                # injected/wrapper error reached Python. Reconcile by the inode
                # we created; never infer publication from path existence.
                try:
                    published = _read_checked_entry(parent, name, None)
                except DesktopSwitchInitializationRefused:
                    published = None
                if (
                    published is not None
                    and published[0] == payload
                    and _same_identity(published[1], scratch_identity)
                ):
                    replaced = True
                    break
                try:
                    retained = _read_checked_entry(parent, scratch.name, None)
                except DesktopSwitchInitializationRefused:
                    retained = None
                if (
                    retained is None
                    or retained[0] != payload
                    or not _same_identity(retained[1], scratch_identity)
                ):
                    _claim_publish_failure(
                        "desktop initial-arm claim publication is indeterminate",
                        exc,
                    )
                if time.monotonic() >= deadline:
                    raise last_error
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))

        published = _read_checked_entry(parent, name, None)
        if (
            published is None
            or published[0] != payload
            or not _same_identity(published[1], scratch_identity)
        ):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim state publication changed identity"
            )
        return published[1]
    finally:
        if not replaced:
            try:
                leftover = _checked_existing_entry(parent, scratch.name, None)
                if leftover is not None and _same_identity(
                    leftover, scratch_identity
                ):
                    scratch.unlink()
            except OSError:
                pass


def _publish_claim_body(
    parent: Path,
    name: str,
    directory_fd: int | None,
    payload: bytes,
    *,
    expected_identity: os.stat_result,
    expected_body: bytes,
) -> os.stat_result:
    if os.name == "nt":
        return _publish_windows_claim_body(
            parent,
            name,
            payload,
            expected_identity=expected_identity,
            expected_body=expected_body,
        )
    return _publish_posix_claim_body(
        parent,
        name,
        int(directory_fd),
        payload,
        expected_identity=expected_identity,
        expected_body=expected_body,
    )


def _read_stop_evidence(
    switch: Any,
    parent: Path,
    switch_path: Path,
    directory_fd: int | None,
) -> tuple[bool, bool]:
    """Return ``(exact_stop_artifact, permit_absent)`` from pinned disk state."""

    marker = _read_checked_entry(
        parent, switch.marker_path.name, directory_fd
    )
    permit = _read_checked_entry(parent, switch_path.name, directory_fd)
    exact_stop = bool(
        (marker is not None and _first_token(marker[0]) == b"STOP")
        or (permit is not None and _first_token(permit[0]) == b"STOP")
    )
    return exact_stop, permit is None


def _restore_pending_claim(
    parent: Path,
    claim_path: Path,
    directory_fd: int | None,
) -> bool:
    """Leave an ambiguous arm attempt in the only non-accepting claim state."""

    try:
        current = _read_checked_entry(parent, claim_path.name, directory_fd)
        if current is None:
            return False
        if current[0] == _INITIAL_ARM_CLAIM_PENDING:
            return True
        if current[0] != _INITIAL_ARM_CLAIM_COMPLETE:
            return False
        _publish_claim_body(
            parent,
            claim_path.name,
            directory_fd,
            _INITIAL_ARM_CLAIM_PENDING,
            expected_identity=current[1],
            expected_body=current[0],
        )
        retained = _read_checked_entry(parent, claim_path.name, directory_fd)
        return bool(retained is not None and retained[0] == _INITIAL_ARM_CLAIM_PENDING)
    except BaseException:
        return False


def _revoke_initial_arm_or_raise(
    switch: Any,
    switch_path: Path,
    claim_path: Path,
    directory_fd: int | None,
    reason: str,
    cause: BaseException,
) -> None:
    """Require durable state-machine rollback plus direct STOP evidence.

    Neither ``stop()``'s return value nor ``read_state().running=False`` is a
    revocation proof: both may be produced by a transient read failure while a
    RUN permit remains on disk. The only safe continuation after arm() was
    entered is an exact regular/single-link STOP marker or permit, read beneath
    the still-pinned parent, with the claim retained as PENDING.
    """

    parent = switch_path.parent
    stop_error: BaseException | None = None
    try:
        switch.stop(reason)
    except BaseException as exc:
        stop_error = exc

    claim_pending = _restore_pending_claim(parent, claim_path, directory_fd)
    try:
        exact_stop, _ = _read_stop_evidence(
            switch, parent, switch_path, directory_fd
        )
    except BaseException as exc:
        proof_error: BaseException = exc
        exact_stop = False
    else:
        proof_error = stop_error or cause

    if claim_pending and exact_stop:
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm failed after arm was entered; a persistent "
            "STOP representation was verified and the claim remains PENDING"
        ) from cause

    raise DesktopSwitchRevocationUnproven(
        "desktop initial-arm revocation is unproven and the permit may still "
        "be RUN; refusing to start the runtime"
    ) from proof_error


def _claim_with_active_run_is_fatal(
    claim_body: bytes,
    permit: tuple[bytes, os.stat_result] | None,
    marker: tuple[bytes, os.stat_result] | None,
) -> bool:
    return bool(
        claim_body != _INITIAL_ARM_CLAIM_COMPLETE
        and permit is not None
        and _first_token(permit[0]) == b"RUN"
        and not (marker is not None and _first_token(marker[0]) == b"STOP")
    )


def _return_existing_switch_state(
    switch: Any,
    switch_path: Path,
    claim_path: Path,
    directory_fd: int | None,
    verify_parent: Callable[[], None],
    *,
    expected_claim: tuple[bytes, os.stat_result] | None,
):
    """Return a pre-existing state only after a fresh pinned reconciliation.

    ``KillSwitch.read_state`` is necessarily pathname-based. On POSIX the
    directory descriptor pins an inode but does not prevent its name from
    being replaced. Verify the literal parent both before and after that read,
    then reconcile its answer with a new descriptor-bound artifact snapshot.
    """

    parent = switch_path.parent

    def verify_or_fatal() -> None:
        try:
            verify_parent()
        except BaseException as exc:
            raise DesktopSwitchRevocationUnproven(
                "desktop initial-arm parent identity is unproven and the "
                "literal permit may still be RUN; refusing to start the runtime"
            ) from exc

    verify_or_fatal()
    state = switch.read_state()
    verify_or_fatal()
    try:
        marker = _read_checked_entry(
            parent, switch.marker_path.name, directory_fd
        )
        permit = _read_checked_entry(parent, switch_path.name, directory_fd)
        claim = _read_checked_entry(parent, claim_path.name, directory_fd)
    except DesktopSwitchInitializationRefused as exc:
        raise DesktopSwitchRevocationUnproven(
            "desktop initial-arm state cannot be reconciled and the permit may "
            "still be RUN; refusing to start the runtime"
        ) from exc
    verify_or_fatal()

    if expected_claim is not None:
        if (
            claim is None
            or claim[0] != expected_claim[0]
            or not _same_identity(claim[1], expected_claim[1])
        ):
            raise DesktopSwitchRevocationUnproven(
                "desktop initial-arm claim changed during state reconciliation; "
                "the permit may still be RUN; refusing to start the runtime"
            )

    effective_claim = claim[0] if claim is not None else None
    direct_active_run = bool(
        permit is not None
        and _first_token(permit[0]) == b"RUN"
        and not (marker is not None and _first_token(marker[0]) == b"STOP")
    )
    if effective_claim is not None and effective_claim != _INITIAL_ARM_CLAIM_COMPLETE:
        if state.running or direct_active_run:
            raise DesktopSwitchRevocationUnproven(
                "desktop initial-arm claim is PENDING or malformed while the "
                "permit may still be RUN; refusing to start the runtime"
            )
    return state


def _initialize_desktop_switch_inside_parent(
    switch: Any,
    switch_path: Path,
    claim_path: Path,
    directory_fd: int | None,
    verify_parent: Callable[[], None],
):
    """Run the PENDING -> arm -> verified COMPLETE state machine."""

    parent = switch_path.parent
    marker: tuple[bytes, os.stat_result] | None
    permit: tuple[bytes, os.stat_result] | None
    try:
        marker = _read_checked_entry(
            parent, switch.marker_path.name, directory_fd
        )
    except DesktopSwitchInitializationRefused:
        # Any marker that KillSwitch can stat suppresses work. Keep the strict
        # refusal but never manufacture a permit beside it.
        raise
    try:
        permit = _read_checked_entry(parent, switch_path.name, directory_fd)
    except DesktopSwitchInitializationRefused as exc:
        # KillSwitch.read_state follows the permit path and can accept RUN.
        # If we cannot prove its exact inode beneath the pin, HTTP startup
        # would hand an unsafe file to the later effect owner.
        raise DesktopSwitchRevocationUnproven(
            "desktop permit identity is unproven and may be RUN; refusing to "
            "start the runtime"
        ) from exc

    try:
        claim = _read_checked_entry(parent, claim_path.name, directory_fd)
    except DesktopSwitchInitializationRefused as exc:
        active_run = bool(
            permit is not None
            and _first_token(permit[0]) == b"RUN"
            and not (
                marker is not None and _first_token(marker[0]) == b"STOP"
            )
        )
        if active_run:
            raise DesktopSwitchRevocationUnproven(
                "desktop initial-arm claim is malformed while the permit may "
                "still be RUN; refusing to start the runtime"
            ) from exc
        raise

    if claim is not None:
        if _claim_with_active_run_is_fatal(claim[0], permit, marker):
            raise DesktopSwitchRevocationUnproven(
                "desktop initial-arm claim is PENDING or malformed while the "
                "permit may still be RUN; refusing to start the runtime"
            )
        # Every pre-existing claim suppresses automatic arm forever. COMPLETE
        # is the sole state that may coexist with an active RUN permit; PENDING
        # and malformed claims are safely read-only only when pinned evidence
        # directly proves no active RUN.
        return _return_existing_switch_state(
            switch,
            switch_path,
            claim_path,
            directory_fd,
            verify_parent,
            expected_claim=claim,
        )

    # A sticky marker or any prior permit also means this is not a pristine
    # install. Presence suppresses initialization even when the token is STOP.
    if marker is not None or permit is not None:
        return _return_existing_switch_state(
            switch,
            switch_path,
            claim_path,
            directory_fd,
            verify_parent,
            expected_claim=None,
        )

    identity = (
        _create_windows_claim_new(claim_path, _INITIAL_ARM_CLAIM_PENDING)
        if os.name == "nt"
        else _create_posix_claim_new(
            parent,
            claim_path.name,
            int(directory_fd),
            _INITIAL_ARM_CLAIM_PENDING,
        )
    )
    if identity is None:
        # A racing creator owns the state. Re-enter the exact classifier rather
        # than trusting a transient SwitchState.
        claim = _read_checked_entry(parent, claim_path.name, directory_fd)
        permit = _read_checked_entry(parent, switch_path.name, directory_fd)
        marker = _read_checked_entry(
            parent, switch.marker_path.name, directory_fd
        )
        if claim is None:
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm claim disappeared after CREATE_NEW refusal"
            )
        if _claim_with_active_run_is_fatal(claim[0], permit, marker):
            raise DesktopSwitchRevocationUnproven(
                "desktop initial-arm claim is PENDING or malformed while the "
                "permit may still be RUN; refusing to start the runtime"
            )
        return _return_existing_switch_state(
            switch,
            switch_path,
            claim_path,
            directory_fd,
            verify_parent,
            expected_claim=claim,
        )

    claimed = _read_checked_entry(parent, claim_path.name, directory_fd)
    if (
        claimed is None
        or claimed[0] != _INITIAL_ARM_CLAIM_PENDING
        or not _same_identity(claimed[1], identity)
    ):
        raise DesktopSwitchInitializationRefused(
            "desktop initial-arm claim no longer names the created file"
        )
    # Re-check both stop representations after the claim is durable. A crash
    # or refusal from here leaves the claim behind and permanently suppresses
    # automatic re-arming.
    if (
        _read_checked_entry(parent, switch.marker_path.name, directory_fd)
        is not None
        or _read_checked_entry(parent, switch_path.name, directory_fd) is not None
    ):
        return _return_existing_switch_state(
            switch,
            switch_path,
            claim_path,
            directory_fd,
            verify_parent,
            expected_claim=claimed,
        )

    arm_returned = False
    try:
        verify_parent()
        # arm() itself is inside the post-arm fault region: its atomic writer
        # may publish RUN and then raise before returning to this frame.
        state = switch.arm(note="packaged desktop first-run initialization")
        arm_returned = True
        if not state.running:
            raise DesktopSwitchInitializationRefused(
                f"desktop initial arm did not produce a running permit: {state.reason}"
            )
        permit = _read_checked_entry(parent, switch_path.name, directory_fd)
        marker = _read_checked_entry(
            parent, switch.marker_path.name, directory_fd
        )
        retained_claim = _read_checked_entry(parent, claim_path.name, directory_fd)
        if (
            permit is None
            or _first_token(permit[0]) != b"RUN"
            or marker is not None
            or retained_claim is None
            or retained_claim[0] != _INITIAL_ARM_CLAIM_PENDING
            or not _same_identity(retained_claim[1], identity)
        ):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm postcondition could not be verified"
            )
        verify_parent()
        _publish_claim_body(
            parent,
            claim_path.name,
            directory_fd,
            _INITIAL_ARM_CLAIM_COMPLETE,
            expected_identity=retained_claim[1],
            expected_body=_INITIAL_ARM_CLAIM_PENDING,
        )
        complete = _read_checked_entry(parent, claim_path.name, directory_fd)
        if complete is None or complete[0] != _INITIAL_ARM_CLAIM_COMPLETE:
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm COMPLETE claim could not be verified"
            )
    except BaseException as exc:
        if not arm_returned:
            # Preserve an arm() exception that demonstrably happened before it
            # published a permit. PENDING + pinned absence is the durable
            # pre-arm-crash state and needs no fabricated wrapper or stop().
            prearm_absence_proven = False
            try:
                retained = _read_checked_entry(
                    parent, claim_path.name, directory_fd
                )
                _, permit_absent = _read_stop_evidence(
                    switch, parent, switch_path, directory_fd
                )
                if (
                    retained is not None
                    and retained[0] == _INITIAL_ARM_CLAIM_PENDING
                    and permit_absent
                ):
                    verify_parent()
                    prearm_absence_proven = True
            except BaseException:
                pass
            if prearm_absence_proven:
                raise
        _revoke_initial_arm_or_raise(
            switch,
            switch_path,
            claim_path,
            directory_fd,
            "desktop initial-arm postcondition failed",
            exc,
        )
    return state


def initialize_desktop_switch_once():
    """Arm exactly one pristine packaged desktop control root.

    Tauri supplies stable app-data paths but never writes authority. Python is
    already inside ``cli.desktop_sidecar`` when this runs. It first publishes a
    durable CREATE_NEW claim; that claim is never removed. Consequently an
    existing claim, a sticky ``.stopped`` marker, a manually deleted permit, or
    a crash after claim creation can never be turned into an automatic re-arm.
    Direct/development sidecars without the claim environment remain unchanged.
    """

    paths = _initial_arm_paths()
    if paths is None:
        return None
    switch_path, claim_path = paths

    from daedalus.spine.killswitch import KillSwitch

    switch = KillSwitch(path=switch_path, sweep_managed=False)
    # This creates/verifies the parent, checks redirection, and proves another
    # process can observe the literal control path. A failed check is STOP, not
    # a reason to manufacture either the claim or permit.
    initial = switch.read_state()
    if not switch.control_check.ok:
        return initial

    parent = switch_path.parent
    initial_parent_identity = _parent_identity(parent)
    if os.name == "nt":
        # Reuse the settings owner's already-audited no-FILE_SHARE_DELETE
        # directory pin; it prevents parent rename/reparse substitution while
        # CREATE_NEW, arm(), and the postcondition are evaluated.
        from .effects import _pin_windows_directory

        with _pin_windows_directory(parent):
            def verify_windows_parent() -> None:
                if _parent_identity(parent) != initial_parent_identity:
                    raise DesktopSwitchInitializationRefused(
                        "desktop initial-arm parent identity changed"
                    )

            return _initialize_desktop_switch_inside_parent(
                switch,
                switch_path,
                claim_path,
                None,
                verify_windows_parent,
            )

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(parent, flags)
    try:
        pinned = os.fstat(directory_fd)
        if initial_parent_identity != (pinned.st_dev, pinned.st_ino):
            raise DesktopSwitchInitializationRefused(
                "desktop initial-arm parent identity changed"
            )
        def verify_posix_parent() -> None:
            pinned_now = os.fstat(directory_fd)
            if _parent_identity(parent) != initial_parent_identity:
                raise DesktopSwitchInitializationRefused(
                    "desktop initial-arm parent identity changed"
                )
            if not _same_identity(pinned_now, pinned):
                raise DesktopSwitchInitializationRefused(
                    "desktop initial-arm pinned parent identity changed"
                )

        return _initialize_desktop_switch_inside_parent(
            switch,
            switch_path,
            claim_path,
            directory_fd,
            verify_posix_parent,
        )
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> None:
    # The frozen sidecar mutates its writable runtime before the HTTP server's
    # narrower listen-socket boundary exists. Admit that bootstrap explicitly
    # through the canonical registry first; the nested web and desktop owners
    # retain authority for their own later effects.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.desktop_sidecar",
        REGISTRY_BY_ID["cli.desktop_sidecar"].effects,
        (process_guard_boundary_decision(),),
    )
    runtime = prepare_runtime()
    try:
        initialize_desktop_switch_once()
    except DesktopSwitchRevocationUnproven:
        # A RUN permit whose revocation cannot be proven is not a read-only
        # startup. Propagate the typed fatal result so the frozen sidecar exits
        # before chdir, environment adoption, manager construction, or HTTP.
        raise
    except Exception as exc:
        # Kill-switch initialization must fail closed for effects without
        # turning the switch into a guard that blocks read-only inspection.
        # The later owner reads the same stopped path and returns its typed
        # refusal when the operator requests an effect.
        print(f"Daedalus desktop initial arm refused: {exc}", file=sys.stderr)
    os.chdir(runtime)

    # Load the operator-owned desktop .env before importing modules that may
    # read OLLAMA_* at import time.
    from daedalus.foundation.env import load_env

    load_env(runtime / ".env")

    from daedalus.desktop_runtime import (
        DesktopRuntimeManager,
        install_tunnel_egress_policy,
        install_web_integration,
    )

    manager = DesktopRuntimeManager(runtime)
    install_tunnel_egress_policy()

    # One control plane only: extend the authenticated loopback server instead
    # of starting a second settings/service server beside it.
    from daedalus.interfaces.http import web_api

    install_web_integration(web_api, manager)
    try:
        web_api.main(argv, on_bound=manager.bootstrap)
    finally:
        manager.close()


__all__ = [
    "DESKTOP_INITIAL_ARM_CLAIM_ENV",
    "DESKTOP_PROJECT_COMMENT",
    "DESKTOP_PROJECT_SCHEMA",
    "DesktopSwitchInitializationRefused",
    "DesktopSwitchRevocationUnproven",
    "bundled_root",
    "initialize_desktop_switch_once",
    "main",
    "prepare_runtime",
]
