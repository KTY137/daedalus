"""Builder report contracts shared by every builder lane.

Kept apart from ``builders.py`` so a lane module (the Sous-Chef) can import
the contract without importing the lane registry that imports it back.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class BuilderUnavailable(RuntimeError):
    pass


@dataclass
class BuilderReport:
    lane: str
    ok: bool
    exit_code: int | None
    seconds: float
    summary: str
    changed_files: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    model: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"lane": self.lane, "ok": self.ok, "exit_code": self.exit_code, "seconds": round(self.seconds, 2),
                "summary": self.summary[:4000], "changed_files": self.changed_files[:400], "model": self.model,
                "stdout_tail": self.stdout_tail[-2000:], "stderr_tail": self.stderr_tail[-2000:], "details": self.details}


__all__ = ["BuilderReport", "BuilderUnavailable"]
