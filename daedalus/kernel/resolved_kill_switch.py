"""Exact runtime binding between a signed kill-switch ref and its live permit."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from daedalus.spine.killswitch import KillSwitch, LoopHalted


_RESOLVE_TOKEN = object()


def _resolved_path(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.realpath(os.fspath(path))))


def kill_switch_path_sha256(path: str | os.PathLike[str]) -> str:
    """Digest the immutable permit/marker/counter/lock sibling identity."""

    permit = Path(path)
    marker = permit.with_name(permit.name + ".stopped")
    counter = permit.with_name(permit.name + ".generation")
    operator_lock = permit.with_name(permit.name + ".lock")
    payload = json.dumps(
        {
            "domain": "daedalus.kill-switch-path/3",
            "permit_path": _resolved_path(permit),
            "marker_path": _resolved_path(marker),
            "generation_path": _resolved_path(counter),
            "operator_lock_path": _resolved_path(operator_lock),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def kill_switch_ref_for_path(path: str | os.PathLike[str]) -> str:
    """Return the canonical EffectScope identifier for one permit path."""

    return f"kill-switch:{kill_switch_path_sha256(path)}"


class ResolvedKillSwitch:
    """Live-only exact permit/generation capability for a canonical executor."""

    __slots__ = ("_switch", "kill_switch_ref", "generation", "path_sha256")

    def __init__(
        self,
        *,
        switch: KillSwitch,
        kill_switch_ref: str,
        generation: int,
        path_sha256: str,
        _token: object | None = None,
    ) -> None:
        if _token is not _RESOLVE_TOKEN:
            raise TypeError("ResolvedKillSwitch may only be created from a live permit")
        object.__setattr__(self, "_switch", switch)
        object.__setattr__(self, "kill_switch_ref", kill_switch_ref)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "path_sha256", path_sha256)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ResolvedKillSwitch is immutable")

    @classmethod
    def resolve(
        cls,
        switch: KillSwitch,
        *,
        expected_kill_switch_ref: str,
        expected_generation: int,
    ) -> "ResolvedKillSwitch":
        """Resolve live state only when it matches signed external authority."""

        if type(switch) is not KillSwitch:
            raise TypeError("switch must be an exact KillSwitch")
        if not isinstance(expected_kill_switch_ref, str) or not expected_kill_switch_ref:
            raise ValueError("expected_kill_switch_ref must be a non-empty string")
        if (
            isinstance(expected_generation, bool)
            or not isinstance(expected_generation, int)
            or expected_generation < 0
        ):
            raise ValueError("expected_generation must be a non-negative integer")
        state = switch.read_state()
        if not state.running or state.generation is None:
            raise LoopHalted(
                f"cannot resolve a stopped or unreadable kill switch: {state.reason}"
            )
        if state.generation == 0:
            raise LoopHalted(
                "legacy sidecar-less RUN permit must be explicitly re-armed "
                "before canonical effect authorization"
            )
        path_sha = kill_switch_path_sha256(switch.path)
        actual_ref = f"kill-switch:{path_sha}"
        if actual_ref != expected_kill_switch_ref:
            raise LoopHalted("live kill-switch path does not match signed effect scope")
        if state.generation != expected_generation:
            raise LoopHalted(
                "live kill-switch generation does not match signed execution authority"
            )
        return cls(
            switch=switch,
            kill_switch_ref=actual_ref,
            generation=state.generation,
            path_sha256=path_sha,
            _token=_RESOLVE_TOKEN,
        )

    @property
    def path(self) -> Path:
        return self._switch.path

    def checkpoint(self) -> None:
        """Re-read exact path, running state and generation; fail closed on drift."""

        current_path_sha = kill_switch_path_sha256(self._switch.path)
        if current_path_sha != self.path_sha256:
            raise LoopHalted("kill-switch permit path changed after resolution")
        if f"kill-switch:{current_path_sha}" != self.kill_switch_ref:
            raise LoopHalted("kill-switch ref changed after resolution")
        state = self._switch.read_state()
        if not state.running:
            raise LoopHalted(
                f"kill switch engaged: {state.reason} [{self._switch.path}]"
            )
        if state.generation != self.generation:
            raise LoopHalted(
                "kill-switch generation changed after execution authorization"
            )
        self._switch.checkpoint()

    def __repr__(self) -> str:
        return (
            "ResolvedKillSwitch("
            f"ref={self.kill_switch_ref!r}, generation={self.generation})"
        )


__all__ = [
    "ResolvedKillSwitch",
    "kill_switch_path_sha256",
    "kill_switch_ref_for_path",
]
