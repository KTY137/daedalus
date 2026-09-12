"""Toolchain: detect how a candidate is built, tested and run, then run it.

The builder writes ``daedalus-candidate.json`` (``{"build": [...], "test": [...],
"run": [...], "preview": "..."}``); when it does not, detection falls back to
the lockfiles and layout on disk. Every command runs with a timeout, bounded
output and the workspace as cwd. Results are *observations*: a green check is
evidence, not promotion.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST = "daedalus-candidate.json"
MAX_OUTPUT = 12_000
DEFAULT_STEP_TIMEOUT_S = 900


@dataclass
class Step:
    name: str
    argv: list[str]
    required: bool = True


@dataclass
class Plan:
    steps: list[Step]
    run: list[str] | None
    preview: str | None
    source: str
    stack: str

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [{"name": s.name, "argv": s.argv, "required": s.required} for s in self.steps],
                "run": self.run, "preview": self.preview, "source": self.source, "stack": self.stack}


@dataclass
class Observation:
    name: str
    argv: list[str]
    exit_code: int | None
    seconds: float
    passed: bool
    output_tail: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "argv": self.argv, "exit_code": self.exit_code, "seconds": round(self.seconds, 2),
                "passed": self.passed, "required": self.required, "output_tail": self.output_tail[-MAX_OUTPUT:]}


def _npm() -> str | None:
    return shutil.which("npm.cmd") or shutil.which("npm")


def _python() -> str:
    return sys.executable


def _argv(value: Any) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value) and value:
        return list(value)
    if isinstance(value, str) and value.strip():
        return shlex.split(value, posix=os.name != "nt")
    return None


def _from_manifest(workspace: Path) -> Plan | None:
    path = workspace / MANIFEST
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    steps: list[Step] = []
    for name in ("install", "build", "lint", "test"):
        argv = _argv(payload.get(name))
        if argv:
            steps.append(Step(name, _resolve(argv), required=name in ("build", "test")))
    run = _argv(payload.get("run"))
    preview = payload.get("preview") if isinstance(payload.get("preview"), str) else None
    stack = payload.get("stack") if isinstance(payload.get("stack"), str) else "declared"
    if not steps and not run:
        return None
    return Plan(steps, run, preview, "manifest", stack)


def _resolve(argv: list[str]) -> list[str]:
    head = argv[0]
    if head in ("npm", "npx", "pnpm", "yarn") and os.name == "nt":
        found = shutil.which(head + ".cmd") or shutil.which(head)
        return [found or head, *argv[1:]]
    if head in ("python", "python3", "py"):
        return [_python(), *argv[1:]]
    return argv


def _package_scripts(workspace: Path) -> dict[str, str]:
    try:
        payload = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def detect(workspace: Path) -> Plan:
    manifest = _from_manifest(workspace)
    if manifest is not None:
        return manifest
    steps: list[Step] = []
    run: list[str] | None = None
    preview: str | None = None
    if (workspace / "package.json").is_file():
        npm = _npm() or "npm"
        scripts = _package_scripts(workspace)
        steps.append(Step("install", [npm, "ci"] if (workspace / "package-lock.json").is_file() else [npm, "install"], required=True))
        if "build" in scripts:
            steps.append(Step("build", [npm, "run", "build"]))
        if "lint" in scripts:
            steps.append(Step("lint", [npm, "run", "lint"], required=False))
        if "test" in scripts and "no test specified" not in scripts["test"]:
            steps.append(Step("test", [npm, "test", "--", "--run"] if "vitest" in scripts["test"] else [npm, "test"]))
        for name in ("dev", "start", "preview"):
            if name in scripts:
                run = [npm, "run", name]
                preview = "http://127.0.0.1:5173" if name == "dev" else None
                break
        return Plan(steps, run, preview, "package.json", "node")
    has_py = (workspace / "pyproject.toml").is_file() or (workspace / "requirements.txt").is_file() or any(workspace.glob("*.py"))
    if has_py:
        python = _python()
        if (workspace / "requirements.txt").is_file():
            steps.append(Step("install", [python, "-m", "pip", "install", "-q", "-r", "requirements.txt"], required=False))
        elif (workspace / "pyproject.toml").is_file():
            steps.append(Step("install", [python, "-m", "pip", "install", "-q", "-e", "."], required=False))
        steps.append(Step("build", [python, "-m", "compileall", "-q", "."]))
        if (workspace / "tests").is_dir() or list(workspace.glob("test_*.py")) or list(workspace.glob("*_test.py")):
            steps.append(Step("test", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]))
        for entry in ("main.py", "app.py", "server.py", "cli.py"):
            if (workspace / entry).is_file():
                run = [python, entry]
                break
        return Plan(steps, run, preview, "python", "python")
    if (workspace / "Cargo.toml").is_file():
        steps.append(Step("build", ["cargo", "build", "--locked"]))
        steps.append(Step("test", ["cargo", "test", "--locked"]))
        return Plan(steps, ["cargo", "run"], None, "Cargo.toml", "rust")
    if (workspace / "go.mod").is_file():
        steps.append(Step("build", ["go", "build", "./..."]))
        steps.append(Step("test", ["go", "test", "./..."]))
        return Plan(steps, ["go", "run", "."], None, "go.mod", "go")
    if (workspace / "index.html").is_file():
        return Plan([Step("build", [_python(), "-c", "import pathlib,sys; html=pathlib.Path('index.html').read_text(encoding='utf-8'); sys.exit(0 if '<html' in html.lower() else 1)"])],
                    [_python(), "-m", "http.server", "8765", "--bind", "127.0.0.1"], "http://127.0.0.1:8765", "index.html", "static-web")
    return Plan([], None, None, "none", "unknown")


def _run_step(step: Step, workspace: Path, timeout_s: int) -> Observation:
    started = time.time()
    if not step.argv or (shutil.which(step.argv[0]) is None and not Path(step.argv[0]).exists()):
        return Observation(step.name, step.argv, None, 0.0, False, f"executable not found: {step.argv[0] if step.argv else '?'}", step.required)
    env = dict(os.environ)
    env.setdefault("CI", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.pop("CLAUDECODE", None)
    try:
        completed = subprocess.run(step.argv, cwd=str(workspace), text=True, capture_output=True, encoding="utf-8",
                                   errors="replace", timeout=timeout_s, env=env, check=False, stdin=subprocess.DEVNULL)
        output = (completed.stdout or "") + ("\n--- stderr ---\n" + completed.stderr if completed.stderr else "")
        return Observation(step.name, step.argv, completed.returncode, time.time() - started, completed.returncode == 0,
                           output[-MAX_OUTPUT:], step.required)
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return Observation(step.name, step.argv, None, time.time() - started, False, (partial or "")[-MAX_OUTPUT:] + "\n--- timeout ---", step.required)
    except OSError as exc:
        return Observation(step.name, step.argv, None, time.time() - started, False, f"spawn failed: {exc}", step.required)


def run_plan(plan: Plan, workspace: Path, *, timeout_s: int = DEFAULT_STEP_TIMEOUT_S) -> list[Observation]:
    observations: list[Observation] = []
    for step in plan.steps:
        observation = _run_step(step, workspace, timeout_s)
        observations.append(observation)
        if not observation.passed and step.required and step.name == "install":
            break
    return observations


def verdict(observations: list[Observation]) -> tuple[bool, list[str]]:
    failures = [o.name for o in observations if o.required and not o.passed]
    return not failures, failures


def failure_digest(observations: list[Observation]) -> str:
    parts = []
    for o in observations:
        if not o.passed:
            parts.append(f"### {o.name} (exit {o.exit_code})\n{o.output_tail[-3000:]}")
    return "\n\n".join(parts)


__all__ = ["Plan", "Step", "Observation", "detect", "run_plan", "verdict", "failure_digest", "MANIFEST"]
