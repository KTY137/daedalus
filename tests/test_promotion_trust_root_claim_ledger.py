# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""F3 + F4: the single-use claim, and the stage that selected it by typo.

ADDED beside ``test_promotion_trust_root_truth_table.py``,
``…_adversarial.py`` and ``…_single_caller.py`` rather than folded into them:
those three pin the four precommitted cells and the sole production caller,
and this one pins two things that were true underneath all of them.

F3, MEASURED (Odysseus probe 2, reproduced against the pristine HEAD module).
The single-use record was one predictable file. The nonce is public -- it is in
the owner's signed tag -- so ``replay_key`` and therefore the marker path are
computable by anyone who can read the tag::

    A. pre-created marker -> (False, 'approval … was already spent')   # DoS
    B. after deleting     -> (True,  'approval … claimed …')
    B2. immediately again -> (False, 'approval … was already spent')
    B3. delete + retry    -> (True,  'approval … claimed …')           # REPLAY

Pre-create the marker and the owner's approval can never be spent, and the
refusal says "already spent" so nobody looks further. Unlink it and the
approval is fresh again. Same probe after the chained ledger landed::

    A. -> (False, 'marker without ledger: … has no claim for approval …')
    B. -> (True,  '… (claim ledger record 5ede8fed178c)')
    B2 -> (False, 'ledger says spent: … records approval … as already claimed')
    B3 -> (False, 'ledger says spent: … while its single-use marker is MISSING')

WHAT F3 IS NOT, asserted in ``TheChainIsEvidenceNotABoundaryTests`` so the
limit is in the suite and not only in a docstring: both records live under the
same control root at the same integrity level, so an attacker who can unlink
the marker can also rewrite the chain. The chain makes each attack a two-file
edit, makes partial damage detectable, and keeps a CONTAINED candidate (denied
the control root by the kernel) out of both. The ACL is the boundary.

F4, MEASURED in the same probe. ``stage`` was compared with
``== SEALED_STAGE`` and nothing else, so every other string took the
preauthorization branch, which SKIPS the claim::

    stage='sealed'           promote=True claimed=True  marker_exists=True
    stage='preauthorization' promote=True claimed=False marker_exists=False
    stage='SEALED'           promote=True claimed=False marker_exists=False  <-- FAIL OPEN
    stage='typo'             promote=True claimed=False marker_exists=False  <-- FAIL OPEN

After: ``'SEALED'`` and ``'typo'`` return ``promote=False``, and the two real
constants behave exactly as before.

TO SEE THESE GO RED:

  * F3 -- in ``claim_approval``, delete the ``if key in spent`` and
    ``if present`` blocks (``…_a_planted_marker_is_refused``,
    ``…_a_deleted_marker_does_not_refresh_the_approval``);
  * F3 chain -- delete the ``if status != "ok"`` block
    (``…_a_broken_chain_refuses``);
  * F4 -- delete the ``if stage not in PROMOTION_STAGES`` guard at the top of
    ``evaluate_promotion_trust`` (``UnknownStageFailsClosedTests``), and the
    matching guard in ``authorize_persisted_promotion``
    (``ThePublicKeywordValidatesTheStageTests``).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.kernel.promotion_trust_root import (  # noqa: E402
    PREAUTHORIZATION_STAGE,
    PROMOTION_STAGES,
    SEALED_STAGE,
    ApprovalVerdict,
    SecondFactorOutcome,
    _promotion_state_root,
    claim_approval,
    claim_ledger_path,
    evaluate_promotion_trust,
    replay_key,
)

CAND = "a" * 64
EVID = "b" * 64
REV = "c" * 40
NONCE = "0123456789abcdef0123456789abcdef"


def _verdict(nonce: str = NONCE, candidate: str = CAND) -> ApprovalVerdict:
    return ApprovalVerdict(
        approved=True, reason="test", tag=f"daedalus-approval/{candidate}",
        candidate_sha256=candidate, evidence_sha256=EVID, source_revision=REV,
        signer="owner@test", owner_approval_ref="ref-1", nonce=nonce)


class _RootedInATempControlRoot(unittest.TestCase):
    """Every test gets its own control root, keyed by its own repo identity.

    The state root is DERIVED and takes no parameter -- that is the A12 fix and
    it must stay. This fixture used to isolate by moving ``USERPROFILE``; since
    e23d342d the promotion root folds ``profile_root_disagreement`` into every
    claim, and an environment that disagrees with the OS-reported profile is
    refused with ``profile.root_relocated`` (MEASURED 2026-08-23: all eight
    tests here red on exactly that reason). That refusal is the product being
    right, so the honest isolation is the one ``tests/test_loop.py`` uses: a
    fresh temp REPO per test hashes to a digest nothing was ever written under,
    so the control root beneath the real profile is fresh too. The directory
    it creates is removed on cleanup.
    """

    def setUp(self):
        from daedalus.spine.killswitch import control_root

        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        root = control_root(self.repo)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        self.addCleanup(self._tmp.cleanup)

    def marker(self, verdict: ApprovalVerdict) -> Path:
        key = replay_key(verdict.nonce, verdict.candidate_sha256)
        return _promotion_state_root(self.repo) / "spent" / f"{key}.claimed"


class ClaimApprovalSpendsExactlyOnceTests(_RootedInATempControlRoot):

    def test_the_ordinary_claim_succeeds_and_writes_a_chained_record(self):
        """The control. Without it every refusal below could be produced by a
        function that refuses unconditionally."""
        verdict = _verdict()
        claimed, reason = claim_approval(self.repo, verdict)
        self.assertTrue(claimed, reason)
        self.assertIn("claim ledger record", reason)
        self.assertTrue(self.marker(verdict).exists())
        lines = claim_ledger_path(self.repo).read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["replay_key"],
                         replay_key(NONCE, CAND))
        self.assertEqual(record["prev_sha256"], "")
        self.assertEqual(record["tag"], verdict.tag)

    def test_the_second_claim_is_refused(self):
        verdict = _verdict()
        self.assertTrue(claim_approval(self.repo, verdict)[0])
        claimed, reason = claim_approval(self.repo, verdict)
        self.assertFalse(claimed)
        self.assertIn("ledger says spent", reason)

    def test_a_deleted_marker_does_not_refresh_the_approval(self):
        """B3 in the probe: the replay. Deleting the one predictable file used
        to return ``(True, 'claimed')``."""
        verdict = _verdict()
        self.assertTrue(claim_approval(self.repo, verdict)[0])
        os.unlink(self.marker(verdict))
        claimed, reason = claim_approval(self.repo, verdict)
        self.assertFalse(claimed)
        self.assertIn("ledger says spent", reason)
        self.assertIn("MISSING", reason)

    def test_a_planted_marker_is_refused_as_a_planted_marker(self):
        """A in the probe: the denial of promotion. The old refusal said
        "already spent", which is the same words an honest reuse gets -- so an
        owner whose approval was DoS'd could not tell the difference."""
        verdict = _verdict()
        marker = self.marker(verdict)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("planted by a process running as this user")
        claimed, reason = claim_approval(self.repo, verdict)
        self.assertFalse(claimed)
        self.assertIn("marker without ledger", reason)
        self.assertNotIn("was already spent", reason)
        self.assertIn(str(marker), reason)

    def test_a_different_approval_is_unaffected_by_a_spent_one(self):
        """The ledger must record one approval, not close the gate."""
        first = _verdict()
        second = _verdict(nonce="fedcba9876543210fedcba9876543210")
        self.assertTrue(claim_approval(self.repo, first)[0])
        claimed, reason = claim_approval(self.repo, second)
        self.assertTrue(claimed, reason)
        lines = claim_ledger_path(self.repo).read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["prev_sha256"],
                         _sha_of_line(lines[0]))

    def test_an_unapproved_or_nonce_less_verdict_is_never_claimable(self):
        self.assertFalse(claim_approval(
            self.repo, ApprovalVerdict(False, "no", CAND, "t", nonce=NONCE))[0])
        self.assertFalse(claim_approval(
            self.repo, ApprovalVerdict(True, "yes", CAND, "t", nonce=None))[0])


class TheChainIsEvidenceNotABoundaryTests(_RootedInATempControlRoot):

    def test_a_broken_chain_refuses_rather_than_reading_around_it(self):
        verdict = _verdict()
        self.assertTrue(claim_approval(self.repo, verdict)[0])
        os.unlink(self.marker(verdict))
        path = claim_ledger_path(self.repo)
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        record["prev_sha256"] = "f" * 64          # unlink the chain's first link
        path.write_text(json.dumps(record, sort_keys=True,
                                   separators=(",", ":")) + "\n",
                        encoding="utf-8")
        claimed, reason = claim_approval(self.repo, verdict)
        self.assertFalse(claimed)
        self.assertIn("not trustworthy", reason)
        self.assertIn("does not follow", reason)

    def test_a_truncated_ledger_plus_a_deleted_marker_still_replays(self):
        """THE HONEST NEGATIVE RESULT, kept in the suite on purpose.

        An attacker who can delete the marker can also delete the ledger line,
        and then the approval IS fresh again. This test asserts that hole
        exists so that nobody reads the class above as a security boundary. It
        goes red the day someone anchors the chain head somewhere the control
        root cannot reach -- and that is the day to rewrite it, not silence it.
        """
        verdict = _verdict()
        self.assertTrue(claim_approval(self.repo, verdict)[0])
        os.unlink(self.marker(verdict))
        claim_ledger_path(self.repo).write_text("", encoding="utf-8")
        claimed, _ = claim_approval(self.repo, verdict)
        self.assertTrue(
            claimed,
            "the chain became tamper-PROOF; rewrite this test rather than "
            "deleting it, and say where the head is anchored now")

    def test_pre_migration_promotion_state_is_refused(self):
        # Only %LOCALAPPDATA% is relocated here: that is where the legacy root
        # is read from, and it is not the profile directory the disagreement
        # check guards, so the claim is refused for the legacy state and
        # nothing else.
        la = tempfile.TemporaryDirectory()
        self.addCleanup(la.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": la.name})
        env.start()
        self.addCleanup(env.stop)
        legacy = (Path(la.name) / "daedalus-kernel" / "promotion"
                  / _digest(self.repo))
        (legacy / "spent").mkdir(parents=True)
        claimed, reason = claim_approval(self.repo, _verdict())
        self.assertFalse(claimed)
        self.assertIn("pre-migration", reason)
        self.assertIn(str(legacy), reason)


class UnknownStageFailsClosedTests(_RootedInATempControlRoot):
    """F4: the strictest path was selected by exact string equality."""

    def _decide(self, stage):
        verdict = _verdict()
        return evaluate_promotion_trust(
            repo_root=self.repo, candidate_artifact_sha256=CAND,
            evidence_packet_sha256=EVID, source_revision=REV, stage=stage,
            _root_verifier=lambda *a, **k: verdict,
            _second_factor=SecondFactorOutcome(valid=True, reason="test"))

    def test_a_case_variant_is_refused(self):
        decision = self._decide("SEALED")
        self.assertFalse(decision.promote)
        self.assertEqual(decision.outcome, "REJECT")
        self.assertEqual(decision.record_note, "unknown-promotion-stage")
        self.assertIn("unknown promotion stage", decision.deny_reason)

    def test_a_typo_is_refused(self):
        for stage in ("typo", "sealed ", "", "seal", "Preauthorization"):
            with self.subTest(stage=stage):
                self.assertFalse(self._decide(stage).promote)

    def test_an_unknown_stage_neither_claims_nor_leaves_a_marker(self):
        """The specific fail-open: promote=True with claimed=False."""
        decision = self._decide("SEALED")
        self.assertFalse(decision.claimed)
        self.assertFalse(self.marker(_verdict()).exists())

    def test_the_two_real_constants_still_behave_exactly_as_before(self):
        """Both directions. A guard that rejected every stage would satisfy
        every assertion above and break promotion entirely."""
        sealed = self._decide(SEALED_STAGE)
        self.assertTrue(sealed.promote)
        self.assertTrue(sealed.claimed)
        self.assertTrue(self.marker(_verdict()).exists())

        pre = self._decide(PREAUTHORIZATION_STAGE)
        self.assertTrue(pre.promote)
        self.assertFalse(pre.claimed, "preauthorization must not spend the use")

    def test_the_stage_set_is_the_two_constants(self):
        self.assertEqual(set(PROMOTION_STAGES),
                         {SEALED_STAGE, PREAUTHORIZATION_STAGE})


class ThePublicKeywordValidatesTheStageTests(unittest.TestCase):
    """The same validation at ``authorize_persisted_promotion``'s keyword.

    Two guards for one property is normally a smell; here it is deliberate.
    The trust root's guard protects every caller; this one names the CALLER'S
    OWN spelling in the error, at the boundary where a typo is introduced.
    """

    def test_an_unknown_promotion_stage_is_refused_before_any_work(self):
        from daedalus.kernel.promotion import (
            PromotionAuthorizationError, authorize_persisted_promotion)

        with self.assertRaises(PromotionAuthorizationError) as caught:
            authorize_persisted_promotion(
                approval_ledger=None, owner_keyring={}, consumed_approval=None,
                evidence_packet=None, candidates=(), target_ref="refs/heads/x",
                live_target_revision=None, repo_root=".",
                promotion_stage="SEALED")
        message = str(caught.exception)
        self.assertIn("unknown promotion_stage", message)
        self.assertIn("'SEALED'", message)


def _sha_of_line(line: str) -> str:
    import hashlib
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _digest(repo: Path) -> str:
    import hashlib
    return hashlib.sha256(str(Path(repo).resolve()).encode("utf-8")).hexdigest()[:12]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
