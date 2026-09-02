"""G1-HIER-03B acceptance for the kernel-owned Attempt lifecycle core."""

from __future__ import annotations

import ast
import importlib
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import REGISTRY_BY_ID, registry_sha256


REPO_ROOT = Path(__file__).resolve().parents[2]
OWNER_PATH = REPO_ROOT / "daedalus" / "kernel" / "attempt_execution.py"
FACADE_PATH = REPO_ROOT / "daedalus" / "spine" / "attempt.py"


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def test_owner_has_no_kairos_or_evaluator_import_edge() -> None:
    forbidden = ("daedalus.kairos", "daedalus.eval")
    violations = [
        f"{line}:{name}"
        for line, name in _imports(OWNER_PATH)
        if name.startswith(forbidden)
    ]
    assert violations == []


def test_cold_owner_import_does_not_load_default_composition() -> None:
    code = (
        "import json,sys; "
        "import daedalus.kernel.attempt_execution; "
        "print(json.dumps(sorted(n for n in sys.modules "
        "if n == 'daedalus.kairos' or n.startswith('daedalus.kairos.') "
        "or n == 'daedalus.eval' or n.startswith('daedalus.eval.'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "[]"


def test_legacy_objects_resolve_to_one_owner_except_documented_composition() -> None:
    facade = importlib.import_module("daedalus.spine.attempt")
    owner = importlib.import_module("daedalus.kernel.attempt_execution")

    for name in (
        "TaskSpec",
        "TaskSpecInvalid",
        "RunnerContext",
        "AttemptResult",
        "GateResult",
        "PatchArtifact",
        "GitCommandError",
        "_git",
        "_contained_gate_child",
        "offload_runner",
        "pytest_gate_argv",
    ):
        assert getattr(facade, name) is getattr(owner, name)

    assert facade.TaskAttempt.__bases__ == (owner.TaskAttempt,)
    assert facade.TaskAttempt.__module__ == "daedalus.spine.attempt"
    assert owner.TaskAttempt.__module__ == "daedalus.kernel.attempt_execution"
    assert "run" not in owner.TaskAttempt.__dict__
    assert "run" in facade.TaskAttempt.__dict__


def test_legacy_pickle_globals_resolve_after_the_owner_cut() -> None:
    facade = importlib.import_module("daedalus.spine.attempt")
    owner = importlib.import_module("daedalus.kernel.attempt_execution")
    assert pickle.loads(
        b"cdaedalus.spine.attempt\nTaskSpec\n."
    ) is owner.TaskSpec
    assert pickle.loads(
        b"cdaedalus.spine.attempt\nTaskAttempt\n."
    ) is facade.TaskAttempt


class _Workspace:
    def __init__(self, root: Path) -> None:
        self.worktree_root = root

    def create_worktree(self, base_commit: str, branch_name: str) -> Path:
        raise AssertionError("construction must not materialize a workspace")

    def cleanup_worktree(self, path: str | Path) -> None:
        raise AssertionError("construction must not clean a workspace")

    def reap_branches(self) -> list[dict]:
        return []


class _Evaluator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def command_gate(self, argv, *, timeout_s, name):
        self.calls.append(("command", (tuple(argv), timeout_s, name)))
        return lambda _ctx: True

    def correctness_gate(self, task, repo_root, *, timeout_s):
        self.calls.append(("correctness", (task, repo_root, timeout_s)))
        return lambda _ctx: True

    def pytest_gate(self, paths, *, timeout_s, use_default_timeout):
        self.calls.append(
            ("pytest", (tuple(paths), timeout_s, use_default_timeout))
        )
        return lambda _ctx: True


def test_kernel_core_fails_closed_without_workspace_or_evaluator_ports(
    tmp_path: Path,
) -> None:
    owner = importlib.import_module("daedalus.kernel.attempt_execution")
    task = owner.TaskSpec("port-test", "change a file")

    with pytest.raises(owner.AttemptPortMissing, match="workspace_port"):
        owner.TaskAttempt(task, runner=lambda _ctx: None, gate=lambda _ctx: True)

    with pytest.raises(owner.AttemptPortMissing, match="evaluator_port"):
        owner.TaskAttempt(
            task,
            runner=lambda _ctx: None,
            workspace_port=_Workspace(tmp_path),
        )


def test_kernel_core_uses_the_injected_evaluator_and_exact_workspace(
    tmp_path: Path,
) -> None:
    owner = importlib.import_module("daedalus.kernel.attempt_execution")
    evaluator = _Evaluator()
    workspace = _Workspace(tmp_path)
    task = owner.TaskSpec(
        "port-test",
        "change a file",
        fail_to_pass=("tests/test_value.py::test_value",),
    )

    attempt = owner.TaskAttempt(
        task,
        runner=lambda _ctx: None,
        repo_root=tmp_path,
        workspace_port=workspace,
        evaluator_port=evaluator,
    )

    assert attempt._manager is workspace
    assert evaluator.calls == [
        ("correctness", (task, tmp_path.resolve(), task.gate_timeout_s))
    ]


def test_definitions_and_registry_targets_remain_single_and_stable() -> None:
    owner_tree = ast.parse(OWNER_PATH.read_text(encoding="utf-8"))
    facade_tree = ast.parse(FACADE_PATH.read_text(encoding="utf-8"))

    owner_classes = {
        node.name for node in owner_tree.body if isinstance(node, ast.ClassDef)
    }
    facade_classes = {
        node.name for node in facade_tree.body if isinstance(node, ast.ClassDef)
    }
    assert {"TaskSpec", "RunnerContext", "AttemptResult", "TaskAttempt"} <= (
        owner_classes
    )
    assert "TaskSpec" not in facade_classes
    assert "RunnerContext" not in facade_classes
    assert "AttemptResult" not in facade_classes
    assert "TaskAttempt" in facade_classes  # registered composition door only

    assert REGISTRY_BY_ID["python.attempt"].target == (
        "daedalus.spine.attempt:run_attempt"
    )
    assert REGISTRY_BY_ID["python.command_gate"].target == (
        "daedalus.spine.attempt:command_gate"
    )
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )


def test_offload_runner_refuses_without_the_injected_workload_port() -> None:
    """The kernel takes the workload as a port and refuses without it.

    G1-SCC-CUT1 retired the repository's single recorded boundary violation --
    ``daedalus/kernel/attempt_execution.py`` importing ``daedalus.offload`` --
    by handing the workload in instead. The refusal is what stops that from
    being a silent capability loss: a caller that forgot to compose the port
    gets told, at COMPOSITION time, before a worktree, a branch or a provider
    call exists.
    """
    owner = importlib.import_module("daedalus.kernel.attempt_execution")

    with pytest.raises(owner.AttemptPortMissing) as excinfo:
        owner.offload_runner(live=True)
    assert "offload" in str(excinfo.value)

    # The kernel names the workload in no import statement, at any scope. The
    # census in tests/contracts/test_import_scc_hierarchy.py counts an edge
    # wherever an import APPEARS, module or function body, so a deferred
    # re-import inside the runner would reinstate the violation while looking
    # local. Assert over the parsed imports, not over the source text: the
    # docstring and the refusal message both mention daedalus.offload on
    # purpose, and a substring check would forbid explaining the boundary.
    assert not [
        (line, name)
        for line, name in _imports(OWNER_PATH)
        if name == "daedalus.offload" or name.startswith("daedalus.offload.")
    ]


def test_offload_port_resolves_the_workload_attribute_at_call_time(monkeypatch) -> None:
    """The composed port must re-read the module attribute on every call.

    This is the fixture-killing shape this repository keeps meeting: if
    ``offload_port()`` returned ``daedalus.offload.offload`` itself, it would
    bind the function object once at composition time. Every existing test that
    monkeypatches that exact module attribute would keep passing while the
    runner called the original -- green, and testing nothing.

    So: compose the port FIRST, patch the attribute AFTERWARDS, and require the
    patch to win. Capturing at composition time reds this test.
    """
    from daedalus.orchestration.execution import offload_port

    port = offload_port()

    calls: list[tuple[object, ...]] = []

    def _fake_offload(*args, **kwargs):
        calls.append((args, kwargs))
        return {"action": "stubbed", "wrote": []}

    monkeypatch.setattr("daedalus.offload.offload", _fake_offload)

    assert port.run_offload("objective", "/tmp/wt", live=False) == {
        "action": "stubbed",
        "wrote": [],
    }
    assert calls == [(("objective", "/tmp/wt"), {"live": False})]
