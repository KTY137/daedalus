"""Evidence-based accelerator inventory for optional RTX compute lanes.

This module deliberately separates three questions that are often blurred:

* is NVIDIA hardware visible to this process?
* is a software backend installed and actually CUDA-capable?
* is that backend applicable to the Daedalus operation being discussed?

Finding a GPU or a DLL never implies semantic capability.  In particular,
DLSS accepts renderer-specific image resources; it is not exposed here as a
general tensor or code model.  The status rows are facts and explicit gates,
not performance claims.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


RTX_OLLAMA_ENV = "DAEDALUS_RTX_OLLAMA_HOST"
RTX_TOKEN_ENV = "DAEDALUS_RTX_OLLAMA_TOKEN"
# Pre-doc-alignment name; kept as fallback so existing deployments stay authorized.
RTX_TOKEN_FALLBACK_ENV = "DAEDALUS_RTX_TOKEN"
# ssh target for probing the bench's COMPUTE units rather than only its Ollama
# endpoint. The room skill already carries the same address under
# ROOM_BENCH_SSH, so that is honoured as a fallback instead of asking an
# operator to configure the same host twice under two names.
RTX_SSH_ENV = "DAEDALUS_RTX_SSH"
RTX_SSH_FALLBACK_ENV = "ROOM_BENCH_SSH"
NVOF_SDK_ENV = "DAEDALUS_NVOF_SDK"


@dataclass(frozen=True)
class ComputeLane:
    id: str
    label: str
    state: str
    applicable_to: tuple[str, ...]
    evidence: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _parse_nvidia_csv(line: str) -> dict[str, Any]:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 4:
        raise ValueError("unexpected nvidia-smi output")
    memory_text = parts[2].split()[0]
    try:
        memory_mib: int | None = int(memory_text)
    except ValueError:
        memory_mib = None
    return {
        "name": parts[0],
        "compute_capability": parts[1],
        "memory_mib": memory_mib,
        "driver_version": parts[3],
    }


@lru_cache(maxsize=1)
def nvidia_hardware_status() -> dict[str, Any]:
    """Return bounded, read-only NVIDIA hardware evidence from ``nvidia-smi``."""
    command = shutil.which("nvidia-smi")
    if not command:
        return {
            "available": False,
            "command": "",
            "devices": [],
            "error": "nvidia-smi not found on PATH",
        }
    try:
        result = subprocess.run(
            [
                command,
                "--query-gpu=name,compute_cap,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "available": False,
            "command": command,
            "devices": [],
            "error": str(exc),
        }
    if result.returncode != 0:
        return {
            "available": False,
            "command": command,
            "devices": [],
            "error": (result.stderr or result.stdout or "nvidia-smi failed").strip(),
        }
    devices: list[dict[str, Any]] = []
    try:
        for line in result.stdout.splitlines():
            if line.strip():
                devices.append(_parse_nvidia_csv(line))
    except ValueError as exc:
        return {
            "available": False,
            "command": command,
            "devices": [],
            "error": str(exc),
        }
    return {
        "available": bool(devices),
        "command": command,
        "devices": devices,
        "error": "" if devices else "nvidia-smi returned no devices",
    }


_DEEP_PROBE = r"""
import importlib
import json

out = {}
for name in ("torch", "cupy", "warp", "cuvs", "cugraph", "newton"):
    row = {"installed": False, "cuda_ready": False, "detail": ""}
    try:
        mod = importlib.import_module(name)
        row["installed"] = True
        row["detail"] = str(getattr(mod, "__version__", "installed"))
        if name == "torch":
            row["cuda_ready"] = bool(mod.cuda.is_available())
            row["detail"] += " / cuda=" + str(getattr(mod.version, "cuda", None))
        elif name == "cupy":
            row["cuda_ready"] = int(mod.cuda.runtime.getDeviceCount()) > 0
        elif name == "warp":
            mod.init()
            row["cuda_ready"] = bool(mod.get_cuda_devices())
        elif name in ("cuvs", "cugraph", "newton"):
            # These lack a cheap device-touching check here; import success
            # alone must not claim CUDA readiness (module docstring standard).
            row["cuda_ready"] = None
            row["detail"] += " / import_only: no device kernel smoke"
    except Exception as exc:
        row["detail"] = type(exc).__name__ + ": " + str(exc)
    out[name] = row
print(json.dumps(out))
"""


@lru_cache(maxsize=1)
def deep_framework_status() -> dict[str, dict[str, Any]]:
    """Probe optional Python compute runtimes in an isolated, bounded process."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _DEEP_PROBE],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"probe": {"installed": False, "cuda_ready": False, "detail": str(exc)}}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "framework probe failed").strip()
        return {"probe": {"installed": False, "cuda_ready": False, "detail": detail}}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {
            "probe": {
                "installed": False,
                "cuda_ready": False,
                "detail": f"invalid probe output: {exc}",
            }
        }
    return payload if isinstance(payload, dict) else {}


def _redacted_endpoint(raw: str) -> str:
    """Remove credentials, path, query and fragment before surfacing an endpoint."""
    parsed = urllib.parse.urlsplit(raw)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit((parsed.scheme, f"{host}{port}", "", "", ""))


def _remote_rtx_status(*, probe: bool) -> dict[str, Any]:
    raw = os.environ.get(RTX_OLLAMA_ENV, "").strip()
    if not raw:
        return {
            "configured": False,
            "available": False,
            "endpoint": "",
            "models": [],
            "error": f"{RTX_OLLAMA_ENV} is not set",
            "warning": "",
        }
    endpoint = _redacted_endpoint(raw)
    parsed = urllib.parse.urlsplit(raw)
    warning = ""
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        warning = "remote endpoint uses plaintext HTTP; prefer a private tunnel or TLS"
    if not probe:
        return {
            "configured": True,
            "available": None,
            "endpoint": endpoint,
            "models": [],
            "error": "",
            "warning": warning,
        }
    request = urllib.request.Request(raw.rstrip("/") + "/api/tags")
    token = (
        os.environ.get(RTX_TOKEN_ENV, "").strip()
        or os.environ.get(RTX_TOKEN_FALLBACK_ENV, "").strip()
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = sorted(
            str(row.get("model") or row.get("name"))
            for row in payload.get("models", [])
            if row.get("model") or row.get("name")
        )
        return {
            "configured": True,
            "available": True,
            "endpoint": endpoint,
            "models": models,
            "error": "",
            "warning": warning,
        }
    except (
        urllib.error.URLError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return {
            "configured": True,
            "available": False,
            "endpoint": endpoint,
            "models": [],
            "error": str(exc),
            "warning": warning,
        }


_CC_FLOORS: dict[str, tuple[int, int]] = {
    # Tensor cores arrived with Volta. Below this there is no MMA unit at all,
    # so "install torch and it will be fast" is false by construction.
    "tensor_cores": (7, 0),
    # RT cores arrived with Turing. Everything in the RT-accelerated
    # neighbour-search literature (RTNN, RT-kNNS, JUNO) needs these; on Pascal
    # the papers do not apply, they are not merely unimplemented.
    "rt_cores": (7, 5),
}


def capability_lanes(compute_capability: str) -> dict[str, Any]:
    """Which accelerator classes a device can host AT ALL, from its CC.

    Exists because this module answered hardware questions about the machine it
    RUNS on while the capable card lives on the bench. The local MX330 reports
    CC 6.1 -- Pascal, which has neither tensor cores nor RT cores -- so every
    lane read "missing" when the honest word was "impossible here". Meanwhile
    the bench's RTX 5080 reports CC 12.0 and can host all of them.

    "missing" invites someone to go install a library. "impossible" tells them
    to stop. Reporting the first when the second is true is how an afternoon
    gets spent against the wrong silicon.
    """
    try:
        major, _, minor = (compute_capability or "").partition(".")
        cc = (int(major), int(minor or 0))
    except (TypeError, ValueError):
        return {"compute_capability": compute_capability or "", "known": False,
                "supports": {}, "note": "unparseable compute capability"}
    supports = {name: cc >= floor for name, floor in _CC_FLOORS.items()}
    return {"compute_capability": compute_capability, "known": True,
            "supports": supports,
            "note": ("architecture supports " +
                     ", ".join(sorted(k for k, v in supports.items() if v))
                     if any(supports.values())
                     else "pre-Volta: no tensor cores, no RT cores")}


def _remote_compute_status(*, probe: bool) -> dict[str, Any]:
    """The bench's COMPUTE units, not just its Ollama endpoint.

    ``_remote_rtx_status`` asks the bench "are you serving models". That is a
    different question from "what can this card do", and answering the first
    while reporting on the second is what made the local report misleading.

    Deliberately OPT-IN and off by default: this needs ssh, which is a wider
    trust surface than an unauthenticated HTTP GET, and a readiness report has
    no business opening one unless an operator asked for it. Unconfigured
    returns ``available: None`` -- unknown, never ``False``, because "we did not
    look" and "it is not there" are the two answers this repo most insists on
    keeping apart.
    """
    target = (os.environ.get(RTX_SSH_ENV, "").strip()
              or os.environ.get(RTX_SSH_FALLBACK_ENV, "").strip())
    if not target:
        return {"configured": False, "available": None, "target": "",
                "devices": [], "lanes": {}, "error": "",
                "hint": f"set {RTX_SSH_ENV}=user@host to probe the bench's GPU"}
    if not probe:
        return {"configured": True, "available": None, "target": target,
                "devices": [], "lanes": {}, "error": "",
                "hint": "pass --probe-remote to actually query it"}
    if shutil.which("ssh") is None:
        return {"configured": True, "available": None, "target": target,
                "devices": [], "lanes": {}, "error": "ssh not on PATH",
                "hint": ""}
    query = ("nvidia-smi --query-gpu=name,compute_cap,memory.total,driver_version "
             "--format=csv,noheader")
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, query],
            capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"configured": True, "available": False, "target": target,
                "devices": [], "lanes": {},
                "error": f"{type(exc).__name__}: {exc}", "hint": ""}
    if result.returncode != 0:
        return {"configured": True, "available": False, "target": target,
                "devices": [], "lanes": {},
                "error": (result.stderr or result.stdout or "ssh failed").strip()[:400],
                "hint": ""}

    devices: list[dict[str, Any]] = []
    for line in (result.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        name, cc, mem, driver = parts[0], parts[1], parts[2], parts[3]
        devices.append({
            "name": name, "compute_capability": cc,
            "memory_mib": int(mem.split()[0]) if mem.split()[:1] and
            mem.split()[0].isdigit() else None,
            "driver_version": driver,
            "capability": capability_lanes(cc),
        })
    lanes: dict[str, Any] = {}
    for dev in devices:
        for k, v in (dev["capability"].get("supports") or {}).items():
            lanes[k] = lanes.get(k, False) or bool(v)
    return {"configured": True, "available": bool(devices), "target": target,
            "devices": devices, "lanes": lanes,
            "error": "" if devices else "nvidia-smi returned no devices",
            "hint": ""}


def _framework_rows(*, deep: bool) -> dict[str, dict[str, Any]]:
    names = ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
    if deep:
        rows = deep_framework_status()
        return {
            name: {
                "installed": bool(rows.get(name, {}).get("installed")),
                # None means "installed but unverified"; only real device
                # checks may report True, so preserve the tri-state.
                "cuda_ready": (
                    None
                    if rows.get(name, {}).get("cuda_ready") is None
                    else bool(rows.get(name, {}).get("cuda_ready"))
                ),
                "detail": str(rows.get(name, {}).get("detail", "")),
                "probed": True,
            }
            for name in names
        }
    return {
        name: {
            "installed": _has_module(name),
            "cuda_ready": None,
            "detail": "deep probe not requested",
            "probed": False,
        }
        for name in names
    }


def accelerator_status(*, deep: bool = False, probe_remote: bool = False) -> dict[str, Any]:
    """Describe local and remote accelerator readiness without capability inflation."""
    hardware = nvidia_hardware_status()
    frameworks = _framework_rows(deep=deep)
    gpu = bool(hardware["available"])

    # THE LOCAL BRANCH HAS TO ASK THE SAME QUESTION THE REMOTE ONE DOES.
    # ``hardware["available"]`` only means nvidia-smi found a device -- it says
    # nothing about what that device can host. This machine's MX330 reports
    # compute capability 6.1: Pascal, which has no tensor cores at all. torch
    # installs there and reports cuda_ready, so `gpu and cuda_ready` was True
    # for a lane the silicon cannot run.
    #
    # capability_lanes() was written today to fix exactly this and was wired
    # into _remote_compute_status() only -- not back into the local branch that
    # motivated it. Found by Aristaeus surveying the tree afterwards, which is
    # the correct outcome and an uncomfortable one: the docstring of the
    # function names this scenario as its reason to exist.
    #
    # The distinction that matters is 'missing' versus 'impossible here'. The
    # first invites an operator to go install something; the second tells them
    # to stop. Reporting the first when the second is true is how an afternoon
    # gets spent against the wrong silicon.
    local_caps = [capability_lanes(str(dev.get("compute_capability") or ""))
                  for dev in (hardware.get("devices") or [])]
    hosts_tensor_cores = any(
        cap.get("supports", {}).get("tensor_cores") for cap in local_caps)
    architecturally_incapable = gpu and local_caps and not hosts_tensor_cores

    tensor_ready = gpu and hosts_tensor_cores and any(
        frameworks[name]["cuda_ready"] is True for name in ("torch", "cupy")
    )
    def _unverified(name: str) -> bool:
        # installed with cuda_ready None: no device check ran (shallow mode,
        # or a deep import-only probe) -> the lane may not claim readiness.
        return bool(
            frameworks[name]["installed"] and frameworks[name]["cuda_ready"] is None
        )

    tensor_unverified = gpu and any(_unverified(name) for name in ("torch", "cupy"))
    tensor_missing = []
    if not gpu:
        tensor_missing.append("NVIDIA CUDA device")
    elif architecturally_incapable:
        # Named, not silently folded into the runtime line below: no install
        # fixes this, and saying "CUDA-capable PyTorch" here would send someone
        # to pip for a card that predates the hardware entirely.
        names = ", ".join(sorted({str(d.get("name") or "?")
                                  for d in (hardware.get("devices") or [])}))
        tensor_missing.append(
            f"tensor cores (this device is pre-Volta: {names}, "
            f"compute capability "
            f"{', '.join(sorted({c.get('compute_capability', '?') for c in local_caps}))}"
            f") -- not installable, the silicon does not have them")
    if not tensor_ready and not architecturally_incapable:
        tensor_missing.append("CUDA-capable PyTorch or CuPy runtime")

    graph_ready = gpu and (
        frameworks["cuvs"]["cuda_ready"] is True
        or frameworks["cugraph"]["cuda_ready"] is True
    )
    graph_unverified = gpu and (_unverified("cuvs") or _unverified("cugraph"))
    warp_ready = gpu and frameworks["warp"]["cuda_ready"] is True
    warp_unverified = gpu and _unverified("warp")
    newton_ready = warp_ready and frameworks["newton"]["cuda_ready"] is True
    newton_unverified = (
        gpu
        and frameworks["warp"]["installed"]
        and (warp_ready or _unverified("warp"))
        and _unverified("newton")
    )

    nvof_path = os.environ.get(NVOF_SDK_ENV, "").strip()
    nvof_configured = bool(nvof_path and Path(nvof_path).exists())

    lanes = (
        ComputeLane(
            id="tensor_inference",
            label="CUDA tensor inference",
            # "unsupported" before "missing": the vocabulary already carries the
            # right word (dlss uses it below), and the difference is the whole
            # point of the capability check above. A pre-Volta card is not
            # missing a library somebody could install -- it is missing silicon.
            state=("ready" if tensor_ready
                   else "unsupported" if architecturally_incapable
                   else "unverified" if tensor_unverified
                   else "missing"),
            applicable_to=("embedding batches", "learned DSS residuals", "rerankers"),
            evidence=tuple(
                name for name in ("torch", "cupy")
                if frameworks[name]["cuda_ready"] is True
            ),
            missing=tuple(tensor_missing),
        ),
        ComputeLane(
            id="sparse_graph",
            label="CUDA sparse graph / ANN",
            state="ready" if graph_ready else ("unverified" if graph_unverified else "missing"),
            applicable_to=("large-forest graph propagation", "vector nearest-neighbour search"),
            evidence=tuple(
                name for name in ("cuvs", "cugraph")
                if frameworks[name]["cuda_ready"] is True
            ),
            missing=() if graph_ready else ("CUDA-capable cuVS or cuGraph runtime",),
        ),
        ComputeLane(
            id="warp_kernels",
            label="NVIDIA Warp differentiable kernels",
            state="ready" if warp_ready else ("unverified" if warp_unverified else "missing"),
            applicable_to=(
                "experimental differentiable graph/layout kernels",
                "domain physics evaluators",
            ),
            evidence=("warp",) if warp_ready else (),
            missing=() if warp_ready else ("CUDA-capable warp-lang runtime",),
            warning="experimental for AgentOS; no semantic claim",
        ),
        ComputeLane(
            id="newton_physics",
            label="Newton / Warp physics",
            state="ready" if newton_ready else ("unverified" if newton_unverified else "missing"),
            applicable_to=(
                "physics-domain task evaluation",
                "synthetic physical training data",
                "experimental forest visualization",
            ),
            evidence=("newton", "warp") if newton_ready else (),
            missing=() if newton_ready else ("Newton plus CUDA-capable Warp",),
            warning="not a code-retrieval or semantic-reasoning primitive",
        ),
        ComputeLane(
            id="nvidia_optical_flow",
            label="NVIDIA Optical Flow SDK",
            state="configured" if nvof_configured else "missing",
            applicable_to=("image-frame correspondence experiments",),
            evidence=(str(Path(nvof_path).resolve()),) if nvof_configured else (),
            missing=() if nvof_configured else (NVOF_SDK_ENV,),
            warning="pixel/image API; code-history transfer requires an evaluated encoding experiment",
        ),
        ComputeLane(
            id="dlss",
            label="NVIDIA DLSS",
            state="unsupported",
            applicable_to=("renderer image reconstruction only",),
            missing=("general tensor API", "code-domain model weights/API"),
            warning="DLSS is inspiration for DSS, not an executable Daedalus backend",
        ),
    )

    return {
        "schema": "daedalus-accelerators/1",
        "hardware": hardware,
        "frameworks": frameworks,
        "remote_rtx_ollama": _remote_rtx_status(probe=probe_remote),
        # The card that can actually host these lanes is the bench's, not this
        # machine's. Reporting only local silicon is how "missing" got read as
        # "go install it" when the local CC 6.1 made every lane impossible.
        "remote_compute": _remote_compute_status(probe=probe_remote),
        "lanes": [lane.to_dict() for lane in lanes],
        "claims": {
            "hardware_visible_is_not_backend_ready": True,
            "backend_ready_is_not_semantic_validity": True,
            "dlss_general_tensor_backend": False,
        },
    }
