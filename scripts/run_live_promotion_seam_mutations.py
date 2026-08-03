from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "seam": ROOT / "daedalus" / "kairos" / "gated_writes.py",
    "promotion": ROOT / "daedalus" / "kernel" / "promotion.py",
}
TESTS = (
    "tests/kernel/test_live_promotion_seam.py",
    "tests/kernel/test_live_promotion_seam_review.py",
    "tests/kernel/test_live_promotion_legacy_retirement.py",
    "tests/kernel/test_persisted_promotion_authorization.py",
    "tests/kernel/test_persisted_promotion_authorization_review.py",
    "tests/kernel/test_promotion_material_review.py",
    "tests/kernel/test_sealed_promotion.py",
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
    originals = {name: path.read_bytes() for name, path in TARGETS.items()}
    sources = {name: data.decode("utf-8") for name, data in originals.items()}
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("focused baseline failed\n" + baseline.stdout + baseline.stderr)
        return 2

    mutations: list[tuple[str, str, list[tuple[str, str]]]] = [
        (
            "bypass-retained-source-integrity",
            "seam",
            [
                (
                    "    if not _hmac.compare_digest(actual, _RETAINED_SOURCE_GIT_BLOB_SHA1):\n",
                    "    if False:\n",
                )
            ],
        ),
        (
            "allow-unpersisted-promotion-effects",
            "seam",
            [
                (
                    "    if approval_ledger is None or not owner_keyring:\n",
                    "    if False:\n",
                )
            ],
        ),
        (
            "skip-pre-effect-persisted-auth",
            "seam",
            [
                (
                    "        from daedalus.kernel.promotion import authorize_persisted_promotion\n\n"
                    "        authorize_persisted_promotion(\n",
                    "        authorize_persisted_promotion = lambda **_kwargs: None\n\n"
                    "        authorize_persisted_promotion(\n",
                )
            ],
        ),
        (
            "bypass-persisted-approval",
            "seam",
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
            "seam",
            [
                (
                    "        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):\n",
                    "        if True:\n",
                )
            ],
        ),
        (
            "allow-stale-regeneration",
            "seam",
            [
                (
                    "            if artifact.base_revision != authorization.live_target_revision:\n",
                    "            if False:\n",
                )
            ],
        ),
        (
            "allow-multi-candidate-retry",
            "seam",
            [
                (
                    "    if len(submitted_candidates) != 1:\n",
                    "    if False:\n",
                )
            ],
        ),
        (
            "apply-mutable-original-after-authorization",
            "seam",
            [
                (
                    "            report = _promote_locked(\n"
                    "                root,\n"
                    "                manager,\n"
                    "                sealed_candidates,\n",
                    "            report = _promote_locked(\n"
                    "                root,\n"
                    "                manager,\n"
                    "                list(submitted_candidates),\n",
                )
            ],
        ),
        (
            "trust-declared-diff-digest",
            "promotion",
            [
                (
                    "        if not hmac.compare_digest(actual_diff_sha256, declared_diff_sha256):\n",
                    "        if False:\n",
                )
            ],
        ),
        (
            "allow-result-artifact-base-split",
            "promotion",
            [
                (
                    "        if result_base != artifact_base:\n",
                    "        if False:\n",
                )
            ],
        ),
        (
            "accept-unearned-terminal-gate",
            "promotion",
            [
                (
                    "        if (\n"
                    "            not isinstance(gate, GateResult)\n"
                    "            or not gate.passed\n"
                    "            or gate.cancelled\n"
                    "            or gate.timed_out\n"
                    "        ):\n",
                    "        if False:\n",
                )
            ],
        ),
    ]

    killed: list[str] = []
    try:
        for label, target_name, replacements in mutations:
            target = TARGETS[target_name]
            mutated = sources[target_name]
            for old, new in replacements:
                mutated = _replace_once(mutated, old, new, label)
            target.write_text(mutated, encoding="utf-8")
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            target.write_bytes(originals[target_name])
    finally:
        for name, target in TARGETS.items():
            target.write_bytes(originals[name])

    for name, target in TARGETS.items():
        if target.read_bytes() != originals[name]:
            raise RuntimeError(
                f"mutation runner failed to restore source bytes for {name}"
            )
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
