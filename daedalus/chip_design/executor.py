"""Bounded execution receipts for EDA commands."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


_MAX_CAPTURE_CHARS = 128_000
_TRUNCATION_MARKER = "\n\n... [Daedalus truncated EDA output] ...\n\n"


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    argv: tuple[str, ...]
    cwd: str
    returncode: int | None
    duration_s: float
    stdout: str
    stderr: str
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _bounded(text: str | bytes) -> tuple[str, bool]:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= _MAX_CAPTURE_CHARS:
        return text, False

    payload_chars = _MAX_CAPTURE_CHARS - len(_TRUNCATION_MARKER)
    if payload_chars < 0:  # defensive if the constants are changed later
        return _TRUNCATION_MARKER[:_MAX_CAPTURE_CHARS], True
    head_chars = payload_chars // 2
    tail_chars = payload_chars - head_chars
    tail = text[-tail_chars:] if tail_chars else ""
    return text[:head_chars] + _TRUNCATION_MARKER + tail, True


def execute_argv(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    timeout_s: float = 300.0,
    dry_run: bool = True,
    env_overrides: Mapping[str, str] | None = None,
) -> ExecutionResult:
    if not argv or not str(argv[0]).strip():
        raise ValueError("argv must contain a command")
    root = Path(cwd).resolve()
    if not root.is_dir():
        raise ValueError(f"cwd is not a directory: {root}")
    clean_argv = tuple(str(x) for x in argv)
    if dry_run:
        return ExecutionResult(
            status="planned", argv=clean_argv, cwd=str(root), returncode=None,
            duration_s=0.0, stdout="", stderr="",
        )

    resolved = shutil.which(clean_argv[0])
    if not resolved:
        return ExecutionResult(
            status="missing", argv=clean_argv, cwd=str(root), returncode=None,
            duration_s=0.0, stdout="", stderr=f"{clean_argv[0]} not found on PATH",
        )
    run_argv = (resolved, *clean_argv[1:])
    env = os.environ.copy()
    if env_overrides:
        env.update({str(k): str(v) for k, v in env_overrides.items()})

    started = time.monotonic()
    try:
        completed = subprocess.run(
            run_argv,
            cwd=str(root),
            env=env,
            text=True,
            capture_output=True,
            timeout=float(timeout_s),
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - started
        out, trunc1 = _bounded(exc.stdout or "")
        err, trunc2 = _bounded(exc.stderr or "")
        return ExecutionResult(
            status="timeout", argv=clean_argv, cwd=str(root), returncode=None,
            duration_s=round(elapsed, 3), stdout=out, stderr=err,
            truncated=trunc1 or trunc2,
        )
    except OSError as exc:
        elapsed = time.monotonic() - started
        return ExecutionResult(
            status="error", argv=clean_argv, cwd=str(root), returncode=None,
            duration_s=round(elapsed, 3), stdout="", stderr=str(exc),
        )

    elapsed = time.monotonic() - started
    out, trunc1 = _bounded(completed.stdout or "")
    err, trunc2 = _bounded(completed.stderr or "")
    return ExecutionResult(
        status="ok" if completed.returncode == 0 else "failed",
        argv=clean_argv,
        cwd=str(root),
        returncode=completed.returncode,
        duration_s=round(elapsed, 3),
        stdout=out,
        stderr=err,
        truncated=trunc1 or trunc2,
    )
