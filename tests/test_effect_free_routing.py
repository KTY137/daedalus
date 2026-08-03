"""A frozen routing leaf must not discover, build, probe, or mutate.

The fixture index is built by the real StructCore implementation before the
planning boundary.  Inside that boundary every relevant mutation, process, and
network seam raises immediately.  This is deliberately one chain test over the
production router rather than isolated mocks of its helpers.
"""

from __future__ import annotations

import builtins
import concurrent.futures
import hashlib
import io
import json
import os
import socket
import subprocess
import urllib.request
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from daedalus.provider_router import (
    LATENT_DISABLED,
    route_and_select_precomputed,
)
from daedalus.structcore.index import build_index


AVAILABILITY = {
    "claude_cli": True,
    "ollama": True,
    "deepseek": False,
    "codex_cli": False,
}


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _chain_repo(root: Path) -> None:
    _write(
        root,
        "utils/clamp.py",
        "def clamp(v, lo, hi):\n    return max(lo, min(hi, v))\n",
    )
    _write(
        root,
        "lib/mid.py",
        "from utils.clamp import clamp\n\n"
        "def scale(v):\n    return clamp(v, 0, 10)\n",
    )
    _write(
        root,
        "controller/hv_interlock.py",
        "from lib.mid import scale\n\n"
        "def trip(v):\n    return scale(v) > 5\n",
    )
    # A real project-local role keeps the chain independent of the repository's
    # global roster and makes the un-fenced baseline an Ollama write.
    _write(
        root,
        ".agentenv/agents/coder.json",
        json.dumps(
            {
                "name": "coder",
                "call_name": "Coder",
                "external_ok": True,
                "owns": ["utils/"],
                "triggers": ["adjust"],
            }
        ),
    )


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@contextmanager
def _refuse_planning_effects():
    """Reject writes, process starts, network calls, probes, and index builds."""

    attempted: list[str] = []

    def reject(name: str):
        def _blocked(*_args, **_kwargs):
            attempted.append(name)
            raise AssertionError(f"planning attempted forbidden effect: {name}")

        return _blocked

    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in "wax+"):
            return reject("filesystem.open-write")(file, mode, *args, **kwargs)
        return original_open(file, mode, *args, **kwargs)

    def guarded_io_open(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in "wax+"):
            return reject("filesystem.io-open-write")(file, mode, *args, **kwargs)
        return original_io_open(file, mode, *args, **kwargs)

    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & write_flags:
            return reject("filesystem.os-open-write")(path, flags, *args, **kwargs)
        return original_os_open(path, flags, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch("builtins.open", guarded_open))
        stack.enter_context(patch("io.open", guarded_io_open))
        stack.enter_context(patch("os.open", guarded_os_open))
        for name in ("mkdir", "makedirs", "remove", "unlink", "rename", "replace"):
            stack.enter_context(patch(f"os.{name}", reject(f"filesystem.os-{name}")))
        for name in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace"):
            stack.enter_context(
                patch.object(Path, name, reject(f"filesystem.path-{name}"))
            )

        stack.enter_context(
            patch("daedalus.structcore.index.FileCache", reject("structcore.FileCache"))
        )
        stack.enter_context(
            patch(
                "daedalus.structcore.index.cached_index",
                reject("structcore.cached_index"),
            )
        )
        stack.enter_context(
            patch.object(
                concurrent.futures,
                "ProcessPoolExecutor",
                reject("process.ProcessPoolExecutor"),
            )
        )
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            stack.enter_context(
                patch.object(subprocess, name, reject(f"process.subprocess.{name}"))
            )

        stack.enter_context(
            patch.object(socket.socket, "connect", reject("network.socket.connect"))
        )
        stack.enter_context(
            patch.object(socket, "create_connection", reject("network.create_connection"))
        )
        stack.enter_context(
            patch.object(urllib.request, "urlopen", reject("network.urlopen"))
        )
        stack.enter_context(
            patch(
                "daedalus.provider_router.semantic_route_explained",
                reject("network.embedding-route"),
            )
        )
        stack.enter_context(
            patch(
                "daedalus.provider_router.available_providers",
                reject("provider.availability-probe"),
            )
        )
        stack.enter_context(patch("daedalus.doctor.check", reject("doctor.check")))
        stack.enter_context(patch("daedalus.doctor.main", reject("doctor.main")))
        yield attempted


def test_precomputed_route_runs_the_real_chain_without_planning_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "chain"
        _chain_repo(root)
        # Index construction is an explicit upstream artifact step, outside the
        # no-effect planning boundary. Disable pool use only to keep this test's
        # setup cheap; the returned graph is produced by real StructCore code.
        monkeypatch.setenv("DAEDALUS_SCAN_WORKERS", "0")
        idx = build_index(root)
        before = _snapshot(root)

        with _refuse_planning_effects() as attempted:
            agent, decision = route_and_select_precomputed(
                "Adjust the clamp helper defaults",
                ["utils/clamp.py"],
                availability=AVAILABILITY,
                repo_root=str(root),
                idx=idx,
            )

        assert attempted == []
        assert _snapshot(root) == before
        assert agent["name"] == "coder"
        assert decision.provider == "claude_cli"
        assert decision.risk == "high"
        assert decision.reachability["escalate"] is True
        assert decision.reachability["chain"] == [
            "utils/clamp.py",
            "lib/mid.py",
            "controller/hv_interlock.py",
        ]
        assert decision.latent_route["mechanism"] == LATENT_DISABLED
        assert decision.latent_route["attempted"] is False


def test_precomputed_route_refuses_an_index_bound_to_another_repository() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "target"
        other = Path(tmp) / "other"
        _chain_repo(root)
        idx = {"root": str(other), "modules": {}, "import_edges": {}}

        with _refuse_planning_effects() as attempted:
            with pytest.raises(ValueError, match="does not match repo_root"):
                route_and_select_precomputed(
                    "Adjust the clamp helper defaults",
                    ["utils/clamp.py"],
                    availability=AVAILABILITY,
                    repo_root=str(root),
                    idx=idx,
                )

        assert attempted == []
