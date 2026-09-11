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
import tempfile
import time
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
# Interpreter used for the isolated deep framework probe.  It exists because
# ``sys.executable`` is a Python interpreter only in a source checkout; see
# ``probe_interpreter``.
ACCELERATOR_PYTHON_ENV = "DAEDALUS_ACCELERATOR_PYTHON"

# The optional compute runtimes this module reports on, in reporting order.
FRAMEWORK_NAMES = ("torch", "cupy", "warp", "cuvs", "cugraph", "newton")
# Of those, the ones the desktop build strips from the bundle BY NAME.  This is
# a deliberate local copy of the accelerator entries of
# ``DESKTOP_PYINSTALLER_EXCLUDES`` in ``tools/build_tauri_sidecar.py``: a
# runtime module must not import a build script (it is not shipped, and it
# reaches for the repository root).  ``tests/test_accelerators.py`` asserts the
# two lists still agree, so drift fails a test instead of producing a message
# that is wrong for some rows.
#
# cuvs and cugraph are NOT on that list, and saying they were would be a lie
# told to an operator who is already looking at a surprising panel.  They are
# invisible to a frozen backend for the other reason named in
# ``_shallow_framework_detail``: a frozen process imports from its own bundle.
DESKTOP_EXCLUDED_FRAMEWORKS = frozenset({"torch", "cupy", "warp", "newton"})


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


_DEEP_PROBE_SENTINEL = "__DAEDALUS_ACCELERATOR_PROBE_JSON_V1__:"
_DEEP_PROBE_DIAGNOSTIC_LIMIT = 4_000
# Wall-clock bound for the child. A module constant so a test can shorten it
# instead of sleeping for half a minute.
_DEEP_PROBE_TIMEOUT_SECONDS = 30.0
# How long the kill is given to land before the transport stops waiting on the
# direct child at all.
_DEEP_PROBE_KILL_GRACE_SECONDS = 5.0
# Bytes read back from each redirected stream. The child writes to a temporary
# file rather than a pipe, so a runaway writer costs disk, not the parent's
# memory -- but the parent still refuses to load an unbounded file.
_DEEP_PROBE_OUTPUT_LIMIT = 1_000_000
# Total bytes the child may WRITE before it is killed. The probe emits one JSON
# line plus whatever banners an imported runtime prints; 64 MiB is far past any
# honest answer and far short of the ~50 GiB a 30s flood would cost. See the
# measured figures in ``_run_deep_probe``.
_DEEP_PROBE_OUTPUT_CEILING = 64 * 1024 * 1024
# How often the wait loop looks at the size. At the measured flood rate this
# admits roughly 170 MiB of overshoot between polls, which is the price of not
# owning a Job object.
_DEEP_PROBE_POLL_SECONDS = 0.1

_DEEP_PROBE_TEMPLATE = r"""
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
# Start a fresh line because an imported runtime may have written an
# unterminated banner. The parent accepts exactly one sentinel record and
# keeps all other output as diagnostics.
print("\n" + __DAEDALUS_PROBE_SENTINEL__ + json.dumps(out, sort_keys=True), flush=True)
"""
_DEEP_PROBE = _DEEP_PROBE_TEMPLATE.replace(
    "__DAEDALUS_PROBE_SENTINEL__", repr(_DEEP_PROBE_SENTINEL)
)


def _bounded_probe_diagnostic(raw: str) -> str:
    text = raw.strip()
    if len(text) <= _DEEP_PROBE_DIAGNOSTIC_LIMIT:
        return text
    omitted = len(text) - _DEEP_PROBE_DIAGNOSTIC_LIMIT
    return f"{text[:_DEEP_PROBE_DIAGNOSTIC_LIMIT]} ... [{omitted} chars omitted]"


def _probe_failure(detail: str, *, stdout: str = "", stderr: str = "") -> dict[str, dict[str, Any]]:
    # The detail is bounded like the streams are. It carries text this module
    # did not write -- an OSError message, a decoder complaint -- and that text
    # is copied onto all six rows by ``_framework_rows``, so an unbounded one
    # is six unbounded ones.
    detail = _bounded_probe_diagnostic(detail)
    diagnostics: dict[str, str] = {}
    if stdout.strip():
        diagnostics["stdout"] = _bounded_probe_diagnostic(stdout)
    if stderr.strip():
        diagnostics["stderr"] = _bounded_probe_diagnostic(stderr)
    full_detail = "; ".join(
        (
            detail,
            *(f"{stream}: {message}" for stream, message in diagnostics.items()),
        )
    )
    payload = {
        "probe": {
            "installed": False,
            "cuda_ready": None,
            "detail": full_detail,
            "probed": False,
        }
    }
    if diagnostics:
        payload["_diagnostics"] = diagnostics
    return payload


def _decode_deep_probe_output(stdout: str, stderr: str) -> dict[str, dict[str, Any]]:
    records: list[str] = []
    noise: list[str] = []
    for line in stdout.splitlines():
        if line.startswith(_DEEP_PROBE_SENTINEL):
            records.append(line.removeprefix(_DEEP_PROBE_SENTINEL))
        elif line.strip():
            noise.append(line)
    if len(records) != 1:
        raise ValueError(f"expected one probe sentinel record, found {len(records)}")
    try:
        payload = json.loads(records[0])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid sentinel JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("sentinel JSON must be an object")

    diagnostics: dict[str, str] = {}
    stdout_noise = _bounded_probe_diagnostic("\n".join(noise))
    stderr_noise = _bounded_probe_diagnostic(stderr)
    if stdout_noise:
        diagnostics["stdout"] = stdout_noise
    if stderr_noise:
        diagnostics["stderr"] = stderr_noise
    if diagnostics:
        payload["_diagnostics"] = diagnostics
    return payload


def _frozen_application() -> bool:
    """True when this process is a frozen (PyInstaller) application."""

    return bool(getattr(sys, "frozen", False))


def probe_interpreter() -> tuple[str, str]:
    """Return ``(interpreter, refusal)``; exactly one of the two is non-empty.

    ``sys.executable`` names a Python interpreter only in a source checkout.
    In the packaged desktop backend it names the frozen application, and the
    frozen application does not accept ``-c``.

    MEASURED 2026-09-10 against the shipped generation
    ``.../backend-generations/021ad229.../daedalus-web-api.exe``::

        $ ./daedalus-web-api.exe -c "import sys; print('PROBE_RAN')"
        EXIT=2
        usage: daedalus-web-api.exe [-h] [--host HOST] [--port PORT]
                                    [--allow-remote-clients]
        daedalus-web-api.exe: error: unrecognized arguments: -c import sys; ...

    So the deep probe never probed anything in the desktop app: it reported
    every accelerator row as unprobed-and-absent, and it paid for that answer
    with a *second complete sidecar bootstrap* (effect admission, runtime
    preparation, kill-switch arm, chdir, manager construction) before argparse
    rejected the arguments.  Refusing with a reason is both honest and cheaper.

    An operator who wants a real answer from the packaged app points
    ``DAEDALUS_ACCELERATOR_PYTHON`` at an interpreter whose environment has the
    optional runtimes.  Absent that, the refusal says so instead of letting a
    frozen bundle's exclusion list masquerade as a fact about the machine.
    """

    configured = os.environ.get(ACCELERATOR_PYTHON_ENV, "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            # Not ``!r``: this string is read by an operator who is about to
            # retype the path, and ``repr`` doubles every backslash in it.
            return "", (
                f"{ACCELERATOR_PYTHON_ENV}={configured} is not an existing file"
            )
        return str(candidate), ""
    if _frozen_application():
        return "", (
            "the frozen desktop backend ships no Python interpreter: "
            f"sys.executable is the packaged application "
            f"({os.path.basename(sys.executable)}), which rejects -c. "
            f"Set {ACCELERATOR_PYTHON_ENV} to a python executable whose "
            "environment carries the optional accelerator runtimes."
        )
    return sys.executable, ""


# Environment the probe child is allowed to inherit.
#
# The parent is the Daedalus backend, and its environment carries provider
# credentials: MEASURED 2026-09-11 in this process, a child spawned with the
# default inherited environment received ANTHROPIC_API_KEY,
# DAEDALUS_RTX_OLLAMA_TOKEN and CLAUDE_CODE_MESSAGING_TOKEN.  The probe is an
# operator-named executable -- ``DAEDALUS_ACCELERATOR_PYTHON`` points wherever
# the operator says -- so handing it every secret in the backend's environment
# to answer "is torch importable" is authority it never needed.
#
# An allowlist rather than a denylist: a new secret must not become inherited
# merely because nobody added its name here.  Entries exist to let the child
# START (OS plumbing, temp dir) and to let a CUDA runtime FIND ITS LIBRARIES
# (search path, CUDA root).
#
# Four names are deliberately ABSENT for one reason.  PYTHONPATH and PYTHONHOME
# describe the PARENT's interpreter, and handing them to the operator's would
# make it import the parent's tree.  ``LD_LIBRARY_PATH`` and
# ``DYLD_LIBRARY_PATH`` are the same mistake one layer down: a PyInstaller
# bootloader PREPENDS its own bundle directory to them, so a frozen parent on
# Linux or macOS would hand the operator's interpreter a library path pointing
# into the bundle.  Latent today -- ``tools/build_tauri_sidecar.py`` has no
# linux/darwin build path -- and it must not survive into one.  ``PATH`` stays
# because Windows resolves DLLs through it and the bootloader does not rewrite
# it the same way.
_PROBE_ENV_ALLOWLIST = frozenset(
    {
        # process plumbing the interpreter itself needs to start
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "NUMBER_OF_PROCESSORS",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "USERPROFILE",
        "WINDIR",
        # where a runtime unpacks, caches and finds its own installation
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "TEMP",
        "TMP",
        "TMPDIR",
        # where the CUDA/driver libraries are found
        "CUDA_HOME",
        "CUDA_PATH",
        "CUDA_VISIBLE_DEVICES",
        "NVIDIA_VISIBLE_DEVICES",
        "PATH",
    }
)


def _probe_environment() -> dict[str, str]:
    """The filtered environment handed to the probe child."""

    return {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _PROBE_ENV_ALLOWLIST
    }


@dataclass(frozen=True)
class _ProbeTransport:
    """What the child process did, separated from what it claimed."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    overflowed: bool = False


def _read_bounded_stream(handle: Any) -> str:
    handle.seek(0)
    return handle.read(_DEEP_PROBE_OUTPUT_LIMIT).decode("utf-8", errors="replace")


def _written_bytes(*handles: Any) -> int:
    """How much the child has written so far, without reading any of it."""

    total = 0
    for handle in handles:
        try:
            total += os.fstat(handle.fileno()).st_size
        except OSError:
            # A handle we can no longer stat tells us nothing; it must not be
            # read as "nothing was written".
            return _DEEP_PROBE_OUTPUT_CEILING + 1
    return total


def _run_deep_probe(interpreter: str) -> _ProbeTransport:
    """Run the probe under a bound that survives a launcher shim.

    WHY NOT ``subprocess.run(..., timeout=...)``.  That timeout is not a
    wall-clock bound on Windows.  CPython's ``run`` reacts to ``TimeoutExpired``
    with ``process.kill()`` and then, on Windows only, a SECOND ``communicate()``
    with no timeout at all.  ``kill()`` is ``TerminateProcess`` on the direct
    child alone, so a grandchild that inherited the pipe keeps the write end
    open and the untimed read blocks until the grandchild exits.

    MEASURED against the previous implementation.  By the independent review of
    2026-09-10, with ``timeout=30``: ``HANG elapsed=600.1s`` (direct child
    spawns a grandchild holding stdout, then exits) and ``FLOOD elapsed=45.6s``
    on 8 GiB of stdout, all of which the untimed second read pulled into the
    parent's memory.  Reproduced here on 2026-09-11 by
    ``test_the_probe_is_bounded_by_wall_clock_even_through_a_launcher_shim``:
    ``30.1s`` for a ``2s`` bound -- 30s being the test grandchild's own
    deadline, so the call ended when the GRANDCHILD did, not when the bound
    did.  The same test measures ``2.01s`` against this implementation.

    That is the NATURAL value of ``DAEDALUS_ACCELERATOR_PYTHON`` on Windows:
    ``py.exe`` is a launcher that spawns the real interpreter, a conda
    ``activate.bat`` and any ``.cmd`` wrapper are ``cmd.exe`` spawning a child.
    Following this module's own advice would have armed the trap.

    So the transport does not use pipes.  Each stream is a temporary file, the
    wait is ``Popen.wait(timeout=...)`` -- ``WaitForSingleObject`` on the direct
    child's handle, which no descendant can extend -- and the parent reads a
    bounded prefix of each file afterwards.

    WHAT THE OUTPUT CEILING BOUNDS, AND WHAT IT DOES NOT.  Redirecting to a file
    moves a flood off the parent's heap and onto the disk, which is an
    improvement and not a bound: MEASURED 2026-09-11 by the review, a child
    writing flat out produced 1.94 GiB in 1.17s, so the 30s wall-clock bound
    alone would admit roughly 50 GiB against 27.5 GiB free on this host.  The
    loop below therefore polls ``os.fstat`` on the two handles and kills the
    child at ``_DEEP_PROBE_OUTPUT_CEILING``.

    That bounds the DIRECT child, which is every case where the configured
    interpreter is a real python.  It does not bound a surviving GRANDCHILD,
    and the residual there is worse than "costs disk": MEASURED, the temporary
    file reached 597 MiB in six seconds, and because it is created delete-on-
    close it is left DELETE-PENDING once the parent closes its handle -- no
    process, including an administrator, can then open or truncate it.  Only
    killing the grandchild reclaims the space.  Killing a whole process tree
    needs a Job object and is a larger change than this repair; the residual is
    stated rather than implied away.
    """

    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        # A list argv, never a shell string: the interpreter path comes from an
        # environment variable and must not be word-split or expanded.
        process = subprocess.Popen(
            [interpreter, "-c", _DEEP_PROBE],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=_probe_environment(),
        )
        timed_out = False
        overflowed = False
        returncode: int | None = None
        deadline = time.monotonic() + _DEEP_PROBE_TIMEOUT_SECONDS
        while True:
            try:
                returncode = process.wait(timeout=_DEEP_PROBE_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            # Checked BEFORE the deadline: a child that is flooding has already
            # cost what it is going to cost, and waiting out the clock only
            # makes the bill larger.
            if _written_bytes(out, err) > _DEEP_PROBE_OUTPUT_CEILING:
                overflowed = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
        if returncode is None:
            process.kill()
            try:
                returncode = process.wait(timeout=_DEEP_PROBE_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                # Even the kill did not land in time. Stop waiting: the caller
                # is a read endpoint, not a process supervisor.
                returncode = -1
        return _ProbeTransport(
            returncode=returncode,
            stdout=_read_bounded_stream(out),
            stderr=_read_bounded_stream(err),
            timed_out=timed_out,
            overflowed=overflowed,
        )


@lru_cache(maxsize=1)
def deep_framework_status() -> dict[str, dict[str, Any]]:
    """Probe optional Python compute runtimes in an isolated, bounded process."""
    interpreter, refusal = probe_interpreter()
    if refusal:
        # Not a probe result and not an import verdict: nothing was executed.
        return _probe_failure(refusal)
    try:
        result = _run_deep_probe(interpreter)
    except (OSError, subprocess.SubprocessError) as exc:
        return _probe_failure(f"{type(exc).__name__}: {exc}")
    if result.overflowed:
        return _probe_failure(
            "framework probe exceeded its "
            f"{_DEEP_PROBE_OUTPUT_CEILING // (1024 * 1024)} MiB output ceiling "
            "and was killed",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    if result.timed_out:
        # Deliberately not ``str(TimeoutExpired)``: that renders the whole argv,
        # and argv[2] is the entire probe source -- which used to be copied onto
        # all six rows. What an operator needs is the bound that was exceeded.
        return _probe_failure(
            f"framework probe exceeded its {_DEEP_PROBE_TIMEOUT_SECONDS:g}s bound "
            "and was killed",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    if result.returncode != 0:
        return _probe_failure(
            f"framework probe exited with status {result.returncode}",
            stdout=result.stdout,
            stderr=result.stderr,
        )
    try:
        return _decode_deep_probe_output(result.stdout, result.stderr)
    except ValueError as exc:
        return _probe_failure(
            f"invalid probe output: {exc}",
            stdout=result.stdout,
            stderr=result.stderr,
        )


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


def _deep_probe_hint() -> str:
    """How this process could get a real answer, in the operator's terms."""

    configured = os.environ.get(ACCELERATOR_PYTHON_ENV, "").strip()
    interpreter, refusal = probe_interpreter()
    if interpreter:
        return (
            f"a deep probe through {ACCELERATOR_PYTHON_ENV}={interpreter} can "
            "answer it; this shallow read runs nothing"
        )
    if configured:
        # The operator DID follow the instruction and the value does not work.
        # Repeating "set the variable" here would read as if they had not.
        return (
            f"{refusal}; point it at a python executable whose environment "
            "carries the optional accelerator runtimes, then request a deep probe"
        )
    return (
        f"set {ACCELERATOR_PYTHON_ENV} to a python executable whose environment "
        "carries the optional accelerator runtimes, then request a deep probe"
    )


def _shallow_framework_detail(name: str, *, host_visible: bool) -> str:
    """The detail of one shallow row, true for THAT row.

    The first version of this message said "this frozen backend excludes the
    optional accelerator runtimes" on all six rows. It is not true of two:
    cuvs and cugraph are absent from ``DESKTOP_PYINSTALLER_EXCLUDES``. They are
    invisible to the frozen backend anyway, for the other reason -- a frozen
    process imports from its bundle, not from the machine's site-packages -- so
    the row says that instead of asserting a build decision that was not made.
    """

    if host_visible:
        # A source checkout: find_spec really did look at this machine, and the
        # cockpit suppresses exactly this string as the noise it is.
        return "deep probe not requested"
    if name in DESKTOP_EXCLUDED_FRAMEWORKS:
        reason = (
            f"the desktop build excludes {name} from the bundle "
            "(DESKTOP_PYINSTALLER_EXCLUDES in tools/build_tauri_sidecar.py), so "
            "a missing import here is guaranteed by the build"
        )
    else:
        reason = (
            "this frozen backend imports from its own bundle rather than from "
            f"the machine's environment, and {name} is not in the bundle, so a "
            "missing import here is a fact about the bundle"
        )
    return f"not measured on this machine: {reason} -- {_deep_probe_hint()}"


def _framework_rows(
    *,
    deep: bool,
    probe_diagnostics: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    names = FRAMEWORK_NAMES
    # Can ``_has_module`` see the machine at all?  A frozen PyInstaller process
    # has its bundle on ``sys.path`` and not the machine's site-packages, so its
    # ``find_spec`` answers a question about the bundle.  Rows say so, because a
    # False that is guaranteed by construction must not be drawn as the measured
    # absence that the cockpit paints red.
    host_visible = not _frozen_application()
    if deep:
        rows = deep_framework_status()
        if probe_diagnostics is not None:
            raw_diagnostics = rows.get("_diagnostics")
            diagnostics = raw_diagnostics if isinstance(raw_diagnostics, dict) else {}
            probe_failure = rows.get("probe")
            probe_diagnostics.update(
                {
                    # This is only the child-process transport outcome. It is
                    # deliberately not a framework- or lane-readiness claim.
                    "transport_outcome": (
                        "failed" if isinstance(probe_failure, dict) else "decoded"
                    ),
                    "stdout": _bounded_probe_diagnostic(
                        str(diagnostics.get("stdout") or "")
                    ),
                    "stderr": _bounded_probe_diagnostic(
                        str(diagnostics.get("stderr") or "")
                    ),
                    "failure": (
                        _bounded_probe_diagnostic(
                            str(probe_failure.get("detail") or "unknown probe failure")
                        )
                        if isinstance(probe_failure, dict)
                        else ""
                    ),
                }
            )
        probe_failure = rows.get("probe")
        if isinstance(probe_failure, dict):
            detail = str(probe_failure.get("detail") or "unknown probe failure")
            return {
                name: {
                    # A failed deep probe says nothing about imports. Retain
                    # the safe, non-executing find_spec evidence instead --
                    # and, with it, whether that evidence saw the machine.
                    "installed": _has_module(name),
                    "cuda_ready": None,
                    "detail": f"deep probe failed: {detail}",
                    "probed": False,
                    "host_visible": host_visible,
                }
                for name in names
            }

        normalized: dict[str, dict[str, Any]] = {}
        for name in names:
            source = rows.get(name)
            if not isinstance(source, dict):
                normalized[name] = {
                    "installed": _has_module(name),
                    "cuda_ready": None,
                    "detail": f"deep probe returned no result for {name}",
                    "probed": False,
                    "host_visible": host_visible,
                }
                continue
            normalized[name] = {
                "installed": bool(source.get("installed")),
                # None means "installed but unverified"; only real device
                # checks may report True, so preserve the tri-state.
                "cuda_ready": (
                    None
                    if source.get("cuda_ready") is None
                    else bool(source.get("cuda_ready"))
                ),
                "detail": str(source.get("detail", "")),
                "probed": True,
                # A row that came back from the child was produced by an
                # interpreter that actually imported in a real environment --
                # the running one, or the operator's. That is a measurement of
                # a machine even when this process could not make it.
                "host_visible": True,
            }
        return normalized
    # The cockpit calls /api/accelerators/status WITHOUT deep=1, so this is the
    # branch the desktop capability panel actually renders. In a frozen build
    # ``_has_module`` answers a question about the BUNDLE, not about the host,
    # and it does so no matter how ``DAEDALUS_ACCELERATOR_PYTHON`` is set: that
    # variable selects an interpreter for the DEEP probe and changes nothing
    # about find_spec in this process. Gating the honest detail on the variable
    # therefore switched the fix off for exactly the operator who followed its
    # instructions. The gate is the one fact that decides the question: whether
    # this process can see the machine's environment at all.
    return {
        name: {
            "installed": _has_module(name),
            "cuda_ready": None,
            "detail": _shallow_framework_detail(name, host_visible=host_visible),
            "probed": False,
            "host_visible": host_visible,
        }
        for name in names
    }


def accelerator_status(*, deep: bool = False, probe_remote: bool = False) -> dict[str, Any]:
    """Describe local and remote accelerator readiness without capability inflation."""
    hardware = nvidia_hardware_status()
    probe_interpreter_path, _probe_interpreter_refusal = probe_interpreter()
    framework_probe_diagnostics: dict[str, Any] = {
        "requested": deep,
        # Which interpreter was asked. Empty means none was: either no deep
        # probe was requested, or no usable interpreter exists in this process
        # (see ``probe_interpreter``), in which case ``failure`` says why.
        "interpreter": probe_interpreter_path if deep else "",
        "transport_outcome": "not_requested" if not deep else "not_observed",
        "stdout": "",
        "stderr": "",
        "failure": "",
        "retained_char_limit": _DEEP_PROBE_DIAGNOSTIC_LIMIT,
    }
    frameworks = _framework_rows(
        deep=deep,
        probe_diagnostics=framework_probe_diagnostics,
    )
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
            missing=(
                ()
                if newton_ready
                else ("Newton device execution was not probed",)
                if newton_unverified
                else ("Newton plus CUDA-capable Warp",)
            ),
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
        # Bounded child-process output and transport failures are operational
        # diagnostics only. Readiness remains exclusively in framework rows
        # and the policy-derived lane states below.
        "framework_probe_diagnostics": framework_probe_diagnostics,
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
