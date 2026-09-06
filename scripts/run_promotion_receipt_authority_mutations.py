"""Mutation campaign for the single promotion-receipt authority.

Six mutants, each a way a second promotion authority could creep back into the
kernel, each expected to be KILLED by ``tests/kernel/test_promotion_receipt_authority.py``.
The script edits production files on disk and restores their bytes afterwards,
so run it in an isolated checkout (a scratch ``git worktree``), never in a tree
other people are editing.

Retargeted 2026-09-05: the original (2026-08) pointed at ``daedalus/kernel/contracts.py``
and at a ``PromotionReceipt`` defined in ``daedalus/schemas.py``. Both moved:
``daedalus/kernel/contracts`` is a package, ``OwnerApproval`` lives in
``contracts/security.py``, the canonical ``PromotionReceipt`` and its
``CONTRACT_TYPE`` in ``contracts/canonical.py``, and ``daedalus/schemas.py`` only
re-exports. The script therefore aborted before its first mutation (wiki lane
finding B1, ``runs/wiki_findings_20260905.md``). Markers are checked for
uniqueness before every edit so a further move fails loudly instead of mutating
the wrong line, and they follow the file's own line endings: a fresh Windows
checkout carries CRLF (``core.autocrlf``), the pinned files LF, and a marker
written for one silently matched nothing in the other (measured 2026-09-05).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOCUSED = "tests/kernel/test_promotion_receipt_authority.py"


def _pytest() -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", FOCUSED],
        cwd=ROOT,
        check=False,
    ).returncode


def _require_killed(name: str) -> None:
    if _pytest() == 0:
        raise SystemExit(f"mutation survived: {name}")
    print(f"killed: {name}", flush=True)


def _newline(source: str) -> str:
    return "\r\n" if "\r\n" in source else "\n"


def _unique(source: str, marker: str, name: str) -> None:
    if source.count(marker) != 1:
        raise SystemExit(f"{name} mutation marker is not unique (count={source.count(marker)})")


def _write(path: Path, text: str) -> None:
    # newline="" keeps the file's own line endings instead of re-translating them.
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def main() -> int:
    if _pytest() != 0:
        raise SystemExit("focused baseline failed before mutation campaign")

    security = ROOT / "daedalus" / "kernel" / "contracts" / "security.py"
    canonical = ROOT / "daedalus" / "kernel" / "contracts" / "canonical.py"
    kernel_init = ROOT / "daedalus" / "kernel" / "__init__.py"
    competing_module = ROOT / "daedalus" / "kernel" / "promotion_receipts.py"
    if competing_module.exists():
        raise SystemExit("a competing module already exists; refusing to run the campaign")
    originals = {
        security: security.read_bytes(),
        canonical: canonical.read_bytes(),
        kernel_init: kernel_init.read_bytes(),
    }

    try:
        # 1. A second class named PromotionReceipt in another contracts module.
        source = originals[security].decode("utf-8")
        nl = _newline(source)
        owner_marker = f"@dataclass(frozen=True){nl}class OwnerApproval"
        _unique(source, owner_marker, "duplicate-authority")
        _write(security, source.replace(
            owner_marker,
            f"class PromotionReceipt:{nl}    pass{nl}{nl}{nl}" + owner_marker,
            1,
        ))
        _require_killed("duplicate-promotion-receipt-class")
        security.write_bytes(originals[security])

        # 2. A hidden subclass of the canonical receipt (same package, no import cycle).
        _write(security, source.replace(
            owner_marker,
            f"from daedalus.kernel.contracts.canonical import PromotionReceipt as CanonicalPromotionReceipt{nl}{nl}"
            f"class AlternatePromotionReceipt(CanonicalPromotionReceipt):{nl}"
            f"    pass{nl}{nl}{nl}"
            + owner_marker,
            1,
        ))
        _require_killed("hidden-promotion-receipt-subclass")
        security.write_bytes(originals[security])

        # 3. OwnerApproval claiming the promotion contract type.
        owner_contract = 'CONTRACT_TYPE: ClassVar[str] = "daedalus.owner-approval"'
        _unique(source, owner_contract, "owner contract-type")
        _write(security, source.replace(
            owner_contract,
            'CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion"',
            1,
        ))
        _require_killed("duplicate-canonical-promotion-contract-owner")
        security.write_bytes(originals[security])

        # 4. The canonical receipt renamed to a competing contract type.
        source = originals[canonical].decode("utf-8")
        contract_marker = 'CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion"'
        _unique(source, contract_marker, "contract-type")
        _write(canonical, source.replace(
            contract_marker,
            'CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion-receipt"',
            1,
        ))
        _require_killed("competing-promotion-contract-type")
        canonical.write_bytes(originals[canonical])

        # 5. The retired promotion_receipts module resurrected.
        _write(competing_module,
               'class PromotionExecutionReceipt:\n    """Competing authority mutant."""\n')
        _require_killed("obsolete-promotion-receipts-module")
        competing_module.unlink()

        # 6. The kernel facade claiming authority in its own docstring.
        source = originals[kernel_init].decode("utf-8")
        authority_marker = "not a second contract authority"
        _unique(source, authority_marker, "kernel-authority")
        _write(kernel_init, source.replace(
            authority_marker,
            "an alternate contract authority",
            1,
        ))
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
