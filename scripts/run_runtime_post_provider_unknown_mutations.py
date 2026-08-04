#!/usr/bin/env python3
"""Run bounded mutations over the post-provider unknown-outcome boundary."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/runtimes/broker.py"
BEHAVIOR = "tests/runtimes/test_runtime_provider_broker.py"
DURABLE = "tests/runtimes/test_runtime_provider_post_invoke_unknown.py"
REVIEW = "tests/runtimes/test_runtime_provider_post_invoke_unknown_review.py"
MUTATIONS = {
    "restore-failed-terminal": (
        """    except BaseException as exc:\n        raise RuntimeProviderReconciliationRequired(\n            entrypoint_id=spec.id,\n            runtime_id=spec.runtime_id,\n            start_receipt=start.receipt,\n            phase=\"output-evidence\",\n            cause_sha256=_exception_detail(\"output-evidence\", exc),\n        ) from exc\n""",
        """    except BaseException as exc:\n        _finish_or_raise_state(\n            authorization,\n            start.receipt,\n            outcome=\"failed\",\n            detail_sha256=_exception_detail(\"output-evidence\", exc),\n        )\n        raise\n""",
        BEHAVIOR,
    ),
    "reinvoke-exact-replay": (
        "if not start.execute:\n        return RuntimeInvocationResult(",
        "if False and not start.execute:\n        return RuntimeInvocationResult(",
        DURABLE,
    ),
    "retain-provider-value": (
        "self.cause_sha256 = cause_sha256",
        "self.cause_sha256 = cause_sha256\n        self.value = object()",
        REVIEW,
    ),
    "expose-raw-cause-text": (
        '"authenticated reconciliation is required"',
        '"authenticated reconciliation is required: " + str(self.__cause__)',
        REVIEW,
    ),
}


def _run(*tests: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    try:
        baseline = _run(BEHAVIOR, DURABLE, REVIEW)
    except subprocess.TimeoutExpired:
        print("baseline timed out", file=sys.stderr)
        return 2
    if baseline.returncode != 0:
        print("baseline failed before mutations", file=sys.stderr)
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    timeouts: list[str] = []
    try:
        for name, (needle, replacement, selected) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            try:
                completed = _run(selected)
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} post-provider unknown-outcome mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
