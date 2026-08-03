from __future__ import annotations

import ast
from pathlib import Path

import daedalus.kernel as kernel
from daedalus.schemas import PromotionReceipt


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "daedalus"
SCHEMA_PATH = Path("daedalus/schemas.py")


def _production_modules() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py")))


def _relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


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
            if any(
                alias.asname == "PromotionReceipt"
                or (alias.asname is None and alias.name == "PromotionReceipt")
                for alias in node.names
            ):
                imports.append((_relative(path), node.module))

    assert all(module == "daedalus.schemas" for _, module in imports)


def test_canonical_promotion_receipt_identity_is_stable() -> None:
    assert PromotionReceipt.CONTRACT_TYPE == "daedalus.promotion"
    compatibility_export = getattr(kernel, "PromotionReceipt", PromotionReceipt)
    assert compatibility_export is PromotionReceipt


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
    assert "canonical wire contracts remain in :mod:`daedalus.schemas`" in source
