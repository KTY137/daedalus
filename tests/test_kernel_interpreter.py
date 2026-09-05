"""``daedalus.kernel.interpreter``: the interpreter for stdlib-only contained payloads.

The resolution is a property of the PAYLOAD, not of the gate: it is used by
callers whose child runs stdlib-only code under ``-I -S``. It is deliberately
not applied inside ``command_gate``, because the kernel's own pytest gate
(``pytest_gate_argv``) needs the venv's site-packages and its receipts are
verified against the exact argv it was handed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from daedalus.kernel import interpreter as I


@pytest.mark.parametrize(
    ("platform", "base", "expect_base"),
    [
        ("win32", "real", True),
        ("win32", "missing", False),
        ("win32", "absent", False),
        ("linux", "real", False),
        ("darwin", "real", False),
    ],
)
def test_stdlib_interpreter_resolution(tmp_path, monkeypatch, platform, base, expect_base):
    """win32 prefers an existing base interpreter; everything else keeps sys.executable."""
    monkeypatch.setattr(I.sys, "platform", platform)
    if base == "real":
        real = tmp_path / "base-python.exe"
        real.write_bytes(b"MZ")
        monkeypatch.setattr(I.sys, "_base_executable", str(real), raising=False)
    elif base == "missing":
        monkeypatch.setattr(I.sys, "_base_executable", str(tmp_path / "gone.exe"), raising=False)
    else:
        monkeypatch.delattr(I.sys, "_base_executable", raising=False)

    resolved = I.stdlib_interpreter()
    if expect_base:
        assert resolved == str(tmp_path / "base-python.exe")
    else:
        assert resolved == I.sys.executable


def test_resolve_python_argv_substitutes_only_a_leading_python_literal(monkeypatch):
    monkeypatch.setattr(I, "stdlib_interpreter", lambda: "/opt/base/python")
    assert I.resolve_python_argv(("python", "-I", "-c", "print(1)")) == (
        "/opt/base/python", "-I", "-c", "print(1)",
    )
    assert I.resolve_python_argv((sys.executable, "-c", "x")) == ("/opt/base/python", "-c", "x")
    # Anything else is handed back untouched: pytest, git, a candidate binary.
    assert I.resolve_python_argv(("git", "status")) == ("git", "status")
    assert I.resolve_python_argv(("/usr/bin/python3", "-m", "pytest")) == ("/usr/bin/python3", "-m", "pytest")
    assert I.resolve_python_argv(()) == ()


def test_resolve_python_argv_does_not_inspect_the_payload(monkeypatch):
    """Documented limitation (Codex review): argv[0] decides, the rest is not read.

    The kernel pytest gate keeps the venv interpreter because
    ``pytest_gate_argv`` never calls this helper, not because the helper
    recognises ``-m pytest``. Callers own the stdlib-only precondition.
    """
    monkeypatch.setattr(I, "stdlib_interpreter", lambda: "/opt/base/python")
    assert I.resolve_python_argv((sys.executable, "-m", "pytest", "-q")) == (
        "/opt/base/python", "-m", "pytest", "-q",
    )
    from daedalus.kernel.attempt_execution import pytest_gate_argv

    assert pytest_gate_argv([])[0] == sys.executable


def test_interpreter_provenance_is_path_free_and_content_bound(tmp_path):
    binary = tmp_path / "interp.exe"
    binary.write_bytes(b"MZ-interpreter-bytes")
    provenance = I.interpreter_provenance(str(binary))
    assert set(provenance) == {"implementation", "version", "platform", "binary_sha256"}
    assert provenance["binary_sha256"] == hashlib.sha256(b"MZ-interpreter-bytes").hexdigest()
    assert provenance["version"] == "%d.%d.%d" % sys.version_info[:3]
    assert provenance["implementation"] == sys.implementation.name
    assert str(tmp_path) not in json.dumps(provenance)
    assert all(type(value) is str for value in provenance.values())


def test_stdlib_interpreter_is_not_the_launcher_stub_on_this_host():
    """Discriminating witness: only meaningful where a venv launcher stub exists."""
    base = getattr(sys, "_base_executable", None)
    if sys.platform != "win32" or not base or not Path(base).is_file():
        pytest.skip("no venv base interpreter on this host; nothing to discriminate")
    if Path(base).resolve() == Path(sys.executable).resolve():
        pytest.skip("sys.executable is already the base interpreter; no launcher stub")
    resolved = Path(I.stdlib_interpreter())
    assert resolved.resolve() == Path(base).resolve()
    assert b"Making stdin inheritable" not in resolved.read_bytes()
    assert b"Making stdin inheritable" in Path(sys.executable).read_bytes(), (
        "this host's sys.executable is not the uv/venv stub the test documents"
    )
