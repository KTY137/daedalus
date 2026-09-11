from __future__ import annotations

import ast
from pathlib import Path

import daedalus.kernel as kernel
from daedalus.kernel.contracts.promotion import PromotionReceipt as HierarchyPromotionReceipt
from daedalus.schemas import PromotionReceipt


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "daedalus"
SCHEMA_PATH = Path("daedalus/kernel/contracts/canonical.py")
COMPATIBILITY_PATHS = {
    Path("daedalus/schemas.py"),
    Path("daedalus/kernel/contracts/__init__.py"),
    Path("daedalus/kernel/contracts/promotion.py"),
}


def _production_modules() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py")))


def _relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _assigned_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(
            name for item in target.elts for name in _assigned_names(item)
        )
    return ()


def _references_promotion_receipt(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Name) and node.id == "PromotionReceipt"
    ) or (
        isinstance(node, ast.Attribute) and node.attr == "PromotionReceipt"
    )


def _class_contract_type(node: ast.ClassDef) -> str | None:
    for statement in node.body:
        if isinstance(statement, ast.AnnAssign):
            if (
                isinstance(statement.target, ast.Name)
                and statement.target.id == "CONTRACT_TYPE"
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                return statement.value.value
        if isinstance(statement, ast.Assign):
            if (
                any(
                    isinstance(target, ast.Name) and target.id == "CONTRACT_TYPE"
                    for target in statement.targets
                )
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                return statement.value.value
    return None


def test_promotion_receipt_has_one_class_authority() -> None:
    definitions: list[Path] = []
    for path in _production_modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ClassDef) and node.name == "PromotionReceipt":
                definitions.append(_relative(path))

    assert definitions == [SCHEMA_PATH]


def test_promotion_receipt_imports_cannot_select_another_authority() -> None:
    imports: list[tuple[Path, str | None]] = []
    for path in _production_modules():
        if _relative(path) == SCHEMA_PATH:
            continue
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            if any(alias.name == "PromotionReceipt" for alias in node.names):
                imports.append((_relative(path), node.module))

    assert all(
        path in COMPATIBILITY_PATHS or module == "daedalus.schemas"
        for path, module in imports
    )


def test_promotion_receipt_cannot_be_shadowed_or_subclassed() -> None:
    assignments: list[Path] = []
    subclasses: list[tuple[Path, str]] = []
    for path in _production_modules():
        relative = _relative(path)
        if relative == SCHEMA_PATH:
            continue
        tree = _tree(path)
        imported_names = {"PromotionReceipt"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "daedalus.schemas":
                imported_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "PromotionReceipt"
                )
            if isinstance(node, ast.Assign):
                if any(
                    "PromotionReceipt" in _assigned_names(target)
                    for target in node.targets
                ) or _references_promotion_receipt(node.value):
                    assignments.append(relative)
            elif isinstance(node, ast.AnnAssign):
                if (
                    "PromotionReceipt" in _assigned_names(node.target)
                    or (
                        node.value is not None
                        and _references_promotion_receipt(node.value)
                    )
                ):
                    assignments.append(relative)
            elif isinstance(node, ast.ClassDef):
                if any(
                    (isinstance(base, ast.Name) and base.id in imported_names)
                    or _references_promotion_receipt(base)
                    for base in node.bases
                ):
                    subclasses.append((relative, node.name))

    assert assignments == []
    assert subclasses == []


def test_canonical_promotion_receipt_identity_is_stable() -> None:
    assert PromotionReceipt.CONTRACT_TYPE == "daedalus.promotion"
    assert HierarchyPromotionReceipt is PromotionReceipt
    compatibility_export = getattr(kernel, "PromotionReceipt", PromotionReceipt)
    assert compatibility_export is PromotionReceipt


def test_canonical_contract_type_has_one_owner() -> None:
    owners: list[tuple[Path, str]] = []
    for path in _production_modules():
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.ClassDef)
                and _class_contract_type(node) == "daedalus.promotion"
            ):
                owners.append((_relative(path), node.name))
    assert owners == [(SCHEMA_PATH, "PromotionReceipt")]


def test_no_competing_promotion_receipt_contract_type() -> None:
    offenders: list[Path] = []
    for path in _production_modules():
        if "daedalus.promotion-receipt" in path.read_text(encoding="utf-8"):
            offenders.append(_relative(path))
    assert offenders == []


def test_obsolete_kernel_receipt_authority_is_absent() -> None:
    assert not (PACKAGE / "kernel" / "promotion_receipts.py").exists()


def test_kernel_remains_a_strangler_not_contract_authority() -> None:
    source = (PACKAGE / "kernel" / "__init__.py").read_text(encoding="utf-8")
    assert "not a second contract authority" in source
    assert "canonical wire contracts are owned by :mod:`daedalus.kernel.contracts`" in source
