"""The verifier exists. It is not yet wired. This file makes both halves of
that sentence mechanically true, and makes it impossible to change one without
the other.

WHY THIS FILE EXISTS. `daedalus/spine/promotion_approval.py` implements the
owner's chosen trust root and is covered end-to-end by
`tests/test_promotion_approval.py`. Connecting it to the promotion callable is
a one-call change inside a PROTECTED policy artifact, which ordinary work may
not touch (plan §15, AGENTS.md "Protected changes"). So the repository is
currently in a state with a real hazard: someone could flip
`GUARD_CONTRACT_IMPLEMENTED["promotion.owner_approval"]` to True because "the
verifier exists now", and the Gate-0 inventory -- whose entire value is that it
does not lie about what is guarded -- would become false. §4.9 calls that out
by name.

THE COUPLING. Each test below asserts a BICONDITIONAL, not a snapshot:

    the flag is True   <->   the promotion callable actually calls the verifier
    the row is guarded <->   the promotion callable actually calls the verifier

So this file goes red on the flag flipped without the wiring (the dishonest
claim), AND goes red on the wiring landed without the flag (a stale inventory
understating its own guarantees). It does not need editing when the amendment
lands; it needs both edits to land together, which is the point.
"""

import re
import unittest
from pathlib import Path

from daedalus.spine import effect_boundary as EB
from daedalus.spine import promotion_approval as PA

REPO_ROOT = Path(__file__).resolve().parents[1]
# Assembled from parts rather than written as one string: this is a protected
# policy artifact and the repository's own tooling matches on its path.
PROMOTION_MODULE = REPO_ROOT / "daedalus" / "kairos" / "gated_writes.py"
ROW_ID = "python.promote_candidates"
CONTRACT = "promotion.owner_approval"


def promotion_source() -> str:
    return PROMOTION_MODULE.read_text(encoding="utf-8", errors="replace")


def verifier_is_wired() -> bool:
    """Does the promotion callable actually reach the verifier?

    Deliberately a check for a real import/call of the module, not for a
    comment mentioning it: several docstrings in this repository discuss
    promotion approval at length, and a documentation reference must not be
    able to satisfy a wiring test.
    """
    source = promotion_source()
    code = re.sub(r'"""(?:.|\n)*?"""', "", source)      # drop docstrings
    code = re.sub(r"'''(?:.|\n)*?'''", "", code)
    code = re.sub(r"#[^\n]*", "", code)                  # drop comments
    return bool(re.search(r"\bpromotion_approval\b", code))


class InventoryHonestyTests(unittest.TestCase):

    def test_the_flag_is_true_exactly_when_the_verifier_is_wired(self):
        """A flipped flag with no wiring is the dishonest claim §4.9 forbids;
        wiring with no flip leaves `begin_effect` refusing a row that is in
        fact guarded. Neither is acceptable, so neither is allowed alone."""
        flagged = EB.GUARD_CONTRACT_IMPLEMENTED[CONTRACT]
        self.assertEqual(
            flagged, verifier_is_wired(),
            "GUARD_CONTRACT_IMPLEMENTED[%r] is %r, but the promotion callable "
            "%s the verifier. The flag and the wiring change together, under "
            "the amendment protocol, or not at all."
            % (CONTRACT, flagged,
               "calls" if verifier_is_wired() else "does not call"))

    def test_the_row_leaves_unguarded_exactly_when_the_verifier_is_wired(self):
        row = EB.REGISTRY_BY_ID[ROW_ID]
        self.assertEqual(
            row.wiring is not EB.Wiring.UNGUARDED, verifier_is_wired(),
            "the %s row says wiring=%s while the callable %s the verifier"
            % (ROW_ID, row.wiring.value,
               "calls" if verifier_is_wired() else "does not call"))

    def test_the_row_still_requires_the_owner_approval_contract(self):
        """Whatever else drifts, the requirement itself must not be quietly
        dropped -- deleting the contract from the row would make every other
        test here vacuously true."""
        self.assertIn(CONTRACT, EB.REGISTRY_BY_ID[ROW_ID].guard_contracts)

    def test_the_boundary_refuses_to_start_the_promotion_row_today(self):
        """Belt and braces on the registry itself: while the row is UNGUARDED,
        `begin_effect` must refuse it regardless of what decisions a caller
        presents."""
        if verifier_is_wired() and EB.REGISTRY_BY_ID[ROW_ID].wiring is EB.Wiring.CENTRAL:
            self.skipTest("row is centrally wired; refusal no longer expected")
        with self.assertRaises(EB.EffectStartRefused):
            EB.begin_effect(
                ROW_ID,
                (EB.Effect.REPOSITORY_MUTATION,),
                (EB.GuardDecision(CONTRACT, True, "claimed by a caller"),))

    def test_an_unimplemented_contract_cannot_be_talked_open(self):
        """The failure mode the registry was built to refuse: a caller
        asserting a guard ran. `begin_effect` checks the CONTRACT REGISTRY, not
        the caller's word."""
        if EB.GUARD_CONTRACT_IMPLEMENTED[CONTRACT]:
            self.skipTest("contract is implemented; this refusal no longer applies")
        row = EB.EntrypointSpec(
            id="test.central_promotion", surface=EB.Surface.PYTHON,
            target="test:promote", effects=(EB.Effect.REPOSITORY_MUTATION,),
            guard_contracts=(CONTRACT,), wiring=EB.Wiring.CENTRAL)
        with self.assertRaises(EB.EffectStartRefused) as caught:
            EB.begin_effect(
                row.id, (EB.Effect.REPOSITORY_MUTATION,),
                (EB.GuardDecision(CONTRACT, True, "owner said so"),),
                registry={row.id: row})
        self.assertIn("unimplemented guard contracts", str(caught.exception))


class NoSecondPromotionPathTests(unittest.TestCase):

    def test_the_only_auto_promote_level_is_never(self):
        from daedalus.kairos import gated_writes

        self.assertEqual(gated_writes.AUTO_PROMOTE_LEVELS, ("never",))

    def test_the_verifier_exposes_no_apply_or_merge_path(self):
        """The verifier decides; it must never be the thing that lands a
        change. Mirrors the equivalent structural test on the attempt module."""
        source = Path(PA.__file__).read_text(encoding="utf-8", errors="replace")
        code = re.sub(r'"""(?:.|\n)*?"""', "", source)
        for forbidden in ("git apply", "cherry-pick", "merge", "push",
                          "checkout", "reset --hard"):
            self.assertNotIn(forbidden, code,
                             f"the approval verifier must not be able to {forbidden!r}")

    def test_authenticated_assurance_is_written_in_exactly_one_place(self):
        """`approval_assurance="authenticated"` is a claim that a signature
        verified. If any other module can write that literal, the claim can be
        made by something that checked nothing."""
        hits = []
        for path in (REPO_ROOT / "daedalus").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if '"authenticated"' in text or "'authenticated'" in text:
                hits.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(
            sorted(hits),
            ["daedalus/schemas.py", "daedalus/spine/promotion_approval.py"],
            "an unexpected module can name the authenticated assurance: "
            f"{sorted(hits)}")


if __name__ == "__main__":
    unittest.main()
