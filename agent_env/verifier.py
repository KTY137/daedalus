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
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode == 0, (proc.stderr.strip()[:300] or "ok")


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


def _run_tests(test_command: str, cwd: str, timeout_s: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            shlex.split(test_command), cwd=cwd, capture_output=True, text=True, timeout=timeout_s
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"could not run tests: {exc}"[:300]
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    return proc.returncode == 0, " | ".join(tail)[:300]


def verify(
    report: dict,
    repo_root: str,
    *,
    test_command: str | None = None,
    test_cwd: str | None = None,
    timeout_s: int = 120,
) -> VerifyResult:
    checks: list[dict] = []

    errs = validate_report(report)
    checks.append({"name": "schema", "ok": not errs, "detail": "; ".join(errs) or "valid"})

    for rel in report.get("files_changed", []):
        s = str(rel)
        if s.endswith(".py"):
            ok, detail = _py_compile(repo_root, s)
            checks.append({"name": f"syntax:{s}", "ok": ok, "detail": detail})
        elif s.endswith((".json", ".yaml", ".yml")):
            ok, detail = _config_check(repo_root, s)
            checks.append({"name": f"parse:{s}", "ok": ok, "detail": detail})

    if test_command:
        ok, detail = _run_tests(test_command, test_cwd or repo_root, timeout_s)
        checks.append({"name": "tests", "ok": ok, "detail": detail})

    return VerifyResult(ok=all(c["ok"] for c in checks), checks=checks)
