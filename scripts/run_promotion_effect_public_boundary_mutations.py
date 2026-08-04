from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "promotion_effect_public_boundary.py"
TESTS = (
    "tests/kernel/test_promotion_effect_public_boundary.py",
    "tests/kernel/test_promotion_effect_public_boundary_adversarial.py",
    "tests/kernel/test_promotion_effect_public_boundary_review.py",
)
MUTATIONS = (
    (
        "claim-direct-delegate-unblocked",
        '        "direct_delegate_blocked": True,\n',
        '        "direct_delegate_blocked": False,  # mutant\n',
    ),
    (
        "accept-namespace-substitution",
        "    if source_module.__dict__ is not namespace:\n",
        "    if False:  # mutant accepts another module namespace\n",
    ),
    (
        "skip-capability-presence-guard",
        '        if "promotion_effect_capability" not in kwargs:\n',
        '        if False:  # mutant enters without capability\n',
    ),
    (
        "remove-direct-delegate-scope-guard",
        "            if call_scope.get() is not scope_capability:\n",
        "            if False:  # mutant exposes retained delegate\n",
    ),
    (
        "authorize-scope-without-token",
        "        token = call_scope.set(scope_capability)\n",
        "        token = call_scope.set(None)  # mutant\n",
    ),
    (
        "leak-delegate-scope-after-call",
        "            call_scope.reset(token)\n",
        "            pass  # mutant leaves current context authorized\n",
    ),
    (
        "publish-wrapped-delegate",
        "    public.__signature__ = inspect.signature(delegate)  # type: ignore[attr-defined]\n",
        "    public.__signature__ = inspect.signature(delegate)  # type: ignore[attr-defined]\n    public.__wrapped__ = delegate  # mutant bypass\n",
    ),
    (
        "ignore-public-entrypoint-tampering",
        "        if current is not retained.public_entrypoint:\n",
        "        if False:  # mutant ignores public replacement\n",
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
        sys.stderr.write("baseline failed before promotion-boundary mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} promotion-boundary mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
