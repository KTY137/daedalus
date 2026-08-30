# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Is THIS machine fit to produce a discrimination receipt, and who is it?

Two jobs, deliberately in one tool because they answer one question.

**Fitness.** A receipt is only evidence if the machine that produced it could
run the measurement. A missing test dependency does not produce a red gate; it
produces a gate that measures something else and says nothing about it. So every
requirement is checked and every answer is reported, including the ones that are
fine.

**Identity.** A receipt produced on machine B measures machine B. That is
perfectly legitimate -- and it stops being legitimate the moment two receipts from
two machines are compared as though they came from one. MEASURED on the primary
box 2026-07-30: the suite runs in ~105 s in a warm checkout and ~18 min per
mutation under the gate, a factor of ten that is entirely environmental (cold
structcore index per subprocess, Windows process-spawn cost, virus scanning of a
fresh worktree). A kill rate is comparable across machines; a DURATION is not,
and a receipt with no host block invites exactly that comparison.

FAIL-CLOSED. Anything this tool cannot determine is reported as ``unknown`` and
counts as NOT satisfied. A preflight that shrugs is worse than no preflight,
because it is the thing standing between "the gate refused" and "the gate was
never able to run".

    python -m tools.gate_host_preflight                 # human report
    python -m tools.gate_host_preflight --json          # the host block
    python -m tools.gate_host_preflight --json --out runs/gate/host.json

Exit code is 0 only when every REQUIRED check passes. Optional checks lower
precision when absent and never fail the run -- that distinction is the whole
point of separating them.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PY = sys.executable
REPO_ROOT = Path(__file__).resolve().parents[1]

#: The gate is a pytest run, and pytest is not optional for it.
REQUIRED_MODULES = ("pytest", "coverage")

#: structcore degrades cleanly without these -- unit-level clone detection and
#: real cyclomatic complexity light up when they are present and are simply
#: absent when they are not. They are listed so a duration difference between
#: two machines has a visible cause rather than being a mystery.
OPTIONAL_MODULES = ("tree_sitter_language_pack", "lizard")

#: Python this repo is developed and measured on. A different MINOR version is
#: not automatically wrong, but it is a difference a receipt must carry: the
#: `Path.write_text(newline=...)` argument daedalus.atomic relies on is 3.10+,
#: and match statements would not parse below 3.10 at all.
EXPECTED_PY = (3, 10)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "required": self.required}


@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)
    host: dict = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str, *, required: bool = True) -> None:
        self.checks.append(Check(name, ok, detail, required))

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.required and not c.ok]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.required and not c.ok]

    @property
    def fit(self) -> bool:
        return not self.failures


def _run(argv: list[str], *, cwd: str | None = None, timeout: float = 30.0
         ) -> tuple[int, str]:
    """Run a command, never raise. Returns (rc, combined output).

    rc 127 is this function's own "could not run at all", distinct from a
    command that ran and failed -- a missing binary and a broken binary need
    different fixes and must not report identically.
    """
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# --------------------------------------------------------------------------- #
# host identity                                                                #
# --------------------------------------------------------------------------- #

def _cpu_name() -> str:
    """A human-readable CPU model, or "unknown".

    ``platform.processor()`` returns a useless family string on Windows
    ("AMD64 Family 26 Model 68..."), so the registry name is preferred where it
    exists. Everything degrades to "unknown" rather than to a guess: a receipt
    that says "unknown" is honest, and one that says "AMD64" while running on a
    9950X3D is misleading about the only fact anyone would use it for.
    """
    env = os.environ.get("PROCESSOR_IDENTIFIER", "")
    if sys.platform == "win32":
        rc, out = _run(["reg", "query",
                        r"HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                        "/v", "ProcessorNameString"])
        if rc == 0:
            for line in out.splitlines():
                if "ProcessorNameString" in line:
                    parts = line.split("REG_SZ")
                    if len(parts) > 1:
                        return parts[1].strip()
        return env or "unknown"
    for path, key in (("/proc/cpuinfo", "model name"),):
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.lower().startswith(key):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or env or "unknown"


def _physical_cores() -> int | None:
    """Physical cores, or None. Distinct from ``os.cpu_count()`` on purpose.

    ``os.cpu_count()`` reports LOGICAL processors (SMT threads). Test-suite
    throughput tracks physical cores far better, because the workload is
    process-spawn and I/O bound rather than ALU bound -- so a 16-core/32-thread
    part and an 8-core/16-thread part both report "16" to a naive reader while
    differing by a factor of two on this workload.
    """
    if sys.platform == "win32":
        rc, out = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_Processor | "
                        "Measure-Object -Property NumberOfCores -Sum).Sum"])
        if rc == 0:
            digits = "".join(ch for ch in out if ch.isdigit())
            if digits:
                return int(digits)
        return None
    try:
        import re
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
        ids = set(re.findall(r"core id\s*:\s*(\d+)", text))
        return len(ids) or None
    except (OSError, ValueError):
        return None


def _total_ram_gb() -> float | None:
    if sys.platform == "win32":
        rc, out = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        if rc == 0:
            digits = "".join(ch for ch in out if ch.isdigit())
            if digits:
                return round(int(digits) / 1024**3, 1)
        return None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024**2, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def collect_host(repo_root: Path) -> dict:
    """The block a receipt carries so two receipts are never silently compared."""
    logical = os.cpu_count()
    physical = _physical_cores()
    free_gb = None
    try:
        free_gb = round(shutil.disk_usage(str(repo_root)).free / 1024**3, 1)
    except OSError:
        pass
    return {
        # Deliberately NOT the hostname by default -- see --include-hostname.
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu": _cpu_name(),
        "cores_physical": physical,
        "cores_logical": logical,
        "ram_gb": _total_ram_gb(),
        "disk_free_gb_at_repo": free_gb,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "executable": sys.executable,
        "repo_root": str(repo_root),
    }


# --------------------------------------------------------------------------- #
# fitness                                                                      #
# --------------------------------------------------------------------------- #

def run_checks(repo_root: Path) -> Preflight:
    pf = Preflight()
    pf.host = collect_host(repo_root)

    # --- python -------------------------------------------------------------
    v = sys.version_info
    pf.add("python version",
           (v.major, v.minor) >= EXPECTED_PY,
           f"{platform.python_version()} at {sys.executable} "
           f"(expected >= {EXPECTED_PY[0]}.{EXPECTED_PY[1]}; "
           "daedalus.atomic uses Path.write_text(newline=...), which is 3.10+)")

    # --- required modules ---------------------------------------------------
    for mod in REQUIRED_MODULES:
        rc, out = _run([PY, "-c", f"import {mod}; print({mod}.__version__)"])
        pf.add(f"module {mod}", rc == 0,
               out.strip().splitlines()[0] if rc == 0 and out.strip()
               else f"NOT IMPORTABLE ({out.strip()[:120]})")

    # --- optional modules ---------------------------------------------------
    for mod in OPTIONAL_MODULES:
        rc, _ = _run([PY, "-c", f"import {mod}"])
        pf.add(f"optional {mod}", rc == 0,
               "present -- structcore runs at full precision" if rc == 0
               else "absent -- structcore degrades cleanly, and a duration "
                    "difference against a machine that HAS it is expected",
               required=False)

    # --- the package itself -------------------------------------------------
    rc, out = _run([PY, "-c",
                    "import daedalus, pathlib; print(pathlib.Path(daedalus.__file__).parent)"],
                   cwd=str(repo_root))
    resolved = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ""
    expected = str(repo_root / "daedalus")
    same = bool(resolved) and Path(resolved).resolve() == Path(expected).resolve()
    pf.add("daedalus resolves to THIS checkout", same,
           f"{resolved or 'import failed'} (expected {expected})\n"
           "        This is ADR-015 Finding 1 in miniature: the gate calls pytest, "
           "and if `daedalus` resolves to a DIFFERENT checkout the run measures "
           "that one instead -- silently, and green.")

    # --- git ----------------------------------------------------------------
    rc, out = _run(["git", "--version"])
    pf.add("git", rc == 0, out.strip() or "not found on PATH")

    rc, out = _run(["git", "rev-parse", "HEAD"], cwd=str(repo_root))
    head = out.strip().splitlines()[0] if rc == 0 else ""
    pf.add("git HEAD readable", rc == 0 and len(head) == 40,
           head or f"could not read HEAD ({out.strip()[:120]})")
    pf.host["head"] = head

    rc, out = _run(["git", "status", "--porcelain"], cwd=str(repo_root))
    dirty = [l for l in out.splitlines() if l.strip()] if rc == 0 else []
    # NOT a failure. --head-only exists precisely so a dirty tree can still be
    # measured, by cloning committed HEAD and ignoring the diff. It is reported
    # because a reader of the receipt should know the tree was dirty even though
    # the measurement did not include it.
    pf.add("working tree clean", not dirty,
           "clean" if not dirty else
           f"{len(dirty)} modified/untracked path(s) -- NOT a blocker: run with "
           "--head-only, which clones committed HEAD and skips the diff",
           required=False)

    # --- worktree support ---------------------------------------------------
    rc, out = _run(["git", "worktree", "list"], cwd=str(repo_root))
    pf.add("git worktree usable", rc == 0,
           f"{len(out.strip().splitlines())} worktree(s)" if rc == 0
           else out.strip()[:160])

    # --- disk ---------------------------------------------------------------
    free = pf.host.get("disk_free_gb_at_repo")
    # Each mutation gets its own clone of the tree. Twelve of them plus pytest
    # caches is the floor here; the number is a guard against the failure mode
    # where a run dies at mutation 9 and the partial receipt has to be thrown
    # away entirely.
    pf.add("disk headroom", free is not None and free >= 10.0,
           f"{free} GiB free at the repo (want >= 10; each mutation clones "
           "the tree)" if free is not None else "unknown -- treated as NOT ok")

    # --- cores --------------------------------------------------------------
    phys = pf.host.get("cores_physical")
    logi = pf.host.get("cores_logical")
    pf.add("core count known", phys is not None or logi is not None,
           f"physical={phys} logical={logi} -- physical is the number that "
           "predicts this workload; the gate is process-spawn and I/O bound, "
           "not ALU bound")

    return pf


# --------------------------------------------------------------------------- #
# reporting                                                                    #
# --------------------------------------------------------------------------- #

def render(pf: Preflight) -> str:
    lines: list[str] = []
    h = pf.host
    lines.append("HOST")
    lines.append(f"  cpu        {h.get('cpu')}")
    lines.append(f"  cores      physical={h.get('cores_physical')} "
                 f"logical={h.get('cores_logical')}")
    lines.append(f"  ram        {h.get('ram_gb')} GiB")
    lines.append(f"  platform   {h.get('platform')}")
    lines.append(f"  python     {h.get('python')} ({h.get('python_implementation')})")
    lines.append(f"  repo       {h.get('repo_root')}")
    lines.append(f"  head       {h.get('head') or 'unknown'}")
    lines.append("")
    lines.append("CHECKS")
    for c in pf.checks:
        mark = "ok  " if c.ok else ("FAIL" if c.required else "warn")
        lines.append(f"  [{mark}] {c.name}: {c.detail}")
    lines.append("")
    if pf.fit:
        lines.append("FIT TO MEASURE. Suggested invocation:")
        lines.append("  python -u tools/gate_discrimination.py --dry-run")
        lines.append("  python -u tools/gate_discrimination.py --head-only "
                     "--coverage-guided")
        lines.append("")
        lines.append("  --head-only        the working tree may be edited "
                     "concurrently; measure committed HEAD")
        lines.append("  --coverage-guided  skip mutants on lines no test "
                     "executes -- a guaranteed SURVIVED that proves nothing. "
                     "OPT-IN: without it the corpus is not narrowed at all "
                     "(a run reporting '0 pre-excluded by coverage' was not "
                     "asked to exclude anything).")
        if pf.warnings:
            lines.append("")
            lines.append(f"  {len(pf.warnings)} warning(s) above lower precision "
                         "or explain a duration difference. Neither blocks.")
    else:
        lines.append(f"NOT FIT: {len(pf.failures)} required check(s) failed.")
        for c in pf.failures:
            lines.append(f"  - {c.name}")
        lines.append("")
        lines.append("A gate run on this host would not measure what the "
                     "receipt would claim it measured.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tools.gate_host_preflight",
        description="Check whether this machine can produce a discrimination "
                    "receipt, and emit the host block that stamps it.")
    p.add_argument("--json", action="store_true",
                   help="emit the machine-readable block instead of the report")
    p.add_argument("--out", metavar="PATH", default=None,
                   help="also write the JSON block here")
    p.add_argument("--include-hostname", action="store_true",
                   help="include the network hostname and user. OFF by default: "
                        "a receipt is a shareable artefact and the CPU model "
                        "plus core count already identify the machine for every "
                        "purpose a reader has.")
    p.add_argument("--repo-root", default=str(REPO_ROOT))
    args = p.parse_args(argv)

    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.gate_host_preflight",
        REGISTRY_BY_ID["tools.gate_host_preflight"].effects,
        (process_guard_boundary_decision(),),
    )
    root = Path(args.repo_root).resolve()
    pf = run_checks(root)
    if args.include_hostname:
        pf.host["hostname"] = platform.node()
        pf.host["user"] = os.environ.get("USERNAME") or os.environ.get("USER") or ""

    block = {
        "host": pf.host,
        "fit": pf.fit,
        "checks": [c.to_dict() for c in pf.checks],
        "failed_required": [c.name for c in pf.failures],
        "warnings": [c.name for c in pf.warnings],
    }
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(block, indent=2), encoding="utf-8")
    print(json.dumps(block, indent=2) if args.json else render(pf))
    return 0 if pf.fit else 1


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
