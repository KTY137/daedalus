"""Pinned effect ownership for desktop settings and local services.

The authenticated HTTP facade only dispatches. This module owns exact settings
publication and explicit loopback Ollama observation/adoption. v0.1.6 owns no
service process handles and therefore has no service-termination authority.
The file bridge keeps its separately registered ``file_bridge.watch`` boundary.

Managed IDE start and remote SSH are deliberately unavailable in v0.1.6. The
kernel has no long-lived project-write/network contract for OpenVSCode and no
physical SSH peer plus private-key custody contract. An underscore or a broad
HTTP row would not make either authority real.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ...atomic import REPLACE_RETRY_S
from ...kernel.offload_lease import (
    EgressAdmissionObservation,
    WaveLeaseDenied,
    WaveLeaseKillSwitchEngaged,
    acquire_effect_lease,
    control_root,
)
from ...sensitivity import Policy
from ...spine.envelope import canonical_sha
from ...spine.killswitch import KillSwitch, LoopHalted


SETTINGS_ENTRYPOINT_ID = "python.desktop_settings_persist"
OLLAMA_ENTRYPOINT_ID = "python.desktop_ollama_adopt"
SWITCH_ENTRYPOINT_ID = "python.desktop_switch"

REMOTE_SSH_UNAVAILABLE = (
    "Remote SSH is unavailable in Daedalus v0.1.6: an exact SSH peer/host-key "
    "admission and private-key custody contract is not implemented"
)
MANAGED_IDE_UNAVAILABLE = (
    "Managed IDE start is unavailable in Daedalus v0.1.6: the long-lived "
    "project-write and network authority is not implemented; the desktop "
    "does not probe or adopt an external IDE in this release"
)
MANAGED_OLLAMA_UNAVAILABLE = (
    "Managed Ollama start is unavailable in Daedalus v0.1.6: the desktop "
    "can adopt an already running loopback Ollama, but no enforced child "
    "filesystem boundary exists for spawning it"
)
MANAGED_BRIDGE_UNAVAILABLE = (
    "Managed bridge start is unavailable in Daedalus v0.1.6: run the registered "
    "`python -m daedalus.file_bridge watch --repo-root <repo>` "
    "entrypoint explicitly"
)


class DesktopEffectRefused(RuntimeError):
    """A desktop effect was rejected before application work started."""

    status_code = 400
    error_code = "desktop_effect_refused"
    committed = False


class DesktopValidationError(DesktopEffectRefused, ValueError):
    """Submitted desktop data failed exact validation."""

    error_code = "desktop_validation_error"


class DesktopPolicyDenied(DesktopEffectRefused):
    """Policy evaluated successfully and denied the requested effect."""

    status_code = 403
    error_code = "desktop_policy_denied"


class DesktopFeatureUnavailable(DesktopEffectRefused):
    """The release deliberately exposes no authority for this feature."""

    status_code = 409
    error_code = "desktop_feature_unavailable"


class DesktopEffectStopped(DesktopEffectRefused):
    """The canonical operator switch stopped the requested effect."""

    status_code = 423
    error_code = "desktop_operator_stop"


class DesktopEffectUnavailable(DesktopEffectRefused):
    """Kernel authorization/evidence was unavailable, so nothing may start."""

    status_code = 503
    error_code = "desktop_effect_authorization_unavailable"


class DesktopOllamaUnreachable(DesktopEffectUnavailable):
    """An authorized exact loopback Ollama probe did not verify Ollama."""

    error_code = "desktop_ollama_unreachable"


class DesktopSettingsDurabilityIndeterminate(DesktopEffectUnavailable):
    """Published bytes became visible but durable directory state is unknown."""

    error_code = "desktop_settings_durability_indeterminate"
    committed = True


class DesktopSettingsCommittedUnrecorded(DesktopEffectUnavailable):
    """Settings committed, but their terminal receipt could not be retained."""

    error_code = "desktop_settings_committed_receipt_unavailable"
    committed = True


class DesktopSettingsCommittedFollowupError(DesktopEffectUnavailable):
    """Settings and receipt completed, but a non-authoritative follow-up failed."""

    error_code = "desktop_settings_committed_followup_failed"
    committed = True


def _kernel_failure(context: str, exc: BaseException) -> DesktopEffectRefused:
    """Translate kernel failures at the owner edge into the HTTP contract."""

    if isinstance(exc, DesktopEffectRefused):
        return exc
    detail = f"{type(exc).__name__}: {str(exc)[:500]}"
    if isinstance(exc, (WaveLeaseKillSwitchEngaged, LoopHalted)):
        return DesktopEffectStopped(f"{context}: {detail}")
    if isinstance(exc, WaveLeaseDenied):
        return DesktopPolicyDenied(f"{context}: {detail}")
    return DesktopEffectUnavailable(f"{context}: {detail}")


def _hash_file(hasher: Any, path: Path, label: str) -> None:
    data = path.read_bytes()
    encoded = label.encode("utf-8")
    hasher.update(len(encoded).to_bytes(8, "big"))
    hasher.update(encoded)
    hasher.update(len(data).to_bytes(8, "big"))
    hasher.update(data)


def _compute_source_revision() -> str:
    """Hash the desktop execution closure once while this module is imported.

    The durable lease schema is still 40-hex. A source checkout hashes the
    exact implementation bytes loaded for this process, including dirty edits,
    instead of re-hashing mutable checkout files for every lease. A frozen
    build hashes its executable, binding the receipt to the shipped sidecar.
    """

    # The v0 lease field is 40 hex characters wide; truncating SHA-256 keeps
    # that wire contract without creating a new SHA-1 content identity.
    digest = hashlib.sha256()
    try:
        if bool(getattr(sys, "frozen", False)):
            _hash_file(digest, Path(sys.executable).resolve(), "frozen-sidecar")
        else:
            package = Path(__file__).resolve().parents[2]
            root = package.parent
            paths = (
                package / "atomic.py",
                package / "budget.py",
                package / "desktop_runtime.py",
                package / "interfaces" / "desktop" / "configuration.py",
                package / "interfaces" / "desktop" / "effects.py",
                package / "interfaces" / "desktop" / "http.py",
                package / "interfaces" / "desktop" / "projection.py",
                package / "interfaces" / "desktop" / "settings.py",
                package / "interfaces" / "http" / "effects.py",
                package / "kernel" / "offload_lease.py",
                package / "kernel" / "policy" / "ledger.py",
                package / "kernel" / "policy" / "limits.py",
                package / "limit_policy.py",
                package / "providers" / "ollama.py",
                package / "sensitivity.py",
                package / "spine" / "effect_boundary.py",
                package / "spine" / "envelope.py",
                package / "spine" / "killswitch.py",
            )
            for path in paths:
                _hash_file(digest, path, path.relative_to(root).as_posix())
    except OSError as exc:
        raise DesktopEffectRefused(
            f"desktop source identity is unreadable: {type(exc).__name__}: {exc}"
        ) from exc
    return digest.hexdigest()[:40]


_SOURCE_REVISION = _compute_source_revision()


def _source_revision() -> str:
    """Return the import-bound revision; never attest later disk mutations."""

    return _SOURCE_REVISION


def _operation_sha256(kind: str, material: Any) -> str:
    try:
        return canonical_sha({"kind": kind, "material": material})
    except (TypeError, ValueError):
        # Never serialise repr(material): it may contain credentials or invoke
        # attacker-controlled __repr__ code.
        return canonical_sha(
            {"kind": kind, "invalid_material_type": type(material).__name__}
        )


def _terminal_evidence_detail(granted: Any) -> str:
    """Bound evidence-store diagnostics for a typed owner-edge failure."""

    try:
        entrypoint_id = str(granted.lease.entrypoint_id)
        expected_not_applicable = (
            f"disjointness: {entrypoint_id} declares no containment contract, "
            "so this grant retains no primary-checkout disjointness record"
        )
        errors = tuple(
            str(value)[:300]
            for value in granted.evidence_errors
            if str(value) != expected_not_applicable
        )[-3:]
    except (AttributeError, TypeError):
        return ""
    return "; evidence errors: " + "; ".join(errors) if errors else ""


def _retained_record_is_valid(value: Any) -> bool:
    if type(value) is not dict:
        return False
    digest = value.get("record_sha256")
    return bool(
        type(digest) is str
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _prospective_section(manager: Any, raw: Any, name: str) -> Any:
    """Return one section as the submitted update would select it.

    ``section_updates`` is additive at the document level, so every omitted
    section comes from the manager's current canonical document.  Keeping this
    selection in the effect owner prevents admission from accidentally judging
    the old route when a scoped request supplies a new Ollama section.
    """

    if not isinstance(raw, dict):
        return manager.config[name]
    updates = raw.get("section_updates")
    if isinstance(updates, dict) and name in updates:
        return updates[name]
    if name in raw:
        return raw[name]
    return manager.config[name]


def _prospective_mode(manager: Any, raw: Any) -> str:
    """Select the Ollama mode from a full or owner-scoped settings request."""

    section = _prospective_section(manager, raw, "ollama")
    return str(section.get("mode", "local")).strip() if isinstance(section, dict) else ""


def _prospective_endpoints(manager: Any, raw: Any) -> tuple[str, str]:
    """Select the exact local Ollama and IDE endpoints from a request."""

    ollama = _prospective_section(manager, raw, "ollama")
    ide = _prospective_section(manager, raw, "ide")
    ollama_endpoint = (
        str(ollama.get("local_host", "")).strip()
        if isinstance(ollama, dict)
        else ""
    )
    ide_endpoint = (
        str(ide.get("endpoint", "")).strip() if isinstance(ide, dict) else ""
    )
    return ollama_endpoint, ide_endpoint


def _egress_admission(endpoint: str):
    """Compose the existing Ollama classifier into the issuer's exact port."""

    from ...providers.ollama import ollama_endpoint_admission
    from ...spine.effect_boundary import GuardDecision

    allowed, lane, why = ollama_endpoint_admission(endpoint)

    def admit(requested_lanes: tuple[str, ...]) -> EgressAdmissionObservation:
        requested = tuple(str(value) for value in requested_lanes)
        exact = requested == (lane,)
        return EgressAdmissionObservation(
            requested_lanes=requested,
            endpoints=(endpoint,),
            decision=GuardDecision(
                "provider.egress_policy",
                bool(allowed and exact),
                why
                if exact
                else (
                    f"requested lanes {requested!r} differ from endpoint lane "
                    f"{(lane,)!r}; {why}"
                ),
            ),
        )

    return (lane,), admit


def _is_reparse_point(path: Path) -> bool:
    """Detect symlinks and Windows reparse points without following them."""

    state = os.lstat(path)
    attributes = int(getattr(state, "st_file_attributes", 0))
    return bool(
        stat.S_ISLNK(state.st_mode)
        or attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        or getattr(state, "st_reparse_tag", 0)
    )


@contextlib.contextmanager
def _pin_windows_directory(path: Path):
    """Hold a Windows directory against rename/reparse substitution."""

    if os.name != "nt":
        yield None
        return

    import ctypes
    from ctypes import wintypes

    create_file = ctypes.windll.kernel32.CreateFileW
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
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD

    # FILE_LIST_DIRECTORY; share reads/writes but deliberately not DELETE, so
    # the opened directory cannot be renamed or replaced until publication is
    # complete. OPEN_REPARSE_POINT lets us reject, rather than traverse, a
    # final-component junction.
    handle = create_file(
        str(path),
        0x0001,
        0x0001 | 0x0002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise OSError(ctypes.get_last_error(), f"cannot pin directory {path}")
    try:
        if _is_reparse_point(path):
            raise DesktopEffectRefused(
                f"desktop settings directory is a reparse point: {path}"
            )
        size = get_final_path(handle, None, 0, 0)
        if not size:
            raise OSError(
                ctypes.get_last_error(), f"cannot resolve pinned directory {path}"
            )
        buffer = ctypes.create_unicode_buffer(size + 1)
        if not get_final_path(handle, buffer, len(buffer), 0):
            raise OSError(
                ctypes.get_last_error(), f"cannot resolve pinned directory {path}"
            )
        actual = buffer.value
        if actual.startswith("\\\\?\\UNC\\"):
            actual = "\\\\" + actual[8:]
        elif actual.startswith("\\\\?\\"):
            actual = actual[4:]
        if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(
            os.path.abspath(path)
        ):
            raise DesktopEffectRefused(
                "desktop settings directory handle resolved to an unexpected path"
            )
        yield handle
    finally:
        close_handle(handle)


def _flush_windows_directory(handle: Any) -> bool:
    """Attempt an additional parent flush for Windows directory handles.

    Windows filesystems do not uniformly permit ``FlushFileBuffers`` on a
    directory opened for ``FILE_LIST_DIRECTORY``. A supported flush must
    succeed. Known "directory flush unsupported" results are safe only because
    publication already used ``MoveFileExW(..., MOVEFILE_WRITE_THROUGH)``;
    callers may not substitute an ordinary ``os.replace`` and keep that claim.
    """

    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    flush = ctypes.WinDLL("kernel32", use_last_error=True).FlushFileBuffers
    flush.argtypes = (wintypes.HANDLE,)
    flush.restype = wintypes.BOOL
    if flush(handle):
        return True
    error = ctypes.get_last_error()
    if error in {1, 5, 6, 50, 87}:
        return False
    raise OSError(error, "cannot flush desktop settings directory")


def _regular_single_link(state: os.stat_result) -> bool:
    attributes = int(getattr(state, "st_file_attributes", 0))
    return bool(
        stat.S_ISREG(state.st_mode)
        and state.st_nlink == 1
        and not stat.S_ISLNK(state.st_mode)
        and not attributes
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        and not getattr(state, "st_reparse_tag", 0)
    )


_WINDOWS_REPLACE_PUBLISHED = "published"
_WINDOWS_REPLACE_PUBLISHED_AFTER_ERROR = "published_after_error"
_WINDOWS_REPLACE_UNKNOWN = "commit_unknown"


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _inspect_windows_publish_name(path: Path) -> tuple[str, os.stat_result | None]:
    """Return an explicit name observation without collapsing IO errors."""

    try:
        state = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "absent", None
    except OSError:
        return "uninspectable", None
    try:
        if not _regular_single_link(state):
            return "unsafe", state
    except BaseException:
        return "uninspectable", None
    return "regular", state


def _reconcile_windows_move_error(
    temp: Path,
    target: Path,
    *,
    intended: os.stat_result,
    original: os.stat_result | None,
) -> str:
    """Classify a MoveFileEx error by the exact inode intended for publish."""

    target_kind, target_state = _inspect_windows_publish_name(target)
    temp_kind, temp_state = _inspect_windows_publish_name(temp)
    target_is_intended = bool(
        target_kind == "regular"
        and target_state is not None
        and _same_file_identity(target_state, intended)
    )
    if target_is_intended:
        return _WINDOWS_REPLACE_PUBLISHED_AFTER_ERROR

    temp_is_intended = bool(
        temp_kind == "regular"
        and temp_state is not None
        and _same_file_identity(temp_state, intended)
    )
    target_is_original = bool(
        (original is None and target_kind == "absent")
        or (
            original is not None
            and target_kind == "regular"
            and target_state is not None
            and _same_file_identity(target_state, original)
        )
    )
    if temp_is_intended and target_is_original:
        return "uncommitted"
    return _WINDOWS_REPLACE_UNKNOWN


def _replace_windows_pinned(
    temp: Path,
    target: Path,
    *,
    switch: Any,
    intended: os.stat_result,
    original: os.stat_result | None,
) -> tuple[str, OSError | None]:
    """Retry one durable pinned-parent replace without scratch cleanup.

    ``FlushFileBuffers`` is not a portable directory-flush primitive on
    Windows (and commonly returns ``ERROR_ACCESS_DENIED`` for the pinned
    directory handle).  The publish operation therefore uses the documented
    Win32 write-through move itself.  ``MOVEFILE_REPLACE_EXISTING`` preserves
    the atomic replace contract and ``MOVEFILE_WRITE_THROUGH`` prevents a
    successful return before the move has reached disk.
    """

    deadline = time.monotonic() + REPLACE_RETRY_S
    while True:
        # Every retry is a new effect attempt: the operator may stop while a
        # concurrent Windows reader temporarily blocks the destination.
        switch.checkpoint()
        try:
            _move_file_ex_windows_write_through(temp, target)
            return _WINDOWS_REPLACE_PUBLISHED, None
        except OSError as exc:
            reconciled = _reconcile_windows_move_error(
                temp,
                target,
                intended=intended,
                original=original,
            )
            if reconciled != "uncommitted":
                # The caller owns manager refresh and typed terminal evidence.
                # In particular, an unknown result must not be translated to
                # committed=False and must not trigger scratch cleanup.
                return reconciled, exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.02, remaining))


def _move_file_ex_windows_write_through(temp: Path, target: Path) -> None:
    """Replace ``target`` with the exact Win32 durable-move flags.

    Microsoft documents ``MOVEFILE_WRITE_THROUGH`` as not returning until the
    file is actually moved on disk.  Keeping this call behind a tiny Python
    seam also lets the fault tests prove that a successful settings receipt
    cannot fall back to ``os.replace`` when a directory handle is unflushable.
    """

    if os.name != "nt":
        raise OSError("MoveFileExW is available only on Windows")

    import ctypes
    from ctypes import wintypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    move_file_ex.restype = wintypes.BOOL
    movefile_replace_existing = 0x00000001
    movefile_write_through = 0x00000008
    if not move_file_ex(
        str(temp),
        str(target),
        movefile_replace_existing | movefile_write_through,
    ):
        error = ctypes.get_last_error()
        raise OSError(
            error,
            "durable MoveFileExW could not publish desktop settings",
            str(target),
        )


class DesktopEffectOwner:
    """One manager's fixed settings and explicit Ollama-adoption authority."""

    def __init__(self, manager: Any, *, error_type: type[Exception]) -> None:
        self.manager = manager
        self.error_type = error_type
        self.root = Path(manager.root).resolve()
        self._switch = KillSwitch(repo_root=self.root, sweep_managed=False)
        self._switch_lock = threading.Lock()
        self._source_revision = _source_revision()

    def _resolved_paths(self, relatives: tuple[Path, ...]) -> tuple[str, ...]:
        """Validate fixed targets and return exact repository-relative paths."""

        root = self.root.resolve()
        resolved: list[str] = []
        for relative in relatives:
            if relative.is_absolute() or ".." in relative.parts:
                raise DesktopEffectRefused(
                    f"desktop write target is not repository-relative: {relative}"
                )
            lexical = root / relative
            try:
                target = lexical.resolve(strict=False)
                target.relative_to(root)
            except (OSError, ValueError) as exc:
                raise DesktopEffectRefused(
                    f"desktop write target escapes the application root: {relative}"
                ) from exc
            try:
                if lexical.is_symlink():
                    raise DesktopEffectRefused(
                        f"desktop write target is a symbolic link: {relative}"
                    )
            except OSError as exc:
                raise DesktopEffectRefused(
                    f"desktop write target cannot be inspected: {relative}: {exc}"
                ) from exc
            # Canonical EffectScope paths are repository-relative.  Returning
            # an absolute drive-qualified path here is both broader than needed
            # and invalid under the lease contract on Windows.
            resolved.append(relative.as_posix())
        return tuple(dict.fromkeys(resolved))

    def _settings_paths(self, nonce: str) -> tuple[str, ...]:
        config = Path(self.manager.config_path)
        expected = self.root / "config" / "connections.json"
        if config.absolute() != expected.absolute():
            raise DesktopEffectRefused(
                "desktop settings path differs from config/connections.json"
            )
        temp = (
            Path("config")
            / f".connections.json.{os.getpid()}.{nonce}.tmp"
        )
        return self._resolved_paths(
            (Path("config"), Path("config/connections.json"), temp)
        )

    def _ensure_switch(self) -> KillSwitch:
        """Authorize the control-root probe, then accept an operator permit.

        The first ``read_state`` in an interpreter proves that the control
        root is visible to another process.  That proof writes a nonce file
        and invokes the platform reader (``cmd /c type`` or ``cat``), so it is
        itself an exact registered effect and must start before the read.  This
        owner never arms or otherwise manufactures a permit.
        """

        from ...budget import process_guard_boundary_decision
        from ...spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        with self._switch_lock:
            try:
                row = REGISTRY_BY_ID[SWITCH_ENTRYPOINT_ID]
                begin_effect(
                    SWITCH_ENTRYPOINT_ID,
                    row.effects,
                    (process_guard_boundary_decision(),),
                )
                state = self._switch.read_state()
                if not state.running:
                    raise LoopHalted(
                        f"desktop kill switch is not armed: {state.reason}"
                    )
            except Exception as exc:
                raise _kernel_failure("desktop kill switch refused", exc) from exc
            return self._switch

    @staticmethod
    def _begin_authorized(
        granted: Any,
        writable_paths: tuple[str, ...],
        tools: tuple[str, ...],
        operation_sha256: str,
    ):
        if isinstance(granted, WaveLeaseDenied):
            raise DesktopPolicyDenied(
                "desktop effect lease denied: " + "; ".join(granted.reasons)
            )
        execution = granted.execution_for(
            0,
            writable_paths=writable_paths,
            tools=tools,
            operation_sha256=operation_sha256,
        )
        # The generic lease store reports a deliberately non-applicable
        # containment record as an evidence error for rows that declare no
        # containment contract.  That one exact note is metadata, not missing
        # evidence.  Every other retention error is fatal here: this desktop
        # owner requires a reproducible subject and exact execution record
        # *before* it lets the ledger enter STARTED.
        entrypoint_id = str(granted.lease.entrypoint_id)
        expected_not_applicable = (
            f"disjointness: {entrypoint_id} declares no containment contract, "
            "so this grant retains no primary-checkout disjointness record"
        )
        unexpected_errors = tuple(
            str(error)
            for error in granted.evidence_errors
            if str(error) != expected_not_applicable
        )
        execution_key = f"lease_execution:{execution.execution_id}"
        required_records = ("lease_subject", execution_key)
        missing_records = tuple(
            key
            for key in required_records
            if not isinstance(granted.evidence_records.get(key), str)
            or len(granted.evidence_records[key]) != 64
            or any(
                character not in "0123456789abcdef"
                for character in granted.evidence_records[key]
            )
        )
        if unexpected_errors or missing_records:
            details: list[str] = []
            if unexpected_errors:
                details.append("; ".join(unexpected_errors))
            if missing_records:
                details.append(
                    "missing retained records: " + ", ".join(missing_records)
                )
            raise DesktopEffectUnavailable(
                "desktop effect evidence unavailable before start: "
                + "; ".join(details)
            )
        started = granted.authorization.begin_effect(execution)
        if not started.execute:
            raise DesktopEffectRefused(
                "desktop effect already has a pending or terminal execution receipt"
            )
        return execution, started

    @staticmethod
    def _fail_authorized(
        granted: Any, execution: Any, started: Any, exc: BaseException
    ) -> bool:
        """Best-effort FAILED terminalisation, including retained evidence."""

        detail = hashlib.sha256(
            f"{type(exc).__name__}:{str(exc)[:500]}".encode("utf-8", "replace")
        ).hexdigest()
        terminalized = False
        try:
            granted.authorization.finish_effect(
                started.receipt,
                outcome="FAILED",
                detail_sha256=detail,
            )
            terminalized = True
        except BaseException:
            # A durable finish can fail after its own commit.  Still ask the
            # evidence store for the ledger's terminal truth instead of
            # assuming the absence of a Python return means no receipt exists.
            pass
        before_errors = len(granted.evidence_errors)
        try:
            retained = granted.retain_terminal_record(execution)
        except BaseException:
            return False
        return bool(
            terminalized
            and _retained_record_is_valid(retained)
            and len(granted.evidence_errors) == before_errors
        )

    @staticmethod
    def _complete_authorized(
        granted: Any, execution: Any, started: Any, detail_sha256: str
    ) -> None:
        before_errors = len(granted.evidence_errors)
        granted.authorization.finish_effect(
            started.receipt,
            outcome="COMPLETED",
            detail_sha256=detail_sha256,
        )
        retained = granted.retain_terminal_record(execution)
        if not _retained_record_is_valid(retained) or len(
            granted.evidence_errors
        ) != before_errors:
            details = "; ".join(granted.evidence_errors[before_errors:])
            raise DesktopEffectUnavailable(
                "desktop terminal effect evidence was not retained"
                + (f": {details}" if details else "")
            )

    def _apply_environment_from(
        self,
        config: dict[str, Any],
        *,
        budget_policy_error: str,
    ) -> None:
        """Apply environment values from one private, normalized generation."""

        from ... import budget as budget_kernel
        from ...limit_policy import ENV_EXECUTION_LIMIT_POLICY, ExecutionLimitPolicy
        from . import settings as desktop_settings
        from .configuration import normalize_config

        try:
            detached = json.loads(json.dumps(config))
        except (TypeError, ValueError, RuntimeError) as exc:
            raise DesktopValidationError(
                "desktop environment configuration is not JSON-compatible"
            ) from exc
        frozen = normalize_config(
            detached,
            budget_defaults=detached.get("budget"),
            caps_defaults=detached.get("caps"),
            allow_legacy_remote=True,
        )
        view = SimpleNamespace(
            config=frozen,
            _budget_policy_error=str(budget_policy_error),
            _base_trusted=str(getattr(self.manager, "_base_trusted", "")),
        )

        assignments, removals = desktop_settings.environment_projection(
            view,
            budget_kernel=budget_kernel,
            env_execution_limit_policy=ENV_EXECUTION_LIMIT_POLICY,
            execution_limit_policy=ExecutionLimitPolicy,
            tunnel_forward_var="DAEDALUS_OLLAMA_TUNNEL_FORWARD",
            tunnel_target_var="DAEDALUS_OLLAMA_TUNNEL_TARGET",
            remote_ok_var="DAEDALUS_OLLAMA_REMOTE_OK",
            trusted_hosts_var="DAEDALUS_TRUSTED_HOSTS",
        )
        for name in removals:
            if name not in assignments:
                os.environ.pop(name, None)
        os.environ.update(assignments)

    def _detached_snapshot(self) -> dict[str, Any]:
        """Run the fixed read-only projector and detach its JSON result."""

        from ... import file_bridge
        from . import projection as desktop_projection

        projected = desktop_projection.snapshot(
            self.manager,
            file_bridge=file_bridge,
            environ=os.environ,
            tunnel_target_var="DAEDALUS_OLLAMA_TUNNEL_TARGET",
        )
        return json.loads(json.dumps(projected))

    def _authorize_settings(
        self,
        request: dict[str, Any],
        prepared: dict[str, Any],
    ) -> dict[str, Any]:
        """Lease, publish, adopt, and receipt one private validated snapshot."""

        prospective_mode = _prospective_mode(self.manager, request)
        prospective_endpoints = _prospective_endpoints(self.manager, request)
        prepared_endpoints = (
            prepared["ollama"]["local_host"],
            prepared["ide"]["endpoint"],
        )
        if (
            prospective_mode != prepared["ollama"]["mode"]
            or prospective_endpoints != prepared_endpoints
        ):
            raise DesktopValidationError(
                "desktop settings admission differs from validated prospective routes"
            )
        if prospective_mode == "remote_ssh":
            raise DesktopFeatureUnavailable(REMOTE_SSH_UNAVAILABLE)
        nonce = uuid.uuid4().hex
        paths = self._settings_paths(nonce)
        switch = self._ensure_switch()
        operation_sha = _operation_sha256("settings-persist", prepared)
        # Authorize the repair under the currently loaded canonical policy,
        # never under the prospective document.  Passing it explicitly keeps
        # an invalid deployment env repairable without letting new settings
        # authorize their own persistence.
        from ...limit_policy import ExecutionLimitPolicy

        current_limit_policy = ExecutionLimitPolicy.from_dict(
            self.manager.config["caps"]
        )
        try:
            granted = acquire_effect_lease(
                self.root,
                entrypoint_id=SETTINGS_ENTRYPOINT_ID,
                source_revision=self._source_revision,
                mission_id="desktop-runtime",
                attempt_id=f"settings-persist-{nonce}",
                positions=1,
                writable_paths=paths,
                lanes=(),
                tools=(),
                max_spend_usd=0.0,
                timeout_s=120.0,
                contained=False,
                write_policy=Policy(write_allow=paths),
                limit_policy=current_limit_policy,
                switch=switch,
                trace_id=f"desktop:settings-persist:{nonce}",
                lease_id=f"desktop-settings-persist-{nonce}",
                evidence_root=(
                    control_root(self.root) / "desktop-effect-evidence" / nonce
                ),
                operation_sha256=operation_sha,
            )
            execution, started = self._begin_authorized(
                granted, paths, (), operation_sha
            )
        except Exception as exc:
            raise _kernel_failure(
                "desktop settings authorization unavailable", exc
            ) from exc

        manager = self.manager
        previous = json.loads(json.dumps(manager.config))
        old_route = (
            previous["ollama"]["mode"],
            previous["ollama"]["local_host"],
            json.dumps(previous["ollama"]["remote"], sort_keys=True),
        )
        new_route = (
            prepared["ollama"]["mode"],
            prepared["ollama"]["local_host"],
            json.dumps(prepared["ollama"]["remote"], sort_keys=True),
        )
        encoded = (
            json.dumps(prepared, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        target = self.root / "config" / "connections.json"
        parent = target.parent
        temp = self.root / Path(paths[-1])
        published_visible = False
        publication_indeterminate = False
        committed = False
        try:
            if Path(manager.config_path) != target or temp.parent != parent:
                raise DesktopEffectRefused("desktop settings commit path changed")
            if not self.root.is_dir() or _is_reparse_point(self.root):
                raise DesktopEffectRefused(
                    "desktop application root must be a regular directory"
                )
            switch.checkpoint()
            parent.mkdir(exist_ok=True)
            if _is_reparse_point(parent) or parent.resolve() != parent:
                raise DesktopEffectRefused(
                    f"desktop settings directory is redirected: {parent}"
                )

            if os.name == "nt":
                with _pin_windows_directory(parent) as directory_handle:
                    scratch_created = False
                    replaced = False
                    scratch_cleanup_safe = True
                    identity: os.stat_result | None = None
                    try:
                        try:
                            existing = os.lstat(target)
                        except FileNotFoundError:
                            existing = None
                        if existing is not None and not _regular_single_link(existing):
                            raise DesktopEffectRefused(
                                "desktop settings target is redirected or hard-linked"
                            )
                        # CREATE_NEW refuses every pre-planted link instead of
                        # opening and truncating an attacker-selected inode.
                        switch.checkpoint()
                        with temp.open("xb") as output:
                            scratch_created = True
                            identity = os.fstat(output.fileno())
                            switch.checkpoint()
                            written = output.write(encoded)
                            if written != len(encoded):
                                raise OSError(
                                    f"short settings write: {written} of {len(encoded)}"
                                )
                            output.flush()
                            os.fsync(output.fileno())
                            identity = os.fstat(output.fileno())
                        named = os.lstat(temp)
                        if (
                            not _regular_single_link(named)
                            or identity is None
                            or (named.st_dev, named.st_ino)
                            != (identity.st_dev, identity.st_ino)
                        ):
                            raise DesktopEffectRefused(
                                "desktop settings scratch identity changed"
                            )
                        move_status, move_error = _replace_windows_pinned(
                            temp,
                            target,
                            switch=switch,
                            intended=identity,
                            original=existing,
                        )
                        if move_status in {
                            _WINDOWS_REPLACE_PUBLISHED,
                            _WINDOWS_REPLACE_PUBLISHED_AFTER_ERROR,
                        }:
                            replaced = True
                            published_visible = True
                            # Never retain a stale in-memory generation after
                            # the intended inode becomes the target, even if a
                            # wrapper reports an error after native publication.
                            manager.config = prepared
                        else:
                            publication_indeterminate = True
                            scratch_cleanup_safe = False
                            # Unknown means exactly that: do not pretend either
                            # generation won. Adopt prepared only when the exact
                            # encoded bytes can independently be read back.
                            try:
                                if target.read_bytes() == encoded:
                                    manager.config = prepared
                            except OSError:
                                pass
                        if move_error is not None:
                            raise move_error
                        published = os.lstat(target)
                        if (
                            not _regular_single_link(published)
                            or (published.st_dev, published.st_ino)
                            != (identity.st_dev, identity.st_ino)
                        ):
                            raise DesktopEffectRefused(
                                "desktop settings publication identity changed"
                            )
                        # The file bytes were flushed before the documented
                        # write-through move. When the filesystem additionally
                        # supports a directory-handle flush, require it. A known
                        # unsupported result is covered by MoveFileExW's
                        # MOVEFILE_WRITE_THROUGH contract, never by a bare
                        # os.replace fallback.
                        _flush_windows_directory(directory_handle)
                        committed = True
                    finally:
                        # Cleanup is legal only while the parent remains pinned
                        # and only when the name still identifies our inode.
                        if (
                            scratch_created
                            and not replaced
                            and scratch_cleanup_safe
                            and identity is not None
                        ):
                            try:
                                leftover = os.lstat(temp)
                                if (
                                    _regular_single_link(leftover)
                                    and (leftover.st_dev, leftover.st_ino)
                                    == (identity.st_dev, identity.st_ino)
                                ):
                                    temp.unlink()
                            except OSError:
                                pass
            else:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                directory_flags |= getattr(os, "O_CLOEXEC", 0)
                directory_flags |= getattr(os, "O_NOFOLLOW", 0)
                directory_fd = os.open(parent, directory_flags)
                file_fd = -1
                scratch_created = False
                replaced = False
                identity = None
                try:
                    directory_identity = os.fstat(directory_fd)
                    named_directory = os.stat(parent, follow_symlinks=False)
                    if (
                        not stat.S_ISDIR(named_directory.st_mode)
                        or (named_directory.st_dev, named_directory.st_ino)
                        != (directory_identity.st_dev, directory_identity.st_ino)
                    ):
                        raise DesktopEffectRefused(
                            "desktop settings directory identity changed"
                        )
                    try:
                        existing = os.stat(
                            target.name,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        existing = None
                    if existing is not None and not _regular_single_link(existing):
                        raise DesktopEffectRefused(
                            "desktop settings target is redirected or hard-linked"
                        )
                    switch.checkpoint()
                    file_fd = os.open(
                        temp.name,
                        flags,
                        0o600,
                        dir_fd=directory_fd,
                    )
                    scratch_created = True
                    identity = os.fstat(file_fd)
                    view = memoryview(encoded)
                    while view:
                        switch.checkpoint()
                        count = os.write(file_fd, view)
                        if count <= 0:
                            raise OSError("short settings write")
                        view = view[count:]
                    os.fsync(file_fd)
                    identity = os.fstat(file_fd)
                    named = os.stat(
                        temp.name,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                    if (
                        not _regular_single_link(named)
                        or (named.st_dev, named.st_ino)
                        != (identity.st_dev, identity.st_ino)
                    ):
                        raise DesktopEffectRefused(
                            "desktop settings scratch identity changed"
                        )
                    switch.checkpoint()
                    os.replace(
                        temp.name,
                        target.name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                    )
                    replaced = True
                    published_visible = True
                    manager.config = prepared
                    published = os.stat(
                        target.name,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                    if (
                        not _regular_single_link(published)
                        or (published.st_dev, published.st_ino)
                        != (identity.st_dev, identity.st_ino)
                    ):
                        raise DesktopEffectRefused(
                            "desktop settings publication identity changed"
                        )
                    os.fsync(directory_fd)
                    named_directory = os.stat(parent, follow_symlinks=False)
                    if (
                        named_directory.st_dev,
                        named_directory.st_ino,
                    ) != (
                        directory_identity.st_dev,
                        directory_identity.st_ino,
                    ):
                        raise DesktopEffectRefused(
                            "desktop settings directory identity changed"
                        )
                    committed = True
                finally:
                    if file_fd >= 0:
                        try:
                            os.close(file_fd)
                        except OSError:
                            # The file was already fsync'd; close is not allowed
                            # to turn a durable publication into a false FAILED.
                            pass
                    # Keep cleanup descriptor-relative and inside the pinned
                    # directory lifetime. Never unlink an outer pathname.
                    if scratch_created and not replaced and identity is not None:
                        try:
                            leftover = os.stat(
                                temp.name,
                                dir_fd=directory_fd,
                                follow_symlinks=False,
                            )
                            if (
                                _regular_single_link(leftover)
                                and (leftover.st_dev, leftover.st_ino)
                                == (identity.st_dev, identity.st_ino)
                            ):
                                os.unlink(temp.name, dir_fd=directory_fd)
                        except OSError:
                            pass
                    try:
                        os.close(directory_fd)
                    except OSError:
                        pass

        except BaseException as exc:
            retained_failure = self._fail_authorized(
                granted, execution, started, exc
            )
            if not isinstance(exc, Exception):
                raise
            if published_visible or publication_indeterminate:
                detail = (
                    "settings became visible, but publication durability could not "
                    "be confirmed"
                    if published_visible
                    else "settings publication outcome could not be determined"
                )
                error: DesktopEffectRefused = DesktopSettingsDurabilityIndeterminate(
                    f"{detail}; reload settings before retrying"
                )
            else:
                error = _kernel_failure("desktop settings persistence failed", exc)
            if not retained_failure:
                evidence_detail = _terminal_evidence_detail(granted)
                if published_visible or publication_indeterminate:
                    raise DesktopSettingsDurabilityIndeterminate(
                        f"{error}; FAILED terminal effect evidence was not retained"
                        f"{evidence_detail}"
                    ) from exc
                raise DesktopEffectUnavailable(
                    f"{error}; FAILED terminal effect evidence was not retained"
                    f"{evidence_detail}"
                ) from exc
            raise error from exc

        if not committed:
            # Defensive invariant: both platform publishers set this only after
            # exact identity plus their strongest available durability check.
            terminal: DesktopEffectRefused
            if published_visible or publication_indeterminate:
                terminal = DesktopSettingsDurabilityIndeterminate(
                    "desktop settings publisher returned without durable completion"
                )
            else:
                terminal = DesktopEffectUnavailable(
                    "desktop settings publisher returned without publication"
                )
            retained_failure = self._fail_authorized(
                granted, execution, started, terminal
            )
            if not retained_failure:
                evidence_detail = _terminal_evidence_detail(granted)
                if published_visible or publication_indeterminate:
                    raise DesktopSettingsDurabilityIndeterminate(
                        f"{terminal}; FAILED terminal effect evidence was not retained"
                        f"{evidence_detail}"
                    )
                raise DesktopEffectUnavailable(
                    f"{terminal}; FAILED terminal effect evidence was not retained"
                    f"{evidence_detail}"
                )
            raise terminal

        # The settings effect is complete at durable publish + exact identity.
        # Terminalise and retain it before any environment/projection follow-up;
        # no later failure may rewrite this receipt to FAILED.
        try:
            self._complete_authorized(granted, execution, started, operation_sha)
        except BaseException as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:500]}"
            raise DesktopSettingsCommittedUnrecorded(
                "settings were persisted but their terminal effect receipt could "
                "not be retained; reload settings before retrying; " + detail
            ) from exc

        manager._config_error = ""
        manager._budget_policy_error = ""
        if old_route != new_route:
            manager._ollama_observation = {
                "observed": False,
                "endpoint": prepared["ollama"]["local_host"],
                "observed_at": None,
                "reachable": False,
                "last_error": "not probed for the configured endpoint",
            }
        adoption_errors: list[str] = []
        try:
            self._apply_environment_from(prepared, budget_policy_error="")
        except Exception as exc:
            adoption_errors.append(
                f"environment adoption: {type(exc).__name__}: {str(exc)[:500]}"
            )
        try:
            result = self._detached_snapshot()
        except Exception as exc:
            raise DesktopSettingsCommittedFollowupError(
                "settings and terminal receipt were committed, but the detached "
                "status projection failed; reload settings before retrying"
            ) from exc
        if adoption_errors:
            result["startup_error"] = "; ".join(adoption_errors)
        return result

    def save_settings(self, raw: Any) -> dict[str, Any]:
        """Validate first, then persist and adopt through exact nested owners."""

        from ...limit_policy import ExecutionLimitPolicy, LimitAxes, MODE_CUSTOM
        from . import settings as desktop_settings
        from . import configuration as desktop_configuration

        try:
            request = json.loads(json.dumps(raw))
        except (TypeError, ValueError, RuntimeError) as exc:
            raise DesktopValidationError(
                "settings must be a JSON-compatible object"
            ) from exc

        with self.manager._lock:
            current_remote = json.loads(
                json.dumps(self.manager.config["ollama"]["remote"])
            )

            def normalize_update(value: Any, **kwargs: Any) -> dict[str, Any]:
                return desktop_configuration.normalize_config(
                    value,
                    current_remote=current_remote,
                    **kwargs,
                )

            try:
                prepared = desktop_settings.prepare_settings(
                    self.manager,
                    request,
                    json_module=json,
                    normalize_config=normalize_update,
                    execution_limit_policy=ExecutionLimitPolicy,
                    limit_axes=LimitAxes,
                    mode_custom=MODE_CUSTOM,
                )
            except ValueError as exc:
                raise DesktopValidationError(str(exc)) from exc
            return self._authorize_settings(request, prepared)

    def start_bridge(self) -> dict[str, Any]:
        raise DesktopFeatureUnavailable(MANAGED_BRIDGE_UNAVAILABLE)

    def start_ollama(self) -> dict[str, Any]:
        """Adopt an existing loopback Ollama; never spawn a desktop child."""

        from .configuration import normalize_config

        with self.manager._lock:
            try:
                frozen = normalize_config(
                    json.loads(json.dumps(self.manager.config)),
                    allow_legacy_remote=True,
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                raise DesktopValidationError(
                    f"desktop Ollama configuration is invalid: {exc}"
                ) from exc
        if frozen["ollama"]["mode"] == "remote_ssh":
            raise DesktopFeatureUnavailable(REMOTE_SSH_UNAVAILABLE)
        endpoint = frozen["ollama"]["local_host"]
        switch = self._ensure_switch()
        operation_sha = _operation_sha256(
            "local-ollama-adopt", {"endpoint": endpoint}
        )
        lanes, admission = _egress_admission(endpoint)
        nonce = uuid.uuid4().hex
        try:
            granted = acquire_effect_lease(
                self.root,
                entrypoint_id=OLLAMA_ENTRYPOINT_ID,
                source_revision=self._source_revision,
                mission_id="desktop-runtime",
                attempt_id=f"local-ollama-adopt-{nonce}",
                positions=1,
                writable_paths=(),
                lanes=lanes,
                tools=(),
                max_spend_usd=0.0,
                timeout_s=120.0,
                contained=False,
                switch=switch,
                trace_id=f"desktop:local-ollama-adopt:{nonce}",
                lease_id=f"desktop-local-ollama-adopt-{nonce}",
                evidence_root=(
                    control_root(self.root) / "desktop-effect-evidence" / nonce
                ),
                egress_admission=admission,
                operation_sha256=operation_sha,
            )
            execution, started = self._begin_authorized(
                granted, (), (), operation_sha
            )
        except Exception as exc:
            raise _kernel_failure(
                "local Ollama adoption authorization unavailable", exc
            ) from exc
        try:
            result = self.manager._adopt_local_ollama_owned(
                endpoint,
                switch=switch,
            )
        except BaseException as exc:
            retained_failure = self._fail_authorized(
                granted, execution, started, exc
            )
            if not isinstance(exc, Exception):
                raise
            error = _kernel_failure("local Ollama adoption failed", exc)
            if not retained_failure:
                evidence_detail = _terminal_evidence_detail(granted)
                raise DesktopEffectUnavailable(
                    f"{error}; FAILED terminal effect evidence was not retained"
                    f"{evidence_detail}"
                ) from exc
            raise error from exc
        try:
            self._complete_authorized(granted, execution, started, operation_sha)
        except BaseException as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:500]}"
            raise DesktopEffectUnavailable(
                "local Ollama adoption terminal evidence was not retained; "
                f"no child was started; {detail}"
            ) from exc
        return result

    def start_ide(self, project: Any = None) -> dict[str, Any]:
        del project
        raise DesktopFeatureUnavailable(MANAGED_IDE_UNAVAILABLE)

    def stop_ollama(self) -> None:
        raise DesktopFeatureUnavailable(
            "Ollama stop is unavailable in Daedalus v0.1.6: the desktop does "
            "not own or terminate an external/adopted Ollama process"
        )

    def stop_ide(self, *, strict: bool = False, timeout: float = 8.0) -> None:
        del strict, timeout
        raise DesktopFeatureUnavailable(
            "IDE stop is unavailable in Daedalus v0.1.6: the desktop does not "
            "own or terminate an external/adopted IDE process"
        )

    def close(self, *, strict: bool = False, timeout: float = 8.0) -> None:
        del strict, timeout
        with self.manager._lock:
            self.manager._closed = True

    def bootstrap(self) -> dict[str, Any]:
        """Return startup state without starting or probing a managed service."""

        return self._detached_snapshot()


__all__ = [
    "DesktopEffectOwner",
    "DesktopEffectRefused",
    "DesktopEffectStopped",
    "DesktopEffectUnavailable",
    "DesktopFeatureUnavailable",
    "DesktopOllamaUnreachable",
    "DesktopPolicyDenied",
    "DesktopSettingsCommittedFollowupError",
    "DesktopSettingsCommittedUnrecorded",
    "DesktopSettingsDurabilityIndeterminate",
    "DesktopValidationError",
    "MANAGED_BRIDGE_UNAVAILABLE",
    "MANAGED_IDE_UNAVAILABLE",
    "MANAGED_OLLAMA_UNAVAILABLE",
    "OLLAMA_ENTRYPOINT_ID",
    "REMOTE_SSH_UNAVAILABLE",
    "SETTINGS_ENTRYPOINT_ID",
    "_prospective_endpoints",
    "_prospective_mode",
]
