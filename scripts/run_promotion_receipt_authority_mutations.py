from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOCUSED = "tests/kernel/test_promotion_receipt_authority.py"


def _pytest() -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", FOCUSED],
        cwd=ROOT,
        check=False,
    ).returncode


def _require_killed(name: str) -> None:
    if _pytest() == 0:
        raise SystemExit(f"mutation survived: {name}")


def main() -> int:
    if _pytest() != 0:
        raise SystemExit("focused baseline failed before mutation campaign")

    contracts = ROOT / "daedalus" / "kernel" / "contracts.py"
    schemas = ROOT / "daedalus" / "schemas.py"
    kernel_init = ROOT / "daedalus" / "kernel" / "__init__.py"
    competing_module = ROOT / "daedalus" / "kernel" / "promotion_receipts.py"
    originals = {
        contracts: contracts.read_bytes(),
        schemas: schemas.read_bytes(),
        kernel_init: kernel_init.read_bytes(),
    }

    try:
        source = originals[contracts].decode("utf-8")
        owner_marker = "@dataclass(frozen=True)\nclass OwnerApproval"
        if source.count(owner_marker) != 1:
            raise SystemExit("duplicate-authority mutation marker is not unique")
        contracts.write_text(
            source.replace(
                owner_marker,
                "class PromotionReceipt:\n    pass\n\n\n" + owner_marker,
                1,
            ),
            encoding="utf-8",
        )
        _require_killed("duplicate-promotion-receipt-class")
        contracts.write_bytes(originals[contracts])

        contracts.write_text(
            source.replace(
                owner_marker,
                "from daedalus.schemas import PromotionReceipt as CanonicalPromotionReceipt\n\n"
                "class AlternatePromotionReceipt(CanonicalPromotionReceipt):\n"
                "    pass\n\n\n"
                + owner_marker,
                1,
            ),
            encoding="utf-8",
        )
        _require_killed("hidden-promotion-receipt-subclass")
        contracts.write_bytes(originals[contracts])

        owner_contract = 'CONTRACT_TYPE: ClassVar[str] = "daedalus.owner-approval"'
        if source.count(owner_contract) != 1:
            raise SystemExit("owner contract-type mutation marker is not unique")
        contracts.write_text(
            source.replace(
                owner_contract,
                'CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion"',
                1,
            ),
            encoding="utf-8",
        )
        _require_killed("duplicate-canonical-promotion-contract-owner")
        contracts.write_bytes(originals[contracts])

        source = originals[schemas].decode("utf-8")
        contract_marker = 'CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion"'
        if source.count(contract_marker) != 1:
            raise SystemExit("contract-type mutation marker is not unique")
        schemas.write_text(
            source.replace(
                contract_marker,
                'CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-receipt"',
                1,
            ),
            encoding="utf-8",
        )
        _require_killed("competing-promotion-contract-type")
        schemas.write_bytes(originals[schemas])

        competing_module.write_text(
            'class PromotionExecutionReceipt:\n    """Competing authority mutant."""\n',
            encoding="utf-8",
        )
        _require_killed("obsolete-promotion-receipts-module")
        competing_module.unlink()

        source = originals[kernel_init].decode("utf-8")
        authority_marker = "not a second contract authority"
        if source.count(authority_marker) != 1:
            raise SystemExit("kernel-authority mutation marker is not unique")
        kernel_init.write_text(
            source.replace(
                authority_marker,
                "an alternate contract authority",
                1,
            ),
            encoding="utf-8",
        )
        _require_killed("kernel-contract-authority-drift")
        kernel_init.write_bytes(originals[kernel_init])
    finally:
        for path, original in originals.items():
            path.write_bytes(original)
        if competing_module.exists():
            competing_module.unlink()

    for path, original in originals.items():
        if path.read_bytes() != original:
            raise SystemExit(f"source restoration failed: {path.relative_to(ROOT)}")
    if competing_module.exists():
        raise SystemExit("temporary competing module was not removed")

    print("promotion receipt authority mutations: 6 killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
