"""Revision-bound inventory for the live promotion effect boundary.

This module is deliberately read-only. It does not issue OwnerApproval,
consume an EffectLease, invoke Git, create a worktree, merge a branch, or
perform a promotion. It projects the exact promotion-related rows required in
the canonical Gate-0 effect registry and verifies that the source anchors those
rows claim still exist at the inspected repository revision.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    Effect,
    EntrypointSpec,
    Wiring,
    registry_sha256,
)


SCHEMA = "daedalus-promotion-effect-inventory/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MAX_SOURCE_BYTES = 4 * 1024 * 1024


class PromotionEffectInventoryError(RuntimeError):
    """The promotion inventory could not be established conservatively."""


@dataclass(frozen=True)
class PromotionEffectRequirement:
    entrypoint_id: str
    target: str
    effects: tuple[Effect, ...]
    guard_contracts: tuple[str, ...]
    source_path: str
    owner_kind: str
    owner_name: str
    required_calls: tuple[str, ...]


REQUIREMENTS: tuple[PromotionEffectRequirement, ...] = (
    PromotionEffectRequirement(
        entrypoint_id="python.promote_candidates",
        target="daedalus.kairos.gated_writes:promote_candidates",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=(
            "spine.intent_ledger",
            "containment.worktree",
            "promotion.owner_approval",
        ),
        source_path="daedalus/kairos/gated_writes.py",
        owner_kind="module",
        owner_name="",
        required_calls=(
            "_install_promotion_manager_boundary",
            "_install_promotion_manager_replay_boundary",
        ),
    ),
    PromotionEffectRequirement(
        entrypoint_id="kernel.promotion_execution.open",
        target=(
            "daedalus.kernel.promotion_execution:"
            "PromotionExecutionLedger.__init__"
        ),
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("spine.intent_ledger",),
        source_path="daedalus/kernel/promotion_execution.py",
        owner_kind="method",
        owner_name="PromotionExecutionLedger.__init__",
        required_calls=(
            "open_gate0_spine_writer",
            "_install_single_start_invariant",
        ),
    ),
    PromotionEffectRequirement(
        entrypoint_id="kernel.promotion_execution.begin",
        target=(
            "daedalus.kernel.promotion_execution:"
            "PromotionExecutionLedger.begin"
        ),
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("spine.intent_ledger",),
        source_path="daedalus/kernel/promotion_execution.py",
        owner_kind="method",
        owner_name="PromotionExecutionLedger.begin",
        required_calls=("record_intent",),
    ),
    PromotionEffectRequirement(
        entrypoint_id="kernel.promotion_execution.complete",
        target=(
            "daedalus.kernel.promotion_execution:"
            "PromotionExecutionLedger.complete"
        ),
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("spine.intent_ledger",),
        source_path="daedalus/kernel/promotion_execution.py",
        owner_kind="method",
        owner_name="PromotionExecutionLedger.complete",
        required_calls=("mark_completed",),
    ),
)


@dataclass(frozen=True)
class PromotionEffectFinding:
    entrypoint_id: str
    target: str
    status: str
    blockers: tuple[str, ...]
    source_path: str
    source_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "entrypoint_id": self.entrypoint_id,
            "target": self.target,
            "status": self.status,
            "blockers": list(self.blockers),
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True)
class PromotionEffectInventoryReport:
    source_revision: str
    registry_sha256: str
    findings: tuple[PromotionEffectFinding, ...]
    closed: bool
    report_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "source_revision": self.source_revision,
            "registry_sha256": self.registry_sha256,
            "findings": [finding.to_dict() for finding in self.findings],
            "closed": self.closed,
            "report_sha256": self.report_sha256,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_bytes(root: Path, relative: str) -> tuple[Path, bytes]:
    candidate = root / relative
    try:
        resolved_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PromotionEffectInventoryError(
            f"promotion inventory source is unavailable: {relative}"
        ) from exc
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PromotionEffectInventoryError(
            f"promotion inventory source escapes repository: {relative}"
        ) from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise PromotionEffectInventoryError(
            "promotion inventory source must be a regular non-symlink file: "
            f"{relative}"
        )
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise PromotionEffectInventoryError(
            f"promotion inventory source is unreadable: {relative}"
        ) from exc
    if len(payload) > _MAX_SOURCE_BYTES:
        raise PromotionEffectInventoryError(
            f"promotion inventory source exceeds {_MAX_SOURCE_BYTES} bytes: {relative}"
        )
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PromotionEffectInventoryError(
            f"promotion inventory source is not UTF-8: {relative}"
        ) from exc
    return resolved, payload


def _call_names(node: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        function = child.func
        if isinstance(function, ast.Name):
            names.add(function.id)
        elif isinstance(function, ast.Attribute):
            names.add(function.attr)
    return frozenset(names)


def _method_node(tree: ast.Module, qualified_name: str) -> ast.FunctionDef:
    class_name, method_name = qualified_name.split(".", 1)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name == method_name
            ):
                return child
    raise PromotionEffectInventoryError(
        f"promotion inventory source lacks method {qualified_name}"
    )


def _source_blockers(
    root: Path,
    requirement: PromotionEffectRequirement,
) -> tuple[tuple[str, ...], str]:
    path, payload = _source_bytes(root, requirement.source_path)
    source_sha = _sha256_bytes(payload)
    source = payload.decode("utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise PromotionEffectInventoryError(
            f"promotion inventory source does not parse: {requirement.source_path}"
        ) from exc

    if requirement.owner_kind == "module":
        calls = _call_names(tree)
    elif requirement.owner_kind == "method":
        calls = _call_names(_method_node(tree, requirement.owner_name))
    else:
        raise PromotionEffectInventoryError(
            f"unknown promotion inventory owner kind: {requirement.owner_kind}"
        )

    missing = tuple(
        f"source.missing_call:{name}"
        for name in requirement.required_calls
        if name not in calls
    )
    return missing, source_sha


def _row_map(registry: Sequence[EntrypointSpec]) -> Mapping[str, EntrypointSpec]:
    rows: dict[str, EntrypointSpec] = {}
    for row in registry:
        if row.id in rows:
            raise PromotionEffectInventoryError(
                f"duplicate effect-registry row: {row.id}"
            )
        rows[row.id] = row
    return rows


def _finding(
    root: Path,
    requirement: PromotionEffectRequirement,
    row: EntrypointSpec | None,
) -> PromotionEffectFinding:
    source_blockers, source_sha = _source_blockers(root, requirement)
    blockers = list(source_blockers)
    if row is None:
        blockers.append("registry.missing")
    else:
        if row.target != requirement.target:
            blockers.append("registry.target_mismatch")
        if tuple(row.effects) != requirement.effects:
            blockers.append("registry.effects_mismatch")
        if tuple(row.guard_contracts) != requirement.guard_contracts:
            blockers.append("registry.guards_mismatch")
        if row.wiring is not Wiring.CENTRAL:
            blockers.append(f"registry.not_central:{row.wiring.value}")

    normalized = tuple(sorted(set(blockers)))
    if not normalized:
        status = "central"
    elif row is None:
        status = "missing"
    elif any(value.endswith("_mismatch") for value in normalized):
        status = "mismatched"
    else:
        status = "blocked"
    return PromotionEffectFinding(
        entrypoint_id=requirement.entrypoint_id,
        target=requirement.target,
        status=status,
        blockers=normalized,
        source_path=requirement.source_path,
        source_sha256=source_sha,
    )


def build_promotion_effect_inventory(
    repository_root: str | Path,
    *,
    source_revision: str,
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> PromotionEffectInventoryReport:
    """Build a deterministic fail-closed report for promotion effect ownership."""
    if not isinstance(source_revision, str) or not _REVISION.fullmatch(
        source_revision
    ):
        raise PromotionEffectInventoryError(
            "source_revision must be exactly 40 lowercase hexadecimal characters"
        )
    root = Path(repository_root)
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PromotionEffectInventoryError("repository root is unavailable") from exc
    if root.is_symlink() or not resolved_root.is_dir():
        raise PromotionEffectInventoryError(
            "repository root must be a regular non-symlink directory"
        )

    rows = _row_map(registry)
    findings = tuple(
        _finding(resolved_root, requirement, rows.get(requirement.entrypoint_id))
        for requirement in REQUIREMENTS
    )
    closed = all(finding.status == "central" for finding in findings)
    payload = {
        "schema": SCHEMA,
        "source_revision": source_revision,
        "registry_sha256": registry_sha256(registry),
        "findings": [finding.to_dict() for finding in findings],
        "closed": closed,
    }
    return PromotionEffectInventoryReport(
        source_revision=source_revision,
        registry_sha256=str(payload["registry_sha256"]),
        findings=findings,
        closed=closed,
        report_sha256=_sha256_bytes(_canonical_json(payload).encode("ascii")),
    )


def verify_promotion_effect_inventory(
    report: PromotionEffectInventoryReport,
    repository_root: str | Path,
    *,
    expected_source_revision: str,
    registry: Sequence[EntrypointSpec] = ENTRYPOINTS,
) -> PromotionEffectInventoryReport:
    """Rebuild and require byte-semantic equality with a retained report."""
    if not isinstance(report, PromotionEffectInventoryReport):
        raise PromotionEffectInventoryError(
            "promotion effect verification requires a typed report"
        )
    rebuilt = build_promotion_effect_inventory(
        repository_root,
        source_revision=expected_source_revision,
        registry=registry,
    )
    if rebuilt != report:
        raise PromotionEffectInventoryError(
            "promotion effect inventory differs from live repository state"
        )
    return rebuilt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit the revision-bound promotion effect inventory"
    )
    parser.add_argument("repository_root")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--require-closed", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        report = build_promotion_effect_inventory(
            args.repository_root,
            source_revision=args.source_revision,
        )
    except PromotionEffectInventoryError as exc:
        raise SystemExit(str(exc)) from exc
    print(_canonical_json(report.to_dict()))
    if args.require_closed and not report.closed:
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "PromotionEffectFinding",
    "PromotionEffectInventoryError",
    "PromotionEffectInventoryReport",
    "PromotionEffectRequirement",
    "REQUIREMENTS",
    "SCHEMA",
    "build_promotion_effect_inventory",
    "main",
    "verify_promotion_effect_inventory",
]
