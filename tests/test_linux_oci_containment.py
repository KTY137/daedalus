"""Deterministic acceptance tests for Linux rootless-OCI containment.

Most tests run on Windows and do not require Podman: the create/inspect/start
protocol and its fail-closed verifier are exercised through process seams.  A
live Linux test is opt-in because it requires a deliberately provisioned,
digest-pinned local toolchain image.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.kernel import attempt_execution as attempt_mod
from daedalus.spine import linux_containment as L
from daedalus.spine.containment import ContainmentAttestation, ContainmentUnavailable


IMAGE_ID = "1" * 64
REFERENCE_DIGEST = "sha256:" + "2" * 64
LOCAL_DIGEST = "sha256:" + "3" * 64
CONTAINER_ID = "4" * 64
IMAGE_REFERENCE = f"registry.example/daedalus/python@{REFERENCE_DIGEST}"
TEST_SECCOMP = Path("verified-seccomp.json")


def _preflight(tmp_path: Path, *, uid: int = 1000, gid: int = 1000) -> L._Preflight:
    return L._Preflight(
        runtime=tmp_path / "podman",
        runtime_env={"HOME": str(tmp_path), "XDG_RUNTIME_DIR": str(tmp_path / "run")},
        runtime_version="5.4.2",
        image_reference=IMAGE_REFERENCE,
        image_reference_digest=REFERENCE_DIGEST,
        local_image_id=IMAGE_ID,
        local_image_digest=LOCAL_DIGEST,
        uid=uid,
        gid=gid,
        cgroup_version="v2",
        seccomp_profile=TEST_SECCOMP,
        seccomp_profile_sha256="a" * 64,
        automatic_host_mounts_disabled=True,
        oci_runtime_path=tmp_path / "crun",
        process_monitor_path=tmp_path / "conmon",
        limit_helper_path=tmp_path / "prlimit",
    )


def _hooks(tmp_path: Path) -> Path:
    path = tmp_path / "hooks"
    path.mkdir(exist_ok=True)
    path.chmod(0o700)
    return path


def _inspect(
    workspace: Path,
    command: tuple[str, ...],
    *,
    name: str = "daedalus-gate-test",
    uid: int = 1000,
    gid: int = 1000,
) -> dict:
    env = [f"{key}={value}" for key, value in sorted(L._CANDIDATE_ENV.items())]
    return {
        "Id": CONTAINER_ID,
        "Name": name,
        "State": {"Running": False},
        "Image": IMAGE_ID,
        "ImageDigest": LOCAL_DIGEST,
        "Pod": "",
        "Dependencies": [],
        "OCIRuntime": "crun",
        "EffectiveCaps": [],
        "BoundingCaps": [],
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(workspace),
                "Destination": "/workspace",
                "RW": True,
                "Mode": "Z",
                "Propagation": "rprivate",
                "Options": ["bind"],
            }
        ],
        "Config": {
            "User": f"{uid}:{gid}",
            "WorkingDir": "/workspace",
            "Entrypoint": [],
            "Cmd": list(command),
            "Env": env,
            "Volumes": None,
            "Secrets": [],
            "CreateCommand": ["podman", "create", "--ipc=private"],
            "Timeout": int(L.DEFAULT_OCI_RUNTIME_TIMEOUT_S),
            "SystemdMode": False,
            "sdNotifyMode": "ignore",
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "NetworkMode": "none",
            "Privileged": False,
            "PublishAllPorts": False,
            "PortBindings": {},
            "Devices": [],
            "GroupAdd": [],
            "VolumesFrom": [],
            "AutoRemove": True,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "LogConfig": {"Type": "none", "Config": {}, "Path": ""},
            "Init": False,
            "SecurityOpt": [
                "no-new-privileges",
                f"seccomp={TEST_SECCOMP}",
            ],
            "Binds": [f"{workspace}:/workspace:rw,Z,rprivate,bind"],
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=536870912,mode=1777"
            },
            "IDMappings": {
                "UidMap": [f"0:1:{uid}", f"{uid}:0:1", f"{uid + 1}:{uid + 1}:64536"],
                "GidMap": [f"0:1:{gid}", f"{gid}:0:1", f"{gid + 1}:{gid + 1}:64536"],
            },
            "PidsLimit": L.OCI_PIDS_LIMIT,
            "Memory": L.OCI_MEMORY_LIMIT_BYTES,
            "MemorySwap": L.OCI_MEMORY_LIMIT_BYTES,
            "NanoCpus": int(L.OCI_CPU_LIMIT * 1_000_000_000),
            "PidMode": "private",
            "IpcMode": "private",
            "UTSMode": "private",
            "CgroupMode": "private",
        },
        "NetworkSettings": {"Networks": {}},
    }


def _completed(
    argv: tuple[str, ...] = ("podman",),
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr=stderr)


def test_create_policy_has_no_host_fallback_and_closes_crosstalk(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    command = ("python3", "-c", "print('ok')")
    hooks = _hooks(tmp_path)
    argv = L._create_argv(
        preflight,
        tmp_path.resolve(),
        command,
        "daedalus-gate-test",
        hooks,
        37,
    )

    assert argv[0] == str(preflight.runtime)
    assert argv[1] == "--remote=false"
    assert f"--runtime={preflight.oci_runtime_path}" in argv
    assert f"--conmon={preflight.process_monitor_path}" in argv
    assert f"--hooks-dir={hooks}" in argv
    assert "create" in argv
    for exact in (
        "--pull=never",
        "--read-only=true",
        "--read-only-tmpfs=false",
        "--image-volume=ignore",
        "--network=none",
        "--pid=private",
        "--ipc=private",
        "--uts=private",
        "--cgroupns=private",
        "--userns=keep-id:uid=1000,gid=1000",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--security-opt=seccomp={TEST_SECCOMP}",
        "--rm",
        "--timeout=37",
        "--systemd=false",
        "--init=false",
        "--sdnotify=ignore",
        "--log-driver=none",
        "--unsetenv-all",
        "--http-proxy=false",
    ):
        assert exact in argv
    mounts = [part for part in argv if part.startswith("--mount=")]
    assert len(mounts) == 1
    assert "dst=/workspace,rw" in mounts[0]
    assert "bind-nonrecursive" in mounts[0]
    assert IMAGE_REFERENCE in argv
    assert argv[-len(command):] == command


def test_podman_control_environment_drops_remote_auth_and_config_injection() -> None:
    env = L._runtime_env(
        {
            "HOME": "/home/genesis",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "PATH": "/candidate/bin:/usr/bin",
            "CONTAINER_HOST": "ssh://attacker",
            "CONTAINERS_CONF": "/candidate/containers.conf",
            "REGISTRY_AUTH_FILE": "/candidate/auth.json",
            "API_TOKEN": "secret",
        }
    )
    assert env == {
        "HOME": "/home/genesis",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "CONTAINERS_CONF": "/dev/null",
    }


def test_linux_gate_dispatch_forwards_timeout_and_parent_output(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    output_path = scratch / "gate.out"
    sentinel = object()
    seen: dict[str, object] = {}

    def fake_spawn(argv, *, cwd, output, timeout_s):
        seen.update(
            argv=tuple(argv),
            cwd=cwd,
            output_name=output.name,
            output_open=not output.closed,
            timeout_s=timeout_s,
        )
        return sentinel

    monkeypatch.setattr(attempt_mod.os, "name", "posix")
    monkeypatch.setattr(attempt_mod.sys, "platform", "linux")
    monkeypatch.setattr(L, "spawn_oci_contained", fake_spawn)

    proc, output = attempt_mod._contained_gate_child(
        ("python3", "-V"),
        workspace,
        output_path,
        scratch,
        timeout_s=12.5,
    )
    try:
        assert proc is sentinel
        assert seen == {
            "argv": ("python3", "-V"),
            "cwd": workspace,
            "output_name": str(output_path),
            "output_open": True,
            "timeout_s": 12.5,
        }
    finally:
        output.close()


def test_unsupported_gate_dispatch_has_no_host_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(attempt_mod.os, "name", "posix")
    monkeypatch.setattr(attempt_mod.sys, "platform", "unsupported-os")

    with pytest.raises(ContainmentUnavailable, match="no measured"):
        attempt_mod._contained_gate_child(
            ("python3", "-V"),
            workspace,
            scratch / "gate.out",
            scratch,
            timeout_s=12.5,
        )
    assert not (scratch / "gate.out").exists()


def test_runtime_timeout_is_always_bounded() -> None:
    assert L._runtime_timeout_seconds(None) == 900
    assert L._runtime_timeout_seconds(0) == 1
    assert L._runtime_timeout_seconds(0.1) == 1
    assert L._runtime_timeout_seconds(1.1) == 2
    with pytest.raises(ContainmentUnavailable, match="finite"):
        L._runtime_timeout_seconds(float("inf"))
    with pytest.raises(ContainmentUnavailable, match="non-negative"):
        L._runtime_timeout_seconds(-1)
    with pytest.raises(ContainmentUnavailable, match="finite"):
        L._runtime_timeout_seconds("not-a-number")


def test_resolved_configuration_is_attested_not_merely_requested(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    command = ("python3", "-c", "print('ok')")
    facts = L._verify_container(
        [_inspect(workspace, command)],
        preflight=_preflight(tmp_path),
        container_id=CONTAINER_ID,
        container_name="daedalus-gate-test",
        workspace=workspace,
        command=command,
        hooks_dir=_hooks(tmp_path),
    )

    summary = facts.summary()
    assert summary["runtime_rootless"] is True
    assert summary["runtime_chain"] == ["prlimit", "podman", "conmon", "crun"]
    assert summary["subordinate_id_ranges_verified"] is True
    assert summary["rootfs_read_only"] is True
    assert summary["network_mode"] == "none"
    assert summary["host_write_mounts"] == ["/workspace"]
    assert summary["workspace_private_relabel_option"] is True
    assert summary["workspace_bind_nonrecursive"] is True
    assert summary["workspace_propagation"] == "rprivate"
    assert summary["tmpfs_size_bytes"] == 512 * 1024 * 1024
    assert summary["tmpfs_mode"] == "1777"
    assert summary["effective_capabilities"] == []
    assert summary["bounding_capabilities"] == []
    assert summary["no_new_privileges"] is True
    assert summary["seccomp_profile_sha256"] == "a" * 64
    assert summary["user_namespace"] == "keep-id"
    assert summary["automatic_host_mounts_disabled"] is True
    assert summary["oci_hooks_disabled"] is True
    assert summary["ipc_namespace_evidence"] == "container-inspect"
    assert summary["pids_limit"] == 96
    assert summary["memory_limit_bytes"] == 4 * 1024 * 1024 * 1024
    assert summary["runtime_timeout_s"] == 900
    assert summary["auto_remove"] is True
    assert summary["output_limit_bytes"] == L.OCI_OUTPUT_LIMIT_BYTES
    assert summary["container_log_driver"] == "none"
    assert summary["systemd_mode"] is False
    assert summary["init_process"] is False
    assert summary["sdnotify_mode"] == "ignore"
    assert summary["image_volumes_ignored"] is True
    assert "workspace_source_sha256" in summary
    assert str(workspace) not in json.dumps(summary)


def test_manifest_list_reference_digest_variant_and_structured_idmaps_are_admitted(
    tmp_path: Path,
) -> None:
    workspace = tmp_path.resolve()
    command = ("python3", "-c", "print('ok')")
    body = _inspect(workspace, command)
    body["ImageDigest"] = REFERENCE_DIGEST
    body["HostConfig"]["IDMappings"] = {
        "UIDMap": [{"ContainerID": 1000, "HostID": 0, "Size": 1}],
        "GIDMap": [{"container_id": 1000, "host_id": 0, "size": 1}],
    }

    facts = L._verify_container(
        [body],
        preflight=_preflight(tmp_path),
        container_id=CONTAINER_ID,
        container_name="daedalus-gate-test",
        workspace=workspace,
        command=command,
        hooks_dir=_hooks(tmp_path),
    )
    assert facts.image_digest == REFERENCE_DIGEST


def test_podman_43_private_ipc_inspect_bug_is_narrowly_verified(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    command = ("python3", "-c", "print('ok')")
    body = _inspect(workspace, command)
    body["HostConfig"]["IpcMode"] = "shareable"
    podman_43 = replace(_preflight(tmp_path), runtime_version="4.3.1")

    facts = L._verify_container(
        [body],
        preflight=podman_43,
        container_id=CONTAINER_ID,
        container_name="daedalus-gate-test",
        workspace=workspace,
        command=command,
        hooks_dir=_hooks(tmp_path),
    )
    assert facts.ipc_namespace == "private"
    assert facts.ipc_namespace_evidence == "podman-4.3-create-command"

    body["Config"]["CreateCommand"] = ["podman", "create"]
    with pytest.raises(ContainmentUnavailable, match="shared IPC"):
        L._verify_container(
            [body],
            preflight=podman_43,
            container_id=CONTAINER_ID,
            container_name="daedalus-gate-test",
            workspace=workspace,
            command=command,
            hooks_dir=_hooks(tmp_path),
        )

    body["Config"]["CreateCommand"].append("--ipc=private")
    with pytest.raises(ContainmentUnavailable, match="shared IPC"):
        L._verify_container(
            [body],
            preflight=replace(podman_43, runtime_version="4.4.0"),
            container_id=CONTAINER_ID,
            container_name="daedalus-gate-test",
            workspace=workspace,
            command=command,
            hooks_dir=_hooks(tmp_path),
        )


def test_unknown_container_image_digest_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    command = ("python3", "-c", "print('ok')")
    body = _inspect(workspace, command)
    body["ImageDigest"] = "sha256:" + "9" * 64
    with pytest.raises(ContainmentUnavailable, match="inspected local image"):
        L._verify_container(
            [body],
            preflight=_preflight(tmp_path),
            container_id=CONTAINER_ID,
            container_name="daedalus-gate-test",
            workspace=workspace,
            command=command,
            hooks_dir=_hooks(tmp_path),
        )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda body: body["HostConfig"].__setitem__("NetworkMode", "bridge"), "network=none"),
        (lambda body: body.__setitem__("EffectiveCaps", ["CAP_NET_RAW"]), "capability"),
        (lambda body: body.__setitem__("BoundingCaps", ["CAP_NET_RAW"]), "capability"),
        (lambda body: body.__setitem__("OCIRuntime", "runsc"), "OCI runtime"),
        (lambda body: body["HostConfig"].__setitem__("ReadonlyRootfs", False), "read-only"),
        (
            lambda body: body["Mounts"].append(
                {"Type": "bind", "Source": "/", "Destination": "/host", "RW": True}
            ),
            "exactly one",
        ),
        (lambda body: body["Config"]["Env"].append("API_TOKEN=leak"), "unexpected"),
        (lambda body: body["HostConfig"].__setitem__("PidsLimit", 0), "PID ceiling"),
        (lambda body: body["HostConfig"].__setitem__("AutoRemove", False), "automatic"),
        (
            lambda body: body["HostConfig"]["RestartPolicy"].__setitem__(
                "Name", "always"
            ),
            "restarting",
        ),
        (
            lambda body: body["HostConfig"]["LogConfig"].__setitem__(
                "Type", "journald"
            ),
            "container log",
        ),
        (lambda body: body["Config"].__setitem__("Timeout", 0), "runtime deadline"),
        (lambda body: body["Config"].__setitem__("SystemdMode", True), "systemd"),
        (lambda body: body["HostConfig"].__setitem__("Init", True), "init process"),
        (lambda body: body["Config"].__setitem__("sdNotifyMode", "container"), "sd-notify"),
        (lambda body: body["Mounts"][0].__setitem__("Mode", "z"), "private relabel"),
        (lambda body: body["Mounts"][0].__setitem__("Options", ["rbind"]), "nonrecursive"),
        (lambda body: body["Mounts"][0].__setitem__("Propagation", "rshared"), "rprivate"),
        (
            lambda body: body["HostConfig"]["Tmpfs"].__setitem__(
                "/tmp", "rw,noexec,nosuid,nodev,size=1,mode=1777"
            ),
            "512 MiB",
        ),
        (lambda body: body["HostConfig"].__setitem__("IDMappings", None), "IDMappings"),
        (
            lambda body: body["HostConfig"].__setitem__(
                "SecurityOpt", ["no-new-privileges", "seccomp=unconfined"]
            ),
            "unconfined",
        ),
    ],
)
def test_any_weakened_inspection_refuses_before_start(tmp_path: Path, mutate, reason: str) -> None:
    workspace = tmp_path.resolve()
    command = ("python3", "-c", "print('ok')")
    body = _inspect(workspace, command)
    mutate(body)

    with pytest.raises(ContainmentUnavailable, match=reason):
        L._verify_container(
            [body],
            preflight=_preflight(tmp_path),
            container_id=CONTAINER_ID,
            container_name="daedalus-gate-test",
            workspace=workspace,
            command=command,
            hooks_dir=_hooks(tmp_path),
        )


def test_host_absolute_paths_cannot_cross_the_boundary(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    with pytest.raises(ContainmentUnavailable, match="absolute host path"):
        L._container_command((str(outside.resolve()),), tmp_path.resolve())


def test_host_python_is_explicitly_mapped_to_container_python(tmp_path: Path) -> None:
    command = L._container_command(
        (sys.executable, "-c", "print('ok')"), tmp_path.resolve()
    )
    assert command == ("python3", "-c", "print('ok')")
    assert sys.executable not in command


def test_parent_output_inside_candidate_workspace_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output_path = workspace / "gate.out"
    with output_path.open("wb") as output:
        with pytest.raises(ContainmentUnavailable, match="outside.*workspace"):
            L._verified_output(output, workspace.resolve(), output_path.stat().st_uid)


def test_multiply_linked_parent_output_is_refused(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output_path = tmp_path / "gate.out"
    output_path.touch()
    alias = tmp_path / "gate-alias.out"
    try:
        os.link(output_path, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    with output_path.open("wb") as output:
        with pytest.raises(ContainmentUnavailable, match="exactly one hard link"):
            L._verified_output(output, workspace.resolve(), output_path.stat().st_uid)


def test_parent_output_must_start_empty_at_offset_zero(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output_path = tmp_path / "gate.out"
    output_path.write_bytes(b"pre-existing evidence")
    with output_path.open("r+b") as output:
        with pytest.raises(ContainmentUnavailable, match="empty"):
            L._verified_output(output, workspace.resolve(), output_path.stat().st_uid)

    output_path.write_bytes(b"")
    with output_path.open("rb") as output:
        with pytest.raises(ContainmentUnavailable, match="writable"):
            L._verified_output(output, workspace.resolve(), output_path.stat().st_uid)

    with output_path.open("r+b") as output:
        output.seek(1)
        with pytest.raises(ContainmentUnavailable, match="offset zero"):
            L._verified_output(output, workspace.resolve(), output_path.stat().st_uid)


def test_missing_digest_pin_is_a_preflight_refusal(monkeypatch) -> None:
    monkeypatch.delenv(L.LINUX_OCI_IMAGE_ENV, raising=False)
    with pytest.raises(ContainmentUnavailable, match="pinned"):
        L._configured_image()


def test_short_or_tag_only_image_names_are_refused(monkeypatch) -> None:
    for value in ("python@" + REFERENCE_DIGEST, "python:3.13", "python:latest"):
        monkeypatch.setenv(L.LINUX_OCI_IMAGE_ENV, value)
        with pytest.raises(ContainmentUnavailable, match="fully qualified"):
            L._configured_image()


def test_debian_rhel_subordinate_id_ranges_are_parsed_fail_closed() -> None:
    identities = {"genesis", "1000"}
    assert L._has_subordinate_range(["genesis:100000:65536"], identities)
    assert L._has_subordinate_range(["1000:100000:131072"], identities)
    assert not L._has_subordinate_range(["other:100000:65536"], identities)
    assert not L._has_subordinate_range(["genesis:100000:65535"], identities)
    assert not L._has_subordinate_range(["genesis:not-a-number:65536"], identities)


def test_rhel_automatic_subscription_mounts_are_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    user_file = home / ".config" / "containers" / "mounts.conf"
    user_file.parent.mkdir(parents=True)
    user_file.touch()
    payload = b"/usr/share/rhel/secrets:/run/secrets\n"
    monkeypatch.setattr(
        L,
        "_read_trusted_config",
        lambda path, **kwargs: (path, payload),
    )
    with pytest.raises(ContainmentUnavailable, match="automatic host mounts"):
        L._verify_automatic_mounts_disabled({"HOME": str(home)}, 1000)

    payload = b"# deliberately empty rootless override\n"
    L._verify_automatic_mounts_disabled({"HOME": str(home)}, 1000)


def test_seccomp_profile_must_be_deny_by_default(monkeypatch) -> None:
    document = {"defaultAction": "SCMP_ACT_ALLOW", "syscalls": []}
    payload = json.dumps(document).encode() + b" " * 300
    monkeypatch.setattr(
        L,
        "_read_trusted_config",
        lambda *args, **kwargs: (Path(L.DEFAULT_SECCOMP_PROFILE), payload),
    )
    with pytest.raises(ContainmentUnavailable, match="deny-by-default"):
        L._trusted_seccomp_profile(1000)

    document["defaultAction"] = "SCMP_ACT_ERRNO"
    payload = json.dumps(document).encode() + b" " * 300
    path, digest = L._trusted_seccomp_profile(1000)
    assert path == Path(L.DEFAULT_SECCOMP_PROFILE)
    assert digest == L.hashlib.sha256(payload).hexdigest()


def test_preflight_requires_rootless_and_cgroup_v2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(L, "_is_native_linux", lambda: True)
    monkeypatch.setattr(L, "_effective_ids", lambda: (1000, 1000))
    monkeypatch.setattr(L, "_verify_rootless_user_namespace", lambda uid: None)
    monkeypatch.setattr(L, "_trusted_runtime_path", lambda: tmp_path / "podman")
    monkeypatch.setattr(L, "_configured_image", lambda: (IMAGE_REFERENCE, REFERENCE_DIGEST))
    monkeypatch.setattr(L, "_verify_automatic_mounts_disabled", lambda env, uid: None)
    monkeypatch.setattr(
        L, "_trusted_seccomp_profile", lambda uid: (TEST_SECCOMP, "a" * 64)
    )

    info = {
        "host": {
            "serviceIsRemote": False,
            "security": {"rootless": False, "seccompEnabled": True},
            "cgroupVersion": "v2",
            "cgroupControllers": ["cpu", "memory", "pids"],
        },
        "version": {"Version": "5.4.2"},
    }
    monkeypatch.setattr(
        L,
        "_run_control",
        lambda *a, **k: _completed(stdout=json.dumps(info).encode()),
    )
    with pytest.raises(ContainmentUnavailable, match="rootless=true"):
        L._preflight()

    info["host"]["security"]["rootless"] = True
    info["host"]["cgroupVersion"] = "v1"
    with pytest.raises(ContainmentUnavailable, match="cgroup v2"):
        L._preflight()

    info["host"]["serviceIsRemote"] = True
    info["host"]["cgroupVersion"] = "v2"
    with pytest.raises(ContainmentUnavailable, match="runtime is local"):
        L._preflight()

    info["host"]["serviceIsRemote"] = False
    info["host"]["security"]["seccompEnabled"] = False
    with pytest.raises(ContainmentUnavailable, match="seccomp"):
        L._preflight()


class _ExitedAttach:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pid = 4242

    def poll(self) -> int:
        return 0

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        return None


def test_close_never_claims_release_when_container_removal_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        L,
        "_best_effort_control",
        lambda *args, **kwargs: _completed(returncode=125, stderr=b"not removed"),
    )
    proc = L.LinuxContainedProcess(
        _ExitedAttach(),
        runtime=tmp_path / "podman",
        runtime_env={},
        oci_runtime=tmp_path / "crun",
        process_monitor=tmp_path / "conmon",
        container_id=CONTAINER_ID,
        hooks_dir=_hooks(tmp_path),
        attestation=ContainmentAttestation(
            requested=True,
            executes_candidate=True,
            contained=True,
            platform="linux",
        ),
    )
    try:
        with pytest.raises(ContainmentUnavailable, match="not proven dead"):
            proc.close()
        assert proc._closed is False
    finally:
        proc._unregister()


def test_spawn_is_create_inspect_start_and_cleanup_never_host_argv(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    uid = workspace.stat().st_uid
    gid = workspace.stat().st_gid
    preflight = _preflight(tmp_path, uid=uid, gid=gid)
    name: dict[str, str] = {}
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(L, "_preflight", lambda: preflight)
    monkeypatch.setattr(L.uuid, "uuid4", lambda: type("U", (), {"hex": "a" * 32})())
    container_name = "daedalus-gate-" + "a" * 32
    command = ("python3", "-c", "print('ok')")

    def checked(argv, *, env, operation):
        calls.append(tuple(argv))
        if operation == "container create":
            return _completed(tuple(argv), stdout=(CONTAINER_ID + "\n").encode())
        body = _inspect(
            workspace.resolve(), command, name=container_name, uid=uid, gid=gid
        )
        body["Config"]["Timeout"] = 37
        return _completed(
            tuple(argv),
            stdout=json.dumps([body]).encode(),
        )

    attached: list[_ExitedAttach] = []

    def popen(*args, **kwargs):
        proc = _ExitedAttach(*args, **kwargs)
        attached.append(proc)
        return proc

    cleanup: list[tuple[str, ...]] = []
    monkeypatch.setattr(L, "_checked_control", checked)
    monkeypatch.setattr(L.subprocess, "Popen", popen)
    monkeypatch.setattr(
        L,
        "_best_effort_control",
        lambda runtime, runtime_env, oci_runtime, process_monitor, *args: (
            cleanup.append(tuple(args)) or _completed(tuple(args))
        ),
    )

    output_path = tmp_path / "gate.out"
    with output_path.open("wb") as output:
        proc = L.spawn_oci_contained(
            (sys.executable, "-c", "print('ok')"),
            workspace,
            output=output,
            timeout_s=36.2,
        )
        proc.close()

    assert calls[0][0] == str(preflight.runtime)
    assert calls[0][1] == "--remote=false"
    assert "create" in calls[0]
    assert "--timeout=37" in calls[0]
    assert calls[1][-5:-3] == ("container", "inspect")
    start_argv = tuple(attached[0].args[0])
    assert start_argv == (
        str(preflight.limit_helper_path),
        f"--fsize={L.OCI_OUTPUT_LIMIT_BYTES}:{L.OCI_OUTPUT_LIMIT_BYTES}",
        "--",
        str(preflight.runtime),
        "--remote=false",
        f"--runtime={preflight.oci_runtime_path}",
        f"--conmon={preflight.process_monitor_path}",
        next(part for part in calls[0] if part.startswith("--hooks-dir=")),
        "start",
        "--attach",
        "--sig-proxy=true",
        CONTAINER_ID,
    )
    assert sys.executable not in start_argv
    assert proc.attestation.contained is True
    assert proc.attestation.oci is not None
    assert cleanup[-1] == ("rm", "--force", "--ignore", "--time=0", CONTAINER_ID)


def test_spawn_surfaces_cleanup_failure_after_partial_create(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    uid = workspace.stat().st_uid
    gid = workspace.stat().st_gid
    monkeypatch.setattr(L, "_preflight", lambda: _preflight(tmp_path, uid=uid, gid=gid))
    monkeypatch.setattr(
        L,
        "_checked_control",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ContainmentUnavailable("create failed")
        ),
    )
    monkeypatch.setattr(
        L,
        "_best_effort_control",
        lambda *args, **kwargs: _completed(returncode=125, stderr=b"residue remains"),
    )

    output_path = tmp_path / "gate.out"
    with output_path.open("wb") as output:
        with pytest.raises(ContainmentUnavailable, match="partially launched") as caught:
            L.spawn_oci_contained(("python3", "-c", "print('ok')"), workspace, output=output)
    assert isinstance(caught.value.__cause__, ContainmentUnavailable)


@pytest.mark.skipif(
    not (
        sys.platform.startswith("linux")
        and os.environ.get("DAEDALUS_RUN_LINUX_OCI_INTEGRATION") == "1"
        and os.environ.get(L.LINUX_OCI_IMAGE_ENV)
    ),
    reason="requires opt-in native Linux plus a local digest-pinned Podman image",
)
def test_live_linux_container_writes_workspace_but_not_root_and_has_no_network(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "probe.py"
    script.write_text(
        """
import pathlib, socket
pathlib.Path('/workspace/inside.txt').write_text('ok')
try:
    pathlib.Path('/outside.txt').write_text('escape')
except OSError:
    print('ROOT_WRITE=REFUSED')
else:
    print('ROOT_WRITE=ALLOWED')
try:
    socket.create_connection(('1.1.1.1', 53), timeout=1)
except OSError:
    print('NETWORK=REFUSED')
else:
    print('NETWORK=ALLOWED')
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "gate.out"
    with output_path.open("wb") as output:
        with L.spawn_oci_contained((sys.executable, str(script)), workspace, output=output) as proc:
            assert proc.wait(timeout_s=30) == 0

    text = output_path.read_text(encoding="utf-8")
    assert (workspace / "inside.txt").read_text(encoding="utf-8") == "ok"
    assert "ROOT_WRITE=REFUSED" in text
    assert "NETWORK=REFUSED" in text
    assert "ALLOWED" not in text
