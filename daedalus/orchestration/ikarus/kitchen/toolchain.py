"""Toolchain: detect how a candidate is built, tested and run, then run it.

The builder writes ``daedalus-candidate.json`` (``{"build": [...], "test": [...],
"run": [...], "preview": "..."}``); when it does not, detection falls back to
the lockfiles and layout on disk. Every command runs with a timeout, bounded
output and the workspace as cwd. Results are *observations*: a green check is
evidence, not promotion.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST = "daedalus-candidate.json"
MAX_OUTPUT = 12_000
DEFAULT_STEP_TIMEOUT_S = 900
_VERIFICATION_CONFIGS = {
    MANIFEST, "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod",
    "pytest.ini", "tox.ini", "setup.cfg", "setup.py", "conftest.py", "Makefile", "makefile",
    "justfile", ".npmrc", ".yarnrc", ".yarnrc.yml", ".mocharc.json", ".mocharc.js",
}
_IGNORED_VERIFICATION_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", "target", ".next", "coverage",
}
_EVALUATOR_DIRS = {"test", "tests", "__tests__", "__mocks__", "spec", "specs"}


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


@dataclass(frozen=True)
class FrozenVerification:
    """Selected check contract and evaluator bytes retained outside the candidate.

    This detects drift in declared commands, conventional evaluator/config files
    and local command targets. It is not process containment or proof that a
    generated evaluator independently establishes product correctness.
    """

    plan_json: str
    files: tuple[tuple[str, str], ...]
    error: str | None = None


def _plan_json(plan: Plan) -> str:
    return json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":"))


def _local_command_targets(plan: Plan, workspace: Path) -> set[Path]:
    """Resolve local scripts/config arguments, including Python module commands."""
    targets: set[Path] = set()
    commands = [step.argv for step in plan.steps]
    # npm's argv names the script; package.json contains its local entrypoint.
    # Follow only selected checks: a start script may name repairable app code.
    scripts = _package_scripts(workspace)
    selected_scripts: set[str] = set()
    for command in commands:
        for index, arg in enumerate(command):
            if Path(arg).name.lower() in {"npm", "npm.cmd", "pnpm", "pnpm.cmd", "yarn", "yarn.cmd"}:
                script_index = index + 1
                if script_index < len(command) and command[script_index] == "run":
                    script_index += 1
                script = command[script_index] if script_index < len(command) else ""
                body = scripts.get(script)
                if script not in selected_scripts and isinstance(body, str):
                    selected_scripts.add(script)
                    try:
                        commands.append(shlex.split(body, posix=os.name != "nt"))
                    except ValueError:
                        pass
            values = [arg.strip("\"'")]
            if index and command[index - 1] == "-m":
                values = [arg.replace(".", "/") + ".py", arg.replace(".", "/")]
            for value in values:
                # Options such as --config=checks.json also select evaluator input.
                value = value.partition("=")[2] if value.startswith("-") and "=" in value else value
                path = workspace / value
                try:
                    lexical = Path(os.path.abspath(path))
                    local = lexical.is_relative_to(workspace)
                    resolved = path.resolve()
                except (OSError, ValueError):
                    continue
                if local and lexical.is_symlink():
                    raise ValueError(f"verification command target is a symlink: {lexical.relative_to(workspace).as_posix()}")
                if not resolved.is_relative_to(workspace):
                    continue
                if resolved.is_file() or (resolved.is_dir() and index and command[index - 1] == "-m"):
                    targets.add(resolved)
    return targets


def _verification_files(plan: Plan, workspace: Path) -> tuple[tuple[str, str], ...]:
    workspace = workspace.resolve()
    targets = _local_command_targets(plan, workspace)
    files: list[tuple[str, str]] = []

    def fail_walk(error: OSError) -> None:
        raise error

    for directory, dirs, names in os.walk(workspace, onerror=fail_walk, followlinks=False):
        dirs[:] = [name for name in dirs if name not in _IGNORED_VERIFICATION_DIRS
                   or any(target.is_relative_to(Path(directory) / name) for target in targets)]
        relative_dir = Path(directory).relative_to(workspace)
        for name in names:
            path = Path(directory) / name
            relative = relative_dir / name
            lowered = name.lower()
            config = name in _VERIFICATION_CONFIGS or lowered.startswith((
                "vitest.config.", "vite.config.", "jest.config.", "webpack.config.", "tsconfig",
            ))
            evaluator = bool(set(relative.parts[:-1]) & _EVALUATOR_DIRS) or (
                lowered.startswith("test_") or lowered.endswith("_test.py")
                or ".test." in lowered or ".spec." in lowered
            )
            command_target = path.resolve() in targets or any(parent in targets for parent in path.resolve().parents)
            if config or evaluator or command_target:
                if path.is_symlink():
                    raise ValueError(f"verification file is a symlink: {relative.as_posix()}")
                files.append((relative.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink() and (set((relative_dir / name).parts) & _EVALUATOR_DIRS or path.resolve() in targets):
                raise ValueError(f"verification directory is a symlink: {path.relative_to(workspace).as_posix()}")
    return tuple(sorted(files))


def freeze_verification(plan: Plan, workspace: Path) -> FrozenVerification:
    """Freeze before the first check; keep the returned object outside repairs."""
    try:
        return FrozenVerification(_plan_json(plan), _verification_files(plan, workspace))
    except (OSError, ValueError) as exc:
        return FrozenVerification(_plan_json(plan), (), f"cannot freeze verification: {exc}")


def verification_integrity(frozen: FrozenVerification, plan: Plan, workspace: Path) -> Observation | None:
    """Return a required failure on drift; check before and after every run."""
    reason = frozen.error
    if not reason:
        try:
            if _plan_json(plan) != frozen.plan_json or _plan_json(detect(workspace)) != frozen.plan_json:
                reason = "selected verification plan changed"
            current = dict(_verification_files(plan, workspace))
            original = dict(frozen.files)
            changed = sorted(name for name in original.keys() | current.keys() if original.get(name) != current.get(name))
            if changed:
                reason = "verification inputs changed: " + ", ".join(changed)
        except (OSError, ValueError) as exc:
            reason = f"cannot verify frozen verification inputs: {exc}"
    if reason:
        return Observation("verification_integrity", [], None, 0.0, False, reason, True)
    return None


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
    failures = [o.name for o in observations if o.required and (not o.passed or o.exit_code != 0)]
    if not any(o.required and o.name in ("build", "test") and o.argv for o in observations):
        failures.append("required_verification_missing")
    return not failures, failures


def failure_digest(observations: list[Observation]) -> str:
    parts = []
    for o in observations:
        if not o.passed:
            parts.append(f"### {o.name} (exit {o.exit_code})\n{o.output_tail[-3000:]}")
    return "\n\n".join(parts)


__all__ = ["Plan", "Step", "Observation", "FrozenVerification", "detect", "run_plan", "verdict",
           "freeze_verification", "verification_integrity", "failure_digest", "MANIFEST"]
