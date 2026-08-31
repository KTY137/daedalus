"""Neutral receipt for a gate-produced exact repository HEAD observation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from daedalus.schemas import _revision, _sha256
from daedalus.spine.envelope import canonical_sha


_REPOSITORY_PATH = re.compile(
    r"^(?!/)(?![A-Za-z]:/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*//)[^\\\r\n]+$"
)


class RepositoryHeadRevisionError(RuntimeError):
    """Base class for exact repository-HEAD verification failures."""


class RepositoryHeadRevisionShapeError(RepositoryHeadRevisionError):
    """The repository metadata, expected subject, or receipt is malformed."""


class RepositoryHeadRevisionBindingError(RepositoryHeadRevisionError):
    """The stable repository HEAD differs from the expected revision."""


class RepositoryHeadRevisionRaceError(RepositoryHeadRevisionError):
    """Repository or Git metadata changed during verification."""


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryHeadRevisionShapeError(
            f"{label} must be a non-negative strict integer"
        )
    return value


def _revision_value(value: Any, label: str) -> str:
    try:
        return _revision(value, label)
    except (TypeError, ValueError) as exc:
        raise RepositoryHeadRevisionShapeError(
            f"{label} must be a lowercase 40-hex revision"
        ) from exc


def _metadata_path(value: Any) -> str:
    if not isinstance(value, str):
        raise RepositoryHeadRevisionShapeError(
            "symbolic HEAD reference_path is missing"
        )
    if _REPOSITORY_PATH.fullmatch(value) is None:
        raise RepositoryHeadRevisionShapeError(
            "symbolic HEAD reference_path is not canonical"
        )
    return value


def _canonical_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("refs/"):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref must start with refs/"
        )
    if value.endswith(("/", ".", ".lock")):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref has a forbidden suffix"
        )
    if any(token in value for token in ("..", "//", "@{", "\\")):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref is not canonical"
        )
    forbidden = set(" ~^:?*[]")
    if any(
        character in forbidden or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref contains a forbidden character"
        )
    parts = value.split("/")
    if len(parts) < 3 or any(
        not part
        or part in {".", ".."}
        or part.startswith(".")
        or part.endswith(".lock")
        for part in parts
    ):
        raise RepositoryHeadRevisionShapeError(
            "HEAD symbolic ref contains a forbidden path segment"
        )
    return value


@dataclass(frozen=True)
class RepositoryHeadRevisionReceipt:
    """Deterministic proof that one expected revision matched a stable Git HEAD."""

    expected_revision: str
    resolved_revision: str
    head_mode: str
    head_ref: str | None
    resolution_source: str
    head_sha256: str
    head_size: int
    reference_path: str | None
    reference_sha256: str | None
    reference_size: int | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expected_revision",
            _revision_value(self.expected_revision, "expected_revision"),
        )
        object.__setattr__(
            self,
            "resolved_revision",
            _revision_value(self.resolved_revision, "resolved_revision"),
        )
        try:
            object.__setattr__(
                self,
                "head_sha256",
                _sha256(self.head_sha256, "head_sha256"),
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryHeadRevisionShapeError(
                "HEAD observation digest is malformed"
            ) from exc
        _strict_int(self.head_size, "head_size")
        if self.head_mode == "detached":
            if self.head_ref is not None or self.resolution_source != "head":
                raise RepositoryHeadRevisionShapeError(
                    "detached HEAD observation has symbolic-ref fields"
                )
            if any(
                value is not None
                for value in (
                    self.reference_path,
                    self.reference_sha256,
                    self.reference_size,
                )
            ):
                raise RepositoryHeadRevisionShapeError(
                    "detached HEAD observation has reference evidence"
                )
        elif self.head_mode == "symbolic":
            object.__setattr__(self, "head_ref", _canonical_ref(self.head_ref))
            if self.resolution_source not in {"loose_ref", "packed_refs"}:
                raise RepositoryHeadRevisionShapeError(
                    "symbolic HEAD resolution source is unsupported"
                )
            path = _metadata_path(self.reference_path)
            expected_path = (
                f".git/{self.head_ref}"
                if self.resolution_source == "loose_ref"
                else ".git/packed-refs"
            )
            if path != expected_path:
                raise RepositoryHeadRevisionShapeError(
                    "symbolic HEAD reference_path differs from resolution source"
                )
            try:
                object.__setattr__(
                    self,
                    "reference_sha256",
                    _sha256(self.reference_sha256, "reference_sha256"),
                )
            except (TypeError, ValueError) as exc:
                raise RepositoryHeadRevisionShapeError(
                    "symbolic HEAD reference digest is malformed"
                ) from exc
            _strict_int(self.reference_size, "reference_size")
        else:
            raise RepositoryHeadRevisionShapeError(
                "head_mode must be detached or symbolic"
            )
        if self.expected_revision != self.resolved_revision:
            raise RepositoryHeadRevisionBindingError(
                "receipt expected revision differs from resolved HEAD"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-repository-head-revision-receipt/1",
            "expected_revision": self.expected_revision,
            "resolved_revision": self.resolved_revision,
            "head_mode": self.head_mode,
            "head_ref": self.head_ref,
            "resolution_source": self.resolution_source,
            "head_sha256": self.head_sha256,
            "head_size": self.head_size,
            "reference_path": self.reference_path,
            "reference_sha256": self.reference_sha256,
            "reference_size": self.reference_size,
            "repository_head_verified": True,
            "commit_object_verified": False,
            "worktree_clean_verified": False,
            "process_spawned": False,
            "repository_mutated": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RepositoryHeadRevisionReceipt":
        expected = {
            "schema",
            "expected_revision",
            "resolved_revision",
            "head_mode",
            "head_ref",
            "resolution_source",
            "head_sha256",
            "head_size",
            "reference_path",
            "reference_sha256",
            "reference_size",
            "repository_head_verified",
            "commit_object_verified",
            "worktree_clean_verified",
            "process_spawned",
            "repository_mutated",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise RepositoryHeadRevisionShapeError(
                "repository HEAD receipt fields are not exact"
            )
        if payload["schema"] != "daedalus-repository-head-revision-receipt/1":
            raise RepositoryHeadRevisionShapeError(
                "repository HEAD receipt schema does not match"
            )
        if payload["repository_head_verified"] is not True:
            raise RepositoryHeadRevisionShapeError(
                "repository HEAD receipt must retain successful verification"
            )
        if any(
            payload[field] is not False
            for field in (
                "commit_object_verified",
                "worktree_clean_verified",
                "process_spawned",
                "repository_mutated",
            )
        ):
            raise RepositoryHeadRevisionShapeError(
                "repository HEAD receipt contains an unsupported authority claim"
            )
        try:
            return cls(
                expected_revision=payload["expected_revision"],
                resolved_revision=payload["resolved_revision"],
                head_mode=payload["head_mode"],
                head_ref=payload["head_ref"],
                resolution_source=payload["resolution_source"],
                head_sha256=payload["head_sha256"],
                head_size=payload["head_size"],
                reference_path=payload["reference_path"],
                reference_sha256=payload["reference_sha256"],
                reference_size=payload["reference_size"],
            )
        except RepositoryHeadRevisionError:
            raise
        except (TypeError, ValueError) as exc:
            raise RepositoryHeadRevisionShapeError(
                "repository HEAD receipt is malformed"
            ) from exc

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


__all__ = [
    "RepositoryHeadRevisionBindingError",
    "RepositoryHeadRevisionError",
    "RepositoryHeadRevisionRaceError",
    "RepositoryHeadRevisionReceipt",
    "RepositoryHeadRevisionShapeError",
]
