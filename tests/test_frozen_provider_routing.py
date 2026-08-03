"""Frozen provider selection is a value-only Gate-0 planning leaf."""

from __future__ import annotations

import builtins
import concurrent.futures
import io
import os
import socket
import subprocess
import urllib.request
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from daedalus import doctor, router
from daedalus.provider_router import (
    FROZEN_PATH_ABSENT,
    FROZEN_PATH_INDEXED,
    FROZEN_PATH_PRESENT_UNINDEXED,
    FROZEN_PATH_UNREADABLE,
    FrozenRoutingInputError,
    select_provider_frozen,
)
from daedalus.sensitivity import Policy
from daedalus.structcore.index import build_index


AVAILABILITY = {
    "claude_cli": True,
    "ollama": True,
    "deepseek": False,
    "codex_cli": False,
}
AGENT = {
    "name": "frozen-coder",
    "call_name": "Frozen Coder",
    "external_ok": False,
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
    _write(root, "docs/helper.py", "def render():\n    return 'safe'\n")


@contextmanager
def _deny_ambient_effects():
    attempted: list[str] = []

    def reject(name: str, exc_type=AssertionError):
        def _blocked(*_args, **_kwargs):
            attempted.append(name)
            raise exc_type(f"frozen routing attempted {name}")

        return _blocked

    with ExitStack() as stack:
        # All patch targets are imported before these generic I/O refusals.
        stack.enter_context(patch("builtins.open", reject("filesystem.open")))
        stack.enter_context(patch("io.open", reject("filesystem.io.open")))
        stack.enter_context(patch("os.scandir", reject("filesystem.scandir")))
        stack.enter_context(
            patch.object(
                Path,
                "is_file",
                reject("filesystem.Path.is_file", PermissionError),
            )
        )
        for name in ("exists", "is_dir", "glob", "write_text", "write_bytes", "mkdir"):
            stack.enter_context(
                patch.object(Path, name, reject(f"filesystem.Path.{name}"))
            )
        stack.enter_context(patch.object(router, "load_agents", reject("role-roster-read")))
        stack.enter_context(patch.object(router, "route_task", reject("role-routing-probe")))
        stack.enter_context(
            patch(
                "daedalus.provider_router.external_write_lanes_for_repo",
                reject("policy-file-read"),
            )
        )
        stack.enter_context(
            patch(
                "daedalus.provider_router.available_providers",
                reject("provider-probe"),
            )
        )
        stack.enter_context(
            patch("daedalus.provider_router.persona_for", reject("persona-file-read"))
        )
        stack.enter_context(
            patch("daedalus.sensitivity.lane_for_host", reject("ambient-host-lane"))
        )
        stack.enter_context(
            patch("daedalus.structcore.index.cached_index", reject("index-cache"))
        )
        stack.enter_context(
            patch("daedalus.structcore.index.FileCache", reject("file-cache"))
        )
        stack.enter_context(patch.object(doctor, "check", reject("doctor.check")))
        stack.enter_context(patch.object(doctor, "main", reject("doctor.main")))
        stack.enter_context(
            patch.object(
                concurrent.futures,
                "ProcessPoolExecutor",
                reject("process-pool"),
            )
        )
        stack.enter_context(patch.object(subprocess, "Popen", reject("subprocess.Popen")))
        stack.enter_context(patch.object(subprocess, "run", reject("subprocess.run")))
        stack.enter_context(
            patch.object(socket.socket, "connect", reject("network.socket.connect"))
        )
        stack.enter_context(
            patch.object(urllib.request, "urlopen", reject("network.urlopen"))
        )
        stack.enter_context(
            patch("daedalus.provider_router.logger.handle", reject("logging-handler"))
        )
        yield attempted


def _select(idx: dict, path: str, state: str):
    return select_provider_frozen(
        AGENT,
        "Adjust the helper defaults",
        [path],
        policy=Policy(),
        availability=AVAILABILITY,
        ollama_endpoint="http://127.0.0.1:11434",
        ollama_lane="trusted",
        external_write_lanes=(),
        idx=idx,
        path_states={path: state},
    )


def test_real_frozen_chain_ignores_ollama_env_flip_and_source_stat_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "chain"
        _chain_repo(root)
        # Real StructCore extraction is the upstream artifact-producing phase,
        # outside the pure planning boundary.
        monkeypatch.setenv("DAEDALUS_SCAN_WORKERS", "0")
        idx = build_index(root)

        with _deny_ambient_effects() as attempted:
            monkeypatch.setenv("DAEDALUS_TRUSTED_HOSTS", "")
            monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
            loopback = _select(idx, "docs/helper.py", FROZEN_PATH_INDEXED)

            # The ambient endpoint now says the opposite, but the same frozen
            # observation must produce byte-identical output.
            monkeypatch.setenv("OLLAMA_HOST", "http://203.0.113.7:11434")
            remote_ambient = _select(idx, "docs/helper.py", FROZEN_PATH_INDEXED)

            fenced = _select(idx, "utils/clamp.py", FROZEN_PATH_INDEXED)
            stale = _select(
                idx, "new_helper.py", FROZEN_PATH_PRESENT_UNINDEXED)

            assert loopback.as_dict() == remote_ambient.as_dict()

        assert attempted == []
        assert (loopback.provider, loopback.mode, loopback.risk) == (
            "ollama",
            "write",
            "low",
        )
        assert fenced.provider == "claude_cli"
        assert fenced.risk == "high"
        assert fenced.reachability["chain"] == [
            "utils/clamp.py",
            "lib/mid.py",
            "controller/hv_interlock.py",
        ]
        assert stale.provider == "claude_cli"
        assert stale.risk == "high"
        assert stale.reachability["escalate"] is True
        assert "present but absent" in stale.reachability["reason"]


def test_missing_or_unreadable_frozen_path_fact_is_refused() -> None:
    idx = {
        "root": "frozen/repo",
        "modules": {"known.py": {"loc": 1}},
        "import_edges": {},
        "import_edges_reverse": {},
    }
    common = {
        "policy": Policy(),
        "availability": AVAILABILITY,
        "ollama_endpoint": "http://127.0.0.1:11434",
        "ollama_lane": "trusted",
        "external_write_lanes": (),
        "idx": idx,
    }

    with pytest.raises(FrozenRoutingInputError, match="fact missing"):
        select_provider_frozen(
            AGENT, "Adjust helper", ["unknown.py"], path_states={}, **common)
    with pytest.raises(FrozenRoutingInputError, match="unreadable"):
        select_provider_frozen(
            AGENT,
            "Adjust helper",
            ["unknown.py"],
            path_states={"unknown.py": FROZEN_PATH_UNREADABLE},
            **common,
        )

    # A source artifact claiming absence while the graph contains the node is a
    # contradiction. It is not silently accepted as a cheap-lane plan.
    contradicted = select_provider_frozen(
        AGENT,
        "Adjust helper",
        ["known.py"],
        path_states={"known.py": FROZEN_PATH_ABSENT},
        **common,
    )
    assert contradicted.provider == "claude_cli"
    assert contradicted.risk == "high"
    assert contradicted.reachability["escalate"] is True
