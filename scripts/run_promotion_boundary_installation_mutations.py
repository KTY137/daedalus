from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/kernel/test_promotion_boundary_installation.py",
    "tests/kernel/test_promotion_boundary_installation_review.py",
    "tests/kernel/test_promotion_effect_inventory.py",
    "tests/kernel/test_promotion_manager_installation.py",
)


@dataclass(frozen=True)
class Mutation:
    name: str
    relative_path: str
    needle: str
    replacement: str


MUTATIONS = (
    Mutation(
        "remove-live-manager-installation",
        "daedalus/kairos/gated_writes.py",
        "install_promotion_manager_boundary(globals())\n",
        "pass  # mutant removed manager boundary installation\n",
    ),
    Mutation(
        "remove-live-replay-installation",
        "daedalus/kairos/gated_writes.py",
        "install_promotion_manager_replay_boundary(globals())\n",
        "pass  # mutant removed replay boundary installation\n",
    ),
    Mutation(
        "invert-live-installation-order",
        "daedalus/kairos/gated_writes.py",
        "install_promotion_manager_boundary(globals())\ninstall_promotion_manager_replay_boundary(globals())",
        "install_promotion_manager_replay_boundary(globals())\ninstall_promotion_manager_boundary(globals())",
    ),
    Mutation(
        "upgrade-open-row-without-composition",
        "daedalus/spine/promotion_effect_rows.py",
        "id=\"kernel.promotion_execution.open\",\n            surface=boundary.Surface.PYTHON,\n            target=(\n                \"daedalus.kernel.promotion_execution:\"\n                \"PromotionExecutionLedger.__init__\"\n            ),\n            effects=(boundary.Effect.FILESYSTEM_WRITE,),\n            guard_contracts=(\"spine.intent_ledger\",),\n            wiring=boundary.Wiring.LOCAL_GUARDS,",
        "id=\"kernel.promotion_execution.open\",\n            surface=boundary.Surface.PYTHON,\n            target=(\n                \"daedalus.kernel.promotion_execution:\"\n                \"PromotionExecutionLedger.__init__\"\n            ),\n            effects=(boundary.Effect.FILESYSTEM_WRITE,),\n            guard_contracts=(\"spine.intent_ledger\",),\n            wiring=boundary.Wiring.CENTRAL,",
    ),
    Mutation(
        "leave-begin-effect-on-stale-registry",
        "daedalus/spine/promotion_effect_rows.py",
        "    boundary.begin_effect.__kwdefaults__ = {\n        **(boundary.begin_effect.__kwdefaults__ or {}),\n        \"registry\": boundary.REGISTRY_BY_ID,\n    }\n",
        "    pass  # mutant leaves begin_effect bound to the stale registry\n",
    ),
    Mutation(
        "admit-partial-registry-installation",
        "daedalus/spine/promotion_effect_rows.py",
        "    if any(row is not None for row in present):\n",
        "    if all(row is not None for row in present):\n",
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
    targets = {
        mutation.relative_path: ROOT / mutation.relative_path
        for mutation in MUTATIONS
    }
    originals = {
        relative: path.read_text(encoding="utf-8")
        for relative, path in targets.items()
    }

    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before mutation campaign\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for mutation in MUTATIONS:
            target = targets[mutation.relative_path]
            original = originals[mutation.relative_path]
            count = original.count(mutation.needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {mutation.name} expected one exact source seam, "
                    f"found {count}\n"
                )
                return 3
            target.write_text(
                original.replace(
                    mutation.needle,
                    mutation.replacement,
                    1,
                ),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(mutation.name)
                sys.stderr.write(f"SURVIVED: {mutation.name}\n")
            else:
                print(f"killed: {mutation.name}")
            target.write_text(original, encoding="utf-8")
    finally:
        for relative, original in originals.items():
            targets[relative].write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} promotion installation mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
