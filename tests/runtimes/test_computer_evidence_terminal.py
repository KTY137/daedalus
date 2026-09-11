"""Terminal capability: the fence that keeps it absent (plan §7.2, §11 Gate 1).

Daedalus has no terminal/shell adapter. The general-computer-assistance strand
therefore has to prove *absence*: no command-execution tool exists in the
canonical computer vocabulary, and `app.launch` cannot be turned into a shell by
naming an interpreter as a trusted host application.

Offline, deterministic, no host effect: every case is `ComputerPolicy`
construction or `.admit()`. No process is created.

Which production change turns these red:

* Deleting or shrinking the interpreter stem set in
  `daedalus/kernel/policy/computer.py::ComputerPolicy.__post_init__`
  ("interpreters require a contained terminal adapter, not trusted app.launch").
  Only `python` was pinned before this file (via
  `tests/interfaces/test_computer_configuration.py::
  test_host_configuration_cannot_grant_candidate_or_interpreter_execution`,
  which uses `sys.executable`); the other twelve stems were unguarded by tests.
* Dropping the `.casefold()` so `PowerShell.EXE` slips past.
* Adding a shell/terminal/process tool name to `ALL_COMPUTER_TOOLS` in the same
  module without its own Work Packet and adapter.
* Removing the unknown-tool rejection in `ComputerPolicy.__post_init__` or the
  `tool not in self.tools` check in `ComputerPolicy.admit`.
"""
from __future__ import annotations

import pytest

from daedalus.kernel.policy.computer import (
    ALL_COMPUTER_TOOLS,
    ARIADNE_TOOLS,
    BROWSER_TOOLS,
    DAEDALUS_TOOLS,
    DESKTOP_TOOLS,
    FILE_TOOLS,
    VISION_TOOLS,
    ComputerPolicy,
    ComputerRefused,
)

# The exact stem set the policy refuses today. Kept literal on purpose: this
# test is the inventory, so a silent shrink of the production set breaks it.
INTERPRETER_STEMS = (
    "python", "python3", "pythonw", "node", "cmd", "powershell", "pwsh",
    "bash", "sh", "wscript", "cscript", "mshta", "rundll32",
)


def _policy(tmp_path, executable_name: str) -> ComputerPolicy:
    """Build a policy whose one trusted application is `executable_name`.

    The executable lives outside the workspace so the *candidate executable*
    refusal cannot fire first and make an interpreter case pass for the wrong
    reason.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    apps = tmp_path / "owner-apps"
    apps.mkdir(exist_ok=True)
    return ComputerPolicy(
        workspace,
        tools=("app.launch",),
        applications=(("host", (str((apps / executable_name).resolve()),)),),
    )


@pytest.mark.parametrize("stem", INTERPRETER_STEMS)
def test_every_interpreter_stem_is_refused_as_a_trusted_application(tmp_path, stem):
    with pytest.raises(ComputerRefused, match="interpreters require a contained terminal adapter"):
        _policy(tmp_path, f"{stem}.exe")


@pytest.mark.parametrize("name", ["PowerShell.EXE", "CMD.Exe", "Bash", "PyThOn3.exe"])
def test_interpreter_refusal_is_case_insensitive(tmp_path, name):
    with pytest.raises(ComputerRefused, match="interpreters require a contained terminal adapter"):
        _policy(tmp_path, name)


def test_a_non_interpreter_application_is_still_admitted(tmp_path):
    """Positive control: the refusals above are caused by the stem, nothing else."""
    policy = _policy(tmp_path, "fixture-editor.exe")
    assert dict(policy.applications)["host"][0].endswith("fixture-editor.exe")
    policy.admit("app.launch", {"application": "host"})


def test_the_canonical_vocabulary_contains_no_command_execution_tool():
    """No terminal capability may appear without its own packet and adapter."""
    # G1-IKARUS-46 added the read-only `daedalus.*` observation family with its
    # own packet and adapter (`daedalus.runtimes.computer_daedalus`); the
    # read-only contract is pinned in tests/runtimes/test_computer_daedalus.py.
    # G1-IKARUS-47 added ONE host-mutating member of the same family,
    # `daedalus.ariadne_campaign` (adapter `daedalus.runtimes.computer_ariadne`,
    # granted separately with `confirm-campaigns`), which nominates and never
    # applies; its contract is pinned in tests/runtimes/test_computer_ariadne.py.
    # Neither family is a command execution tool, which is what this test guards.
    assert ALL_COMPUTER_TOOLS == frozenset(
        FILE_TOOLS + VISION_TOOLS + DESKTOP_TOOLS + BROWSER_TOOLS + DAEDALUS_TOOLS + ARIADNE_TOOLS)
    families = {name.split(".", 1)[0] for name in ALL_COMPUTER_TOOLS}
    # "app" is `app.launch` only, and it is fenced against interpreters above.
    assert families == {"file", "vision", "desktop", "browser", "app", "daedalus"}
    assert {n for n in ALL_COMPUTER_TOOLS if n.startswith("app.")} == {"app.launch"}
    forbidden = {"shell", "terminal", "process", "exec", "run", "cmd", "command", "script", "subprocess"}
    assert not families & forbidden
    assert not {n for n in ALL_COMPUTER_TOOLS if n.split(".", 1)[1] in {"run", "exec", "spawn", "shell"}}


@pytest.mark.parametrize("tool", ["shell.run", "terminal.exec", "process.spawn", "desktop.shell"])
def test_a_shell_shaped_tool_cannot_be_configured_or_admitted(tmp_path, tool):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    with pytest.raises(ComputerRefused, match="tools must be unique known computer tools"):
        ComputerPolicy(workspace, tools=(tool,))
    enabled = ComputerPolicy(workspace, tools=DESKTOP_TOOLS)
    with pytest.raises(ComputerRefused, match="tool is not enabled"):
        enabled.admit(tool, {})


def test_app_launch_is_refused_when_the_owner_did_not_enable_the_application(tmp_path):
    policy = _policy(tmp_path, "fixture-editor.exe")
    with pytest.raises(ComputerRefused, match="application is not enabled"):
        policy.admit("app.launch", {"application": "other"})
