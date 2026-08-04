from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "gated_writes.py"
TESTS = (
    "tests/kernel/test_promotion_manager_live_wiring.py",
    "tests/kernel/test_promotion_manager_live_wiring_review.py",
    "tests/kernel/test_promotion_manager_boundary_review.py",
    "tests/kernel/test_promotion_manager_replay_review.py",
    "tests/kernel/test_promotion_effect_inventory.py",
)

MUTATIONS = (
    (
        "remove-manager-install",
        "_install_promotion_manager_boundary(globals())\n",
        "# manager installation removed\n",
    ),
    (
        "remove-replay-install",
        "_install_promotion_manager_replay_boundary(globals())\n",
        "# replay installation removed\n",
    ),
    (
        "reverse-install-order",
        "_install_promotion_manager_boundary(globals())\n_install_promotion_manager_replay_boundary(globals())\n",
        "_install_promotion_manager_replay_boundary(globals())\n_install_promotion_manager_boundary(globals())\n",
    ),
    (
        "remove-function-compatible-facade",
        "promote_candidates = _make_public_promotion_wrapper(\n    promote_candidates,\n    _ACCOUNTED_PROMOTE_CANDIDATES,\n)\n",
        "# function-compatible public facade removed\n",
    ),
    (
        "retain-manager-installer-alias",
        "del _install_promotion_manager_boundary\n",
        "# manager installer alias retained\n",
    ),
    (
        "retain-replay-installer-alias",
        "del _install_promotion_manager_replay_boundary\n",
        "# replay installer alias retained\n",
    ),
    (
        "retain-wrapper-factory-alias",
        "del _make_public_promotion_wrapper\n",
        "# wrapper factory alias retained\n",
    ),
    (
        "retain-wraps-alias",
        "del _wraps\n",
        "# wraps alias retained\n",
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("promotion manager wiring mutation baseline failed\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    killed: list[str] = []
    try:
        for label, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {label} expected one exact seam, found {count}\n"
                )
                return 3
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                sys.stderr.write(result.stdout)
                sys.stderr.write(result.stderr)
                return 1
            killed.append(label)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    print("killed promotion-manager wiring mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
