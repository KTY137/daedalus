from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "clock": ROOT / "daedalus" / "kernel" / "attempt_clock.py",
    "contracts": ROOT / "daedalus" / "kernel" / "attempt_contracts.py",
    "ledger": ROOT / "daedalus" / "kernel" / "attempt_ledger.py",
    "reader": ROOT / "daedalus" / "kernel" / "attempt_spine_reader.py",
    "workspace": ROOT / "daedalus" / "kernel" / "attempt_workspace.py",
}
TESTS = (
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_lifecycle_review.py",
    "tests/kernel/test_isolated_attempt_cas_review.py",
    "tests/kernel/test_isolated_attempt_schema_review.py",
    "tests/kernel/test_isolated_attempt_spine_wire_review.py",
    "tests/kernel/test_isolated_attempt_time_and_preflight.py",
    "tests/kernel/test_isolated_attempt_time_review.py",
    "tests/kernel/test_isolated_attempt_time_tampering.py",
    "tests/kernel/test_isolated_attempt_effect_inventory.py",
    "tests/kernel/test_source_tree_store.py",
    "tests/kernel/test_source_tree_store_adversarial.py",
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
        sys.stderr.write("isolated-attempt mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "workspace",
            "reexecute-pending-or-terminal-attempt",
            "        if not begin.execute:\n            return PreparedAttempt(begin=begin, workspace=None)\n",
            "        if False:\n            return PreparedAttempt(begin=begin, workspace=None)\n",
        ),
        (
            "workspace",
            "allow-coordinator-ledger-store-substitution",
            "        if ledger.source_store is not source_store:\n",
            "        if False:\n",
        ),
        (
            "ledger",
            "accept-start-replay-with-changed-subject",
            "        if not persisted.same_subject(start):\n",
            "        if False:\n",
        ),
        (
            "contracts",
            "allow-success-without-candidate-tree",
            "        if self.outcome == \"succeeded\" and self.candidate_tree is None:\n",
            "        if False:\n",
        ),
        (
            "workspace",
            "terminalize-process-abort-as-known-fault",
            "        except Exception as exc:\n",
            "        except BaseException as exc:\n",
        ),
        (
            "ledger",
            "skip-terminal-report-cas-check",
            "        self.source_store.read_bytes(report, max_bytes=_MAX_REPORT_BYTES)\n        candidate_ref = None\n",
            "        candidate_ref = None\n",
        ),
        (
            "ledger",
            "skip-input-tree-cas-check-in-ledger",
            "        loaded = self.source_store.load_tree(input_tree.ref)\n        if loaded != input_tree.manifest:\n            raise AttemptBindingMismatch(\n                \"input tree manifest differs from the ledger CAS object\"\n            )\n",
            "        loaded = input_tree.manifest\n",
        ),
        (
            "ledger",
            "remove-canonical-event-spine",
            "        self.spine = path if isinstance(path, SpineLedger) else SpineLedger(path)\n",
            "        self.spine = None\n",
        ),
        (
            "ledger",
            "drop-terminal-effect-id-binding",
            "        if intent.effect_id != receipt.digest:\n",
            "        if False:\n",
        ),
        (
            "reader",
            "allow-read-inspection-to-create-store",
            '            f"file:{_uri_path(database)}?mode=ro",\n',
            "            str(database),\n",
        ),
        (
            "reader",
            "accept-extra-terminal-events",
            "            if len(events) > 2 or str(events[0][\"state\"]) != STATE_INTENDED:\n",
            "            if False:\n",
        ),
        (
            "ledger",
            "accept-read-only-spine-as-writer",
            "        if getattr(self.spine, \"read_only\", False):\n",
            "        if False:\n",
        ),
        (
            "ledger",
            "forge-start-time-instead-of-trusted-clock",
            "        trusted_started_at = self._clock.now()\n",
            '        trusted_started_at = "2099-01-01T00:00:00+00:00"\n',
        ),
        (
            "ledger",
            "allow-terminal-time-equal-to-start",
            "        trusted_completed_at = self._clock.now(minimum=start.started_at)\n",
            "        trusted_completed_at = start.started_at\n",
        ),
        (
            "ledger",
            "drop-start-event-causal-time-binding",
            '        if _timestamp_value(start.started_at, "started_at") > _timestamp_value(\n',
            '        if False and _timestamp_value(start.started_at, "started_at") > _timestamp_value(\n',
        ),
        (
            "ledger",
            "drop-terminal-event-causal-time-binding",
            '        if _timestamp_value(receipt.completed_at, "completed_at") > _timestamp_value(\n',
            '        if False and _timestamp_value(receipt.completed_at, "completed_at") > _timestamp_value(\n',
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
        (
            "workspace",
            "create-primary-nested-workspace-before-refusal",
            "    _assert_disjoint(\n        prospective,\n        primary,\n        \"workspace parent and primary checkout\",\n    )\n",
            "",
        ),
        (
            "workspace",
            "create-cas-nested-workspace-before-refusal",
            "    _assert_disjoint(\n        prospective,\n        cas_root,\n        \"workspace parent and source-tree store\",\n    )\n",
            "",
        ),
        (
            "workspace",
            "accept-broken-workspace-leaf-symlink",
            "        if raw_parent.is_symlink():\n            raise AttemptWorkspaceError(\"workspace parent must not be a symlink\")\n        if raw_parent.exists() and not raw_parent.is_dir():\n",
            "        if raw_parent.exists() and not raw_parent.is_dir():\n",
        ),
        (
            "clock",
            "remove-monotonic-clock-floor",
            "            if current <= self._last:\n",
            "            if False:\n",
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
