"""G1-HIER-03D acceptance for explicit Attempt production composition."""
from __future__ import annotations

import ast
import importlib
import json
import pickle
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.orchestration.execution as execution_composition
import daedalus.orchestration.execution.attempts as composition
import daedalus.spine.attempt as attempt_door
import daedalus.spine.effect_boundary as boundary
from daedalus.kernel import attempt_execution as owner
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, registry_sha256


ROOT = Path(__file__).resolve().parents[2]
SPINE_ATTEMPT = ROOT / "daedalus" / "spine" / "attempt.py"
GATED_WRITES = ROOT / "daedalus" / "kairos" / "_gated_writes_legacy.py.src"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return tuple(found)


class _Workspace:
    def __init__(self, root: Path) -> None:
        self.worktree_root = root

    def create_worktree(self, _base: str, _branch: str) -> Path:
        raise AssertionError("construction must not create a worktree")

    def cleanup_worktree(self, _path: str | Path) -> None:
        raise AssertionError("construction must not clean a worktree")

    def reap_branches(self) -> list[dict]:
        return []


class _Evaluator:
    def __init__(self, gate: object) -> None:
        self.gate = gate
        self.calls: list[tuple] = []

    def command_gate(self, argv, *, timeout_s, name):
        self.calls.append(("command", tuple(argv), timeout_s, name))
        return self.gate

    def correctness_gate(self, task, repo_root, *, timeout_s):
        self.calls.append(("correctness", task, repo_root, timeout_s))
        return self.gate

    def pytest_gate(self, paths, *, timeout_s, use_default_timeout):
        self.calls.append(
            ("pytest", tuple(paths), timeout_s, use_default_timeout)
        )
        return self.gate


def test_spine_attempt_has_zero_outer_layer_imports_and_no_import_trick() -> None:
    imports = _imports(SPINE_ATTEMPT)
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imports
        for prefix in (
            "daedalus.eval",
            "daedalus.kairos",
            "daedalus.orchestration",
        )
    )
    source = SPINE_ATTEMPT.read_text(encoding="utf-8")
    assert "importlib" not in source
    assert "__import__(" not in source


def test_cold_spine_attempt_import_loads_no_composition_owner() -> None:
    probe = (
        "import json,sys; import daedalus.spine.attempt; "
        "print(json.dumps(sorted(name for name in sys.modules if "
        "name == 'daedalus.eval' or name.startswith('daedalus.eval.') or "
        "name == 'daedalus.kairos' or name.startswith('daedalus.kairos.') or "
        "name == 'daedalus.orchestration.execution' or "
        "name.startswith('daedalus.orchestration.execution.'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == []


def test_uncomposed_registered_doors_fail_before_runner_or_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = owner.TaskSpec("missing-ports", "do nothing")
    runner_calls: list[object] = []

    with pytest.raises(owner.AttemptPortMissing, match="workspace_port"):
        attempt_door.run_attempt(
            task,
            runner=lambda ctx: runner_calls.append(ctx),
            gate=lambda _ctx: True,
        )
    assert runner_calls == []

    with pytest.raises(owner.AttemptPortMissing, match="evaluator_port"):
        attempt_door.TaskAttempt(
            task,
            runner=lambda ctx: runner_calls.append(ctx),
            workspace_port=_Workspace(tmp_path),
        )
    assert runner_calls == []

    boundary_calls: list[object] = []
    monkeypatch.setattr(
        boundary,
        "begin_effect",
        lambda *args, **kwargs: boundary_calls.append((args, kwargs)),
    )
    with pytest.raises(owner.AttemptPortMissing, match="scratch_cleanup"):
        attempt_door.command_gate((sys.executable, "-c", "pass"))
    assert boundary_calls == []


def test_composer_injects_exact_ports_into_the_registered_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _Workspace(tmp_path)
    gate = object()
    evaluator = _Evaluator(gate)
    monkeypatch.setattr(
        composition, "attempt_workspace_port", lambda _root=None: workspace
    )
    monkeypatch.setattr(
        composition, "attempt_evaluator_port", lambda: evaluator
    )

    task = owner.TaskSpec("composed", "do nothing", gate_paths=("tests",))
    attempt = composition.compose_task_attempt(
        task,
        runner=lambda _ctx: None,
        repo_root=tmp_path,
    )

    assert type(attempt) is attempt_door.TaskAttempt
    assert attempt._manager is workspace
    assert attempt._gate is gate
    assert evaluator.calls == [
        ("pytest", ("tests",), task.gate_timeout_s, True)
    ]


def test_composer_creates_no_global_adapter_singleton() -> None:
    first_workspace, first_evaluator = composition.attempt_ports(ROOT)
    second_workspace, second_evaluator = composition.attempt_ports(ROOT)
    assert first_workspace is not second_workspace
    assert first_evaluator is not second_evaluator


def test_correctness_adapter_preserves_the_authority_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correctness = importlib.import_module("daedalus.eval.correctness")
    sentinel = object()
    calls: list[tuple] = []

    def fake_gate(task, repo_root, **kwargs):
        calls.append((task, repo_root, kwargs))
        return sentinel

    monkeypatch.setattr(correctness, "correctness_gate", fake_gate)
    task = owner.TaskSpec(
        "correctness",
        "fix behavior",
        base_revision="a" * 40,
        fail_to_pass=("tests/test_value.py::test_value",),
        pass_to_pass=("tests/test_other.py::test_other",),
        correctness_before_state={"verified": True},
    )

    result = composition.AttemptEvaluatorAdapter().correctness_gate(
        task,
        tmp_path,
        timeout_s=42.0,
    )

    assert result is sentinel
    assert calls == [(
        {
            "id": "correctness",
            "base_revision": "a" * 40,
            "fail_to_pass": ["tests/test_value.py::test_value"],
            "pass_to_pass": ["tests/test_other.py::test_other"],
            "before_state": {"verified": True},
        },
        tmp_path,
        {"timeout_s": 42.0},
    )]


def test_all_live_attempt_callers_name_explicit_composition() -> None:
    sources = {
        "ignition": (ROOT / "daedalus" / "ignition" / "gate1.py").read_text(
            encoding="utf-8"
        ),
        "supervisor": (ROOT / "daedalus" / "orchestration" / "ikarus_supervisor.py").read_text(
            encoding="utf-8"
        ),
        "picker": (ROOT / "daedalus" / "spine" / "picker.py").read_text(
            encoding="utf-8"
        ),
        "bootstrap": (ROOT / "daedalus" / "spine" / "bootstrap.py").read_text(
            encoding="utf-8"
        ),
        "cli": (ROOT / "daedalus" / "cli.py").read_text(encoding="utf-8"),
    }
    assert "compose_task_attempt as TaskAttempt" in sources["ignition"]
    assert "attempt = attempt_factory(" in sources["supervisor"]
    assert "requires an injected attempt_factory" in sources["supervisor"]
    ports_binding = "workspace_port, evaluator_port = attempt_ports_factory("
    assert ports_binding in sources["picker"]
    assert ports_binding in sources["bootstrap"]
    assert "return run_attempt(" in sources["picker"]
    assert "res = run_attempt(" in sources["bootstrap"]
    assert "attempt_ports_factory=attempt_ports" in sources["cli"]

    gated_imports = _imports(GATED_WRITES)
    assert "daedalus.orchestration.execution" in gated_imports
    gated_source = GATED_WRITES.read_text(encoding="utf-8")
    assert "from daedalus.spine.attempt import run_attempt" not in gated_source
    assert "from daedalus.spine.attempt import command_gate" not in gated_source


def test_retained_gated_write_runtime_delegates_to_orchestration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.kairos import gated_writes

    captured: dict[str, object] = {}
    sentinel = SimpleNamespace(state="no_change")

    def fake_run(task, **kwargs):
        captured["task"] = task
        captured["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(execution_composition, "run_attempt", fake_run)
    monkeypatch.setattr(
        attempt_door,
        "offload_runner",
        lambda **_kwargs: (lambda _ctx: {"action": "offloaded", "wrote": []}),
    )
    assignment = SimpleNamespace(
        objective="change value",
        paths=["value.txt"],
        owner="coder",
        lane="ollama",
        worker="fixture",
    )

    candidate = gated_writes._attempt_assignment(
        assignment,
        "a" * 40,
        tmp_path,
        project=None,
        availability={},
        ledger_path=tmp_path / "spine.sqlite3",
    )

    assert candidate.result is sentinel
    assert captured["task"].target_paths == ("value.txt",)
    assert captured["kwargs"]["repo_root"] == str(tmp_path)


def test_registered_locator_anchor_digest_pickle_and_shim_are_unchanged() -> None:
    attempt_row = REGISTRY_BY_ID["python.attempt"]
    command_row = REGISTRY_BY_ID["python.command_gate"]
    assert attempt_row.target == "daedalus.spine.attempt:run_attempt"
    assert [(anchor.target, anchor.call) for anchor in attempt_row.anchors] == [
        ("daedalus.spine.attempt:TaskAttempt.run", "begin_effect")
    ]
    assert command_row.target == "daedalus.spine.attempt:command_gate"
    assert registry_sha256() == (
        "1afe32ac18cb6cb755a1bf9a3f5aa47834c3716298e8914c0cc6c983633aef3d"
    )
    assert pickle.loads(
        b"cdaedalus.spine.attempt\nTaskAttempt\n."
    ) is attempt_door.TaskAttempt

    registry = json.loads(
        (ROOT / "docs" / "architecture" / "shim-registry.json").read_text(
            encoding="utf-8"
        )
    )
    entry = next(
        row
        for row in registry["entries"]
        if row["import_path"] == "daedalus.spine.attempt"
    )
    assert entry["owner"] == "kernel-attempt-execution"
    assert entry["targets"] == ["daedalus.kernel.attempt_execution"]
