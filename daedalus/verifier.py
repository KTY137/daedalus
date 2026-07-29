"""Verifier gate -- the cascade's quality check.

Before a local-model result is *accepted*, it must pass cheap deterministic
checks. This is what turns risk-tier routing into a real FrugalGPT cascade and
closes the "silent escalation" hole: bad local output is caught here and
escalated to Claude instead of being shipped or looping forever.

Checks (fast by default): report schema validity + Python syntax of any files
the worker wrote. The project's test suite is opt-in (pass ``test_command``),
since running it on every small edit is too slow.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .schemas import validate_report

# How long the project suite may run before we kill it. This is a RUNAWAY
# guard, not a performance budget: its job is to stop a wedged test process
# from pinning the harness forever, not to express an opinion about how fast a
# repo's suite ought to be. Repos whose suite legitimately needs longer declare
# ``test_timeout_s`` in their project config; the default must stay 120 so that
# adding that knob does not silently re-time every other repo's gate.
DEFAULT_TEST_TIMEOUT_S = 120


@dataclass
class VerifyResult:
    ok: bool
    checks: list[dict] = field(default_factory=list)

    @property
    def failed(self) -> list[str]:
        return [c["name"] for c in self.checks if not c["ok"]]

    def as_dict(self) -> dict:
        return {"ok": self.ok, "checks": self.checks, "failed": self.failed}


def _py_compile(repo_root: str, rel: str) -> tuple[bool, str]:
    target = Path(repo_root) / rel
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    return proc.returncode == 0, (proc.stderr.strip()[:300] or "ok")


def _lint_py(repo_root: str, rel: str) -> tuple[bool, str]:
    """Best-effort static lint of a changed .py file -- catches undefined names
    and unused imports that py_compile (syntax-only) misses. Prefers ruff, falls
    back to pyflakes; if NEITHER is installed it skips cleanly (never blocks a
    write on a missing dev tool). Only a real lint error fails the gate."""
    import shutil
    target = str(Path(repo_root) / rel)
    if shutil.which("ruff"):
        cmd = ["ruff", "check", "--quiet", "--select", "E,F", target]
    else:
        try:
            import pyflakes  # noqa: F401
        except ImportError:
            return True, "no linter (ruff/pyflakes) -- skipped"
        cmd = [sys.executable, "-m", "pyflakes", target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=30, cwd=repo_root)
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"lint unavailable ({exc}) -- skipped"
    lines = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, (" | ".join(lines[-3:])[:300] or "clean")


def _js_check(repo_root: str, rel: str) -> tuple[bool, str]:
    """Syntax-check a written .js file via `node --check` when node is on PATH;
    skip cleanly otherwise (never block a write on a missing dev tool)."""
    import shutil
    node = shutil.which("node")
    if not node:
        return True, "node not on PATH -- skipped"
    try:
        proc = subprocess.run([node, "--check", str(Path(repo_root) / rel)],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"node check unavailable ({exc}) -- skipped"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-2:]
    return proc.returncode == 0, (" | ".join(tail)[:300] or "ok")


def _html_check(repo_root: str, rel: str) -> tuple[bool, str]:
    """Cheap structural gate for a written .html file. The dominant local-model
    failure is TRUNCATION (file cut off mid-tag), which shows up as unbalanced
    <script>/<style> containers or an empty file -- both break rendering hard.
    This is a truncation tripwire, not a full validator."""
    import re
    try:
        text = (Path(repo_root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"cannot read: {exc}"[:200]
    if not text.strip():
        return False, "empty html file"
    for tag in ("script", "style"):
        opens = len(re.findall(rf"<{tag}\b[^>]*>", text, re.I))
        closes = len(re.findall(rf"</{tag}\s*>", text, re.I))
        if opens != closes:
            return False, f"unbalanced <{tag}> tags ({opens} open / {closes} close) -- truncated output?"
    if text.rstrip().endswith(("<", "</")):
        return False, "file ends mid-tag -- truncated output"
    return True, "non-empty, script/style balanced"


def _config_check(repo_root: str, rel: str) -> tuple[bool, str]:
    """Parse a written .json/.yaml file so a corrupted config is caught."""
    try:
        text = (Path(repo_root) / rel).read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"cannot read: {exc}"[:200]
    if rel.endswith(".json"):
        try:
            json.loads(text)
            return True, "valid json"
        except json.JSONDecodeError as exc:
            return False, f"invalid json: {exc}"[:200]
    try:
        import yaml  # optional; skip cleanly if the parser isn't installed
    except ImportError:
        return True, "yaml parser unavailable -- skipped"
    try:
        yaml.safe_load(text)
        return True, "valid yaml"
    except yaml.YAMLError as exc:
        return False, f"invalid yaml: {exc}"[:200]


def _effective_timeout(timeout_s: object) -> int | float:
    """Coerce a project-declared ``test_timeout_s`` to a usable positive budget.

    Fail-SAFE, not fail-open: a junk or non-positive value falls back to the
    default rather than to "no timeout". ``subprocess.run(timeout=None)`` waits
    forever, so treating a malformed config as "unlimited" would turn a typo
    into a wedged harness -- the one outcome a runaway guard exists to prevent.
    A ``0`` is likewise not honoured literally: it would expire instantly and
    make every gate report a timeout, silently disabling the local lane.

    A positive value is passed through EXACTLY, never truncated to int:
    ``int(0.5)`` is ``0``, which would quietly convert a small fractional
    budget into the instant-expiry case this function exists to reject.
    ``subprocess.run`` accepts a float timeout, so there is nothing to gain by
    rounding. ``bool`` is excluded because ``True`` is an ``int`` of value 1 and
    a config that says ``true`` means a typo, not a one-second suite.
    """
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
        return DEFAULT_TEST_TIMEOUT_S
    return timeout_s if timeout_s > 0 else DEFAULT_TEST_TIMEOUT_S


def _run_tests(test_command: str, cwd: str, timeout_s: int) -> tuple[bool, str, str]:
    """Run the project suite. Returns ``(ok, detail, status)``.

    ``status`` is the MACHINE-READABLE outcome and is deliberately finer than
    ``ok``: ``pass`` / ``fail`` / ``timeout`` / ``error``.

    Why it must not collapse into ``ok``: a red suite means the write under
    verification is bad, whereas a timeout means *we* set the budget too low
    for a suite that never got to finish. Both must block the write -- but they
    are opposite diagnoses, and the escalation they trigger is recorded against
    the local lane's routing metrics. Reporting a budget shortfall as "the
    local model broke the tests" teaches the router to distrust a lane that did
    nothing wrong. Every non-``pass`` status is ``ok=False``; nothing here may
    ever read a timeout as a pass.
    """
    try:
        proc = subprocess.run(
            shlex.split(test_command), cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"tests did not finish within the {timeout_s}s budget and were killed. "
            f"This is NOT a test failure -- the suite never reported a verdict. "
            f"Raise 'test_timeout_s' in the project config or narrow 'test_command'."
        )[:300], "timeout"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run tests: {exc}"[:300], "error"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    ok = proc.returncode == 0
    return ok, " | ".join(tail)[:300], ("pass" if ok else "fail")


def verify(
    report: dict,
    repo_root: str,
    *,
    test_command: str | None = None,
    test_cwd: str | None = None,
    timeout_s: int = DEFAULT_TEST_TIMEOUT_S,
    require_changes: bool = False,
    disk_changed: list[str] | None = None,
) -> VerifyResult:
    checks: list[dict] = []

    errs = validate_report(report)
    checks.append({"name": "schema", "ok": not errs, "detail": "; ".join(errs) or "valid"})

    # Close the silent-ACCEPTANCE hole: a write-mode task that produced no file
    # changes is a no-op (small models often narrate "I edited X" without ever
    # calling the write tool). Accepting it fakes 100% savings while nothing got
    # done -- so the work would silently be lost. Fail it -> escalate to Claude.
    #
    # CRITICAL: ``report["files_changed"]`` is the model's SELF-REPORT and a
    # narrating model claims edits it never wrote (the exact fake-offload repro).
    # When the caller has real evidence -- content-hash diffs of the target paths
    # taken before/after the run, passed as ``disk_changed`` -- that verified list
    # is the ONLY thing that may satisfy the gate; the self-report is ignored.
    # ``disk_changed is None`` means the caller supplied no evidence (e.g. a
    # direct/unit call); we fall back to the self-report there, but the live
    # offload seam ALWAYS supplies ``disk_changed`` so production never trusts it.
    if require_changes:
        if disk_changed is not None:
            did_write = bool(disk_changed)
            detail = (f"verified on disk: {', '.join(disk_changed)}" if did_write else
                      "write task changed NO files on disk -- model narrated an edit "
                      "without writing (self-reported files_changed is not trusted)")
        else:
            did_write = bool(report.get("files_changed"))
            detail = ("wrote files (self-report; no disk evidence supplied)" if did_write else
                      "write task produced NO file changes (model narrated instead of editing)")
        checks.append({"name": "did_work", "ok": did_write, "detail": detail})

    for rel in report.get("files_changed", []):
        s = str(rel)
        if s.endswith(".py"):
            ok, detail = _py_compile(repo_root, s)
            checks.append({"name": f"syntax:{s}", "ok": ok, "detail": detail})
            lok, ldetail = _lint_py(repo_root, s)
            checks.append({"name": f"lint:{s}", "ok": lok, "detail": ldetail})
        elif s.endswith((".json", ".yaml", ".yml")):
            ok, detail = _config_check(repo_root, s)
            checks.append({"name": f"parse:{s}", "ok": ok, "detail": detail})
        elif s.endswith((".js", ".mjs", ".cjs")):
            ok, detail = _js_check(repo_root, s)
            checks.append({"name": f"jscheck:{s}", "ok": ok, "detail": detail})
        elif s.endswith((".html", ".htm")):
            ok, detail = _html_check(repo_root, s)
            checks.append({"name": f"htmlcheck:{s}", "ok": ok, "detail": detail})

    if test_command:
        import os
        # test_cwd is relative to the TARGET repo, not the offload process cwd.
        cwd = repo_root if test_cwd in (None, "", ".") else os.path.join(repo_root, test_cwd)
        budget = _effective_timeout(timeout_s)
        ok, detail, status = _run_tests(test_command, cwd, budget)
        # ``status`` rides alongside ``ok`` so a consumer can tell a red suite
        # from a budget shortfall without string-matching English out of a
        # 300-char-truncated ``detail``. ``ok`` keeps its exact old meaning.
        checks.append({"name": "tests", "ok": ok, "status": status,
                       "timeout_s": budget, "detail": detail})

    return VerifyResult(ok=all(c["ok"] for c in checks), checks=checks)
