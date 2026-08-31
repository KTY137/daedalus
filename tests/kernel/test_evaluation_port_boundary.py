from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

from daedalus.kernel.contracts import EvaluationPorts as PackageEvaluationPorts
from daedalus.kernel.contracts.evaluation import EvaluationPorts
from daedalus.orchestration.execution import picker_evaluation_ports
from daedalus.spine import picker


ROOT = Path(__file__).resolve().parents[2]
PICKER = ROOT / "daedalus" / "spine" / "picker.py"
CLI = ROOT / "daedalus" / "cli.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                continue
            names.add(module)
    return names


def test_kernel_package_exports_the_exact_neutral_port_object() -> None:
    assert PackageEvaluationPorts is EvaluationPorts


def test_picker_has_no_static_evaluator_implementation_import() -> None:
    imports = _imports(PICKER)
    assert not any(
        name == "daedalus.eval" or name.startswith("daedalus.eval.")
        for name in imports
    )


def test_importing_picker_does_not_load_the_evaluator_package() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import json,sys;"
                f"sys.path.insert(0,{str(ROOT)!r});"
                "import daedalus.spine.picker;"
                "print(json.dumps(sorted(n for n in sys.modules "
                "if n == 'daedalus.eval' or n.startswith('daedalus.eval.'))))"
            ),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(probe.stdout) == []


def test_direct_retained_baseline_matches_the_existing_owner() -> None:
    from daedalus.eval.harness import load_baseline

    baseline, error = picker._load_baseline()
    assert error is None
    assert baseline == load_baseline()


def test_orchestration_adapter_delegates_to_the_existing_evaluator(monkeypatch) -> None:
    from daedalus.eval import harness

    baseline = {"schema": 1, "tasks": {"probe": {"recall": 1.0}}}
    gate = {"passed": True, "n_checked": 1}
    monkeypatch.setattr(harness, "load_baseline", lambda: baseline)
    monkeypatch.setattr(harness, "run_gate", lambda: gate)

    ports = picker_evaluation_ports()
    assert ports.load_baseline() is baseline
    assert ports.run_gate() is gate


def test_injected_ports_supply_both_retained_and_fresh_measurements(tmp_path) -> None:
    calls: list[str] = []

    def load_baseline():
        calls.append("baseline")
        return {"schema": 1, "tasks": {}}

    def run_gate():
        calls.append("gate")
        return {"passed": True, "n_checked": 0, "regressions": []}

    queue = picker.build_queue(
        tmp_path,
        limit=None,
        include_eval=True,
        inventory={},
        map_snapshot={},
        evaluation_ports=EvaluationPorts(
            load_baseline=load_baseline,
            run_gate=run_gate,
        ),
        use_attempt_memory=False,
    )

    assert calls == ["baseline", "gate"]
    assert queue.sources["eval_baseline"]["state"] == "valid"
    assert queue.sources["eval_gate"]["state"] == "valid"
    assert queue.sources["eval_gate"]["ran"] is True


def test_uncomposed_direct_eval_fails_closed_without_importing_eval(tmp_path) -> None:
    queue = picker.build_queue(
        tmp_path,
        limit=None,
        include_eval=True,
        inventory={},
        map_snapshot={},
        baseline={},
        use_attempt_memory=False,
    )
    source = queue.sources["eval_gate"]
    assert source["state"] == "invalid"
    assert source["ran"] is False
    assert "EvaluationPortUnavailable" in source["error"]


def test_cli_composes_ports_at_the_registered_picker_door() -> None:
    tree = ast.parse(CLI.read_text(encoding="utf-8"), filename=str(CLI))
    improve = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(value, ast.Constant) and value.value == "improve"
            for value in node.comparators
        )
    ]
    assert len(improve) == 1
    source = CLI.read_text(encoding="utf-8")
    assert "from .spine.picker import main as m" in source
    assert "evaluation_ports=picker_evaluation_ports()" in source
