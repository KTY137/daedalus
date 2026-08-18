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


# (name, anchor, replacement, test that must fail)
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "worktree-trust-root",
        "    trust_root = TrustRoot(\n"
        "        commit_oid=commit_oid, blob_oid=blob_oid, content=content.stdout\n"
        "    )",
        "    _wt = Path(repo_root) / OWNER_ALLOWED_SIGNERS_PATH\n"
        "    trust_root = TrustRoot(\n"
        "        commit_oid=commit_oid, blob_oid=blob_oid,\n"
        "        content=_wt.read_text(encoding='utf-8') if _wt.exists()\n"
        "        else content.stdout,\n"
        "    )",
        "test_rogue_worktree_signers_file_grants_nothing",
    ),
    (
        # The anchor was stale: extracting ``_check_tag_signature`` moved this
        # code and left the mutation matching nothing, so the campaign was
        # skipping the single most important guard in the module. Re-aimed.
        "ignored-verify-tag-exit",
        "    if verified.returncode != 0:\n"
        '        return False, "", (output.strip() or "no principal matched")',
        '    return True, "owner@daedalus", output.strip()\n'
        "    if verified.returncode != 0:\n"
        '        return False, "", (output.strip() or "no principal matched")',
        "test_foreign_signature_is_refused",
    ),
    (
        "no-purpose-separation",
        "        if self.purpose != APPROVAL_PURPOSE:",
        "        if False:",
        "test_wrong_purpose_cannot_be_replayed_as_an_approval",
    ),
    (
        "no-tag-namespace",
        "    if not tag_name.startswith(APPROVAL_TAG_NAMESPACE):",
        "    if False:",
        "test_tag_outside_the_approval_namespace_is_refused",
    ),
    (
        "no-subject-binding",
        "    _require_binding(body, expectation)",
        "    pass  # binding removed",
        "test_signed_body_naming_another_candidate_is_refused",
    ),
    (
        "no-expiry",
        '    if moment >= _parse_utc(body.expires_at, "expires_at"):',
        "    if False:",
        "test_expired_approval_is_refused",
    ),
    (
        "empty-trust-root-accepted",
        "    if not trust_root.principals():",
        "    if False:",
        "test_committed_root_without_principals_refuses",
    ),
    (
        # Two call sites resolve a tag object -- the read-only describer and
        # the verifier -- so the bare condition matched twice and aborted the
        # campaign before it reached the guards below it. Anchored on the
        # verifier's own refusal.
        "lightweight-tag-accepted",
        "    if resolved.returncode != 0 or not tag_object:\n"
        "        raise SignedApprovalSignatureError(",
        "    if False:\n        raise SignedApprovalSignatureError(",
        "test_lightweight_tag_carries_no_signature",
    ),
    (
        "no-mechanism-binding",
        "    if body.approval_mechanism_sha256 != trust_root.digest:",
        "    if False:",
        "test_trust_root_swap_invalidates_an_existing_approval",
    ),
    (
        "lazy-fetch-enabled",
        '    env["GIT_NO_LAZY_FETCH"] = "1"',
        '    env.pop("GIT_NO_LAZY_FETCH", None)',
        "test_lazy_fetch_is_disabled_for_every_git_call",
    ),
    # --- F3: the amendment chain is the authority for the trust root -------
    (
        "no-chain-walk",
        "    _verify_amendment_chain(records)",
        "    pass  # chain walk removed",
        "test_a_bare_record_with_no_chain_fields_is_refused",
    ),
    (
        "no-chain-link",
        '            if record.get("previous_record_sha256") != previous.get("record_sha256"):\n'
        '                raise refuse(index, "previous-record hash chain is broken")',
        "            if False:\n"
        '                raise refuse(index, "previous-record hash chain is broken")',
        "test_a_mid_chain_insertion_is_refused",
    ),
    (
        "no-genesis-anchor",
        "            if record.get(\"record_sha256\") != AMENDMENT_GENESIS_RECORD_SHA256:",
        "            if False:",
        "test_a_self_consistent_chain_from_a_foreign_genesis_is_refused",
    ),
    (
        "no-plan-binding",
        "    _verify_ledger_head_matches_plan(root, commit_oid, records[-1])",
        "    pass  # plan binding removed",
        "test_a_well_formed_appended_record_is_still_refused",
    ),
    (
        "chain-rules-forked-from-the-guard",
        '        if record.get("sequence") != index:\n'
        '            raise refuse(index, f"sequence must be {index}")',
        "        if False:\n"
        '            raise refuse(index, f"sequence must be {index}")',
        "test_the_chain_rules_are_the_guard_s_and_not_a_second_copy",
    ),
    # --- N1: the additions-only environment check --------------------------
    (
        "env-guard-is-an-assert-again",
        "        if env.get(name) != value:\n"
        "            raise SignedApprovalError(\n"
        '                f"the signed-approval git environment weakened {name}: "\n'
        '                f"canonical {value!r} became {env.get(name)!r}. Refusing to "\n'
        '                "run git in an environment weaker than the canonical one."\n'
        "            )",
        "        assert env.get(name) == value, (\n"
        '            f"the signed-approval git environment weakened {name}"\n'
        "        )",
        "test_the_environment_guard_still_runs_under_python_O",
    ),
    (
        "env-guard-compares-removed-keys",
        "        if name in deliberately_removed:\n            continue",
        "        if False:\n            continue",
        "test_the_scrubbed_variables_being_set_does_not_break_verification",
    ),
    # --- N3: the mint, not the carried construction token ------------------
    (
        "receipt-trusts-isinstance-alone",
        "    if isinstance(verified, VerifiedSignedApproval) and not _is_minted(verified):",
        "    if False:",
        "test_dataclasses_replace_cannot_launder_an_approval",
    ),
    (
        "no-mint-on-verification",
        "    object.__setattr__(verified, _MINT_ATTR, _CONSTRUCTION_TOKEN)",
        "    pass  # mint removed",
        "test_a_real_verification_still_produces_an_approved_receipt",
    ),
)


def _pytest(selector: str) -> int:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", selector],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).returncode


def main() -> int:
    print(f"baseline: {SUITE}")
    if _pytest(SUITE) != 0:
        raise SystemExit("focused baseline failed before the mutation campaign")

    original = MODULE.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, anchor, replacement, test in MUTATIONS:
            if original.count(anchor) != 1:
                raise SystemExit(
                    f"mutation anchor is not unique ({original.count(anchor)}): {name}"
                )
            MODULE.write_text(original.replace(anchor, replacement, 1), encoding="utf-8")
            if _pytest(f"{SUITE}::{test}") == 0:
                survivors.append(f"{name} (expected {test} to fail)")
                print(f"  SURVIVED: {name}")
            else:
                print(f"  killed by {test}: {name}")
            MODULE.write_text(original, encoding="utf-8")
    finally:
        MODULE.write_text(original, encoding="utf-8")

    if survivors:
        raise SystemExit("mutations survived:\n  " + "\n  ".join(survivors))
    print(f"all {len(MUTATIONS)} mutations killed")
    if _pytest(SUITE) != 0:
        raise SystemExit("suite did not return to green after restoration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
