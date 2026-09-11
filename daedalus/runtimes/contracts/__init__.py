"""Neutral runtime admission contracts consumed by gates and runtimes."""

from .claude import (
    CLAUDE_ENTRYPOINT_ID,
    CLAUDE_RUNTIME_ID,
    ClaudeInvocationBindingMismatch,
    ClaudeProviderAuthorizationRequired,
    ClaudeProviderScopeMismatch,
    ClaudeProviderWorkspaceMismatch,
    ClaudeWorkspaceGrant,
)
from .python_targets import (
    PythonTargetBindingError,
    PythonTargetSourceError,
    PythonTargetStructure,
    PythonTargetStructureError,
    module_repository_path,
    parse_python_target,
)
from .ports import (
    PythonTargetStructureResolver,
    RepositoryHeadReceiptVerifier,
    RetentionInventoryScanner,
)
from .provider_report import AgentReport, REPORT_KEYS, validate_report
from .repository import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionError,
    RepositoryHeadRevisionRaceError,
    RepositoryHeadRevisionReceipt,
    RepositoryHeadRevisionShapeError,
)
from .retention import (
    ProviderTargetReceiptRetentionInventory,
    ProviderTargetReceiptRetentionInventoryError,
    ProviderTargetReceiptRetentionSurface,
)

__all__ = [
    "CLAUDE_ENTRYPOINT_ID",
    "CLAUDE_RUNTIME_ID",
    "ClaudeInvocationBindingMismatch",
    "ClaudeProviderAuthorizationRequired",
    "ClaudeProviderScopeMismatch",
    "ClaudeProviderWorkspaceMismatch",
    "ClaudeWorkspaceGrant",
    "AgentReport",
    "REPORT_KEYS",
    "ProviderTargetReceiptRetentionInventory",
    "ProviderTargetReceiptRetentionInventoryError",
    "ProviderTargetReceiptRetentionSurface",
    "PythonTargetBindingError",
    "PythonTargetSourceError",
    "PythonTargetStructure",
    "PythonTargetStructureError",
    "PythonTargetStructureResolver",
    "RepositoryHeadRevisionBindingError",
    "RepositoryHeadRevisionError",
    "RepositoryHeadRevisionRaceError",
    "RepositoryHeadRevisionReceipt",
    "RepositoryHeadRevisionShapeError",
    "RepositoryHeadReceiptVerifier",
    "RetentionInventoryScanner",
    "module_repository_path",
    "parse_python_target",
    "validate_report",
]
