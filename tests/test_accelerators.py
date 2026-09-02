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

    rows = json.loads(stdout.getvalue())
    for name in ("cuvs", "cugraph", "newton"):
        assert rows[name]["installed"] is True
        assert rows[name]["cuda_ready"] is None
        assert "import_only: no device kernel smoke" in rows[name]["detail"]
    assert rows["torch"]["installed"] is False
    assert rows["torch"]["cuda_ready"] is False


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

