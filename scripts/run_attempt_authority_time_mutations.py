from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "contracts": ROOT / "daedalus" / "kernel" / "attempt_contracts.py",
    "ledger": ROOT / "daedalus" / "kernel" / "attempt_ledger.py",
    "reader": ROOT / "daedalus" / "kernel" / "attempt_spine_reader.py",
}
TESTS = (
    "tests/kernel/test_isolated_attempt_authority_time.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_lifecycle_review.py",
    "tests/kernel/test_isolated_attempt_spine_wire_review.py",
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
    sources = {name: value.decode("utf-8") for name, value in originals.items()}
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("attempt authority-time mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "ledger",
            "source-start-time-from-caller-contract",
            "        started_at = _authority_now()\n",
            "        started_at = attempt.provenance.created_at\n",
        ),
        (
            "ledger",
            "source-completion-time-from-start",
            "        completed_at = _authority_now()\n",
            "        completed_at = start.started_at\n",
        ),
        (
            "ledger",
            "expose-caller-start-time-parameter",
            "        workspace_relative_path: str,\n    ) -> AttemptBeginResult:\n",
            "        workspace_relative_path: str,\n        started_at: str | None = None,\n    ) -> AttemptBeginResult:\n",
        ),
        (
            "ledger",
            "expose-caller-completion-time-parameter",
            "        candidate_tree: StoredSourceTree | None,\n    ) -> AttemptCompletion:\n",
            "        candidate_tree: StoredSourceTree | None,\n        completed_at: str | None = None,\n    ) -> AttemptCompletion:\n",
        ),
        (
            "reader",
            "detach-start-event-time-from-intent-row",
            "            if str(events[0][\"ts\"]) != created_ts:\n",
            "            if False:\n",
        ),
        (
            "ledger",
            "accept-completion-before-start",
            "        if _time(completed_at, \"completed_at\") < _time(\n            start.started_at,\n            \"started_at\",\n        ):\n",
            "        if False:\n",
        ),
        (
            "contracts",
            "detach-start-provenance-time",
            "        if self.provenance.created_at != started_at:\n",
            "        if False:\n",
        ),
        (
            "contracts",
            "detach-terminal-provenance-time",
            "        if self.provenance.created_at != completed_at:\n",
            "        if False:\n",
        ),
    )

    killed: list[str] = []
    try:
        for target_name, label, old, new in mutations:
            target = TARGETS[target_name]
            target.write_text(
                _replace_once(sources[target_name], old, new, label),
                encoding="utf-8",
            )
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
            raise RuntimeError(f"mutation runner failed to restore {name}")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
