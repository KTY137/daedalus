"""Strangler-composed effect boundary with recovery-consumption inventory.

The historical :mod:`daedalus.spine.effect_boundary` module remains intact while
callers migrate in small packets.  This adapter composes its canonical registry,
scanner, conformance report and receipt builder with the exact recovery-decision
consumption delta.  It does not monkey-patch legacy globals and therefore can be
reviewed and adopted by individual report/CLI callers without a Big-Bang rename.
"""
from __future__ import annotations

import ast
import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from daedalus.spine.envelope import canonical_sha

from . import effect_boundary as legacy
from .promotion_recovery_consumption_inventory import (
    ENTRYPOINTS as PROPOSED_ENTRYPOINTS,
    GUARD_CONTRACT_IMPLEMENTED as PROPOSED_GUARDS,
    SCANNER_CLASS,
    SCANNER_METHODS,
    SCANNER_MODULE,
)


Surface = legacy.Surface
Effect = legacy.Effect
Wiring = legacy.Wiring
Severity = legacy.Severity
EntrypointSpec = legacy.EntrypointSpec
DiscoveredEntrypoint = legacy.DiscoveredEntrypoint
ConformanceFinding = legacy.ConformanceFinding
ConformanceReport = legacy.ConformanceReport
EffectBoundaryReceipt = legacy.EffectBoundaryReceipt
EffectBoundaryViolation = legacy.EffectBoundaryViolation


GUARD_CONTRACT_IMPLEMENTED: Mapping[str, bool] = MappingProxyType(
    {
        **dict(legacy.GUARD_CONTRACT_IMPLEMENTED),
        **dict(PROPOSED_GUARDS),
    }
)

_SURFACE_BY_VALUE = {item.value: item for item in Surface}
_EFFECT_BY_VALUE = {item.value: item for item in Effect}
_WIRING_BY_VALUE = {item.value: item for item in Wiring}

EXTRA_ENTRYPOINTS: tuple[EntrypointSpec, ...] = tuple(
    EntrypointSpec(
        id=row.id,
        target=row.target,
        surface=_SURFACE_BY_VALUE[row.surface],
        effects=tuple(_EFFECT_BY_VALUE[value] for value in row.effects),
        guard_contracts=row.guard_contracts,
        wiring=_WIRING_BY_VALUE[row.wiring],
        migration=row.migration,
        anchors=row.anchors,
    )
    for row in PROPOSED_ENTRYPOINTS
)

ENTRYPOINTS: tuple[EntrypointSpec, ...] = (
    *legacy.ENTRYPOINTS,
    *EXTRA_ENTRYPOINTS,
)


RECOVERY_SOURCE = Path(*SCANNER_MODULE.split(".")).with_suffix(".py")


def required_guard_contracts(
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                contract
                for spec in registry
                if spec.wiring is not Wiring.LEGACY_CONTAINED
                for contract in spec.guard_contracts
            }
        )
    )


def guard_status(
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> dict[str, bool]:
    return {
        contract: bool(GUARD_CONTRACT_IMPLEMENTED.get(contract, False))
        for contract in required_guard_contracts(registry)
    }


def _recovery_discovery(
    root: Path,
) -> tuple[tuple[DiscoveredEntrypoint, ...], tuple[ConformanceFinding, ...]]:
    path = root / RECOVERY_SOURCE
    target_prefix = (
        f"{SCANNER_MODULE}:{SCANNER_CLASS}."
    )
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return (), (
            ConformanceFinding(
                code="scan.source_unreadable",
                severity=Severity.BLOCKER,
                target=RECOVERY_SOURCE.as_posix(),
                detail=f"{type(exc).__name__}: {exc}",
            ),
        )

    selected_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == SCANNER_CLASS
        ),
        None,
    )
    if selected_class is None:
        return (), (
            ConformanceFinding(
                code="scan.expected_class_missing",
                severity=Severity.BLOCKER,
                target=f"{SCANNER_MODULE}:{SCANNER_CLASS}",
                detail="recovery consumption class is absent from its pinned module",
            ),
        )

    methods = {
        node.name: node
        for node in selected_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    discoveries: list[DiscoveredEntrypoint] = []
    findings: list[ConformanceFinding] = []
    for method in SCANNER_METHODS:
        node = methods.get(method)
        target = f"{target_prefix}{method}"
        if node is None:
            findings.append(
                ConformanceFinding(
                    code="scan.expected_method_missing",
                    severity=Severity.BLOCKER,
                    target=target,
                    detail="registered recovery consumption method is absent",
                )
            )
            continue
        discoveries.append(
            DiscoveredEntrypoint(
                target=target,
                surface=Surface.PYTHON,
                effects=(Effect.FILESYSTEM_WRITE,),
                is_async=isinstance(node, ast.AsyncFunctionDef),
                source=RECOVERY_SOURCE.as_posix(),
                line=node.lineno,
            )
        )
    return tuple(discoveries), tuple(findings)


def discover_entrypoints(
    root: str | Path,
) -> tuple[tuple[DiscoveredEntrypoint, ...], tuple[ConformanceFinding, ...]]:
    """Compose legacy discovery with exact recovery-consumption write methods."""

    repo_root = Path(root).resolve()
    base_discoveries, base_findings = legacy.discover_entrypoints(repo_root)
    extra_discoveries, extra_findings = _recovery_discovery(repo_root)

    by_target = {row.target: row for row in base_discoveries}
    findings = list(base_findings)
    for row in extra_discoveries:
        existing = by_target.get(row.target)
        if existing is not None and existing != row:
            findings.append(
                ConformanceFinding(
                    code="scan.composed_discovery_conflict",
                    severity=Severity.BLOCKER,
                    target=row.target,
                    detail=(
                        "legacy and composed scanners disagree on surface, effects, "
                        "source or line"
                    ),
                )
            )
        else:
            by_target[row.target] = row
    findings.extend(extra_findings)
    return (
        tuple(sorted(by_target.values(), key=lambda row: row.target)),
        tuple(
            sorted(
                findings,
                key=lambda row: (
                    row.code,
                    row.target,
                    row.detail,
                    row.severity.value,
                ),
            )
        ),
    )


def validate_registry(
    root: str | Path,
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> tuple[ConformanceFinding, ...]:
    """Validate the composed registry without mutating legacy module globals."""

    repo_root = Path(root).resolve()
    findings: list[ConformanceFinding] = []
    ids = Counter(spec.id for spec in registry)
    targets = Counter(spec.target for spec in registry)
    for entry_id, count in sorted(ids.items()):
        if count > 1:
            findings.append(
                ConformanceFinding(
                    code="registry.duplicate_id",
                    severity=Severity.BLOCKER,
                    target=entry_id,
                    detail=f"registry ID appears {count} times",
                )
            )
    for target, count in sorted(targets.items()):
        if count > 1:
            findings.append(
                ConformanceFinding(
                    code="registry.duplicate_target",
                    severity=Severity.BLOCKER,
                    target=target,
                    detail=f"registry target appears {count} times",
                )
            )

    for spec in registry:
        if not spec.effects:
            findings.append(
                ConformanceFinding(
                    code="registry.empty_effects",
                    severity=Severity.BLOCKER,
                    target=spec.target,
                    detail="registered entrypoint has no declared effects",
                )
            )
        for contract in spec.guard_contracts:
            if contract not in GUARD_CONTRACT_IMPLEMENTED:
                findings.append(
                    ConformanceFinding(
                        code="registry.unknown_guard_contract",
                        severity=Severity.BLOCKER,
                        target=spec.target,
                        detail=f"unknown guard contract {contract!r}",
                    )
                )
            elif not GUARD_CONTRACT_IMPLEMENTED[contract]:
                findings.append(
                    ConformanceFinding(
                        code="registry.guard_contract_unimplemented",
                        severity=Severity.BLOCKER,
                        target=spec.target,
                        detail=f"guard contract {contract!r} is not implemented",
                    )
                )
        if spec.wiring is Wiring.UNGUARDED:
            findings.append(
                ConformanceFinding(
                    code="registry.unguarded",
                    severity=Severity.BLOCKER,
                    target=spec.target,
                    detail="entrypoint is registered as unguarded",
                )
            )
        elif spec.wiring is Wiring.INVENTORY_ONLY:
            findings.append(
                ConformanceFinding(
                    code="registry.inventory_only",
                    severity=Severity.BLOCKER,
                    target=spec.target,
                    detail="entrypoint is inventoried but not guarded",
                )
            )
        elif spec.wiring is Wiring.LEGACY_CONTAINED:
            if not spec.legacy_reason:
                findings.append(
                    ConformanceFinding(
                        code="registry.legacy_reason_missing",
                        severity=Severity.BLOCKER,
                        target=spec.target,
                        detail="legacy-contained row lacks an explicit reason",
                    )
                )
            if not spec.migration:
                findings.append(
                    ConformanceFinding(
                        code="registry.legacy_migration_missing",
                        severity=Severity.BLOCKER,
                        target=spec.target,
                        detail="legacy-contained row lacks a migration plan",
                    )
                )
        elif spec.legacy_reason:
            findings.append(
                ConformanceFinding(
                    code="registry.legacy_reason_on_active_row",
                    severity=Severity.BLOCKER,
                    target=spec.target,
                    detail="active row carries a legacy-only reason",
                )
            )

        try:
            source_path, source_text, _ = legacy._target_node(repo_root, spec.target)
        except (FileNotFoundError, LookupError, SyntaxError, ValueError) as exc:
            findings.append(
                ConformanceFinding(
                    code="registry.target_unresolvable",
                    severity=Severity.BLOCKER,
                    target=spec.target,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        source_tree = ast.parse(source_text, filename=str(source_path))
        for anchor in spec.anchors:
            if not legacy._anchor_found(source_tree, anchor):
                findings.append(
                    ConformanceFinding(
                        code="registry.anchor_missing",
                        severity=Severity.BLOCKER,
                        target=spec.target,
                        detail=f"declared anchor {anchor!r} is absent",
                    )
                )
    return tuple(
        sorted(
            findings,
            key=lambda row: (
                row.code,
                row.target,
                row.detail,
                row.severity.value,
            ),
        )
    )


def check_conformance(
    root: str | Path,
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> ConformanceReport:
    """Run the legacy checks against the composed registry and scanner."""

    repo_root = Path(root).resolve()
    registry_tuple = tuple(registry)
    registry_by_target = {spec.target: spec for spec in registry_tuple}
    discoveries, scan_findings = discover_entrypoints(repo_root)
    shell_discoveries, shell_findings = legacy.discover_shell_entrypoints(repo_root)
    all_discoveries = tuple(
        sorted(
            (*discoveries, *shell_discoveries),
            key=lambda row: row.target,
        )
    )
    discovered_by_target = {row.target: row for row in all_discoveries}
    findings: list[ConformanceFinding] = [
        *validate_registry(repo_root, registry_tuple),
        *scan_findings,
        *shell_findings,
        *legacy.validate_registered_anchors(repo_root, registry_tuple),
    ]

    for target, discovered in sorted(discovered_by_target.items()):
        spec = registry_by_target.get(target)
        if spec is None:
            findings.append(
                ConformanceFinding(
                    code="scan.unregistered_effect_entrypoint",
                    severity=Severity.BLOCKER,
                    target=target,
                    detail=(
                        f"discovered {discovered.surface.value} entrypoint at "
                        f"{discovered.source}:{discovered.line} with effects "
                        f"{[effect.value for effect in discovered.effects]!r}"
                    ),
                )
            )
            continue
        if discovered.surface is not spec.surface:
            findings.append(
                ConformanceFinding(
                    code="scan.surface_mismatch",
                    severity=Severity.BLOCKER,
                    target=target,
                    detail=(
                        f"registry surface={spec.surface.value}, "
                        f"discovered surface={discovered.surface.value}"
                    ),
                )
            )
        missing_effects = sorted(
            effect.value
            for effect in set(discovered.effects) - set(spec.effects)
        )
        if missing_effects:
            findings.append(
                ConformanceFinding(
                    code="scan.effect_mismatch",
                    severity=Severity.BLOCKER,
                    target=target,
                    detail=f"registry omits discovered effects {missing_effects!r}",
                )
            )

    for spec in registry_tuple:
        if (
            spec.target not in discovered_by_target
            and not spec.allow_missing_discovery
        ):
            findings.append(
                ConformanceFinding(
                    code="registry.missing_discovery",
                    severity=Severity.BLOCKER,
                    target=spec.target,
                    detail="registered entrypoint was not found by static discovery",
                )
            )

    unique_findings: dict[
        tuple[str, str, str, str], ConformanceFinding
    ] = {}
    for finding in findings:
        key = (
            finding.code,
            finding.target,
            finding.detail,
            finding.severity.value,
        )
        unique_findings[key] = finding
    ordered_findings = tuple(
        sorted(
            unique_findings.values(),
            key=lambda row: (
                row.code,
                row.target,
                row.detail,
                row.severity.value,
            ),
        )
    )
    blocker_count, error_count, warning_count = legacy._classify_findings(
        ordered_findings
    )
    inventory_sha256 = legacy._file_sha(repo_root / "daedalus" / "spine" / "effect_boundary.py")
    extension_sha256 = legacy._file_sha(
        repo_root
        / "daedalus"
        / "spine"
        / "promotion_recovery_consumption_inventory.py"
    )
    composed_inventory_sha256 = canonical_sha(
        {
            "legacy_inventory_sha256": inventory_sha256,
            "extension_inventory_sha256": extension_sha256,
            "registry": [spec.to_dict() for spec in registry_tuple],
        }
    )
    return ConformanceReport(
        root=str(repo_root),
        registry=registry_tuple,
        discovered=all_discoveries,
        findings=ordered_findings,
        guard_status=guard_status(registry_tuple),
        inventory_sha256=composed_inventory_sha256,
        closed=blocker_count == 0 and error_count == 0,
        blocker_count=blocker_count,
        error_count=error_count,
        warning_count=warning_count,
    )


def build_receipt(
    root: str | Path,
    *,
    source_revision: str | None = None,
    generated_at: str | None = None,
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> EffectBoundaryReceipt:
    repo_root = Path(root).resolve()
    report = check_conformance(repo_root, registry)
    revision = source_revision or os.environ.get("GITHUB_SHA") or "unknown"
    timestamp = generated_at or legacy._utc_now()
    receipt_body = {
        "source_revision": revision,
        "generated_at": timestamp,
        "report_sha256": report.digest,
        "inventory_sha256": report.inventory_sha256,
        "closed": report.closed,
        "blocker_count": report.blocker_count,
        "error_count": report.error_count,
        "warning_count": report.warning_count,
    }
    return EffectBoundaryReceipt(
        **receipt_body,
        receipt_sha256=canonical_sha(receipt_body),
    )


def write_receipt(path: str | Path, receipt: EffectBoundaryReceipt) -> Path:
    return legacy.write_receipt(path, receipt)


def load_receipt(path: str | Path) -> EffectBoundaryReceipt:
    return legacy.load_receipt(path)


def validate_receipt(
    receipt: EffectBoundaryReceipt,
    *,
    source_revision: str,
    inventory_sha256: str,
) -> None:
    return legacy.validate_receipt(
        receipt,
        source_revision=source_revision,
        inventory_sha256=inventory_sha256,
    )


def enforce(root: str | Path) -> ConformanceReport:
    report = check_conformance(root)
    if not report.closed:
        raise EffectBoundaryViolation(report)
    return report


__all__ = [
    "ConformanceFinding",
    "ConformanceReport",
    "DiscoveredEntrypoint",
    "Effect",
    "EffectBoundaryReceipt",
    "EffectBoundaryViolation",
    "ENTRYPOINTS",
    "EXTRA_ENTRYPOINTS",
    "EntrypointSpec",
    "GUARD_CONTRACT_IMPLEMENTED",
    "Severity",
    "Surface",
    "Wiring",
    "build_receipt",
    "check_conformance",
    "discover_entrypoints",
    "enforce",
    "guard_status",
    "load_receipt",
    "required_guard_contracts",
    "validate_receipt",
    "validate_registry",
    "write_receipt",
]
