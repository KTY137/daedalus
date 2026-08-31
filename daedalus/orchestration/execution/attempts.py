"""Concrete production composition for the canonical Attempt effect doors.

Workspace and evaluator authority remain in their existing owners.  This
module only binds those implementations to the neutral ports consumed by the
kernel-owned lifecycle and passes the capabilities into the registered
``daedalus.spine.attempt`` doors.  Every factory call creates fresh adapters;
there is no mutable process-wide registry or implicit kernel default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from daedalus.kernel import attempt_execution as _owner
from daedalus.spine import attempt as _door


class AttemptEvaluatorAdapter:
    """Bind the existing evaluator and registered gate door to one Attempt."""

    def command_gate(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float | None,
        name: str,
    ) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
        return command_gate(argv, timeout_s=timeout_s, name=name)

    def correctness_gate(
        self,
        task: _owner.TaskSpec,
        repo_root: Path,
        *,
        timeout_s: float | None,
    ) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
        from daedalus.eval.correctness import correctness_gate

        return correctness_gate(
            {
                "id": task.task_id,
                "base_revision": task.base_revision,
                "fail_to_pass": list(task.fail_to_pass),
                "pass_to_pass": list(task.pass_to_pass),
                "before_state": dict(task.correctness_before_state),
            },
            repo_root,
            timeout_s=timeout_s,
        )

    def pytest_gate(
        self,
        paths: Sequence[str],
        *,
        timeout_s: float | None,
        use_default_timeout: bool,
    ) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
        # Keep the established default-timeout call shape.  It is observable
        # through the registered facade's monkeypatch seam.
        if use_default_timeout:
            return pytest_gate(paths)
        return pytest_gate(paths, timeout_s=timeout_s)


def attempt_workspace_port(
    repo_root: str | Path | None = None,
) -> _owner.AttemptWorkspacePort:
    """Create the existing Kairos workspace manager for one composition."""

    from daedalus.kairos.worktree import GitWorktreeManager

    root = Path(repo_root).resolve() if repo_root is not None else _owner.ROOT
    return GitWorktreeManager(root)


def attempt_evaluator_port() -> _owner.AttemptEvaluatorPort:
    """Create the existing evaluator adapter for one composition."""

    return AttemptEvaluatorAdapter()


def attempt_ports(
    repo_root: str | Path | None = None,
) -> tuple[_owner.AttemptWorkspacePort, _owner.AttemptEvaluatorPort]:
    """Create one fresh workspace/evaluator capability pair."""

    return attempt_workspace_port(repo_root), attempt_evaluator_port()


def _composed_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    bound = dict(kwargs)
    if (
        bound.get("worktree_manager") is None
        and bound.get("workspace_port") is None
    ):
        bound.pop("worktree_manager", None)
        bound.pop("workspace_port", None)
        bound["workspace_port"] = attempt_workspace_port(bound.get("repo_root"))
    if bound.get("evaluator_port") is None:
        bound.pop("evaluator_port", None)
        bound["evaluator_port"] = attempt_evaluator_port()
    return bound


def compose_task_attempt(
    task: _owner.TaskSpec,
    **kwargs: Any,
) -> _door.TaskAttempt:
    """Construct the exact registered Attempt class with explicit ports."""

    return _door.TaskAttempt(task, **_composed_kwargs(kwargs))


def run_attempt(
    task: _owner.TaskSpec,
    **kwargs: Any,
) -> _owner.AttemptResult:
    """Invoke the unchanged registered target with explicit capabilities."""

    return _door.run_attempt(task, **_composed_kwargs(kwargs))


def remove_gate_tmpdir(tmpdir: Path) -> str | None:
    """Use the existing guarded Kairos walker for one scratch directory."""

    from daedalus.kairos.worktree import remove_tree_no_follow

    return _door._remove_gate_tmpdir(
        tmpdir,
        scratch_cleanup=remove_tree_no_follow,
    )


def command_gate(
    argv: Sequence[str],
    *,
    timeout_s: float | None = _owner.DEFAULT_GATE_TIMEOUT_S,
    poll_s: float = 0.25,
    name: str = "command",
    executes_candidate: bool = True,
) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
    """Compose the registered command gate with the guarded scratch walker."""

    from daedalus.kairos.worktree import remove_tree_no_follow

    return _door.command_gate(
        argv,
        timeout_s=timeout_s,
        poll_s=poll_s,
        name=name,
        executes_candidate=executes_candidate,
        scratch_cleanup=remove_tree_no_follow,
    )


def pytest_gate(
    paths: Sequence[str] = (),
    *,
    timeout_s: float | None = _owner.DEFAULT_GATE_TIMEOUT_S,
    poll_s: float = 0.25,
    name: str = "pytest",
    executes_candidate: bool = True,
) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
    """Compose the registered pytest gate with the guarded scratch walker."""

    from daedalus.kairos.worktree import remove_tree_no_follow

    kwargs: dict[str, Any] = {"scratch_cleanup": remove_tree_no_follow}
    if timeout_s != _owner.DEFAULT_GATE_TIMEOUT_S:
        kwargs["timeout_s"] = timeout_s
    if poll_s != 0.25:
        kwargs["poll_s"] = poll_s
    if name != "pytest":
        kwargs["name"] = name
    if executes_candidate is not True:
        kwargs["executes_candidate"] = executes_candidate
    return _door.pytest_gate(paths, **kwargs)


__all__ = [
    "AttemptEvaluatorAdapter",
    "attempt_evaluator_port",
    "attempt_ports",
    "attempt_workspace_port",
    "command_gate",
    "compose_task_attempt",
    "pytest_gate",
    "remove_gate_tmpdir",
    "run_attempt",
]
