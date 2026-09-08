"""Fail-closed Linux candidate containment through rootless Podman/OCI.

The backend is intentionally narrow.  It supports native Linux hosts (the
packaged Podman path used by Debian and RHEL), requires an operator-pinned local
image digest, creates the container without starting it, verifies the resolved
configuration, and only then attaches to it.  There is no host-process
fallback.

The candidate receives one read/write host bind at ``/workspace``.  The image
root is read-only; ``/tmp`` is an ephemeral bounded tmpfs.  Network, PID, IPC,
UTS and cgroup namespaces are private, the network has no interfaces, all Linux
capabilities are dropped, and no-new-privileges is active.  Rootless Podman and
cgroup v2 are mandatory so process and memory limits can be verified.

This is container isolation, not a virtual machine.  It does not claim to
survive a kernel or OCI-runtime escape, a malicious host user racing the
create/inspect/start sequence, or disk exhaustion inside the writable
workspace.  Those limits are kept explicit instead of being delegated to a
prompt.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence

from daedalus.spine.containment import (
    ContainmentAttestation,
    ContainmentUnavailable,
    OciContainmentFacts,
)

LINUX_OCI_IMAGE_ENV = "DAEDALUS_LINUX_OCI_IMAGE"
LINUX_OCI_RUNTIME_ENV = "DAEDALUS_LINUX_OCI_RUNTIME"
DEFAULT_PODMAN_PATH = "/usr/bin/podman"
DEFAULT_PRLIMIT_PATH = "/usr/bin/prlimit"
DEFAULT_SECCOMP_PROFILE = "/usr/share/containers/seccomp.json"
MIN_PODMAN_VERSION = (4, 3, 0)
OCI_WORKSPACE = "/workspace"
OCI_TMP = "/tmp"
OCI_PIDS_LIMIT = 96
OCI_MEMORY_LIMIT_BYTES = 4 * 1024 * 1024 * 1024
OCI_CPU_LIMIT = 2.0
OCI_TMPFS_LIMIT_BYTES = 512 * 1024 * 1024
OCI_OUTPUT_LIMIT_BYTES = 16 * 1024 * 1024
DEFAULT_OCI_RUNTIME_TIMEOUT_S = 900.0
WORKSPACE_ENTRY_LIMIT = 100_000
CONTROL_TIMEOUT_S = 20.0

_IMAGE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._:/-]*)@"
    r"sha256:(?P<digest>[0-9a-f]{64})$"
)
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")

# Nothing from the host environment is copied into the candidate.  These
# values are policy-owned constants and ``--unsetenv-all`` removes image and
# containers.conf defaults before they are installed.
_CANDIDATE_ENV = {
    "CI": "1",
    "HOME": OCI_TMP,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PYTHONDONTWRITEBYTECODE": "1",
    "TEMP": OCI_TMP,
    "TMP": OCI_TMP,
    "TMPDIR": OCI_TMP,
    "TZ": "UTC",
}
_PODMAN_ADDED_ENV = frozenset({"HOSTNAME", "container"})

# Podman itself needs only enough host context to find its rootless storage and
# user runtime directory. Registry credentials and provider tokens are neither
# needed (pulling is forbidden) nor passed.
_RUNTIME_ENV_NAMES = frozenset({
    "DBUS_SESSION_BUS_ADDRESS",
    "HOME",
    "LANG",
    "LC_ALL",
    "XDG_RUNTIME_DIR",
})
_RUNTIME_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass(frozen=True)
class _Preflight:
    runtime: Path
    runtime_env: dict[str, str]
    runtime_version: str
    image_reference: str
    image_reference_digest: str
    local_image_id: str
    local_image_digest: str
    uid: int
    gid: int
    cgroup_version: str
    seccomp_profile: Path
    seccomp_profile_sha256: str
    automatic_host_mounts_disabled: bool
    oci_runtime_path: Path
    process_monitor_path: Path
    limit_helper_path: Path


def _is_native_linux() -> bool:
    return sys.platform.startswith("linux") and os.name == "posix"


def _effective_ids() -> tuple[int, int]:
    if not hasattr(os, "geteuid") or not hasattr(os, "getegid"):
        raise ContainmentUnavailable("Linux containment requires POSIX user IDs")
    return int(os.geteuid()), int(os.getegid())


def _runtime_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    base = os.environ if source is None else source
    result = {
        name: str(value)
        for name, value in base.items()
        if name in _RUNTIME_ENV_NAMES and isinstance(value, str)
    }
    result["PATH"] = _RUNTIME_PATH
    # Podman otherwise merges distribution, administrator and rootless-user
    # containers.conf files.  The candidate boundary supplies every relevant
    # option explicitly; an empty, immutable config source makes that true for
    # every control-plane invocation as well as create/start.
    result["CONTAINERS_CONF"] = "/dev/null"
    return result


def _podman_argv(
    runtime: Path,
    *command: str,
    oci_runtime: Path | None = None,
    process_monitor: Path | None = None,
    hooks_dir: Path | None = None,
) -> tuple[str, ...]:
    """Build one local-only Podman invocation from trusted absolute paths."""
    argv = [str(runtime), "--remote=false"]
    if oci_runtime is not None:
        argv.append(f"--runtime={oci_runtime}")
    if process_monitor is not None:
        argv.append(f"--conmon={process_monitor}")
    if hooks_dir is not None:
        argv.append(f"--hooks-dir={hooks_dir}")
    argv.extend(str(part) for part in command)
    return tuple(argv)


def _stderr_tail(proc: subprocess.CompletedProcess[bytes]) -> str:
    data = proc.stderr or proc.stdout or b""
    text = data.decode("utf-8", "replace").strip().replace("\x00", "")
    return text[-1200:] or "no diagnostic output"


def _run_control(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    timeout_s: float = CONTROL_TIMEOUT_S,
) -> subprocess.CompletedProcess[bytes]:
    """Run trusted Podman control-plane work without a shell."""
    try:
        proc = subprocess.run(
            [str(part) for part in argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            close_fds=True,
            timeout=float(timeout_s),
            check=False,
        )
    except FileNotFoundError as exc:
        raise ContainmentUnavailable("rootless Podman runtime was not found") from exc
    except PermissionError as exc:
        raise ContainmentUnavailable("rootless Podman runtime is not executable") from exc
    except subprocess.TimeoutExpired as exc:
        raise ContainmentUnavailable("rootless Podman control operation timed out") from exc
    except OSError as exc:
        raise ContainmentUnavailable(
            f"rootless Podman control operation could not start: {exc}"
        ) from exc
    return proc


def _checked_control(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    operation: str,
) -> subprocess.CompletedProcess[bytes]:
    proc = _run_control(argv, env=env)
    if proc.returncode != 0:
        raise ContainmentUnavailable(
            f"rootless Podman {operation} refused before candidate start "
            f"(exit {proc.returncode}): {_stderr_tail(proc)}"
        )
    return proc


def _json_payload(proc: subprocess.CompletedProcess[bytes], operation: str) -> Any:
    try:
        return json.loads((proc.stdout or b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContainmentUnavailable(
            f"rootless Podman {operation} returned invalid JSON"
        ) from exc


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContainmentUnavailable(f"Podman {label} is not an object")
    return value


def _ci_get(mapping: Mapping[str, Any], key: str, default: Any = None) -> Any:
    wanted = key.casefold()
    for actual, value in mapping.items():
        if str(actual).casefold() == wanted:
            return value
    return default


def _one_inspect(value: Any, label: str) -> Mapping[str, Any]:
    if isinstance(value, list):
        if len(value) != 1:
            raise ContainmentUnavailable(f"Podman {label} did not identify exactly one object")
        value = value[0]
    return _mapping(value, label)


def _empty(value: Any, *, strings: bool = False) -> bool:
    return value is None or value in ((), [], {}) or (strings and value == "")


def _parse_version(raw: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(raw.strip())
    if match is None:
        raise ContainmentUnavailable(f"Podman reported an unparseable version {raw!r}")
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def _trusted_runtime_path() -> Path:
    configured = os.environ.get(LINUX_OCI_RUNTIME_ENV, DEFAULT_PODMAN_PATH)
    path = Path(configured)
    if not path.is_absolute():
        raise ContainmentUnavailable(
            f"{LINUX_OCI_RUNTIME_ENV} must name an absolute Podman executable"
        )
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise ContainmentUnavailable(f"Podman runtime {path} is unavailable: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise ContainmentUnavailable(f"Podman runtime {resolved} is not an executable file")
    if resolved.name != "podman":
        raise ContainmentUnavailable("remote or wrapped Podman runtimes are not admitted")
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise ContainmentUnavailable(
            "Podman runtime must be root-owned and not group/world writable"
        )
    return resolved


def _trusted_reported_executable(
    raw: Any,
    *,
    allowed_names: set[str],
    label: str,
) -> Path:
    path = Path(str(raw or ""))
    if not path.is_absolute():
        raise ContainmentUnavailable(f"Podman reported no absolute {label} path")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise ContainmentUnavailable(f"Podman {label} is unavailable: {exc}") from exc
    if (
        resolved.name not in allowed_names
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise ContainmentUnavailable(
            f"Podman {label} must be a packaged, root-owned, non-writable executable"
        )
    return resolved


def _has_subordinate_range(lines: Sequence[str], identities: set[str]) -> bool:
    for raw in lines:
        line = raw.partition("#")[0].strip()
        parts = line.split(":")
        if len(parts) != 3 or parts[0] not in identities:
            continue
        try:
            start, count = int(parts[1]), int(parts[2])
        except ValueError:
            continue
        if start > 0 and count >= 65_536:
            return True
    return False


def _verify_rootless_user_namespace(uid: int) -> None:
    """Verify the Debian/RHEL prerequisites for ``--userns=keep-id``.

    A successful ``podman info`` is useful but not enough: an installation can
    report rootless while a later create fails because the shadow-utils helpers
    or this user's subordinate-ID ranges are missing.  Those failures are
    classified here, before any candidate container is created.
    """
    try:
        import pwd

        username = pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError) as exc:
        raise ContainmentUnavailable(
            "rootless Podman user could not be resolved in the local account database"
        ) from exc

    for helper_name in ("newuidmap", "newgidmap"):
        helper = Path("/usr/bin") / helper_name
        try:
            resolved = helper.resolve(strict=True)
            metadata = resolved.stat()
        except OSError as exc:
            raise ContainmentUnavailable(
                f"rootless Podman requires {helper_name} from shadow-utils/uidmap"
            ) from exc
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & 0o022
            or not os.access(resolved, os.X_OK)
        ):
            raise ContainmentUnavailable(
                f"{helper_name} must be a root-owned, non-writable executable"
            )

    identities = {username, str(uid)}
    for database in (Path("/etc/subuid"), Path("/etc/subgid")):
        try:
            resolved = database.resolve(strict=True)
            metadata = resolved.stat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or metadata.st_mode & 0o022
            ):
                raise ContainmentUnavailable(
                    f"{database} must be a root-owned, non-writable regular file"
                )
            lines = resolved.read_text(encoding="utf-8", errors="strict").splitlines()
        except ContainmentUnavailable:
            raise
        except (OSError, UnicodeError) as exc:
            raise ContainmentUnavailable(
                f"rootless Podman could not verify {database}: {exc}"
            ) from exc

        if not _has_subordinate_range(lines, identities):
            raise ContainmentUnavailable(
                f"{database} has no >=65536 subordinate-ID range for {username}"
            )


def _read_trusted_config(
    path: Path,
    *,
    allowed_owners: set[int],
    label: str,
) -> tuple[Path, bytes]:
    """Read a security configuration file after conservative ownership checks."""
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid not in allowed_owners
            or metadata.st_mode & 0o022
            or metadata.st_nlink != 1
        ):
            raise ContainmentUnavailable(
                f"{label} must be a singly-linked, owner-trusted, non-writable regular file"
            )
        payload = resolved.read_bytes()
        after = resolved.stat()
    except ContainmentUnavailable:
        raise
    except OSError as exc:
        raise ContainmentUnavailable(f"could not verify {label} {path}: {exc}") from exc
    if (metadata.st_dev, metadata.st_ino, metadata.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    ):
        raise ContainmentUnavailable(f"{label} changed while it was being verified")
    return resolved, payload


def _trusted_seccomp_profile(uid: int) -> tuple[Path, str]:
    """Require the packaged Debian/RHEL deny-by-default seccomp policy."""
    resolved, payload = _read_trusted_config(
        Path(DEFAULT_SECCOMP_PROFILE),
        allowed_owners={0},
        label="Podman seccomp profile",
    )
    if not 256 <= len(payload) <= 4 * 1024 * 1024:
        raise ContainmentUnavailable("Podman seccomp profile has an implausible size")
    try:
        profile = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContainmentUnavailable("Podman seccomp profile is not valid JSON") from exc
    profile = _mapping(profile, "seccomp profile")
    default_action = str(_ci_get(profile, "defaultAction", "")).upper()
    if default_action not in {
        "SCMP_ACT_ERRNO",
        "SCMP_ACT_KILL",
        "SCMP_ACT_KILL_PROCESS",
        "SCMP_ACT_KILL_THREAD",
        "SCMP_ACT_TRAP",
    }:
        raise ContainmentUnavailable(
            "Podman seccomp profile is not deny-by-default "
            f"(defaultAction={default_action or 'missing'})"
        )
    return resolved, hashlib.sha256(payload).hexdigest()


def _meaningful_mount_lines(payload: bytes, label: str) -> tuple[str, ...]:
    try:
        text = payload.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ContainmentUnavailable(f"{label} is not UTF-8") from exc
    return tuple(
        line
        for raw in text.splitlines()
        if (line := raw.partition("#")[0].strip())
    )


def _verify_automatic_mounts_disabled(runtime_env: Mapping[str, str], uid: int) -> None:
    """Reject Podman's implicit mounts, including RHEL subscription secrets.

    Rootless Podman gives ``$HOME/.config/containers/mounts.conf`` precedence
    over the administrator and vendor files.  An empty trusted rootless file is
    therefore an explicit opt-out.  If it is absent, the effective system file
    must itself be empty or absent.
    """
    home_raw = runtime_env.get("HOME", "")
    home = Path(home_raw)
    if not home_raw or not home.is_absolute():
        raise ContainmentUnavailable(
            "rootless Podman requires an absolute HOME to verify automatic mounts"
        )
    user_file = home / ".config" / "containers" / "mounts.conf"
    candidates: tuple[tuple[Path, set[int]], ...]
    if os.path.lexists(user_file):
        candidates = ((user_file, {0, uid}),)
    elif os.path.lexists(Path("/etc/containers/mounts.conf")):
        candidates = ((Path("/etc/containers/mounts.conf"), {0}),)
    elif os.path.lexists(Path("/usr/share/containers/mounts.conf")):
        candidates = ((Path("/usr/share/containers/mounts.conf"), {0}),)
    else:
        candidates = ()

    for path, owners in candidates:
        _, payload = _read_trusted_config(
            path,
            allowed_owners=owners,
            label="effective containers mounts.conf",
        )
        entries = _meaningful_mount_lines(payload, "effective containers mounts.conf")
        if entries:
            raise ContainmentUnavailable(
                "Podman automatic host mounts are enabled by "
                f"{path}; create an empty, mode-0600 rootless override at {user_file}"
            )


def _configured_image() -> tuple[str, str]:
    reference = os.environ.get(LINUX_OCI_IMAGE_ENV, "").strip()
    match = _IMAGE_RE.fullmatch(reference)
    registry = "" if match is None else match.group("name").partition("/")[0]
    qualified = (
        match is not None
        and "/" in match.group("name")
        and (registry == "localhost" or "." in registry or ":" in registry)
    )
    if (
        match is None
        or not qualified
        or "://" in reference
        or reference.startswith("-")
    ):
        raise ContainmentUnavailable(
            f"{LINUX_OCI_IMAGE_ENV} must be a fully qualified local image "
            "reference pinned as name@sha256:<64 lowercase hex>; images are never pulled"
        )
    return reference, f"sha256:{match.group('digest')}"


def _preflight() -> _Preflight:
    if not _is_native_linux():
        raise ContainmentUnavailable(
            "rootless OCI candidate containment is available only on native Linux"
        )
    uid, gid = _effective_ids()
    if uid == 0:
        raise ContainmentUnavailable("candidate containment refuses rootful Podman")
    _verify_rootless_user_namespace(uid)

    runtime = _trusted_runtime_path()
    runtime_env = _runtime_env()
    _verify_automatic_mounts_disabled(runtime_env, uid)
    seccomp_profile, seccomp_profile_sha256 = _trusted_seccomp_profile(uid)
    image_reference, reference_digest = _configured_image()

    info_proc = _checked_control(
        _podman_argv(runtime, "info", "--format", "json"),
        env=runtime_env,
        operation="info preflight",
    )
    info = _mapping(_json_payload(info_proc, "info preflight"), "info")
    host = _mapping(_ci_get(info, "host"), "info.host")
    security = _mapping(_ci_get(host, "security"), "info.host.security")
    if _ci_get(host, "serviceIsRemote") is not False:
        raise ContainmentUnavailable(
            "Podman info did not prove that the candidate runtime is local"
        )
    if _ci_get(security, "rootless") is not True:
        raise ContainmentUnavailable("Podman info did not attest rootless=true")
    cgroup_version = str(_ci_get(host, "cgroupVersion", "")).lower()
    if cgroup_version not in {"v2", "2"}:
        raise ContainmentUnavailable(
            "rootless Podman requires cgroup v2 so PID and memory limits are enforceable"
        )
    controllers_raw = _ci_get(host, "cgroupControllers", ()) or ()
    controllers = {
        str(value).lower()
        for value in controllers_raw
        if isinstance(value, str)
    }
    missing_controllers = {"cpu", "memory", "pids"} - controllers
    if missing_controllers:
        raise ContainmentUnavailable(
            "rootless Podman lacks delegated cgroup v2 controllers: "
            + ", ".join(sorted(missing_controllers))
        )
    if _ci_get(security, "seccompEnabled") is not True:
        raise ContainmentUnavailable(
            "rootless Podman did not attest that seccomp enforcement is enabled"
        )
    oci_runtime = _mapping(_ci_get(host, "ociRuntime"), "info.host.ociRuntime")
    oci_runtime_path = _trusted_reported_executable(
        _ci_get(oci_runtime, "path"),
        allowed_names={"crun", "runc"},
        label="OCI runtime",
    )
    conmon = _mapping(_ci_get(host, "conmon"), "info.host.conmon")
    monitor_path = _trusted_reported_executable(
        _ci_get(conmon, "path"),
        allowed_names={"conmon"},
        label="process monitor",
    )
    limit_helper_path = _trusted_reported_executable(
        DEFAULT_PRLIMIT_PATH,
        allowed_names={"prlimit"},
        label="output-limit helper",
    )

    version_block = _mapping(_ci_get(info, "version"), "info.version")
    version = str(_ci_get(version_block, "version", ""))
    if _parse_version(version) < MIN_PODMAN_VERSION:
        minimum = ".".join(str(part) for part in MIN_PODMAN_VERSION)
        raise ContainmentUnavailable(
            f"Podman {version or 'unknown'} is older than required {minimum}"
        )

    image_proc = _checked_control(
        _podman_argv(
            runtime,
            "image",
            "inspect",
            "--format",
            "json",
            image_reference,
            oci_runtime=oci_runtime_path,
            process_monitor=monitor_path,
        ),
        env=runtime_env,
        operation="local image inspection",
    )
    image = _one_inspect(
        _json_payload(image_proc, "local image inspection"), "image inspection"
    )
    local_image_id = str(_ci_get(image, "Id", "")).removeprefix("sha256:")
    if _CONTAINER_ID_RE.fullmatch(local_image_id) is None:
        raise ContainmentUnavailable("Podman image inspection returned no immutable image ID")
    local_image_digest = str(_ci_get(image, "Digest", "")).lower()
    repo_digests = {
        str(item).lower()
        for item in (_ci_get(image, "RepoDigests", ()) or ())
        if isinstance(item, str)
    }
    reference_seen = (
        local_image_digest == reference_digest
        or image_reference.lower() in repo_digests
        or any(item.endswith("@" + reference_digest) for item in repo_digests)
    )
    if not reference_seen:
        raise ContainmentUnavailable(
            "the locally inspected image does not attest the configured reference digest"
        )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", local_image_digest):
        # A multi-architecture reference can resolve to a platform manifest;
        # Podman still has to report that resolved immutable digest.
        raise ContainmentUnavailable("Podman image inspection returned no resolved image digest")

    return _Preflight(
        runtime=runtime,
        runtime_env=runtime_env,
        runtime_version=version,
        image_reference=image_reference,
        image_reference_digest=reference_digest,
        local_image_id=local_image_id,
        local_image_digest=local_image_digest,
        uid=uid,
        gid=gid,
        cgroup_version="v2",
        seccomp_profile=seccomp_profile,
        seccomp_profile_sha256=seccomp_profile_sha256,
        automatic_host_mounts_disabled=True,
        oci_runtime_path=oci_runtime_path,
        process_monitor_path=monitor_path,
        limit_helper_path=limit_helper_path,
    )


def _workspace_preflight(cwd: str | Path, uid: int) -> Path:
    literal = Path(cwd)
    if not literal.is_absolute():
        raise ContainmentUnavailable("candidate workspace must be absolute")
    try:
        root_lstat = literal.lstat()
        workspace = literal.resolve(strict=True)
        root_stat = workspace.stat()
    except OSError as exc:
        raise ContainmentUnavailable(f"candidate workspace is unavailable: {exc}") from exc
    if stat.S_ISLNK(root_lstat.st_mode) or literal.absolute() != workspace:
        raise ContainmentUnavailable("candidate workspace itself must not be a symlink")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ContainmentUnavailable("candidate workspace must be a directory")
    if "," in str(workspace) or "\n" in str(workspace) or "\r" in str(workspace):
        raise ContainmentUnavailable(
            "candidate workspace path contains a character unsafe for OCI mount syntax"
        )
    if root_stat.st_uid != uid:
        raise ContainmentUnavailable("candidate workspace must be owned by the rootless Podman user")
    if not os.access(workspace, os.R_OK | os.W_OK | os.X_OK):
        raise ContainmentUnavailable("candidate workspace is not read/write/search accessible")

    root_device = root_stat.st_dev
    pending = [workspace]
    visited = 0
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    visited += 1
                    if visited > WORKSPACE_ENTRY_LIMIT:
                        raise ContainmentUnavailable(
                            f"candidate workspace exceeds {WORKSPACE_ENTRY_LIMIT} preflight entries"
                        )
                    metadata = entry.stat(follow_symlinks=False)
                    mode = metadata.st_mode
                    if stat.S_ISLNK(mode):
                        raise ContainmentUnavailable(
                            f"candidate workspace contains a symlink: {entry.path}"
                        )
                    if metadata.st_dev != root_device:
                        raise ContainmentUnavailable(
                            f"candidate workspace contains a nested mount: {entry.path}"
                        )
                    if stat.S_ISDIR(mode):
                        pending.append(Path(entry.path))
                    elif stat.S_ISREG(mode):
                        if metadata.st_nlink != 1:
                            raise ContainmentUnavailable(
                                f"candidate workspace contains a multiply-linked file: {entry.path}"
                            )
                    else:
                        raise ContainmentUnavailable(
                            f"candidate workspace contains a special file: {entry.path}"
                        )
        except ContainmentUnavailable:
            raise
        except OSError as exc:
            raise ContainmentUnavailable(
                f"candidate workspace could not be scanned without following links: {exc}"
            ) from exc
    return workspace


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _workspace_exposes_inode(workspace: Path, device: int, inode: int) -> bool:
    """Catch bind-mount aliases that a lexical outside-workspace check misses."""
    pending = [workspace]
    visited = 0
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    visited += 1
                    if visited > WORKSPACE_ENTRY_LIMIT:
                        raise ContainmentUnavailable(
                            "candidate workspace changed beyond the preflight entry limit"
                        )
                    metadata = entry.stat(follow_symlinks=False)
                    if (metadata.st_dev, metadata.st_ino) == (device, inode):
                        return True
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append(Path(entry.path))
        except ContainmentUnavailable:
            raise
        except OSError as exc:
            raise ContainmentUnavailable(
                f"candidate workspace changed while output isolation was verified: {exc}"
            ) from exc
    return False


def _verified_output(output: BinaryIO, workspace: Path, uid: int) -> Path:
    """Verify that the parent-owned capture file is not candidate-writable."""
    if not hasattr(output, "fileno"):
        raise ContainmentUnavailable("candidate output requires a real parent-owned file")
    try:
        fd = int(output.fileno())
        metadata = os.fstat(fd)
    except (OSError, TypeError, ValueError) as exc:
        raise ContainmentUnavailable("candidate output file is not open") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ContainmentUnavailable("candidate output must be a regular file")
    try:
        if not output.writable():
            raise ContainmentUnavailable("candidate output file must be writable")
        logical_position = int(output.tell())
    except ContainmentUnavailable:
        raise
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise ContainmentUnavailable(
            "candidate output file state cannot be verified"
        ) from exc
    if metadata.st_uid != uid:
        raise ContainmentUnavailable(
            "candidate output must be owned by the rootless Podman user"
        )
    if metadata.st_nlink != 1:
        raise ContainmentUnavailable("candidate output must have exactly one hard link")
    if metadata.st_size != 0:
        raise ContainmentUnavailable("candidate output must start as an empty file")
    try:
        position = os.lseek(fd, 0, os.SEEK_CUR)
    except OSError as exc:
        raise ContainmentUnavailable(
            "candidate output position cannot be verified"
        ) from exc
    if position != 0 or logical_position != 0:
        raise ContainmentUnavailable("candidate output must start at offset zero")

    proc_fd = Path(f"/proc/self/fd/{fd}")
    try:
        if os.path.lexists(proc_fd):
            output_path = proc_fd.resolve(strict=True)
        else:
            name = getattr(output, "name", None)
            if not isinstance(name, (str, os.PathLike)):
                raise ContainmentUnavailable(
                    "candidate output path cannot be verified on this platform"
                )
            output_path = Path(name).resolve(strict=True)
        path_metadata = output_path.stat()
    except ContainmentUnavailable:
        raise
    except OSError as exc:
        raise ContainmentUnavailable(
            f"candidate output path cannot be verified: {exc}"
        ) from exc
    if (metadata.st_dev, metadata.st_ino) != (path_metadata.st_dev, path_metadata.st_ino):
        raise ContainmentUnavailable("candidate output path does not identify its open file")
    if _path_is_within(output_path, workspace) or _workspace_exposes_inode(
        workspace, metadata.st_dev, metadata.st_ino
    ):
        raise ContainmentUnavailable(
            "candidate output must be outside the writable candidate workspace"
        )
    return output_path


def _prepare_empty_hooks_dir(output_path: Path, uid: int) -> Path:
    """Create an empty, private hooks directory beside the parent capture file."""
    try:
        raw = tempfile.mkdtemp(prefix=".daedalus-oci-hooks-", dir=output_path.parent)
        hooks_dir = Path(raw).resolve(strict=True)
        hooks_dir.chmod(0o700)
        metadata = hooks_dir.stat()
    except OSError as exc:
        raise ContainmentUnavailable(
            f"could not create a private empty OCI hooks directory: {exc}"
        ) from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (_is_native_linux() and metadata.st_uid != uid)
        or (_is_native_linux() and metadata.st_mode & 0o077)
        or any(hooks_dir.iterdir())
    ):
        try:
            hooks_dir.rmdir()
        except OSError:
            pass
        raise ContainmentUnavailable("private OCI hooks directory did not verify empty")
    return hooks_dir


def _verify_empty_hooks_dir(hooks_dir: Path, uid: int) -> None:
    try:
        metadata = hooks_dir.stat()
        entries = tuple(hooks_dir.iterdir())
    except OSError as exc:
        raise ContainmentUnavailable(f"private OCI hooks directory changed: {exc}") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (_is_native_linux() and metadata.st_uid != uid)
        or (_is_native_linux() and metadata.st_mode & 0o077)
        or entries
    ):
        raise ContainmentUnavailable("private OCI hooks directory changed before start")


def _container_command(argv: Sequence[str], workspace: Path) -> tuple[str, ...]:
    if not argv or any(not isinstance(part, str) or not part for part in argv):
        raise ContainmentUnavailable("candidate command must be a non-empty argv vector")
    mapped: list[str] = []
    host_python = Path(sys.executable).resolve()
    for index, part in enumerate(argv):
        candidate = Path(part)
        if index == 0 and candidate.is_absolute() and candidate.resolve() == host_python:
            # Toolchain images expose their Python interpreter through PATH;
            # a host interpreter path is never mounted into the container.
            mapped.append("python3")
            continue
        if candidate.is_absolute():
            try:
                relative = candidate.resolve().relative_to(workspace)
            except (OSError, ValueError) as exc:
                raise ContainmentUnavailable(
                    f"absolute host path cannot cross the OCI boundary: argv[{index}]"
                ) from exc
            mapped.append(str(Path(OCI_WORKSPACE) / relative).replace("\\", "/"))
        else:
            mapped.append(part)
    return tuple(mapped)


def _runtime_timeout_seconds(timeout_s: float | None) -> int:
    """Set a conmon-enforced lifetime even if an in-process poller disappears."""
    try:
        value = DEFAULT_OCI_RUNTIME_TIMEOUT_S if timeout_s is None else float(timeout_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ContainmentUnavailable(
            "candidate runtime timeout must be finite and non-negative"
        ) from exc
    if not math.isfinite(value) or value < 0:
        raise ContainmentUnavailable("candidate runtime timeout must be finite and non-negative")
    # Podman's zero means unlimited, which is the opposite of a zero gate
    # budget.  One second is the narrowest portable conmon deadline.
    return max(1, int(math.ceil(value)))


def _create_argv(
    preflight: _Preflight,
    workspace: Path,
    command: tuple[str, ...],
    name: str,
    hooks_dir: Path,
    runtime_timeout_s: int,
) -> tuple[str, ...]:
    mount = (
        f"type=bind,src={workspace},dst={OCI_WORKSPACE},rw,"
        "bind-nonrecursive,bind-propagation=rprivate,relabel=private"
    )
    tmpfs = (
        f"{OCI_TMP}:rw,noexec,nosuid,nodev,size={OCI_TMPFS_LIMIT_BYTES},mode=1777"
    )
    argv: list[str] = list(
        _podman_argv(
            preflight.runtime,
            "create",
            oci_runtime=preflight.oci_runtime_path,
            process_monitor=preflight.process_monitor_path,
            hooks_dir=hooks_dir,
        )
    )
    argv.extend([
        f"--name={name}",
        "--pull=never",
        "--read-only=true",
        "--read-only-tmpfs=false",
        "--image-volume=ignore",
        "--network=none",
        "--pid=private",
        "--ipc=private",
        "--uts=private",
        "--cgroupns=private",
        f"--userns=keep-id:uid={preflight.uid},gid={preflight.gid}",
        f"--user={preflight.uid}:{preflight.gid}",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--security-opt=seccomp={preflight.seccomp_profile}",
        f"--pids-limit={OCI_PIDS_LIMIT}",
        f"--memory={OCI_MEMORY_LIMIT_BYTES}",
        f"--memory-swap={OCI_MEMORY_LIMIT_BYTES}",
        f"--cpus={OCI_CPU_LIMIT}",
        "--ulimit=nofile=4096:4096",
        "--ulimit=core=0:0",
        "--restart=no",
        "--rm",
        f"--timeout={runtime_timeout_s}",
        "--no-healthcheck",
        "--systemd=false",
        "--init=false",
        "--sdnotify=ignore",
        "--log-driver=none",
        "--http-proxy=false",
        "--unsetenv-all",
        "--entrypoint=[]",
        "--workdir=/workspace",
        "--hostname=daedalus-candidate",
        f"--mount={mount}",
        f"--tmpfs={tmpfs}",
    ])
    for key, value in sorted(_CANDIDATE_ENV.items()):
        argv.append(f"--env={key}={value}")
    argv.extend((preflight.image_reference, *command))
    return tuple(argv)


def _env_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        raise ContainmentUnavailable("Podman container environment is not a list")
    result: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, str) or "=" not in item:
            raise ContainmentUnavailable("Podman container environment has an invalid entry")
        key, value = item.split("=", 1)
        if not key or key in result:
            raise ContainmentUnavailable("Podman container environment has duplicate names")
        result[key] = value
    return result


def _normal_private(value: Any, label: str) -> str:
    mode = str(value or "").lower()
    if mode not in {"", "private"}:
        raise ContainmentUnavailable(f"Podman resolved a shared {label} namespace: {mode!r}")
    return "private"


def _verified_private_ipc(
    value: Any,
    *,
    runtime_version: str,
    create_command: Any,
) -> tuple[str, str]:
    """Verify non-shareable IPC across Podman's 4.3 inspect defect.

    Podman 4.3 records ``NoShmShare`` for ``--ipc=private`` but its inspect
    renderer nevertheless reports ``IpcMode=shareable``.  Podman 4.4 fixed
    that renderer.  On the affected minor release only, admit the value when
    Libpod's own stored create argv contains our exact explicit option.  This
    does not admit the 4.3 default: that command record lacks the marker.
    """
    mode = str(value or "").lower()
    if mode == "private":
        return "private", "container-inspect"
    version = _parse_version(runtime_version)
    if mode == "shareable" and (4, 3, 0) <= version < (4, 4, 0):
        if (
            isinstance(create_command, list)
            and all(isinstance(part, str) for part in create_command)
            and "--ipc=private" in create_command
        ):
            return "private", "podman-4.3-create-command"
    raise ContainmentUnavailable(
        f"Podman resolved a shared IPC namespace: {mode!r}"
    )


def _option_tokens(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, (list, tuple)):
        raw_values = []
        for item in value:
            raw_values.extend(str(item).split(","))
    else:
        raw_values = []
    return tuple(part.strip() for part in raw_values if part.strip())


def _size_bytes(raw: str) -> int:
    match = re.fullmatch(r"(?i)(\d+)([kmgt]?)(?:i?b)?", raw.strip())
    if match is None:
        raise ContainmentUnavailable(f"Podman reported an invalid tmpfs size {raw!r}")
    value = int(match.group(1))
    multiplier = {
        "": 1,
        "k": 1024,
        "m": 1024**2,
        "g": 1024**3,
        "t": 1024**4,
    }[match.group(2).lower()]
    return value * multiplier


def _tmpfs_policy(value: Any) -> tuple[int, str]:
    tokens = _option_tokens(value)
    lowered = {token.lower() for token in tokens}
    for required in ("rw", "noexec", "nosuid", "nodev"):
        if required not in lowered:
            raise ContainmentUnavailable(f"Podman /tmp is missing {required}")
    keyed: dict[str, str] = {}
    for token in tokens:
        if "=" in token:
            key, setting = token.split("=", 1)
            if key.lower() in keyed:
                raise ContainmentUnavailable(
                    f"Podman /tmp repeats the {key.lower()} option"
                )
            keyed[key.lower()] = setting
    if "size" not in keyed or _size_bytes(keyed["size"]) != OCI_TMPFS_LIMIT_BYTES:
        raise ContainmentUnavailable("Podman /tmp did not resolve the 512 MiB ceiling")
    mode = keyed.get("mode", "")
    try:
        numeric_mode = int(mode, 8)
    except ValueError as exc:
        raise ContainmentUnavailable("Podman /tmp did not resolve mode 1777") from exc
    if numeric_mode != 0o1777:
        raise ContainmentUnavailable("Podman /tmp did not resolve mode 1777")
    return OCI_TMPFS_LIMIT_BYTES, "1777"


def _id_map_strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContainmentUnavailable(f"Podman did not expose the {label} user mapping")
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and re.fullmatch(r"\d+:\d+:\d+", item):
            result.append(item)
            continue
        if isinstance(item, Mapping):
            container_id = _ci_get(item, "ContainerID", _ci_get(item, "container_id"))
            host_id = _ci_get(item, "HostID", _ci_get(item, "host_id"))
            size = _ci_get(item, "Size", _ci_get(item, "size"))
            try:
                result.append(f"{int(container_id)}:{int(host_id)}:{int(size)}")
            except (TypeError, ValueError) as exc:
                raise ContainmentUnavailable(
                    f"Podman exposed an invalid {label} user mapping"
                ) from exc
            continue
        raise ContainmentUnavailable(f"Podman exposed an invalid {label} user mapping")
    return tuple(result)


def _verify_keep_id(host: Mapping[str, Any], uid: int, gid: int) -> str:
    mappings = _mapping(_ci_get(host, "IDMappings"), "HostConfig.IDMappings")
    uid_map = _id_map_strings(
        _ci_get(mappings, "UidMap", _ci_get(mappings, "UIDMap")), "UID"
    )
    gid_map = _id_map_strings(
        _ci_get(mappings, "GidMap", _ci_get(mappings, "GIDMap")), "GID"
    )
    # Inspect reports IDs relative to Podman's outer rootless namespace.  Host
    # ID 0 there is the invoking host user; keep-id must map it to the exact
    # numerical identity used by the candidate process.
    if f"{uid}:0:1" not in uid_map or f"{gid}:0:1" not in gid_map:
        raise ContainmentUnavailable("Podman did not resolve the requested keep-id mapping")
    return "keep-id"


def _active_lsm_profiles(item: Mapping[str, Any]) -> tuple[str, ...]:
    profiles: list[str] = []
    for label, field in (
        ("apparmor", "AppArmorProfile"),
        ("selinux-process", "ProcessLabel"),
        ("selinux-mount", "MountLabel"),
    ):
        value = str(_ci_get(item, field, "") or "").strip()
        if value and value.lower() not in {"unconfined", "disable", "disabled"}:
            profiles.append(f"{label}:{value}")
    return tuple(profiles)


def _verify_container(
    raw: Any,
    *,
    preflight: _Preflight,
    container_id: str,
    container_name: str,
    workspace: Path,
    command: tuple[str, ...],
    hooks_dir: Path,
    runtime_timeout_s: int = int(DEFAULT_OCI_RUNTIME_TIMEOUT_S),
) -> OciContainmentFacts:
    item = _one_inspect(raw, "container inspection")
    if str(_ci_get(item, "Id", "")) != container_id:
        raise ContainmentUnavailable("Podman inspected a different container than it created")
    if str(_ci_get(item, "Name", "")).lstrip("/") != container_name:
        raise ContainmentUnavailable("Podman container name changed before verification")
    state = _mapping(_ci_get(item, "State"), "container.State")
    if _ci_get(state, "Running") is not False:
        raise ContainmentUnavailable("candidate container was already running before verification")
    if not _empty(_ci_get(item, "Pod", ""), strings=True) or not _empty(
        _ci_get(item, "Dependencies", [])
    ):
        raise ContainmentUnavailable("candidate container unexpectedly joins a pod or dependency")

    actual_oci_runtime = str(_ci_get(item, "OCIRuntime", "") or "").strip()
    if not actual_oci_runtime or Path(actual_oci_runtime).name != preflight.oci_runtime_path.name:
        raise ContainmentUnavailable(
            "Podman selected a different OCI runtime than the pinned packaged runtime"
        )

    image_id = str(_ci_get(item, "Image", "")).removeprefix("sha256:")
    image_digest = str(_ci_get(item, "ImageDigest", "")).lower()
    admitted_digests = {
        preflight.local_image_digest,
        preflight.image_reference_digest,
    }
    if (
        image_id != preflight.local_image_id
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) is None
        or image_digest not in admitted_digests
    ):
        raise ContainmentUnavailable("candidate container does not bind the inspected local image")

    config = _mapping(_ci_get(item, "Config"), "container.Config")
    host = _mapping(_ci_get(item, "HostConfig"), "container.HostConfig")
    if _ci_get(host, "ReadonlyRootfs") is not True:
        raise ContainmentUnavailable("Podman did not resolve a read-only image root filesystem")
    if str(_ci_get(host, "NetworkMode", "")).lower() != "none":
        raise ContainmentUnavailable("Podman did not resolve network=none")
    if _ci_get(host, "Privileged") is not False:
        raise ContainmentUnavailable("Podman resolved a privileged candidate container")
    if _ci_get(host, "PublishAllPorts") not in {False, None}:
        raise ContainmentUnavailable("Podman resolved published candidate ports")
    if not _empty(_ci_get(host, "PortBindings")):
        raise ContainmentUnavailable("Podman resolved explicit candidate port bindings")
    for field in ("Devices", "GroupAdd", "VolumesFrom"):
        if not _empty(_ci_get(host, field)):
            raise ContainmentUnavailable(f"Podman resolved forbidden {field}")

    # Podman 4.9 serializes empty Go capability slices as null. Missing
    # inspection fields are unknown; they must not share that interpretation.
    missing = object()
    for field in ("EffectiveCaps", "BoundingCaps"):
        capabilities = _ci_get(item, field, missing)
        if capabilities is None or (type(capabilities) is list and not capabilities):
            continue
        raise ContainmentUnavailable(
            "Podman did not drop every effective and bounding Linux capability"
        )
    security_raw = _ci_get(host, "SecurityOpt", ()) or ()
    if not isinstance(security_raw, list):
        raise ContainmentUnavailable("Podman security options are not inspectable")
    security_values = tuple(str(value) for value in security_raw)
    security_opts = {
        value.lower().replace("=true", "") for value in security_values
    }
    if "no-new-privileges" not in security_opts:
        raise ContainmentUnavailable("Podman did not resolve no-new-privileges")
    if any(
        value in {"seccomp=unconfined", "apparmor=unconfined", "label=disable"}
        for value in security_opts
    ):
        raise ContainmentUnavailable("Podman resolved an explicitly unconfined security option")
    expected_seccomp = f"seccomp={preflight.seccomp_profile}"
    seccomp_values = tuple(
        value for value in security_values if value.lower().startswith("seccomp=")
    )
    if seccomp_values != (expected_seccomp,):
        raise ContainmentUnavailable(
            "Podman did not resolve the verified packaged seccomp profile"
        )

    mounts = _ci_get(item, "Mounts")
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise ContainmentUnavailable("candidate must have exactly one user-specified host mount")
    mount = _mapping(mounts[0], "container.Mounts[0]")
    source = Path(str(_ci_get(mount, "Source", ""))).resolve()
    destination = str(_ci_get(mount, "Destination", ""))
    mount_rw = _ci_get(mount, "RW") is True
    mount_mode = _option_tokens(_ci_get(mount, "Mode", ""))
    mount_options = {value.lower() for value in _option_tokens(_ci_get(mount, "Options"))}
    propagation = str(_ci_get(mount, "Propagation", "")).lower()
    private_relabel = "Z" in mount_mode and "z" not in mount_mode
    bind_nonrecursive = "bind" in mount_options and "rbind" not in mount_options
    if (
        str(_ci_get(mount, "Type", "")).lower() != "bind"
        or source != workspace
        or destination != OCI_WORKSPACE
        or not mount_rw
    ):
        raise ContainmentUnavailable("Podman workspace bind differs from the admitted workspace")
    binds = _ci_get(host, "Binds")
    if not isinstance(binds, list) or len(binds) != 1:
        raise ContainmentUnavailable("Podman resolved an additional host bind or volume")
    bind_prefix = f"{workspace}:{OCI_WORKSPACE}:"
    bind_text = str(binds[0])
    bind_options = _option_tokens(bind_text.removeprefix(bind_prefix))
    bind_options_lower = {value.lower() for value in bind_options}
    if (
        not private_relabel
        or propagation != "rprivate"
        or not bind_nonrecursive
        or not bind_text.startswith(bind_prefix)
        or "Z" not in bind_options
        or "z" in bind_options
        or "rprivate" not in bind_options_lower
        or "bind" not in bind_options_lower
        or "rbind" in bind_options_lower
    ):
        raise ContainmentUnavailable(
            "Podman workspace bind lost private relabel, nonrecursive bind, or rprivate propagation"
        )
    if not _empty(_ci_get(config, "Volumes")):
        raise ContainmentUnavailable("the configured image creates an additional writable volume")

    if _ci_get(host, "AutoRemove") is not True:
        raise ContainmentUnavailable("Podman did not resolve automatic container removal")
    restart_policy = _mapping(
        _ci_get(host, "RestartPolicy"), "HostConfig.RestartPolicy"
    )
    if str(_ci_get(restart_policy, "Name", "")).lower() not in {"", "no"}:
        raise ContainmentUnavailable("Podman resolved a restarting candidate container")
    log_config = _mapping(_ci_get(host, "LogConfig"), "HostConfig.LogConfig")
    log_driver = str(_ci_get(log_config, "Type", "")).lower()
    if log_driver != "none":
        raise ContainmentUnavailable("Podman did not disable its unbounded container log")

    tmpfs = _ci_get(host, "Tmpfs")
    if not isinstance(tmpfs, Mapping) or set(tmpfs) != {OCI_TMP}:
        raise ContainmentUnavailable("Podman must resolve exactly the bounded /tmp tmpfs")
    tmpfs_size, tmpfs_mode = _tmpfs_policy(tmpfs[OCI_TMP])

    pids_limit = int(_ci_get(host, "PidsLimit", 0) or 0)
    memory_limit = int(_ci_get(host, "Memory", 0) or 0)
    memory_swap = int(_ci_get(host, "MemorySwap", 0) or 0)
    nano_cpus = int(_ci_get(host, "NanoCpus", 0) or 0)
    if pids_limit != OCI_PIDS_LIMIT:
        raise ContainmentUnavailable("Podman did not resolve the requested PID ceiling")
    if memory_limit != OCI_MEMORY_LIMIT_BYTES or memory_swap != OCI_MEMORY_LIMIT_BYTES:
        raise ContainmentUnavailable("Podman did not resolve the requested memory/swap ceiling")
    if nano_cpus != int(OCI_CPU_LIMIT * 1_000_000_000):
        raise ContainmentUnavailable("Podman did not resolve the requested CPU ceiling")

    configured_timeout = int(_ci_get(config, "Timeout", 0) or 0)
    if configured_timeout != runtime_timeout_s:
        raise ContainmentUnavailable("Podman did not resolve the conmon runtime deadline")
    if _ci_get(config, "SystemdMode", False) is not False:
        raise ContainmentUnavailable("Podman unexpectedly enabled systemd container mode")
    if _ci_get(host, "Init", False) is not False:
        raise ContainmentUnavailable("Podman unexpectedly injected a container init process")
    sdnotify_mode = str(_ci_get(config, "sdNotifyMode", "") or "").lower()
    if sdnotify_mode != "ignore":
        raise ContainmentUnavailable("Podman did not suppress the host sd-notify socket")

    user = str(_ci_get(config, "User", ""))
    if user != f"{preflight.uid}:{preflight.gid}":
        raise ContainmentUnavailable("Podman did not resolve the rootless user identity")
    if str(_ci_get(config, "WorkingDir", "")) != OCI_WORKSPACE:
        raise ContainmentUnavailable("Podman did not resolve /workspace as the working directory")
    entrypoint = _ci_get(config, "Entrypoint")
    if not _empty(entrypoint, strings=True):
        raise ContainmentUnavailable("the image entrypoint was not cleared")
    if tuple(_ci_get(config, "Cmd", ()) or ()) != command:
        raise ContainmentUnavailable("Podman resolved a different candidate command")
    if not _empty(_ci_get(config, "Secrets")):
        raise ContainmentUnavailable("Podman resolved a secret into the candidate container")
    user_namespace = _verify_keep_id(host, preflight.uid, preflight.gid)

    candidate_env = _env_map(_ci_get(config, "Env"))
    for key, expected in _CANDIDATE_ENV.items():
        if candidate_env.get(key) != expected:
            raise ContainmentUnavailable(f"Podman did not resolve the fixed {key} environment")
    unexpected = set(candidate_env) - set(_CANDIDATE_ENV) - _PODMAN_ADDED_ENV
    if unexpected:
        raise ContainmentUnavailable(
            "Podman injected unexpected candidate environment names: "
            + ", ".join(sorted(unexpected))
        )

    networks = _ci_get(
        _mapping(_ci_get(item, "NetworkSettings"), "NetworkSettings"), "Networks", missing
    )
    if not isinstance(networks, Mapping):
        raise ContainmentUnavailable("Podman network inspection is missing or malformed")
    if networks:
        # Before start, Podman 4.9 represents network=none with this exact
        # zero-valued marker. NetworkMode=none was independently required above.
        marker = networks.get("none", missing)
        expected_marker = {
            "EndpointID": "",
            "Gateway": "",
            "IPAddress": "",
            "IPPrefixLen": 0,
            "IPv6Gateway": "",
            "GlobalIPv6Address": "",
            "GlobalIPv6PrefixLen": 0,
            "MacAddress": "",
            "NetworkID": "none",
            "DriverOpts": None,
            "IPAMConfig": None,
            "Links": None,
        }
        if (
            set(networks) != {"none"}
            or not isinstance(marker, Mapping)
            or set(marker) != set(expected_marker)
            or any(
                type(marker[key]) is not type(expected) or marker[key] != expected
                for key, expected in expected_marker.items()
            )
        ):
            raise ContainmentUnavailable("Podman attached the candidate to a network")

    pid_ns = _normal_private(_ci_get(host, "PidMode"), "PID")
    ipc_ns, ipc_ns_evidence = _verified_private_ipc(
        _ci_get(host, "IpcMode"),
        runtime_version=preflight.runtime_version,
        create_command=_ci_get(config, "CreateCommand"),
    )
    uts_ns = _normal_private(_ci_get(host, "UTSMode"), "UTS")
    _normal_private(_ci_get(host, "CgroupMode"), "cgroup")
    _verify_empty_hooks_dir(hooks_dir, preflight.uid)

    for field in ("AppArmorProfile", "ProcessLabel", "MountLabel"):
        if str(_ci_get(item, field, "") or "").strip().lower() in {
            "unconfined",
            "disable",
            "disabled",
        }:
            raise ContainmentUnavailable(f"Podman resolved an unconfined {field}")
    lsm_profiles = _active_lsm_profiles(item)

    return OciContainmentFacts(
        runtime="podman",
        runtime_version=preflight.runtime_version,
        runtime_chain=(
            preflight.limit_helper_path.name,
            "podman",
            preflight.process_monitor_path.name,
            preflight.oci_runtime_path.name,
        ),
        runtime_rootless=True,
        cgroup_version=preflight.cgroup_version,
        subordinate_id_ranges_verified=True,
        image_reference_digest=preflight.image_reference_digest,
        image_digest=image_digest,
        rootfs_read_only=True,
        network_mode="none",
        workspace_destination=destination,
        workspace_source_sha256=hashlib.sha256(str(workspace).encode()).hexdigest(),
        workspace_read_write=mount_rw,
        workspace_private_relabel_option=private_relabel,
        workspace_bind_nonrecursive=bind_nonrecursive,
        workspace_propagation=propagation,
        host_write_mounts=(destination,),
        tmpfs_mounts=(OCI_TMP,),
        tmpfs_size_bytes=tmpfs_size,
        tmpfs_mode=tmpfs_mode,
        effective_capabilities=(),
        bounding_capabilities=(),
        no_new_privileges=True,
        seccomp_profile_sha256=preflight.seccomp_profile_sha256,
        lsm_profiles=lsm_profiles,
        user_namespace=user_namespace,
        automatic_host_mounts_disabled=preflight.automatic_host_mounts_disabled,
        oci_hooks_disabled=True,
        pid_namespace=pid_ns,
        ipc_namespace=ipc_ns,
        ipc_namespace_evidence=ipc_ns_evidence,
        uts_namespace=uts_ns,
        pids_limit=pids_limit,
        memory_limit_bytes=memory_limit,
        cpu_limit=nano_cpus / 1_000_000_000,
        runtime_timeout_s=configured_timeout,
        auto_remove=True,
        output_limit_bytes=OCI_OUTPUT_LIMIT_BYTES,
        container_log_driver=log_driver,
        systemd_mode=False,
        init_process=False,
        sdnotify_mode=sdnotify_mode,
        image_volumes_ignored=True,
        container_user=user,
        environment_names=tuple(sorted(candidate_env)),
        command_sha256=hashlib.sha256(
            json.dumps(list(command), separators=(",", ":")).encode()
        ).hexdigest(),
    )


def _best_effort_control(
    runtime: Path,
    runtime_env: Mapping[str, str],
    oci_runtime: Path,
    process_monitor: Path,
    *args: str,
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return _run_control(
            _podman_argv(
                runtime,
                *args,
                oci_runtime=oci_runtime,
                process_monitor=process_monitor,
            ),
            env=runtime_env,
            timeout_s=10.0,
        )
    except ContainmentUnavailable:
        return None


def _remove_container_strict(
    preflight: _Preflight,
    container: str,
) -> None:
    """Remove a possibly-partial container or surface the surviving residue."""
    result = _best_effort_control(
        preflight.runtime,
        preflight.runtime_env,
        preflight.oci_runtime_path,
        preflight.process_monitor_path,
        "rm",
        "--force",
        "--ignore",
        "--time=0",
        container,
    )
    if result is None or result.returncode != 0:
        detail = "control operation unavailable" if result is None else _stderr_tail(result)
        raise ContainmentUnavailable(
            "Podman could not remove a partially launched candidate container: " + detail
        )


class LinuxContainedProcess:
    """Attached Podman process whose container tree is cancelled as one unit."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        runtime: Path,
        runtime_env: Mapping[str, str],
        oci_runtime: Path,
        process_monitor: Path,
        container_id: str,
        hooks_dir: Path,
        attestation: ContainmentAttestation,
    ) -> None:
        self._process = process
        self.pid = int(process.pid)
        self._runtime = runtime
        self._runtime_env = dict(runtime_env)
        self._oci_runtime = oci_runtime
        self._process_monitor = process_monitor
        self._container_id = container_id
        self._hooks_dir = hooks_dir
        self.attestation = attestation
        self._closed = False
        self._container_removed = False
        self._register()

    def _register(self) -> None:
        try:
            from daedalus.spine import cancel as _cancel

            with _cancel._LIVE_LOCK:
                _cancel._LIVE.add(self)
        except Exception as exc:  # noqa: BLE001 - a missing kill-switch is unsafe
            raise ContainmentUnavailable(
                "candidate container could not enter the global cancellation registry"
            ) from exc

    def _unregister(self) -> None:
        try:
            from daedalus.spine import cancel as _cancel

            with _cancel._LIVE_LOCK:
                _cancel._LIVE.discard(self)
        except Exception:  # noqa: BLE001
            pass

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout_s: float = 900.0) -> int:
        try:
            return int(self._process.wait(timeout=float(timeout_s)))
        except subprocess.TimeoutExpired:
            self.kill()
            return 124

    def _kill_attach_group(self) -> None:
        try:
            os.killpg(self._process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                self._process.kill()
            except OSError:
                pass

    @staticmethod
    def _control_succeeded(result: subprocess.CompletedProcess[bytes] | None) -> bool:
        return result is not None and result.returncode == 0

    def _force_remove(self) -> bool:
        if self._container_removed:
            return True
        removed = _best_effort_control(
            self._runtime,
            self._runtime_env,
            self._oci_runtime,
            self._process_monitor,
            "rm",
            "--force",
            "--ignore",
            "--time=0",
            self._container_id,
        )
        if self._control_succeeded(removed):
            self._container_removed = True
            return True
        return False

    def cancel(self, grace_s: float = 3.0):
        from daedalus.spine.cancel import (
            CancelResult,
            STAGE_GRACEFUL,
            STAGE_TREE_KILL,
        )

        started = time.monotonic()
        seconds = max(0, int(math.ceil(float(grace_s))))
        stopped = _best_effort_control(
            self._runtime,
            self._runtime_env,
            self._oci_runtime,
            self._process_monitor,
            "stop",
            "--ignore",
            f"--time={seconds}",
            self._container_id,
        )
        graceful = self._control_succeeded(stopped)
        if graceful and self.returncode is None:
            try:
                self._process.wait(timeout=max(1.0, float(grace_s) + 2.0))
            except subprocess.TimeoutExpired:
                graceful = False
        if graceful and self.returncode is not None:
            return CancelResult(
                STAGE_GRACEFUL,
                True,
                True,
                self.returncode,
                time.monotonic() - started,
            )

        killed = _best_effort_control(
            self._runtime,
            self._runtime_env,
            self._oci_runtime,
            self._process_monitor,
            "kill",
            "--signal=KILL",
            self._container_id,
        )
        if not self._control_succeeded(killed) and not self._force_remove():
            from daedalus.spine.cancel import CancellationUnavailable

            raise CancellationUnavailable(
                "Podman could not prove the candidate container tree stopped"
            )
        self._kill_attach_group()
        try:
            self._process.wait(timeout=10.0)
        except subprocess.TimeoutExpired:
            self._kill_attach_group()
        return CancelResult(
            STAGE_TREE_KILL,
            False,
            True,
            self.returncode,
            time.monotonic() - started,
        )

    def kill(self) -> None:
        killed = _best_effort_control(
            self._runtime,
            self._runtime_env,
            self._oci_runtime,
            self._process_monitor,
            "kill",
            "--signal=KILL",
            self._container_id,
        )
        if not self._control_succeeded(killed) and not self._force_remove():
            from daedalus.spine.cancel import CancellationUnavailable

            raise CancellationUnavailable(
                "Podman could not prove the candidate container tree stopped"
            )
        self._kill_attach_group()

    def close(self) -> None:
        if self._closed:
            return
        cancellation_error: BaseException | None = None
        try:
            if self.returncode is None:
                try:
                    self.cancel(grace_s=0.0)
                except BaseException as exc:
                    cancellation_error = exc
        finally:
            removed = self._force_remove()
            if not removed:
                # Keep the object in the global cancellation registry so the
                # kill-switch sweep can retry.  Most importantly, never report
                # a clean release when the candidate cgroup may still exist.
                raise ContainmentUnavailable(
                    "Podman could not remove the candidate container; "
                    "its process tree is not proven dead"
                ) from cancellation_error
            if self.returncode is None:
                self._kill_attach_group()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._kill_attach_group()
            try:
                self._hooks_dir.rmdir()
            except OSError:
                pass
            self._closed = True
            self._unregister()

    def __enter__(self) -> "LinuxContainedProcess":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def spawn_oci_contained(
    argv: Sequence[str],
    cwd: str | Path,
    *,
    output: BinaryIO,
    timeout_s: float | None = DEFAULT_OCI_RUNTIME_TIMEOUT_S,
) -> LinuxContainedProcess:
    """Create, verify and start one candidate command in rootless Podman.

    The configured image must already exist locally and be pinned by digest.
    Every preflight or verification error raises :class:`ContainmentUnavailable`.
    No branch executes ``argv`` directly on the host.
    """
    preflight = _preflight()
    workspace = _workspace_preflight(cwd, preflight.uid)
    command = _container_command(tuple(argv), workspace)
    runtime_timeout_s = _runtime_timeout_seconds(timeout_s)
    output_path = _verified_output(output, workspace, preflight.uid)
    hooks_dir = _prepare_empty_hooks_dir(output_path, preflight.uid)

    name = f"daedalus-gate-{uuid.uuid4().hex}"
    create_argv = _create_argv(
        preflight,
        workspace,
        command,
        name,
        hooks_dir,
        runtime_timeout_s,
    )
    try:
        created = _checked_control(
            create_argv,
            env=preflight.runtime_env,
            operation="container create",
        )
    except BaseException as original:
        try:
            _remove_container_strict(preflight, name)
        except BaseException as cleanup_error:
            raise cleanup_error from original
        finally:
            try:
                hooks_dir.rmdir()
            except OSError:
                pass
        raise
    container_id = (created.stdout or b"").decode("ascii", "ignore").strip()
    if _CONTAINER_ID_RE.fullmatch(container_id) is None:
        try:
            _remove_container_strict(preflight, name)
        finally:
            try:
                hooks_dir.rmdir()
            except OSError:
                pass
        raise ContainmentUnavailable("Podman create returned no full immutable container ID")

    try:
        inspected = _checked_control(
            _podman_argv(
                preflight.runtime,
                "container",
                "inspect",
                "--format",
                "json",
                container_id,
                oci_runtime=preflight.oci_runtime_path,
                process_monitor=preflight.process_monitor_path,
            ),
            env=preflight.runtime_env,
            operation="container configuration inspection",
        )
        facts = _verify_container(
            _json_payload(inspected, "container configuration inspection"),
            preflight=preflight,
            container_id=container_id,
            container_name=name,
            workspace=workspace,
            command=command,
            hooks_dir=hooks_dir,
            runtime_timeout_s=runtime_timeout_s,
        )
        attestation = ContainmentAttestation(
            requested=True,
            executes_candidate=True,
            contained=True,
            platform=sys.platform,
            mechanism="rootless-podman-oci-create-inspect-start",
            inherited_handle_count=0,
            oci=facts,
        )
        try:
            process = subprocess.Popen(
                (
                    str(preflight.limit_helper_path),
                    f"--fsize={OCI_OUTPUT_LIMIT_BYTES}:{OCI_OUTPUT_LIMIT_BYTES}",
                    "--",
                    str(preflight.runtime),
                    "--remote=false",
                    f"--runtime={preflight.oci_runtime_path}",
                    f"--conmon={preflight.process_monitor_path}",
                    f"--hooks-dir={hooks_dir}",
                    "start",
                    "--attach",
                    "--sig-proxy=true",
                    container_id,
                ),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=preflight.runtime_env,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            raise ContainmentUnavailable(
                f"verified candidate container could not be started: {exc}"
            ) from exc
    except BaseException as original:
        try:
            _remove_container_strict(preflight, container_id)
        except BaseException as cleanup_error:
            raise cleanup_error from original
        finally:
            try:
                hooks_dir.rmdir()
            except OSError:
                pass
        raise

    try:
        return LinuxContainedProcess(
            process,
            runtime=preflight.runtime,
            runtime_env=preflight.runtime_env,
            oci_runtime=preflight.oci_runtime_path,
            process_monitor=preflight.process_monitor_path,
            container_id=container_id,
            hooks_dir=hooks_dir,
            attestation=attestation,
        )
    except BaseException as original:
        try:
            process.kill()
        except OSError:
            pass
        try:
            _remove_container_strict(preflight, container_id)
        except BaseException as cleanup_error:
            raise cleanup_error from original
        finally:
            try:
                hooks_dir.rmdir()
            except OSError:
                pass
        raise


__all__ = [
    "DEFAULT_PODMAN_PATH",
    "DEFAULT_PRLIMIT_PATH",
    "LINUX_OCI_IMAGE_ENV",
    "LINUX_OCI_RUNTIME_ENV",
    "LinuxContainedProcess",
    "OCI_CPU_LIMIT",
    "OCI_MEMORY_LIMIT_BYTES",
    "OCI_OUTPUT_LIMIT_BYTES",
    "OCI_PIDS_LIMIT",
    "spawn_oci_contained",
]
