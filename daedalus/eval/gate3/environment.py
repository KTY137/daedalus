"""environment.py -- Gate-3 freeze obligation #4: model/hardware reporting
(G3-BASE-01, §4/§5a test A7).

Plan §4 invariant 9 requires "declared hardware/models" for any comparative
claim; plan §4.1 additionally requires that external physical constraints
(provider context windows, hardware capacity, disk, OS limits) be "reported
honestly instead of claiming they were disabled." This module is the single
place that turns "what machine produced this number" into the frozen
``RunEnvironment`` contract (``daedalus/eval/gate3/contracts.py``), plus a
companion ``ExternalLimits`` snapshot for the second half of §4.1.

EXTEND, NEVER DUPLICATE (packet §2): the tokenizer identity is never
re-detected here. ``daedalus.eval.harness`` already degrades from tiktoken to
a chars/4 heuristic and exposes which one is actually in effect via
``tokenizer_name()``; this module calls that function BY MODULE ATTRIBUTE
(``harness.tokenizer_name()``, not ``from ... import tokenizer_name``) so a
test (or a future caller) that monkeypatches ``harness.tokenizer_name`` is
honoured, never bypassed by an import-time snapshot. Reporting a hardcoded
"tiktoken" string while the heuristic silently ran would itself be exactly
the kind of false provenance plan invariant 7 forbids.

HONESTY DESIGN DECISION (read before touching detection logic below):
``RunEnvironment`` requires ``cpu``/``os_name`` non-empty and ``ram_gb``
positive (contracts.py ``__post_init__``). Detection can fail (unknown
platform, sandboxed environment, missing ``/proc``, missing stdlib
capability). The three fields need three different honest "unknown" tokens
because the contract enforces three different constraints:

* ``cpu`` / ``os_name`` (non-empty string): a failed detection returns the
  literal sentinel ``UNKNOWN_CPU`` / ``UNKNOWN_OS`` -- a string that reads
  as "detection failed" on sight, never a plausible-looking but invented
  model name. This satisfies "non-empty" honestly because the sentinel value
  IS the true statement ("unknown"), not a guess dressed as a fact.
* ``ram_gb`` (must be a POSITIVE float -- ``None`` and ``0`` are both
  rejected by the frozen contract, and 0 would misreport a machine with no
  memory rather than an undetected one). There is no positive float that
  means "unknown" by convention the way a sentinel string does. This module
  uses ``float("nan")`` (module constant ``UNKNOWN_RAM_GB``): IEEE-754 NaN
  is neither positive nor a plausible reading, ``nan <= 0`` is ``False`` so
  the frozen contract's positivity check does not reject it, and any
  arithmetic a careless aggregator performs on it (mean, sum, comparison)
  poisons the result loudly (propagates to NaN) rather than silently
  contributing a fabricated number. Use ``is_unknown_ram()`` to test for it
  explicitly rather than comparing with ``==`` (NaN != NaN by definition).

FINDING for the record (see also the caller-facing report): this asymmetry
is a real seam in ``RunEnvironment``, not a workaround this module is happy
to have needed. The contract has no honest positive-typed "unknown" the way
it has one for strings; NaN is the closest IEEE-754-native equivalent, but a
future revision of ``RunEnvironment`` could accept ``ram_gb: float | None``
to remove this asymmetry outright. This module does not make that change --
``contracts.py`` is out of scope for packet G3-BASE-01's two owned files.

No dependency beyond the standard library: ``platform``, ``os``, ``ctypes``
(Windows only, itself stdlib), and ``shutil``/``subprocess`` as a last
resort with failure handled cleanly. No ``psutil``. No network call unless
``describe_external_limits(probe_provider=True)`` is explicitly requested;
the default performs zero network I/O.
"""
from __future__ import annotations

import math
import os
import platform
import shutil
from dataclasses import dataclass

from daedalus.eval import harness

from .contracts import RunEnvironment

#: Declared-unknown sentinels. Never a fabricated value; see module docstring.
UNKNOWN_CPU = "unknown (stdlib cpu detection failed)"
UNKNOWN_OS = "unknown (stdlib os detection failed)"
# None, not NaN. contracts.RunEnvironment.ram_gb is `float | None`
# and explicitly refuses NaN: an earlier revision required a positive
# float, which left no honest way to say "unknown" and drove this module
# to smuggle NaN past a `<= 0` guard. The contract was fixed instead.
UNKNOWN_RAM_GB = None

_BYTES_PER_GB = 1024 ** 3


def is_unknown_ram(ram_gb: float) -> bool:
    """True when ``ram_gb`` is the declared-unknown sentinel.

    NaN never compares equal to itself, so callers must use this instead of
    ``ram_gb == UNKNOWN_RAM_GB``.
    """
    return ram_gb is None


def _safe_platform_system() -> str:
    try:
        return platform.system()
    except Exception:
        return ""


def _detect_os_name() -> str:
    """Best-effort, stdlib-only OS description. Declared-unknown on failure,
    never a blank string (blank would still satisfy "non-empty" but reads as
    a bug, not a statement)."""
    try:
        name = platform.platform()
    except Exception:
        return UNKNOWN_OS
    name = (name or "").strip()
    return name if name else UNKNOWN_OS


def _detect_cpu() -> str:
    """Best-effort, stdlib-only CPU description.

    ``platform.processor()`` is authoritative on Windows (returns the CPU
    identification string from the registry) but is frequently empty on
    Linux distributions; ``/proc/cpuinfo`` is the honest fallback there.
    ``platform.machine()`` (e.g. ``AMD64``, ``x86_64``, ``arm64``) is reported
    as an explicitly-labelled coarse fallback rather than silently upgraded
    to look like a real model string.
    """
    try:
        proc = (platform.processor() or "").strip()
    except Exception:
        proc = ""
    if proc:
        return proc

    if _safe_platform_system() == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        _, _, value = line.partition(":")
                        value = value.strip()
                        if value:
                            return value
        except Exception:
            pass

    try:
        machine = (platform.machine() or "").strip()
    except Exception:
        machine = ""
    if machine:
        return f"{machine} (generic; exact model undetermined)"

    return UNKNOWN_CPU


def _detect_ram_gb_windows() -> float | None:
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        if ok:
            return stat.ullTotalPhys / _BYTES_PER_GB
    except Exception:
        pass
    return None


def _detect_ram_gb_linux() -> float | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = float(line.split()[1])
                    return kb * 1024 / _BYTES_PER_GB
    except Exception:
        pass
    return None


def _detect_ram_gb_posix_sysconf() -> float | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return (pages * page_size) / _BYTES_PER_GB
    except (ValueError, AttributeError, OSError):
        pass
    return None


def _detect_ram_gb_macos() -> float | None:
    try:
        import subprocess

        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, timeout=2, check=True, text=True,
        )
        value = float(out.stdout.strip())
        if value > 0:
            return value / _BYTES_PER_GB
    except Exception:
        pass
    return None


def _detect_ram_gb() -> float:
    system = _safe_platform_system()
    result: float | None = None
    if system == "Windows":
        result = _detect_ram_gb_windows()
    elif system == "Linux":
        result = _detect_ram_gb_linux()
    elif system == "Darwin":
        result = _detect_ram_gb_macos()
    if result is None:
        result = _detect_ram_gb_posix_sysconf()
    return result if result is not None else UNKNOWN_RAM_GB


def capture_environment(
    model_id: str | None = None,
    provider: str | None = None,
    host: str | None = None,
) -> RunEnvironment:
    """Build the frozen ``RunEnvironment`` for the current process/machine.

    ``model_id``/``provider``/``host`` are the caller's declared identity for
    the arm being run -- this function does not probe a network to invent
    them. ``model_id=None`` is valid and common: Tier 1 and arms A/B/C in
    this packet are deterministic and model-free (contracts.py docstring),
    and recording ``None`` is the honest statement for that case.

    ``tokenizer`` is always resolvable (``harness.tokenizer_name()`` itself
    degrades to ``"chars/4 (heuristic)"`` rather than failing), so it never
    needs an unknown sentinel. ``os_name``/``cpu``/``ram_gb`` are detected
    from the standard library only and fall back to the declared-unknown
    values documented at module level when detection fails.
    """
    return RunEnvironment(
        tokenizer=harness.tokenizer_name(),
        os_name=_detect_os_name(),
        cpu=_detect_cpu(),
        ram_gb=_detect_ram_gb(),
        model_id=model_id,
        provider=provider,
        host=host,
    )


@dataclass(frozen=True)
class ExternalLimits:
    """Plan §4.1: "Provider context windows, API quotas/rate limits, hardware
    capacity, disk and operating-system limits are external physical
    constraints and cannot be removed by Daedalus. The UI and evidence report
    them honestly instead of claiming they were disabled."

    Every field is ``Optional``; ``None`` means undetermined, matching the
    string-sentinel honesty rule in ``capture_environment`` -- there is no
    non-null numeric constraint to fight here (unlike ``RunEnvironment.ram_gb``),
    so ``None`` is available and used directly instead of a NaN-style sentinel.

    ``context_window_tokens`` is deliberately always ``None`` today:
    ``daedalus.eval.harness.detect_provider`` (the only provider probe this
    packet is allowed to reuse -- packet §2, "Forbidden: ... a second
    tokenizer, a second gate") returns only ``{kind, host, model, models}``
    and carries no context-length field. Inventing one from a hardcoded
    model-name -> context-length table would be exactly the fabrication this
    packet forbids (module docstring); ``context_window_source`` records
    *why* it is unknown rather than leaving the absence unexplained.
    """

    provider_kind: str | None
    provider_model: str | None
    context_window_tokens: int | None
    context_window_source: str | None
    disk_free_gb: float | None
    cpu_count: int | None


def describe_external_limits(
    probe_provider: bool = False,
    provider: str | None = None,
) -> ExternalLimits:
    """Snapshot of external physical constraints Daedalus does not control.

    No network I/O unless ``probe_provider=True`` is passed explicitly --
    the default is fully offline, matching every deterministic arm's budget
    ("no network call unless an arm explicitly declares one", packet §7).
    When requested, the ONLY network primitive touched is
    ``daedalus.eval.harness.detect_provider`` (called by module attribute,
    same dynamic-dispatch reasoning as ``capture_environment``'s tokenizer
    call), which already skips cleanly -- any connection failure is caught
    inside ``detect_provider`` itself and reported as "no provider", never
    raised here.
    """
    provider_kind: str | None = None
    provider_model: str | None = None
    context_window_tokens: int | None = None
    context_window_source: str | None = None

    if probe_provider:
        descriptor = harness.detect_provider(provider)
        if descriptor:
            provider_kind = descriptor.get("kind")
            provider_model = descriptor.get("model")
            context_window_source = (
                "undetermined: detect_provider() does not expose a context "
                "length; no hardcoded model table is used to avoid inventing one"
            )
        else:
            context_window_source = "undetermined: no provider reachable"
    else:
        context_window_source = "not probed (probe_provider=False)"

    try:
        usage = shutil.disk_usage(os.getcwd())
        disk_free_gb = usage.free / _BYTES_PER_GB
    except Exception:
        disk_free_gb = None

    try:
        cpu_count = os.cpu_count()
    except Exception:
        cpu_count = None

    return ExternalLimits(
        provider_kind=provider_kind,
        provider_model=provider_model,
        context_window_tokens=context_window_tokens,
        context_window_source=context_window_source,
        disk_free_gb=disk_free_gb,
        cpu_count=cpu_count,
    )
