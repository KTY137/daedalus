"""Registered Attempt effect doors and legacy compatibility composition.

The lifecycle implementation is owned by :mod:`daedalus.kernel.attempt_execution`.
This module keeps the historical import target, Effect Registry anchors, and
default composition that selects the existing Kairos workspace manager and the
existing evaluator.  No default is installed in the kernel and no mutable
process-wide port registry is used: each legacy ``TaskAttempt`` receives fresh
port objects at construction.

All non-composition attributes are resolved from, and monkeypatch assignments
are forwarded to, the single owner module.  The deliberately local seams are
``TaskAttempt``, ``run_attempt``, ``command_gate``, ``pytest_gate``, and the
scratch cleanup wrapper; they are the documented effect/composition facade.
"""
from __future__ import annotations

import sys
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Sequence

from daedalus.kernel import attempt_execution as _owner
from daedalus.kairos.worktree import GitWorktreeManager, remove_tree_no_follow


__all__ = [
    "ATTEMPT_STATES",
    "AttemptResult",
    "GateResult",
    "GitCommandError",
    "INTENT_KIND",
    "PatchArtifact",
    "PrimaryCheckoutWrite",
    "READ_ONLY_REPO_VERBS",
    "RunnerContext",
    "STATE_CANCELLED",
    "STATE_CLEAN",
    "STATE_GATES_FAILED",
    "STATE_NO_CHANGE",
    "STATE_RUNNER_FAILED",
    "STATE_STORAGE_UNAVAILABLE",
    "STATE_WORKTREE_FAILED",
    "STATE_LEASE_REFUSED",
    "TaskAttempt",
    "TaskSpec",
    "command_gate",
    "offload_runner",
    "pytest_gate",
    "pytest_gate_argv",
    "run_attempt",
]


def _remove_gate_tmpdir(tmpdir: Path) -> str | None:
    """Compose the kernel scratch-cleanup seam with the existing safe walker."""
    return _owner._remove_gate_tmpdir(tmpdir, remove_tree_no_follow)


def command_gate(
    argv: Sequence[str],
    *,
    timeout_s: float | None = _owner.DEFAULT_GATE_TIMEOUT_S,
    poll_s: float = 0.25,
    name: str = "command",
    executes_candidate: bool = True,
) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
    """Registered command-gate door composed with guarded scratch cleanup."""
    from daedalus.spine.effect_boundary import (
        REGISTRY_BY_ID,
        GuardDecision,
        begin_effect,
    )

    begin_effect(
        "python.command_gate",
        REGISTRY_BY_ID["python.command_gate"].effects,
        (
            GuardDecision(
                "containment.attempt",
                True,
                "gate construction: candidate execution is containment-"
                f"enforced inside the gate (executes_candidate="
                f"{executes_candidate}); there is no contained=False and an "
                "unestablished containment refuses instead of downgrading",
            ),
        ),
    )
    return _owner._command_gate(
        argv,
        scratch_cleanup=lambda path: _remove_gate_tmpdir(path),
        timeout_s=timeout_s,
        poll_s=poll_s,
        name=name,
        executes_candidate=executes_candidate,
    )


def pytest_gate(
    paths: Sequence[str] = (),
    *,
    timeout_s: float | None = _owner.DEFAULT_GATE_TIMEOUT_S,
    poll_s: float = 0.25,
    name: str = "pytest",
    executes_candidate: bool = True,
) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
    """Preserve the historical thin wrapper around the registered gate door."""
    return command_gate(
        _owner.pytest_gate_argv(paths),
        timeout_s=timeout_s,
        poll_s=poll_s,
        name=name,
        executes_candidate=executes_candidate,
    )


class _SpineEvaluatorPort:
    """Per-Attempt adapter to the independently owned gate implementations."""

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
        task: Any,
        repo_root: Path,
        *,
        timeout_s: float | None,
    ) -> Callable[[_owner.RunnerContext], _owner.GateResult]:
        # Lazy for the historical import cycle: correctness imports this facade
        # for the read-only git vocabulary.
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
        # Preserve the old call shapes because tests and callers monkeypatch
        # this facade as the composition seam.
        if use_default_timeout:
            return pytest_gate(paths)
        return pytest_gate(paths, timeout_s=timeout_s)


class TaskAttempt(_owner.TaskAttempt):
    """Legacy registered door over the kernel-owned lifecycle core."""

    @wraps(_owner.TaskAttempt.__init__)
    def __init__(self, task: _owner.TaskSpec, **kwargs: Any) -> None:
        manager = kwargs.get("worktree_manager")
        workspace = kwargs.get("workspace_port")
        if manager is None and workspace is None:
            kwargs.pop("worktree_manager", None)
            kwargs.pop("workspace_port", None)
            raw_root = kwargs.get("repo_root")
            repo_root = Path(raw_root).resolve() if raw_root else _owner.ROOT
            kwargs["workspace_port"] = GitWorktreeManager(repo_root)
        if kwargs.get("evaluator_port") is None:
            kwargs.pop("evaluator_port", None)
            kwargs["evaluator_port"] = _SpineEvaluatorPort()
        super().__init__(task, **kwargs)

    def run(self) -> _owner.AttemptResult:
        """Run one Attempt through the unchanged registered effect boundary."""
        started = _owner.time.monotonic()
        started_ts = _owner._now_iso()

        def finish(state: str, **kw: Any) -> _owner.AttemptResult:
            return _owner.AttemptResult(
                state=state,
                task_id=self.task.task_id,
                started_ts=started_ts,
                finished_ts=_owner._now_iso(),
                duration_s=_owner.time.monotonic() - started,
                effect_key=self.effect_key,
                branch=self.branch,
                **kw,
            )

        try:
            _owner.require_storage(
                str(_owner._existing_ancestor(self._manager.worktree_root))
            )
        except _owner.StorageUnavailable as exc:
            return finish(_owner.STATE_STORAGE_UNAVAILABLE, error=str(exc))
        except OSError as exc:
            return finish(
                _owner.STATE_STORAGE_UNAVAILABLE,
                error=f"storage_unavailable: {exc}",
            )

        if self._is_cancelled():
            return finish(
                _owner.STATE_CANCELLED,
                error="cancelled before any effect",
            )

        try:
            base_revision = self._resolve_base()
        except Exception as exc:  # noqa: BLE001 - run returns failure states
            return finish(
                _owner.STATE_WORKTREE_FAILED,
                error=f"could not resolve base revision: {exc}",
            )

        try:
            ledger = self._get_ledger()
        except Exception as exc:  # noqa: BLE001 - no effect may start
            return finish(
                _owner.STATE_WORKTREE_FAILED,
                base_revision=base_revision,
                error=f"spine ledger unavailable: {exc}",
            )

        from daedalus.spine.effect_boundary import (
            REGISTRY_BY_ID,
            EffectBoundaryError,
            begin_effect,
        )
        from daedalus.spine.receipts import ATTEMPT_ENTRYPOINT_ID

        try:
            self._boundary_receipt = begin_effect(
                ATTEMPT_ENTRYPOINT_ID,
                REGISTRY_BY_ID[ATTEMPT_ENTRYPOINT_ID].effects,
                self._boundary_guard_decisions(ledger),
            )
        except EffectBoundaryError as exc:
            return self._released(
                ledger,
                finish(
                    _owner.STATE_WORKTREE_FAILED,
                    base_revision=base_revision,
                    error=f"effect boundary refused this attempt: {exc}",
                ),
            )
        except Exception as exc:  # noqa: BLE001 - run never raises here
            return self._released(
                ledger,
                finish(
                    _owner.STATE_WORKTREE_FAILED,
                    base_revision=base_revision,
                    error=(
                        "effect boundary could not be evaluated: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                ),
            )

        try:
            result = self._run_with_ledger(ledger, base_revision, finish)
        except BaseException:
            self._finish_lease_terminal(state_hint=_owner.STATE_CANCELLED)
            self._close_ledger(ledger)
            raise
        result = self._attach_lease_terminal(result)
        return self._released(ledger, result)


def run_attempt(task: _owner.TaskSpec, **kwargs: Any) -> _owner.AttemptResult:
    """Construct and run the registered compatibility composition."""
    return TaskAttempt(task, **kwargs).run()


_COMPOSITION_NAMES = frozenset(
    {
        "TaskAttempt",
        "run_attempt",
        "command_gate",
        "pytest_gate",
        "_remove_gate_tmpdir",
        "GitWorktreeManager",
        "remove_tree_no_follow",
    }
)


class _AttemptFacade(ModuleType):
    """Forward legacy private monkeypatch seams to the canonical owner."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_owner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if (
            name.startswith("__")
            or name in _COMPOSITION_NAMES
            or name in {"_owner", "_COMPOSITION_NAMES"}
            or not hasattr(_owner, name)
        ):
            super().__setattr__(name, value)
            return
        setattr(_owner, name, value)

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(dir(_owner)))


_module = sys.modules[__name__]
_module.__class__ = _AttemptFacade
# Runtime source inspection historically followed ``attempt_mod.__file__``.
# Point it at the one implementation owner while the import spec/locator stays
# ``daedalus.spine.attempt`` for compatibility and pickle resolution.
_module.__file__ = _owner.__file__
