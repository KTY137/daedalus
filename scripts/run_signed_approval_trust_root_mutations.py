"""Mutation campaign for the git-signed-tag owner approval trust root.

Each mutation removes exactly one guard from
``daedalus/kernel/signed_approval.py`` and requires one *named* test to fail.
A guard whose removal keeps the suite green is not a guard, and this script
exits non-zero when that happens.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE = "tests/kernel/test_signed_approval_trust_root.py"
MODULE = ROOT / "daedalus" / "kernel" / "signed_approval.py"


def _pytest(selector: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", selector],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).returncode


def _require_killed(name: str, test: str) -> None:
    selector = f"{SUITE}::{test}"
    if _pytest(selector) == 0:
        raise SystemExit(f"mutation survived: {name} (expected {test} to fail)")
    print(f"  killed by {test}: {name}")


def _mutate(original: str, old: str, new: str, name: str) -> str:
    if original.count(old) != 1:
        raise SystemExit(f"mutation anchor is not unique: {name}")
    return original.replace(old, new, 1)


def main() -> int:
    print(f"baseline: {SUITE}")
    if _pytest(SUITE) != 0:
        raise SystemExit("focused baseline failed before the mutation campaign")

    original = MODULE.read_text(encoding="utf-8")
    try:
        # 1. Trust root read from the working tree instead of the committed blob.
        source = _mutate(
            original,
            '        ["show", f"{ALLOWED_SIGNERS_REVISION}:{OWNER_ALLOWED_SIGNERS_PATH}"],\n'
            '        label="reading the committed allowed-signers list",\n'
            '        check=False,\n'
            "    )\n"
            "    if completed.returncode != 0:",
            '        ["show", f"{ALLOWED_SIGNERS_REVISION}:{OWNER_ALLOWED_SIGNERS_PATH}"],\n'
            '        label="reading the committed allowed-signers list",\n'
            '        check=False,\n'
            "    )\n"
            "    _worktree = root / OWNER_ALLOWED_SIGNERS_PATH\n"
            "    if _worktree.exists():\n"
            "        return _worktree.read_text(encoding='utf-8')\n"
            "    if completed.returncode != 0:",
            "worktree-trust-root",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed(
            "worktree-trust-root",
            "test_rogue_worktree_signers_file_grants_nothing",
        )
        MODULE.write_text(original, encoding="utf-8")

        # 2. Signature verification exit code ignored.
        source = _mutate(
            original,
            "    if verified.returncode != 0:\n"
            "        raise SignedApprovalSignatureError(",
            "    if False:\n"
            "        raise SignedApprovalSignatureError(",
            "ignored-verify-tag-exit",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed("ignored-verify-tag-exit", "test_foreign_signature_is_refused")
        MODULE.write_text(original, encoding="utf-8")

        # 3. Purpose/domain separation dropped.
        source = _mutate(
            original,
            "        if self.purpose != APPROVAL_PURPOSE:",
            "        if False:",
            "no-purpose-separation",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed(
            "no-purpose-separation",
            "test_wrong_purpose_cannot_be_replayed_as_an_approval",
        )
        MODULE.write_text(original, encoding="utf-8")

        # 4. Approval namespace dropped.
        source = _mutate(
            original,
            "    if not tag_name.startswith(APPROVAL_TAG_NAMESPACE):",
            "    if False:",
            "no-tag-namespace",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed(
            "no-tag-namespace",
            "test_tag_outside_the_approval_namespace_is_refused",
        )
        MODULE.write_text(original, encoding="utf-8")

        # 5. Subject binding dropped.
        source = _mutate(
            original,
            "    _require_binding(body, expectation)",
            "    pass  # binding removed",
            "no-subject-binding",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed(
            "no-subject-binding",
            "test_signed_body_naming_another_candidate_is_refused",
        )
        MODULE.write_text(original, encoding="utf-8")

        # 6. Expiry dropped.
        source = _mutate(
            original,
            '    if moment >= _parse_utc(body.expires_at, "expires_at"):',
            "    if False:",
            "no-expiry",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed("no-expiry", "test_expired_approval_is_refused")
        MODULE.write_text(original, encoding="utf-8")

        # 7. Empty trust root accepted.
        source = _mutate(
            original,
            "    if not principals:",
            "    if False:",
            "empty-trust-root-accepted",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed(
            "empty-trust-root-accepted",
            "test_committed_root_without_principals_refuses",
        )
        MODULE.write_text(original, encoding="utf-8")

        # 8. Annotated-tag requirement dropped (lightweight tags accepted).
        source = _mutate(
            original,
            "    if resolved.returncode != 0 or not tag_object:",
            "    if False:",
            "lightweight-tag-accepted",
        )
        MODULE.write_text(source, encoding="utf-8")
        _require_killed(
            "lightweight-tag-accepted", "test_lightweight_tag_carries_no_signature"
        )
        MODULE.write_text(original, encoding="utf-8")
    finally:
        MODULE.write_text(original, encoding="utf-8")

    print("all mutations killed")
    if _pytest(SUITE) != 0:
        raise SystemExit("suite did not return to green after restoration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
