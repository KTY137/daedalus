from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.gates.provider_target_receipt_retention_inventory import (
    ProviderTargetReceiptRetentionInventory as GateRetentionInventory,
    ProviderTargetReceiptRetentionInventoryError as GateRetentionInventoryError,
    ProviderTargetReceiptRetentionSurface as GateRetentionSurface,
)
from daedalus.gates.python_target_structure import (
    PythonTargetBindingError as GatePythonTargetBindingError,
    PythonTargetSourceError as GatePythonTargetSourceError,
    PythonTargetStructure as GatePythonTargetStructure,
    PythonTargetStructureError as GatePythonTargetStructureError,
)
from daedalus.gates.repository_head_revision import (
    RepositoryHeadRevisionBindingError as GateRepositoryHeadBindingError,
    RepositoryHeadRevisionError as GateRepositoryHeadError,
    RepositoryHeadRevisionRaceError as GateRepositoryHeadRaceError,
    RepositoryHeadRevisionReceipt as GateRepositoryHeadReceipt,
    RepositoryHeadRevisionShapeError as GateRepositoryHeadShapeError,
)
from daedalus.runtimes.contracts.python_targets import (
    PythonTargetBindingError,
    PythonTargetSourceError,
    PythonTargetStructure,
    PythonTargetStructureError,
)
from daedalus.runtimes.contracts.repository import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionError,
    RepositoryHeadRevisionRaceError,
    RepositoryHeadRevisionReceipt,
    RepositoryHeadRevisionShapeError,
)
from daedalus.runtimes.contracts.retention import (
    ProviderTargetReceiptRetentionInventory,
    ProviderTargetReceiptRetentionInventoryError,
    ProviderTargetReceiptRetentionSurface,
)
from daedalus.runtimes.provider_executable_structure import (
    verify_provider_executable_structure,
    verify_provider_executable_structure_receipt,
)
from daedalus.runtimes.provider_target_receipt_retention_admission import (
    verify_provider_target_receipt_retention_admission,
)
from daedalus.runtimes.provider_target_receipt_retention_preflight import (
    verify_provider_target_receipt_retention_preflight,
)


RUNTIMES = Path("daedalus/runtimes")


def test_runtime_modules_do_not_import_gate_implementations() -> None:
    offenders: list[str] = []
    for path in sorted(RUNTIMES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            if any(
                name == "daedalus.gates" or name.startswith("daedalus.gates.")
                for name in names
            ):
                offenders.append(f"{path.as_posix()}:{node.lineno}")

    assert offenders == []


def test_gate_facades_export_the_exact_neutral_contract_objects() -> None:
    identities = (
        (GateRepositoryHeadError, RepositoryHeadRevisionError),
        (GateRepositoryHeadShapeError, RepositoryHeadRevisionShapeError),
        (GateRepositoryHeadBindingError, RepositoryHeadRevisionBindingError),
        (GateRepositoryHeadRaceError, RepositoryHeadRevisionRaceError),
        (GateRepositoryHeadReceipt, RepositoryHeadRevisionReceipt),
        (GateRetentionInventoryError, ProviderTargetReceiptRetentionInventoryError),
        (GateRetentionSurface, ProviderTargetReceiptRetentionSurface),
        (GateRetentionInventory, ProviderTargetReceiptRetentionInventory),
        (GatePythonTargetStructureError, PythonTargetStructureError),
        (GatePythonTargetSourceError, PythonTargetSourceError),
        (GatePythonTargetBindingError, PythonTargetBindingError),
        (GatePythonTargetStructure, PythonTargetStructure),
    )

    assert all(legacy is canonical for legacy, canonical in identities)
    assert RepositoryHeadRevisionReceipt.__module__ == (
        "daedalus.runtimes.contracts.repository"
    )
    assert ProviderTargetReceiptRetentionInventory.__module__ == (
        "daedalus.runtimes.contracts.retention"
    )
    assert PythonTargetStructure.__module__ == (
        "daedalus.runtimes.contracts.python_targets"
    )


def test_runtime_admission_requires_explicit_read_only_gate_ports() -> None:
    expectations = {
        verify_provider_executable_structure: {"target_resolver"},
        verify_provider_executable_structure_receipt: {"target_resolver"},
        verify_provider_target_receipt_retention_preflight: {
            "repository_head_verifier",
            "retention_inventory_scanner",
        },
        verify_provider_target_receipt_retention_admission: {
            "repository_head_verifier",
            "retention_inventory_scanner",
        },
    }

    for function, names in expectations.items():
        signature = inspect.signature(function)
        for name in names:
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
            assert parameter.default is inspect.Parameter.empty
