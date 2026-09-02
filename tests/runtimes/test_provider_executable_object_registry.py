from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectAdmissionReceipt,
    ProviderExecutableObjectRegistry,
    ProviderExecutableObjectRegistryBindingError,
    ProviderExecutableObjectRegistryShapeError,
    _NativeRunTimeout,
    _native_posix_fork_exec_abi,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _write_adapter(
    root: Path,
    *,
    module_name: str = "daedalus.providers.fixture_adapter",
    source: str | None = None,
):
    if source is None:
        source = (
            "CALLS = []\n"
            "\n"
            "def helper():\n"
            "    return 'ok'\n"
            "\n"
            "def other_helper():\n"
            "    return 'substituted'\n"
            "\n"
            "def invoke():\n"
            "    return helper()\n"
            "\n"
            "def output_digests(value):\n"
            "    return ('a' * 64,)\n"
        )
    relative = Path(*module_name.split(".")).with_suffix(".py")
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")

    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, path, hashlib.sha256(path.read_bytes()).hexdigest()


def _pre_admission(
    *,
    module_name: str,
    source_sha256: str,
) -> ProviderExecutablePreAdmissionReceipt:
    values = {
        "source_revision": REVISION,
        "resolution_sha256": _sha("resolution"),
        "verification_sha256": _sha("verification"),
        "structure_sha256": _sha("structure"),
        "completed_retention_sha256": _sha("retention"),
        "retention_effect_terminal_sha256": _sha("retention-terminal"),
        "repository_head_sha256": _sha("repository-head"),
        "provider_id": "provider-fixture",
        "adapter_id": "adapter-fixture",
        "implementation_id": "implementation-fixture-v1",
        "entrypoint_id": "ikarus-one-shot",
        "runtime_id": "runtime-fixture",
        "execution_id": "execution-1",
        "idempotency_key": "idempotency-1",
        "invocation_authority_sha256": _sha("invocation-authority"),
        "invocation_contract_sha256": _sha("invocation-contract"),
        "invocation_subject_sha256": _sha("invocation-subject"),
        "invocation_identity_projection_sha256": _sha("identity-projection"),
        "identity_registry_sha256": _sha("identity-registry"),
        "identity_descriptor_sha256": _sha("identity-descriptor"),
        "target_authority_sha256": _sha("target-authority"),
        "target_projection_sha256": _sha("target-projection"),
        "target_manifest_sha256": _sha("target-manifest"),
        "target_descriptor_sha256": _sha("target-descriptor"),
        "adapter_artifact_sha256": _sha("adapter-artifact"),
        "adapter_config_sha256": _sha("adapter-config"),
        "lease_sha256": _sha("lease"),
        "invoke_target": f"{module_name}:invoke",
        "invoke_source_sha256": source_sha256,
        "output_digests_target": f"{module_name}:output_digests",
        "output_digests_source_sha256": source_sha256,
    }
    return ProviderExecutablePreAdmissionReceipt(**values)


def _sealed_native_run(tmp_path: Path):
    source = (
        "def invoke(payload):\n"
        "    import subprocess as local_subprocess\n"
        "    return local_subprocess.run\n"
        "\n"
        "def output_digests(value, payload):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    entry = next(iter(registry._entries.values()))
    importer = entry.sealed_operation.invoke.__builtins__["__import__"]
    return importer("subprocess").run


def test_posix_fork_exec_abi_refuses_unknown_future_cpython() -> None:
    assert _native_posix_fork_exec_abi((3, 10)) == 21
    assert _native_posix_fork_exec_abi((3, 12)) == 23
    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="unknown CPython fork_exec ABI",
    ):
        _native_posix_fork_exec_abi((3, 14))


def test_registry_proves_loaded_objects_without_executing_them(tmp_path: Path) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    admission = registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    assert module.CALLS == []
    assert admission.pre_admission_sha256 == subject.digest
    payload = admission.to_dict()
    assert payload["repository_source_bytes_verified"] is True
    assert payload["loaded_object_targets_verified"] is True
    assert payload["loaded_object_bytecode_verified"] is True
    assert payload["provider_code_executed"] is False
    assert payload["provider_execution_allowed"] is False
    assert payload["effect_start_authorized"] is False
    assert payload["callback_seam_removed"] is False
    assert ProviderExecutableObjectAdmissionReceipt.from_dict(payload) == admission
    assert registry.verify_registered(subject) == admission
    assert module.CALLS == []


def test_registry_refuses_provider_object_substitution_before_execution(
    tmp_path: Path,
) -> None:
    first, _first_path, source_sha = _write_adapter(tmp_path)
    second, _second_path, _second_sha = _write_adapter(
        tmp_path,
        module_name="daedalus.providers.other_fixture_adapter",
    )
    subject = _pre_admission(
        module_name=first.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="invoke function target differs",
    ):
        registry.register(
            subject,
            invoke=second.invoke,
            output_digests=first.output_digests,
        )

    assert first.CALLS == []
    assert second.CALLS == []


def test_registry_refuses_repository_source_mutation_after_registration(
    tmp_path: Path,
) -> None:
    module, path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    path.write_text(
        path.read_text(encoding="utf-8") + "\nMUTATED = True\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="repository source digest differs",
    ):
        registry.verify_registered(subject)
    assert module.CALLS == []


def test_registry_refuses_loaded_bytecode_substitution(
    tmp_path: Path,
) -> None:
    module, path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    namespace: dict[str, object] = {}
    exec(
        compile(
            "def invoke():\n    return 'substituted'\n",
            str(path),
            "exec",
        ),
        namespace,
    )
    replacement = namespace["invoke"]
    assert callable(replacement)
    module.invoke.__code__ = replacement.__code__  # type: ignore[attr-defined]

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="loaded bytecode differs",
    ):
        registry.verify_registered(subject)
    assert module.CALLS == []


def test_registry_refuses_rebound_ambient_helper_after_registration(
    tmp_path: Path,
) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    module.helper = module.other_helper

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="ambient helper 'helper' is rebound or aliased",
    ):
        registry.verify_registered(subject)
    assert module.CALLS == []


def test_registry_refuses_mutable_referenced_module_global(tmp_path: Path) -> None:
    source = (
        "CALLS = []\n"
        "\n"
        "def invoke():\n"
        "    CALLS.append('invoke')\n"
        "    return 'ok'\n"
        "\n"
        "def output_digests(value):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="ambient global 'CALLS' is not an admissible same-module helper function",
    ):
        ProviderExecutableObjectRegistry(tmp_path).register(
            subject,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )
    assert module.CALLS == []


def test_registry_refuses_constant_ambient_global_without_signed_dependency_manifest(
    tmp_path: Path,
) -> None:
    source = (
        "MODEL = 'example-model'\n"
        "\n"
        "def invoke():\n"
        "    return MODEL\n"
        "\n"
        "def output_digests(value):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="ambient global 'MODEL' is not an admissible same-module helper function",
    ):
        ProviderExecutableObjectRegistry(tmp_path).register(
            subject,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )


def test_sealed_import_functions_detach_nested_stdlib_globals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        "def invoke(payload):\n"
        "    import hashlib as local_hashlib\n"
        "    import json as local_json\n"
        "    import subprocess as local_subprocess\n"
        "    return (local_hashlib, local_json, local_subprocess, payload)\n"
        "\n"
        "def output_digests(value, payload):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    entry = next(iter(registry._entries.values()))
    importer = entry.sealed_operation.invoke.__builtins__["__import__"]
    sealed_subprocess = importer("subprocess")
    sealed_json = importer("json")
    sealed_hashlib = importer("hashlib")
    original_encoder = json.JSONEncoder
    original_encoder_encode = json.JSONEncoder.encode
    original_decode_error = json.JSONDecodeError
    original_decode_error_init = json.JSONDecodeError.__init__
    original_default_encoder = json._default_encoder
    original_default_decoder = json._default_decoder
    original_sha256 = hashlib.sha256
    decode_error_traps: list[tuple[object, ...]] = []

    def decode_error_trap(*args, **kwargs):
        decode_error_traps.append((*args, kwargs))
        raise AssertionError("ambient JSONDecodeError.__init__ executed")

    if sys.platform == "win32":
        original_process_leaf = subprocess._winapi.CreateProcess
    else:
        import _posixsubprocess

        original_process_leaf = _posixsubprocess.fork_exec

    with monkeypatch.context() as mutation:
        mutation.setattr(subprocess, "Popen", object())
        mutation.setattr(json, "JSONEncoder", object())
        mutation.setattr(json, "JSONDecodeError", object())
        mutation.setattr(json, "_default_encoder", object())
        mutation.setattr(json, "_default_decoder", object())
        mutation.setattr(json.decoder, "scanstring", object())
        mutation.setattr(json.scanner, "make_scanner", object())
        mutation.setattr(original_decode_error, "__init__", decode_error_trap)
        mutation.setattr(hashlib, "sha256", object())
        if sys.platform == "win32":
            mutation.setattr(subprocess._winapi, "CreateProcess", object())
        else:
            mutation.setattr(_posixsubprocess, "fork_exec", object())

        sealed_run_globals = sealed_subprocess.run.__globals__
        assert "Popen" not in sealed_run_globals
        assert "_fork_exec" not in sealed_run_globals
        sealed_encoder = sealed_json.dumps.__globals__["JSONEncoder"]
        assert sealed_encoder is not original_encoder
        assert sealed_encoder.encode is not original_encoder_encode
        assert sealed_encoder.encode.__code__ is original_encoder_encode.__code__
        assert sealed_json.JSONDecodeError is not original_decode_error
        assert (
            sealed_json.JSONDecodeError.__init__.__code__
            is original_decode_error_init.__code__
        )
        assert (
            sealed_json.dumps.__globals__["_default_encoder"]
            is not original_default_encoder
        )
        assert (
            sealed_json.loads.__globals__["_default_decoder"]
            is not original_default_decoder
        )
        assert sealed_hashlib.sha256 is original_sha256
        try:
            sealed_json.loads('{"unterminated":')
        except sealed_json.JSONDecodeError as exc:
            assert exc.msg
        else:
            raise AssertionError("malformed JSON did not raise the sealed exception")
        assert decode_error_traps == []
        if sys.platform == "win32":
            assert (
                sealed_run_globals["_NATIVE_CREATE_PROCESS"]
                is original_process_leaf
            )
        else:
            assert (
                sealed_run_globals["_NATIVE_FORK_EXEC"] is original_process_leaf
            )


def test_registry_refuses_in_place_popen_method_mutation_and_retains_native_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = (
        "def invoke(payload):\n"
        "    import subprocess as local_subprocess\n"
        "    return local_subprocess.run\n"
        "\n"
        "def output_digests(value, payload):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    entry = next(iter(registry._entries.values()))
    importer = entry.sealed_operation.invoke.__builtins__["__import__"]
    sealed_globals = importer("subprocess").run.__globals__
    assert "Popen" not in sealed_globals
    retained_process_leaf = (
        sealed_globals["_NATIVE_CREATE_PROCESS"]
        if sys.platform == "win32"
        else sealed_globals["_NATIVE_FORK_EXEC"]
    )

    def mutated_init(*args, **kwargs):
        del args, kwargs
        raise AssertionError("ambient Popen.__init__ executed")

    with monkeypatch.context() as mutation:
        mutation.setattr(subprocess.Popen, "__init__", mutated_init)
        with pytest.raises(
            ProviderExecutableObjectRegistryBindingError,
            match="dependency subprocess.run state changed after admission",
        ):
            registry.verify_registered(subject)
        assert (
            sealed_globals[
                "_NATIVE_CREATE_PROCESS"
                if sys.platform == "win32"
                else "_NATIVE_FORK_EXEC"
            ]
            is retained_process_leaf
        )


def test_native_runner_preserves_exact_argv_cwd_utf8_and_returncode(
    tmp_path: Path,
) -> None:
    run = _sealed_native_run(tmp_path)
    assert "_NATIVE_OUTPUT_LIMIT" not in run.__globals__
    argument = 'space quote " backslash \\ & echo NOT_A_SHELL'
    completed = run(
        [
            sys.executable,
            "-c",
            (
                "import json,os,sys; "
                "print(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd()})); "
                "sys.stderr.buffer.write(b'bad-utf8-\\xff'); sys.exit(7)"
            ),
            argument,
        ],
        cwd=str(tmp_path),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=10,
        check=False,
    )

    decoded = json.loads(completed.stdout)
    assert decoded == {"argv": [argument], "cwd": str(tmp_path)}
    assert completed.returncode == 7
    assert completed.stderr == "bad-utf8-�"


# The deadline these two tests hand the runner has to outlast ONE thing that is
# not the subject: the child interpreter's own start-up. Both assert that the
# timeout preserved whatever the child had already written, so a child that has
# not reached its first write yet produces an empty `stdout` and a red test that
# says nothing about the runner.
#
# [MEASURED 2026-09-02, this box] a bare `timeout=0.1` is inside that start-up
# window whenever the machine is busy: under a 16-worker `pytest -n 16` run both
# tests failed on `assert "started" in ...stdout` / `assert ...stdout`, and both
# passed serially in the same tree. Idle, `sys.executable -c` reaches its first
# write in well under 100 ms -- which is exactly why the race was invisible for
# as long as the suite only ever ran one test at a time.
#
# So the deadline ESCALATES instead of being raised outright. Idle, the first
# attempt still runs at the original 0.1 s and nothing about the test changed.
# Loaded, it retries at 0.5 s and 2.0 s. Raising the deadline to 2.0 s directly
# was rejected on a measurement: the firehose child below buffers 24 MB at 0.1 s
# but 336 MB at 2.0 s, and a fixed 2.0 s deadline would pay that on every run.
#
# What is NOT relaxed: each attempt must still raise `_NativeRunTimeout`, and
# must still do it promptly (the children run for 30 s and forever respectively,
# so a runner that ignored `timeout` fails the very first attempt on the
# `pytest.raises` and never reaches the retry).
_TIMEOUT_ESCALATION = (0.1, 0.5, 2.0)


def _timed_out_holding_partial_output(run, argv: list[str], cwd: str):
    """The runner's timeout verdict, retried only until the child had spoken.

    Returns the `_NativeRunTimeout` whose `stdout` is non-empty. Fails if the
    runner ever declines to time out, takes longer than its own deadline plus a
    generous scheduling margin, or never captures anything at the longest
    deadline -- that last case is the real defect this asserts against.
    """
    captured_value = None
    for timeout in _TIMEOUT_ESCALATION:
        started = time.monotonic()
        with pytest.raises(_NativeRunTimeout) as captured:
            run(
                argv,
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        assert time.monotonic() - started < timeout + 3
        captured_value = captured.value
        if captured_value.stdout:
            return captured_value
    assert captured_value is not None and captured_value.stdout, (
        "the runner timed out at every deadline up to "
        f"{_TIMEOUT_ESCALATION[-1]}s but never preserved the child's output"
    )
    return captured_value


def test_native_runner_timeout_kills_and_reaps_child(tmp_path: Path) -> None:
    run = _sealed_native_run(tmp_path)

    captured = _timed_out_holding_partial_output(
        run,
        [
            sys.executable,
            "-c",
            "import time; print('started', flush=True); time.sleep(30)",
        ],
        str(tmp_path),
    )

    assert "started" in captured.stdout


def test_native_runner_continuous_output_cannot_starve_timeout(tmp_path: Path) -> None:
    run = _sealed_native_run(tmp_path)

    captured = _timed_out_holding_partial_output(
        run,
        [
            sys.executable,
            "-c",
            "import os; chunk=b'x'*4096;\nwhile True: os.write(1, chunk)",
        ],
        str(tmp_path),
    )

    assert captured.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fork/exec contract")
def test_posix_native_runner_uses_only_the_c_fork_exec_child_leaf(
    tmp_path: Path,
) -> None:
    import _posixsubprocess

    namespace = _sealed_native_run(tmp_path).__globals__

    assert namespace["_NATIVE_FORK_EXEC"] is _posixsubprocess.fork_exec
    assert namespace["_NATIVE_FORK_EXEC_ABI"] in (21, 23)
    assert "_NATIVE_OUTPUT_LIMIT" not in namespace
    for forbidden in (
        "_NATIVE_FORK",
        "_NATIVE_DUP2",
        "_NATIVE_CHDIR",
        "_NATIVE_EXECVE",
        "_NATIVE_WRITE",
        "_NATIVE_EXIT",
    ):
        assert forbidden not in namespace


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX timeout contract")
def test_posix_native_runner_deadline_survives_reaped_child_with_open_pipes(
    tmp_path: Path,
) -> None:
    run = _sealed_native_run(tmp_path)
    started = time.monotonic()

    with pytest.raises(_NativeRunTimeout):
        run(
            [
                sys.executable,
                "-c",
                (
                    "import os,time; "
                    "os.fork() or (time.sleep(2), os._exit(0)); "
                    "os._exit(0)"
                ),
            ],
            cwd=str(tmp_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=0.1,
            check=False,
        )

    assert time.monotonic() - started < 1


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec-error contract")
def test_posix_native_runner_reports_child_chdir_failure(tmp_path: Path) -> None:
    missing_cwd = tmp_path / "missing"
    run = _sealed_native_run(tmp_path)

    with pytest.raises(FileNotFoundError) as captured:
        run(
            [sys.executable, "-c", "raise AssertionError('must not execute')"],
            cwd=str(missing_cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
        )

    assert captured.value.filename == str(missing_cwd)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PATH contract")
@pytest.mark.parametrize("path_entry", ["", "bin"])
def test_posix_native_runner_resolves_relative_path_from_child_cwd(
    tmp_path: Path,
    path_entry: str,
) -> None:
    executable_dir = tmp_path / path_entry
    executable_dir.mkdir(parents=True, exist_ok=True)
    admitted_name = "sealed-python"
    (executable_dir / admitted_name).symlink_to(sys.executable)
    run = _sealed_native_run(tmp_path)
    namespace = run.__globals__
    original_path_entries = namespace["_NATIVE_PATH_ENTRIES"]
    namespace["_NATIVE_PATH_ENTRIES"] = (path_entry,)
    try:
        completed = run(
            [admitted_name, "-c", "print('cwd-path-ok')"],
            cwd=str(tmp_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
        )
    finally:
        namespace["_NATIVE_PATH_ENTRIES"] = original_path_entries

    assert completed.returncode == 0
    assert completed.stdout.strip() == "cwd-path-ok"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX cleanup contract")
@pytest.mark.parametrize("fault_name", ["select", "read", "wait"])
def test_posix_native_runner_reaps_child_after_runtime_fault(
    tmp_path: Path,
    fault_name: str,
) -> None:
    run = _sealed_native_run(tmp_path)
    namespace = run.__globals__
    original_fork_exec = namespace["_NATIVE_FORK_EXEC"]
    original_select = namespace["_NATIVE_SELECT"]
    original_read = namespace["_NATIVE_READ"]
    original_wait = namespace["_NATIVE_WAITPID"]
    probes: list[int] = []

    def capture_fork_exec(*args):
        pid = original_fork_exec(*args)
        probes.append(pid)
        return pid

    def fault(*args):
        del args
        raise OSError(f"injected {fault_name} fault")

    namespace["_NATIVE_FORK_EXEC"] = capture_fork_exec
    namespace[
        {
            "select": "_NATIVE_SELECT",
            "read": "_NATIVE_READ",
            "wait": "_NATIVE_WAITPID",
        }[fault_name]
    ] = fault
    try:
        with pytest.raises(OSError, match="injected"):
            run(
                [
                    sys.executable,
                    "-c",
                    "import time; print('ready', flush=True); time.sleep(30)",
                ],
                cwd=str(tmp_path),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
                check=False,
            )
        assert len(probes) == 1
        with pytest.raises(ChildProcessError):
            os.waitpid(probes[0], os.WNOHANG)
    finally:
        namespace["_NATIVE_FORK_EXEC"] = original_fork_exec
        namespace["_NATIVE_SELECT"] = original_select
        namespace["_NATIVE_READ"] = original_read
        namespace["_NATIVE_WAITPID"] = original_wait


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle-list contract")
def test_windows_native_runner_inherits_only_declared_standard_handles(
    tmp_path: Path,
) -> None:
    import _winapi

    read_handle, write_handle = _winapi.CreatePipe(None, 0)
    process = _winapi.GetCurrentProcess()
    inheritable = _winapi.DuplicateHandle(
        process,
        read_handle,
        process,
        0,
        True,
        _winapi.DUPLICATE_SAME_ACCESS,
    )
    try:
        run = _sealed_native_run(tmp_path)
        completed = run(
            [
                sys.executable,
                "-c",
                (
                    "import _winapi,sys; h=int(sys.argv[1]); "
                    "\ntry: _winapi.GetFileType(h); print('INHERITED')"
                    "\nexcept OSError: print('CLOSED')"
                ),
                str(inheritable),
            ],
            cwd=str(tmp_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert completed.stdout.strip() == "CLOSED"
    finally:
        _winapi.CloseHandle(inheritable)
        _winapi.CloseHandle(read_handle)
        _winapi.CloseHandle(write_handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows cleanup contract")
@pytest.mark.parametrize("fault_name", ["peek", "wait"])
def test_windows_native_runner_reaps_child_after_runtime_fault(
    tmp_path: Path,
    fault_name: str,
) -> None:
    import _winapi

    run = _sealed_native_run(tmp_path)
    namespace = run.__globals__
    original_create = namespace["_NATIVE_CREATE_PROCESS"]
    original_peek = namespace["_NATIVE_PEEK_NAMED_PIPE"]
    original_wait = namespace["_NATIVE_WAIT_FOR_SINGLE_OBJECT"]
    probes: list[int] = []

    def capture_create(*args):
        result = original_create(*args)
        current = _winapi.GetCurrentProcess()
        probes.append(
            _winapi.DuplicateHandle(
                current,
                result[0],
                current,
                0,
                False,
                _winapi.DUPLICATE_SAME_ACCESS,
            )
        )
        return result

    def fault(*args):
        del args
        raise OSError(f"injected {fault_name} fault")

    namespace["_NATIVE_CREATE_PROCESS"] = capture_create
    namespace[
        "_NATIVE_PEEK_NAMED_PIPE"
        if fault_name == "peek"
        else "_NATIVE_WAIT_FOR_SINGLE_OBJECT"
    ] = fault
    try:
        with pytest.raises(OSError, match="injected"):
            run(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=str(tmp_path),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=10,
                check=False,
            )
        assert len(probes) == 1
        assert _winapi.WaitForSingleObject(probes[0], 1000) == _winapi.WAIT_OBJECT_0
    finally:
        namespace["_NATIVE_CREATE_PROCESS"] = original_create
        namespace["_NATIVE_PEEK_NAMED_PIPE"] = original_peek
        namespace["_NATIVE_WAIT_FOR_SINGLE_OBJECT"] = original_wait
        for handle in probes:
            _winapi.CloseHandle(handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows GUI stdin contract")
def test_windows_native_runner_supplies_eof_stdin_without_console(
    tmp_path: Path,
) -> None:
    run = _sealed_native_run(tmp_path)
    namespace = run.__globals__
    original = namespace["_NATIVE_GET_STD_HANDLE"]
    namespace["_NATIVE_GET_STD_HANDLE"] = lambda _kind: None
    try:
        completed = run(
            [
                sys.executable,
                "-c",
                "import sys; print(len(sys.stdin.buffer.read()))",
            ],
            cwd=str(tmp_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert completed.stdout.strip() == "0"
    finally:
        namespace["_NATIVE_GET_STD_HANDLE"] = original


def test_registry_refuses_contradictory_hashes_for_one_source_file(
    tmp_path: Path,
) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    subject = dataclasses.replace(
        subject,
        output_digests_source_sha256=_sha("contradictory-source"),
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="contradictory authenticated digests",
    ):
        registry.register(
            subject,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )
    assert module.CALLS == []


def test_registry_refuses_function_defaults_even_when_source_matches(
    tmp_path: Path,
) -> None:
    source = (
        "def invoke(value='ambient'):\n"
        "    return value\n"
        "\n"
        "def output_digests(value):\n"
        "    return ('a' * 64,)\n"
    )
    module, _path, source_sha = _write_adapter(tmp_path, source=source)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="positional defaults are not admissible",
    ):
        registry.register(
            subject,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )


def test_registry_refuses_reregistration_with_different_function_objects(
    tmp_path: Path,
) -> None:
    module, path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    registry = ProviderExecutableObjectRegistry(tmp_path)
    admission = registry.register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )

    spec = importlib.util.spec_from_file_location(module.__name__, path)
    assert spec is not None and spec.loader is not None
    replacement_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replacement_module)

    with pytest.raises(
        ProviderExecutableObjectRegistryBindingError,
        match="already bound to different executable objects",
    ):
        registry.register(
            subject,
            invoke=replacement_module.invoke,
            output_digests=replacement_module.output_digests,
        )
    assert admission == registry.verify_registered(subject)


def test_admission_deserialization_refuses_authority_escalation(
    tmp_path: Path,
) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )
    admission = ProviderExecutableObjectRegistry(tmp_path).register(
        subject,
        invoke=module.invoke,
        output_digests=module.output_digests,
    )
    payload = admission.to_dict()
    payload["provider_execution_allowed"] = True

    with pytest.raises(
        ProviderExecutableObjectRegistryShapeError,
        match="escalated claim: provider_execution_allowed",
    ):
        ProviderExecutableObjectAdmissionReceipt.from_dict(payload)


def test_registry_refuses_subclassed_pre_admission(tmp_path: Path) -> None:
    module, _path, source_sha = _write_adapter(tmp_path)
    subject = _pre_admission(
        module_name=module.__name__,
        source_sha256=source_sha,
    )

    class SubclassedPreAdmission(ProviderExecutablePreAdmissionReceipt):
        pass

    subclassed = SubclassedPreAdmission(**dataclasses.asdict(subject))
    with pytest.raises(
        ProviderExecutableObjectRegistryShapeError,
        match="pre_admission must be exact",
    ):
        ProviderExecutableObjectRegistry(tmp_path).register(
            subclassed,
            invoke=module.invoke,
            output_digests=module.output_digests,
        )
