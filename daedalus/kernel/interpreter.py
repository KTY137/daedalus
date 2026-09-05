"""The interpreter that runs a stdlib-only contained payload.

Measured 2026-09-05 on the owner's Windows 11 host: a uv/venv
``sys.executable`` is a launcher stub. Spawned by containment with the
deliberately NULL stdin of :func:`daedalus.spine.containment.spawn_contained`,
the stub prints ``warning: Making stdin inheritable failed`` into the merged
gate log before the real interpreter starts. Any gate whose contract is exact
output (the Ariadne frozen evaluator) fails on that prefix; every gate carries
the noise in its retained output.

This module is the ONE shared resolution for callers whose payload is
stdlib-only and runs under ``-I -S``. It is a property of the payload, not of
the gate, and is deliberately not applied inside ``command_gate``:

* the kernel's own pytest gate (``pytest_gate_argv``) needs the venv's
  site-packages, which the base interpreter does not have;
* receipts are verified against the exact argv a gate was handed
  (``daedalus/spine/bootstrap.py``), so a gate must execute and record the
  argv it received, never a substitute.

Callers keep the vendor-neutral literal ``python`` in their frozen identity
(``TaskSpec.gate_argv``) and resolve only the argv they pass to the gate.
Provenance of the executed interpreter is path-free: version, implementation,
platform and the SHA-256 of the binary, never the path, because receipts and
observations leave the machine and an absolute path carries the user profile.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Sequence

__all__ = ["stdlib_interpreter", "resolve_python_argv", "interpreter_provenance"]


def stdlib_interpreter() -> str:
    """Interpreter for a stdlib-only ``-I -S`` payload under containment.

    On ``win32`` prefer ``sys._base_executable`` when it names an existing
    file: that is the venv's real base interpreter, set by the launcher from
    ``pyvenv.cfg`` and identical for uv and stdlib ``venv``. A non-venv
    interpreter (or conda) has ``_base_executable == sys.executable`` and the
    branch is inert. Every other platform returns ``sys.executable`` unchanged.
    """
    if sys.platform == "win32":
        base = getattr(sys, "_base_executable", None)
        if base and Path(base).is_file():
            return str(Path(base))
    return sys.executable


def resolve_python_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Replace a leading ``python`` literal or ``sys.executable`` with the resolved interpreter.

    LIMITATION, stated by Codex in review (2026-09-05): the substitution keys
    on ``argv[0]`` only and never inspects the following arguments, so
    ``(sys.executable, "-m", "pytest", ...)`` IS rewritten too. The guarantee
    that the kernel pytest gate keeps the venv interpreter therefore rests on
    ``pytest_gate_argv`` never calling this helper, not on the helper. Call it
    only for a payload you know to be stdlib-only. Anything whose ``argv[0]``
    is not ``python`` or ``sys.executable`` (a foreign interpreter path,
    ``git``, a candidate binary) is returned untouched.
    """
    parts = tuple(str(part) for part in argv)
    if parts and parts[0] in ("python", sys.executable):
        return (stdlib_interpreter(), *parts[1:])
    return parts


def interpreter_provenance(executable: str) -> dict[str, Any]:
    """Host-independent identity of ``executable``: no path, ever."""
    digest = hashlib.sha256()
    with open(executable, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return {
        "implementation": sys.implementation.name,
        "version": "%d.%d.%d" % sys.version_info[:3],
        "platform": sys.platform,
        "binary_sha256": digest.hexdigest(),
    }
