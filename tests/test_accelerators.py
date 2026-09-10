from __future__ import annotations

import json
from unittest import mock

from daedalus.foundation import accelerators


def _hardware(available: bool = True) -> dict:
    return {
        "available": available,
        "command": "nvidia-smi",
        "devices": (
            [{
                "name": "Example RTX",
                "compute_capability": "8.9",
                "memory_mib": 24576,
                "driver_version": "999.0",
            }]
            if available else []
        ),
        "error": "" if available else "missing",
    }


def _frameworks(cuda: tuple[str, ...] = ()) -> dict:
    return {
        name: {
            "installed": name in cuda,
            "cuda_ready": name in cuda,
            "detail": "",
            "probed": True,
        }
        for name in ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
    }


def test_dlss_is_never_reported_as_general_compute_backend() -> None:
    with mock.patch.object(accelerators, "nvidia_hardware_status", return_value=_hardware()), \
            mock.patch.object(
                accelerators, "_framework_rows", return_value=_frameworks(("torch",))
            ), \
            mock.patch.dict("os.environ", {}, clear=True):
        payload = accelerators.accelerator_status(deep=True)

    lanes = {row["id"]: row for row in payload["lanes"]}
    assert lanes["tensor_inference"]["state"] == "ready"
    assert lanes["dlss"]["state"] == "unsupported"
    assert payload["claims"]["dlss_general_tensor_backend"] is False


def test_physics_lane_requires_both_warp_and_newton() -> None:
    with mock.patch.object(accelerators, "nvidia_hardware_status", return_value=_hardware()), \
            mock.patch.object(
                accelerators, "_framework_rows", return_value=_frameworks(("warp",))
            ), \
            mock.patch.dict("os.environ", {}, clear=True):
        payload = accelerators.accelerator_status(deep=True)

    lanes = {row["id"]: row for row in payload["lanes"]}
    assert lanes["warp_kernels"]["state"] == "ready"
    assert lanes["newton_physics"]["state"] == "missing"


def test_remote_status_redacts_credentials_and_token() -> None:
    env = {
        accelerators.RTX_OLLAMA_ENV: "https://user:password@example.test:11434/private?q=secret",
        accelerators.RTX_TOKEN_ENV: "bearer-secret",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        status = accelerators._remote_rtx_status(probe=False)

    encoded = json.dumps(status)
    assert status["configured"] is True
    assert status["available"] is None
    assert status["endpoint"] == "https://example.test:11434"
    assert "password" not in encoded
    assert "bearer-secret" not in encoded
    assert "private" not in encoded
    assert "secret" not in encoded


def test_remote_probe_uses_documented_token_env() -> None:
    env = {
        accelerators.RTX_OLLAMA_ENV: "https://example.test:11434",
        accelerators.RTX_TOKEN_ENV: "documented-token",
    }
    captured: dict = {}

    def _fake_urlopen(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")
        raise OSError("stop before network")

    with mock.patch.dict("os.environ", env, clear=True), \
            mock.patch.object(accelerators.urllib.request, "urlopen", _fake_urlopen):
        status = accelerators._remote_rtx_status(probe=True)

    assert accelerators.RTX_TOKEN_ENV == "DAEDALUS_RTX_OLLAMA_TOKEN"
    assert captured["auth"] == "Bearer documented-token"
    assert "documented-token" not in json.dumps(status)


def test_remote_probe_falls_back_to_legacy_token_env() -> None:
    env = {
        accelerators.RTX_OLLAMA_ENV: "https://example.test:11434",
        accelerators.RTX_TOKEN_FALLBACK_ENV: "legacy-token",
    }
    captured: dict = {}

    def _fake_urlopen(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")
        raise OSError("stop before network")

    with mock.patch.dict("os.environ", env, clear=True), \
            mock.patch.object(accelerators.urllib.request, "urlopen", _fake_urlopen):
        status = accelerators._remote_rtx_status(probe=True)

    assert accelerators.RTX_TOKEN_FALLBACK_ENV == "DAEDALUS_RTX_TOKEN"
    assert captured["auth"] == "Bearer legacy-token"
    assert "legacy-token" not in json.dumps(status)


def test_remote_probe_prefers_documented_token_over_legacy() -> None:
    env = {
        accelerators.RTX_OLLAMA_ENV: "https://example.test:11434",
        accelerators.RTX_TOKEN_ENV: "documented-token",
        accelerators.RTX_TOKEN_FALLBACK_ENV: "legacy-token",
    }
    captured: dict = {}

    def _fake_urlopen(request, timeout=None):
        captured["auth"] = request.get_header("Authorization")
        raise OSError("stop before network")

    with mock.patch.dict("os.environ", env, clear=True), \
            mock.patch.object(accelerators.urllib.request, "urlopen", _fake_urlopen):
        accelerators._remote_rtx_status(probe=True)

    assert captured["auth"] == "Bearer documented-token"


def test_remote_status_redacts_legacy_fallback_token() -> None:
    env = {
        accelerators.RTX_OLLAMA_ENV: "https://user:password@example.test:11434/private?q=secret",
        accelerators.RTX_TOKEN_FALLBACK_ENV: "bearer-secret",
    }
    with mock.patch.dict("os.environ", env, clear=True):
        status = accelerators._remote_rtx_status(probe=False)

    encoded = json.dumps(status)
    assert status["endpoint"] == "https://example.test:11434"
    assert "bearer-secret" not in encoded
    assert "password" not in encoded


def test_shallow_probe_does_not_claim_framework_readiness() -> None:
    rows = {
        name: {
            "installed": True,
            "cuda_ready": None,
            "detail": "deep probe not requested",
            "probed": False,
        }
        for name in ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
    }
    with mock.patch.object(accelerators, "nvidia_hardware_status", return_value=_hardware()), \
            mock.patch.object(accelerators, "_framework_rows", return_value=rows), \
            mock.patch.dict("os.environ", {}, clear=True):
        payload = accelerators.accelerator_status(deep=False)

    lanes = {row["id"]: row for row in payload["lanes"]}
    assert lanes["tensor_inference"]["state"] == "unverified"
    assert lanes["sparse_graph"]["state"] == "unverified"
    assert lanes["warp_kernels"]["state"] == "unverified"


def test_deep_probe_import_only_yields_unverified_not_ready() -> None:
    """Bare-import success (cuvs/cugraph/newton) must not claim cuda_ready."""
    import contextlib
    import io
    import types

    def _fake_import(name: str):
        if name in ("cuvs", "cugraph", "newton"):
            mod = types.SimpleNamespace(__version__="9.9")
            return mod
        raise ImportError(f"{name} absent")

    stdout = io.StringIO()
    with mock.patch("importlib.import_module", _fake_import), \
            contextlib.redirect_stdout(stdout):
        exec(accelerators._DEEP_PROBE, {})  # noqa: S102 - probe source under test

    rows = accelerators._decode_deep_probe_output(stdout.getvalue(), "")
    for name in ("cuvs", "cugraph", "newton"):
        assert rows[name]["installed"] is True
        assert rows[name]["cuda_ready"] is None
        assert "import_only: no device kernel smoke" in rows[name]["detail"]
    assert rows["torch"]["installed"] is False
    assert rows["torch"]["cuda_ready"] is False


def test_deep_probe_accepts_noisy_stdout_and_retains_diagnostics() -> None:
    probe_rows = {
        name: {
            "installed": name in ("torch", "warp"),
            "cuda_ready": name in ("torch", "warp"),
            "detail": "measured",
        }
        for name in ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
    }
    completed = mock.Mock(
        returncode=0,
        stdout=(
            "Warp 1.17.0 initialized on cuda:0\n"
            f"{accelerators._DEEP_PROBE_SENTINEL}{json.dumps(probe_rows)}\n"
            "runtime shutdown note\n"
        ),
        stderr="CUDA_PATH could not be detected\n",
    )
    with mock.patch.object(accelerators.subprocess, "run", return_value=completed):
        rows = accelerators.deep_framework_status.__wrapped__()

    assert rows["torch"]["installed"] is True
    assert rows["warp"]["cuda_ready"] is True
    assert rows["cupy"]["installed"] is False
    assert rows["_diagnostics"] == {
        "stdout": "Warp 1.17.0 initialized on cuda:0\nruntime shutdown note",
        "stderr": "CUDA_PATH could not be detected",
    }


def test_failed_deep_probe_rows_are_unprobed_with_shallow_presence_evidence() -> None:
    failure = {
        "probe": {
            "installed": False,
            "cuda_ready": None,
            "detail": "invalid probe output: missing sentinel",
            "probed": False,
        }
    }
    with mock.patch.object(accelerators, "deep_framework_status", return_value=failure), \
            mock.patch.object(
                accelerators,
                "_has_module",
                side_effect=lambda name: name in ("torch", "newton"),
            ):
        rows = accelerators._framework_rows(deep=True)

    assert rows["torch"]["installed"] is True
    assert rows["newton"]["installed"] is True
    assert rows["cupy"]["installed"] is False
    assert all(row["probed"] is False for row in rows.values())
    assert all(row["cuda_ready"] is None for row in rows.values())
    assert all("missing sentinel" in row["detail"] for row in rows.values())


def test_deep_rows_preserve_unverified_tristate() -> None:
    probe_rows = {
        name: {
            "installed": name in ("torch", "cuvs", "newton"),
            "cuda_ready": (
                None if name in ("cuvs", "newton")
                else (name == "torch")
            ),
            "detail": "",
        }
        for name in ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
    }
    with mock.patch.object(accelerators, "deep_framework_status", return_value=probe_rows):
        rows = accelerators._framework_rows(deep=True)

    assert rows["torch"]["cuda_ready"] is True
    assert rows["cupy"]["cuda_ready"] is False
    assert rows["cuvs"]["cuda_ready"] is None
    assert rows["newton"]["cuda_ready"] is None
    assert all(row["probed"] for row in rows.values())


def test_deep_import_only_lanes_cap_at_unverified() -> None:
    frameworks = _frameworks(("warp",))
    for name in ("cuvs", "cugraph", "newton"):
        frameworks[name]["installed"] = True
        frameworks[name]["cuda_ready"] = None
        frameworks[name]["detail"] = "9.9 / import_only: no device kernel smoke"
    with mock.patch.object(accelerators, "nvidia_hardware_status", return_value=_hardware()), \
            mock.patch.object(accelerators, "_framework_rows", return_value=frameworks), \
            mock.patch.dict("os.environ", {}, clear=True):
        payload = accelerators.accelerator_status(deep=True)

    lanes = {row["id"]: row for row in payload["lanes"]}
    assert lanes["sparse_graph"]["state"] == "unverified"
    assert not lanes["sparse_graph"]["evidence"]
    assert lanes["warp_kernels"]["state"] == "ready"
    assert lanes["newton_physics"]["state"] == "unverified"
    assert lanes["newton_physics"]["missing"] == (
        "Newton device execution was not probed",
    )


def test_cli_json_exposes_successful_probe_noise_as_bounded_diagnostics(
    capsys,
) -> None:
    from daedalus.interfaces.cli import entry as cli_entry

    oversized_stdout = "x" * (accelerators._DEEP_PROBE_DIAGNOSTIC_LIMIT + 17)
    probe_rows = _frameworks(("torch", "warp"))
    probe_rows["_diagnostics"] = {
        "stdout": oversized_stdout,
        "stderr": "CUDA_PATH fallback used",
    }
    with mock.patch.object(
        accelerators, "deep_framework_status", return_value=probe_rows
    ), mock.patch.object(
        accelerators, "nvidia_hardware_status", return_value=_hardware()
    ), mock.patch.dict("os.environ", {}, clear=True):
        cli_entry._accelerators(["--deep", "--json"])

    payload = json.loads(capsys.readouterr().out)
    diagnostics = payload["framework_probe_diagnostics"]
    assert diagnostics["requested"] is True
    assert diagnostics["transport_outcome"] == "decoded"
    assert diagnostics["stdout"] == (
        "x" * accelerators._DEEP_PROBE_DIAGNOSTIC_LIMIT
        + " ... [17 chars omitted]"
    )
    assert diagnostics["stderr"] == "CUDA_PATH fallback used"
    assert diagnostics["failure"] == ""
    assert (
        diagnostics["retained_char_limit"]
        == accelerators._DEEP_PROBE_DIAGNOSTIC_LIMIT
    )
    assert set(payload["frameworks"]) == {
        "torch",
        "cupy",
        "warp",
        "cuvs",
        "cugraph",
        "newton",
    }
    assert {row["id"] for row in payload["lanes"]} == {
        "tensor_inference",
        "sparse_graph",
        "warp_kernels",
        "newton_physics",
        "nvidia_optical_flow",
        "dlss",
    }
    assert "state" not in diagnostics
    assert "ready" not in diagnostics


def test_accelerator_status_exposes_top_level_probe_failure_diagnostics() -> None:
    failure = accelerators._probe_failure(
        "child process failed",
        stdout="runtime banner",
        stderr="driver warning",
    )
    with mock.patch.object(
        accelerators, "deep_framework_status", return_value=failure
    ), mock.patch.object(
        accelerators, "nvidia_hardware_status", return_value=_hardware()
    ), mock.patch.object(
        accelerators,
        "_has_module",
        side_effect=lambda name: name in ("torch", "newton"),
    ), mock.patch.dict("os.environ", {}, clear=True):
        payload = accelerators.accelerator_status(deep=True)

    diagnostics = payload["framework_probe_diagnostics"]
    assert diagnostics["requested"] is True
    assert diagnostics["transport_outcome"] == "failed"
    assert diagnostics["stdout"] == "runtime banner"
    assert diagnostics["stderr"] == "driver warning"
    assert "child process failed" in diagnostics["failure"]
    assert (
        diagnostics["retained_char_limit"]
        == accelerators._DEEP_PROBE_DIAGNOSTIC_LIMIT
    )
    assert len(payload["frameworks"]) == 6
    assert all(row["probed"] is False for row in payload["frameworks"].values())
    assert all(row["cuda_ready"] is None for row in payload["frameworks"].values())
    assert all(row["state"] != "ready" for row in payload["lanes"])



# --- probe interpreter selection -------------------------------------------
#
# Regression cover for the desktop symptom of 2026-09-10: the capability panel
# of the packaged app reported torch/cupy/warp/cuvs/cugraph/newton as "nicht
# installiert" because the deep probe shelled out to ``sys.executable -c``,
# and in a frozen build ``sys.executable`` is the packaged application, not an
# interpreter.  MEASURED against the shipped generation: exit status 2 with
# ``unrecognized arguments: -c``, after a full second sidecar bootstrap.


def test_source_checkout_probe_uses_the_running_interpreter() -> None:
    import sys as _sys

    with mock.patch.dict("os.environ", {}, clear=True), \
            mock.patch.object(accelerators.sys, "frozen", False, create=True):
        interpreter, refusal = accelerators.probe_interpreter()

    assert refusal == ""
    assert interpreter == _sys.executable


def test_frozen_application_is_refused_and_never_executed() -> None:
    with mock.patch.dict("os.environ", {}, clear=True), \
            mock.patch.object(accelerators.sys, "frozen", True, create=True), \
            mock.patch.object(
                accelerators.sys, "executable", r"C:\app\daedalus-web-api.exe"
            ), \
            mock.patch.object(accelerators.subprocess, "run") as run:
        rows = accelerators.deep_framework_status.__wrapped__()

    # The decisive assertion: the frozen application is NOT spawned. Spawning
    # it cost a second backend bootstrap and produced an argparse usage error
    # that was then read as "no accelerator is installed".
    run.assert_not_called()
    failure = rows["probe"]
    assert failure["probed"] is False
    assert failure["installed"] is False
    assert failure["cuda_ready"] is None
    assert "daedalus-web-api.exe" in failure["detail"]
    assert accelerators.ACCELERATOR_PYTHON_ENV in failure["detail"]


def test_frozen_application_probe_failure_does_not_claim_absence(
    tmp_path,
) -> None:
    """A refused probe must stay 'unprobed', never harden into 'absent'."""

    with mock.patch.dict("os.environ", {}, clear=True), \
            mock.patch.object(accelerators.sys, "frozen", True, create=True), \
            mock.patch.object(
                accelerators.sys, "executable", r"C:\app\daedalus-web-api.exe"
            ), \
            mock.patch.object(accelerators.subprocess, "run") as run, \
            mock.patch.object(accelerators, "_has_module", return_value=False):
        rows = accelerators._framework_rows(deep=True)

    run.assert_not_called()
    assert set(rows) == {"torch", "cupy", "warp", "cuvs", "cugraph", "newton"}
    for name, row in rows.items():
        assert row["probed"] is False, name
        assert row["cuda_ready"] is None, name
        assert accelerators.ACCELERATOR_PYTHON_ENV in row["detail"], name


def test_configured_interpreter_overrides_a_frozen_executable(tmp_path) -> None:
    interpreter = tmp_path / "python.exe"
    interpreter.write_bytes(b"")
    completed = mock.Mock(
        returncode=0,
        stdout=(
            accelerators._DEEP_PROBE_SENTINEL
            + json.dumps(
                {
                    name: {
                        "installed": name == "torch",
                        "cuda_ready": name == "torch",
                        "detail": "measured",
                    }
                    for name in ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
                }
            )
            + "\n"
        ),
        stderr="",
    )
    with mock.patch.dict(
        "os.environ",
        {accelerators.ACCELERATOR_PYTHON_ENV: str(interpreter)},
        clear=True,
    ), mock.patch.object(accelerators.sys, "frozen", True, create=True), \
            mock.patch.object(
                accelerators.subprocess, "run", return_value=completed
            ) as run:
        rows = accelerators.deep_framework_status.__wrapped__()

    assert run.call_args.args[0][0] == str(interpreter)
    assert run.call_args.args[0][1] == "-c"
    assert rows["torch"]["installed"] is True


def test_configured_interpreter_that_is_not_a_file_is_refused() -> None:
    missing = r"C:\nowhere\python.exe"
    with mock.patch.dict(
        "os.environ",
        {accelerators.ACCELERATOR_PYTHON_ENV: missing},
        clear=True,
    ), mock.patch.object(accelerators.subprocess, "run") as run:
        rows = accelerators.deep_framework_status.__wrapped__()

    run.assert_not_called()
    assert "is not an existing file" in rows["probe"]["detail"]
    assert accelerators.ACCELERATOR_PYTHON_ENV in rows["probe"]["detail"]


def test_status_reports_which_interpreter_answered_the_deep_probe() -> None:
    import sys as _sys

    with mock.patch.object(
        accelerators, "deep_framework_status", return_value=_frameworks(("torch",))
    ), mock.patch.object(
        accelerators, "nvidia_hardware_status", return_value=_hardware()
    ), mock.patch.dict("os.environ", {}, clear=True), \
            mock.patch.object(accelerators.sys, "frozen", False, create=True):
        payload = accelerators.accelerator_status(deep=True)

    assert payload["framework_probe_diagnostics"]["interpreter"] == _sys.executable


def test_shallow_status_names_no_interpreter_because_none_was_asked() -> None:
    with mock.patch.object(
        accelerators, "nvidia_hardware_status", return_value=_hardware()
    ), mock.patch.dict("os.environ", {}, clear=True):
        payload = accelerators.accelerator_status(deep=False)

    assert payload["framework_probe_diagnostics"]["interpreter"] == ""
    assert (
        payload["framework_probe_diagnostics"]["transport_outcome"]
        == "not_requested"
    )
