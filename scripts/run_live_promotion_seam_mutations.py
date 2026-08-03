from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "gated_writes.py"
TESTS = (
    "tests/kernel/test_live_promotion_seam.py",
    "tests/kernel/test_live_promotion_seam_review.py",
    "tests/kernel/test_live_promotion_legacy_retirement.py",
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one mutation site, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("focused baseline failed\n" + baseline.stdout + baseline.stderr)
        return 2

    mutations: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "bypass-retained-source-integrity",
            [
                (
                    "    if not _hmac.compare_digest(actual, _RETAINED_SOURCE_GIT_BLOB_SHA1):\n",
                    "    if False:\n",
                )
            ],
        ),
        (
            "bypass-persisted-approval",
            [
                (
                    "            authorize_promotion = authorize_persisted_promotion\n",
                    "            from daedalus.kernel.promotion import authorize_promotion\n",
                ),
                (
                    "            authorization = authorize_promotion(\n"
                    "                approval_ledger=approval_ledger,\n"
                    "                owner_keyring=owner_keyring,\n",
                    "            authorization = authorize_promotion(\n",
                ),
            ],
        ),
        (
            "authorize-outside-lock",
            [
                (
                    "        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):\n",
                    "        if True:\n",
                )
            ],
        ),
        (
            "allow-stale-regeneration",
            [
                (
                    "            if str(artifact.base_revision) != authorization.live_target_revision:\n",
                    "            if False:\n",
                )
            ],
        ),
        (
            "allow-multi-candidate-retry",
            [("    if len(candidates) != 1:\n", "    if False:\n")],
        ),
    ]

    killed: list[str] = []
    try:
        for label, replacements in mutations:
            mutated = source
            for old, new in replacements:
                mutated = _replace_once(mutated, old, new, label)
            TARGET.write_text(mutated, encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore source bytes")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
