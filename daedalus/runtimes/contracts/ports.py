"""Typed read-only gate ports consumed by runtime admission."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .python_targets import PythonTargetStructure
from .repository import RepositoryHeadRevisionReceipt
from .retention import ProviderTargetReceiptRetentionInventory


class RepositoryHeadReceiptVerifier(Protocol):
    def __call__(
        self,
        repository_root: Path,
        expected_revision: str,
        receipt: RepositoryHeadRevisionReceipt,
    ) -> None: ...


class RetentionInventoryScanner(Protocol):
    def __call__(
        self,
        repository_root: Path,
        *,
        source_revision: str,
    ) -> ProviderTargetReceiptRetentionInventory: ...


class PythonTargetStructureResolver(Protocol):
    def __call__(
        self,
        repository_root: Path,
        target: str,
        *,
        expected_source_sha256: str,
    ) -> PythonTargetStructure: ...


__all__ = [
    "PythonTargetStructureResolver",
    "RepositoryHeadReceiptVerifier",
    "RetentionInventoryScanner",
]
