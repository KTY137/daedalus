# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "gates" / "release.py"
TESTS = (
    "tests/gates/test_gate0_release_assessment.py",
    "tests/gates/test_gate0_release_assessment_review.py",
    "tests/gates/test_gate0_release_writer_inventory.py",
    "tests/gates/test_gate_report.py",
    "tests/gates/test_gate_report_writer_inventory_review.py",
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
        sys.stderr.write("Gate-0 release writer-inventory mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "release-accepts-wrong-writer-inventory-digest",
            """    if report.event_store_writer_inventory_sha256 != live_writer_digest:
        writer_mismatches.append("event_store_writer_inventory_sha256")
""",
            """    if False:
        writer_mismatches.append("event_store_writer_inventory_sha256")
""",
        ),
        (
            "release-accepts-forged-writer-failure-projection",
            """    if report.event_store_writer_failures != live_writer_failures:
        writer_mismatches.append("event_store_writer_failures")
""",
            """    if False:
        writer_mismatches.append("event_store_writer_failures")
""",
        ),
        (
            "release-skips-live-writer-blocker-refusal",
            """    if live_writer_failures:
        raise Gate0ReleaseBlocked(
            "live Event-Store writer blockers remain: "
            + ", ".join(live_writer_failures)
        )
""",
            """    if False:
        raise Gate0ReleaseBlocked(
            "live Event-Store writer blockers remain: "
            + ", ".join(live_writer_failures)
        )
""",
        ),
        (
            "release-accepts-v1-report-schema",
            '_REPORT_SCHEMA = "daedalus-gate-report/2"\n',
            '_REPORT_SCHEMA = "daedalus-gate-report/1"\n',
        ),
        (
            "release-omits-writer-digest-field-from-exact-wire",
            '    "event_store_writer_inventory_sha256",\n',
            "",
        ),
        (
            "release-does-not-bind-writer-scan-to-current-revision",
            "            source_revision=current_revision,\n",
            '            source_revision="0" * 40,\n',
        ),
        (
            "release-launders-writer-inventory-refusal",
            """    except WriterInventoryError as exc:
        raise Gate0ReleaseBindingError(
            f"live Event-Store writer inventory refused: {exc}"
        ) from exc
""",
            """    except WriterInventoryError:
        return "0" * 64, ()
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
        raise RuntimeError("mutation runner failed to restore release source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
