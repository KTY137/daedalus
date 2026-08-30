# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_execution_reader.py"
TESTS = (
    "tests/kernel/test_promotion_execution.py",
    "tests/kernel/test_promotion_execution_reader.py",
    "tests/kernel/test_promotion_execution_reader_integrity.py",
    "tests/kernel/test_promotion_execution_index_contract.py",
    "tests/kernel/test_promotion_execution_reader_review.py",
    "tests/kernel/test_promotion_execution_index_review.py",
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
        sys.stderr.write("promotion execution reader mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "accept-duplicate-json-keys",
            "        if key in value:\n",
            "        if False:\n",
        ),
        (
            "accept-noncanonical-json-bytes",
            "    if rendered != raw:\n",
            "    if False:\n",
        ),
        (
            "trust-substituted-payload-digest",
            '            if str(row["payload_sha"]) != expected_payload_sha:\n',
            "            if False:\n",
        ),
        (
            "accept-more-than-two-events",
            '            if len(events) > 2 or str(events[0]["state"]) != STATE_INTENDED:\n',
            '            if False or str(events[0]["state"]) != STATE_INTENDED:\n',
        ),
        (
            "accept-non-intended-first-event",
            '            if len(events) > 2 or str(events[0]["state"]) != STATE_INTENDED:\n',
            "            if len(events) > 2 or False:\n",
        ),
        (
            "accept-detached-start-event-time",
            '            if str(events[0]["ts"]) != created_ts:\n',
            "            if False:\n",
        ),
        (
            "drop-start-detail-payload-binding",
            '            if start_detail != {"payload_sha": expected_payload_sha}:\n',
            "            if False:\n",
        ),
        (
            "accept-malformed-completed-detail",
            "                    if not isinstance(detail, dict) or set(detail) != {\n                        \"effect_id\",\n                        \"result\",\n                    }:\n",
            "                    if False:\n",
        ),
        (
            "skip-index-shape-verification",
            "        _verify_index_shape(connection)\n",
            "        pass  # mutant: index shape is not verified\n",
        ),
        (
            "trust-index-sql-substitution",
            "    if _normalized_sql(master[\"sql\"]) != _normalized_sql(_PROMOTION_INDEX_SQL):\n",
            "    if False:\n",
        ),
        (
            "trust-nonunique-index",
            '    if int(index["unique"]) != 1 or int(index["partial"]) != 1:\n',
            '    if False or int(index["partial"]) != 1:\n',
        ),
        (
            "open-reader-in-create-write-mode",
            '            f"file:{_uri_path(database)}?mode=ro",\n',
            '            f"file:{_uri_path(database)}?mode=rwc",\n',
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
                sys.stderr.write(result.stdout + result.stderr)
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("reader mutation runner failed to restore source")
    print("killed reader mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
