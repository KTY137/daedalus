from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "gates" / "report.py"
TESTS = (
    "tests/gates/test_gate_report.py",
    "tests/gates/test_gate_report_writer_inventory_review.py",
    "tests/gates/test_gate_report_v2_schema.py",
    "tests/test_spine_writer_inventory.py",
    "tests/test_spine_writer_inventory_review.py",
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
        sys.stderr.write("Gate report writer-inventory mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "missing-writer-inventory-is-not-blocking",
            """        if self.event_store_writer_inventory_sha256 is None:
            rows.append("event_store_writer_inventory_sha256:missing")
""",
            """        if False:
            rows.append("event_store_writer_inventory_sha256:missing")
""",
        ),
        (
            "writer-failures-are-not-projected-as-blockers",
            """            "primary_checkout_mutations",
            "event_store_writer_failures",
        ):
""",
            """            "primary_checkout_mutations",
        ):
""",
        ),
        (
            "gate-report-does-not-bind-inventory-digest",
            "    return inventory.digest, failures, ()\n",
            '    return "0" * 64, failures, ()\n',
        ),
        (
            "inventory-refusal-claims-a-digest",
            """        return (
            None,
            ("inventory-refused",),
""",
            """        return (
            "0" * 64,
            ("inventory-refused",),
""",
        ),
        (
            "coerce-string-security-claim-to-boolean",
            """    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value
""",
            """    return bool(value)
""",
        ),
        (
            "skip-v2-canonical-payload-comparison",
            """            if dict(payload) != report.to_dict():
                raise ValueError("gate report v2 is noncanonical")
""",
            """            if False:
                raise ValueError("gate report v2 is noncanonical")
""",
        ),
        (
            "trust-serialized-closed-flag",
            """            if serialized_closed != report.closed:
                raise ValueError("gate report closed flag is inconsistent")
""",
            """            if False:
                raise ValueError("gate report closed flag is inconsistent")
""",
        ),
    )

    killed: list[str] = []
    try:
        for label, old, new in mutations:
            TARGET.write_text(
                _replace_once(source, old, new, label),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore Gate report source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
