"""Sealed promotion, measured against real signatures.

Nothing here is mocked. Every test builds an actual git repository, generates
actual ed25519 keys with ``ssh-keygen``, and creates actual signed tags, so a
refusal proves the verifier refused a real forgery rather than a stub that was
told to say no.

Two rules this file follows throughout:

1. EVERY REFUSAL TEST HAS A CONTROL. A test that only checks "it said no"
   passes just as happily against a function that always says no. Where a test
   flips one field, the control is the identical fixture with the field intact.

2. THE POSITIVE PATH IS ITSELF A TRAP TEST. ``git verify-tag`` prints
   ``Good "git" signature with ED25519 key SHA256:...`` even when the signing
   key matched NO principal in the allowed-signers file -- it only adds a
   separate ``No principal matched.`` line and exits non-zero. So
   ``test_signature_from_an_unlisted_key_is_refused`` is not a formality: an
   implementation that scanned the output for "Good" would accept a signature
   from any key on earth and would pass every other test in this file.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daedalus.spine import promotion_approval as PA

CANDIDATE = "a" * 64
EVIDENCE = "b" * 64
OTHER_SHA = "c" * 64
FUTURE = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
PAST = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()


def _ssh_signing_available() -> bool:
    """SSH tag signing needs git >= 2.34 and ssh-keygen. Skip rather than
    fail on a box without them -- but never skip silently in CI by accident:
    the skip message names exactly what was missing."""
    if not shutil.which("ssh-keygen"):
        return False
    try:
        out = subprocess.run(["git", "--version"], capture_output=True,
                             timeout=30, check=False).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False
    parts = out.strip().split()
    if len(parts) < 3:
        return False
    try:
        major, minor = int(parts[2].split(".")[0]), int(parts[2].split(".")[1])
    except (ValueError, IndexError):
        return False
    return (major, minor) >= (2, 34)


def _rmtree(path: Path) -> None:
    """Windows leaves git's pack files read-only; a plain rmtree raises."""
    def _force(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_force)


def approval_body(*, candidate=CANDIDATE, evidence=EVIDENCE, revision,
                  expires=None, nonce="nonce-00000001",
                  schema=PA.APPROVAL_BODY_SCHEMA, extra=None, omit=()):
    """The canonical approval body an owner signs. Every knob exists because a
    test below flips exactly one of them."""
    fields = {
        "candidate_sha256": candidate,
        "evidence_sha256": evidence,
        "source_revision": revision,
        "expires_at": expires or FUTURE,
        "nonce": nonce,
    }
    for key in omit:
        fields.pop(key, None)
    if extra:
        fields.update(extra)
    lines = [schema] + [f"{k}: {v}" for k, v in fields.items()]
    return "\n".join(lines) + "\n"


class Repo:
    """A throwaway repository with an owner key, an outsider key, and an
    allowed-signers file committed at HEAD naming only the owner."""

    OWNER = "owner@example"
    OUTSIDER = "outsider@example"

    def __init__(self, tmp: Path, *, commit_signers: bool = True,
                 signers_principals=("owner",)):
        # Its own subdirectory: several tests build more than one repository
        # under the same temp root, and ssh-keygen refuses to overwrite an
        # existing key file.
        self.tmp = Path(tempfile.mkdtemp(dir=tmp))
        tmp = self.tmp
        self.root = tmp / "repo"
        self.keys = {}
        for name, principal in (("owner", self.OWNER), ("outsider", self.OUTSIDER)):
            path = tmp / f"{name}key"
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", principal,
                 "-f", str(path)],
                capture_output=True, check=True, timeout=60)
            self.keys[name] = path

        self.root.mkdir(parents=True)
        self._git(["init", "-q", "."])
        (self.root / "seed.txt").write_text("seed\n", encoding="utf-8")

        signers_dir = self.root / ".agentenv"
        signers_dir.mkdir(parents=True, exist_ok=True)
        signers_path = signers_dir / "promotion_allowed_signers"
        signers_path.write_text(self._signers_text(signers_principals),
                                encoding="utf-8")
        self.signers_path = signers_path

        self._git(["add", "seed.txt"])
        if commit_signers:
            self._git(["add", str(signers_path.relative_to(self.root)).replace("\\", "/")])
        self._git(["commit", "-qm", "seed"])
        self.head = self.rev_parse("HEAD")

    def _signers_text(self, principals) -> str:
        lines = []
        for name in principals:
            principal = self.OWNER if name == "owner" else self.OUTSIDER
            pub = (self.tmp / f"{name}key.pub").read_text(encoding="utf-8").strip()
            lines.append(f"{principal} {pub}")
        return "\n".join(lines) + "\n" if lines else ""

    def _base_config(self, key: str | None = None) -> list[str]:
        cfg = [
            "-c", "user.email=owner@example.com",
            "-c", "user.name=Owner",
            "-c", "commit.gpgsign=false",
            "-c", "gpg.format=ssh",
        ]
        if key:
            cfg += ["-c", f"user.signingkey={self.keys[key]}"]
        return cfg

    def _git(self, args, *, key=None, check=True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            ["git", *self._base_config(key), *args], cwd=str(self.root),
            capture_output=True, timeout=120, check=False)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed: "
                f"{proc.stderr.decode('utf-8', 'replace')}")
        return proc

    def rev_parse(self, ref: str) -> str:
        return self._git(["rev-parse", "--verify", ref]).stdout.decode().strip()

    def commit_more(self) -> str:
        (self.root / "more.txt").write_text("more\n", encoding="utf-8")
        self._git(["add", "more.txt"])
        self._git(["commit", "-qm", "more"])
        self.head = self.rev_parse("HEAD")
        return self.head

    def sign_tag(self, candidate=CANDIDATE, *, body=None, key="owner",
                 target="HEAD", mode="signed", name=None):
        """``mode`` is 'signed' | 'annotated' (no signature) | 'lightweight'."""
        tag = name or PA.approval_tag_for(candidate)
        message = body if body is not None else approval_body(
            candidate=candidate, revision=self.head)
        if mode == "lightweight":
            self._git(["tag", tag, target])
            return tag
        flag = "-s" if mode == "signed" else "-a"
        self._git(["tag", flag, "-m", message, tag, target],
                  key=key if mode == "signed" else None)
        return tag

    def tamper_working_signers(self) -> None:
        """Add the outsider to the WORKING COPY only, leaving HEAD untouched."""
        self.signers_path.write_text(
            self._signers_text(("owner", "outsider")), encoding="utf-8")


@unittest.skipUnless(_ssh_signing_available(),
                     "needs ssh-keygen and git >= 2.34 for SSH signing")
class PromotionApprovalTests(unittest.TestCase):

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="promo-approval-"))
        self.addCleanup(_rmtree, self._tmp)

    def repo(self, **kw) -> Repo:
        return Repo(self._tmp, **kw)

    def verify(self, repo: Repo, *, candidate=CANDIDATE, evidence=EVIDENCE,
               revision=None, now=None):
        return PA.verify_promotion_approval(
            repo.root, candidate_sha256=candidate, evidence_sha256=evidence,
            source_revision=revision or repo.head, now=now)

    # ---------------------------------------------------------------- control
    def test_control_a_correctly_signed_approval_is_approved(self):
        """Without this, every refusal below proves only that the function can
        say no."""
        repo = self.repo()
        repo.sign_tag()
        got = self.verify(repo)
        self.assertTrue(got.approved, got.reason)
        self.assertTrue(
            got.owner_approval_ref.startswith("artifact-locator:sha256:"),
            got.owner_approval_ref)
        self.assertEqual(got.candidate_sha256, CANDIDATE)
        self.assertEqual(got.nonce, "nonce-00000001")

    def test_the_approval_ref_is_the_hash_of_the_signed_bytes(self):
        """The locator must name what was verified, not a description of it."""
        repo = self.repo()
        tag = repo.sign_tag()
        raw = repo._git(["cat-file", "tag", tag]).stdout
        got = self.verify(repo)
        self.assertEqual(
            got.owner_approval_ref,
            "artifact-locator:sha256:" + hashlib.sha256(raw).hexdigest())

    # ------------------------------------------------------- the signature
    def test_no_tag_at_all_is_refused(self):
        got = self.verify(self.repo())
        self.assertFalse(got.approved)
        self.assertIn("no approval tag", got.reason)

    def test_lightweight_tag_is_refused(self):
        repo = self.repo()
        repo.sign_tag(mode="lightweight")
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("not an annotated tag object", got.reason)

    def test_annotated_but_unsigned_tag_is_refused(self):
        repo = self.repo()
        repo.sign_tag(mode="annotated")
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("did not verify", got.reason)

    def test_a_branch_named_like_an_approval_is_not_an_approval(self):
        """Only `refs/tags/promote/<sha>` answers. Tags currently outrank
        branches in git's ref-precedence rules, so this is defence in depth --
        an approval must not rest on that ordering staying as it is."""
        repo = self.repo()
        repo._git(["branch", PA.approval_tag_for(CANDIDATE)])
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("no approval tag", got.reason)

    def test_signature_from_an_unlisted_key_is_refused(self):
        """THE FORGERY THAT LOOKS GOOD. The outsider's signature is
        cryptographically valid and git prints `Good "git" signature ...` for
        it; only the exit code and the allowed-signers file say otherwise.
        Its control is test_control_a_correctly_signed_approval_is_approved --
        same body, same tag, different key."""
        repo = self.repo()
        repo.sign_tag(key="outsider")
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("did not verify", got.reason)

    def test_a_working_tree_edit_cannot_add_a_signer(self):
        """The trust root is the COMMITTED file. Anything that can write the
        checkout would otherwise be able to authorise its own promotions."""
        repo = self.repo()
        repo.sign_tag(key="outsider")
        repo.tamper_working_signers()          # outsider now listed on disk
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("did not verify", got.reason)

    def test_control_the_same_edit_committed_would_have_worked(self):
        """Proves the previous test measured 'not committed', not 'this key can
        never work'. Same key, same tag -- only the commit differs."""
        repo = self.repo()
        repo.sign_tag(key="outsider")
        repo.tamper_working_signers()
        repo._git(["add", ".agentenv/promotion_allowed_signers"])
        repo._git(["commit", "-qm", "trust the outsider"])
        # The tag was made against the older HEAD, so promote against that.
        got = self.verify(repo, revision=repo.rev_parse("HEAD~1"))
        self.assertTrue(got.approved, got.reason)

    def test_uncommitted_allowed_signers_file_is_refused(self):
        repo = self.repo(commit_signers=False)
        repo.sign_tag()
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("not committed at HEAD", got.reason)

    def test_empty_committed_allowed_signers_file_is_refused(self):
        repo = self.repo(signers_principals=())
        repo.sign_tag(key="owner")
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("empty", got.reason)

    # ---------------------------------------------------------- the bindings
    def test_tag_pointing_at_a_different_revision_is_refused(self):
        """Approving against one base and landing on a moved tree."""
        repo = self.repo()
        first = repo.head
        repo.sign_tag(body=approval_body(revision=first), target=first)
        moved = repo.commit_more()
        got = self.verify(repo, revision=moved)
        self.assertFalse(got.approved)
        self.assertIn("points at", got.reason)

    def test_control_the_same_tag_against_its_own_base_is_approved(self):
        repo = self.repo()
        first = repo.head
        repo.sign_tag(body=approval_body(revision=first), target=first)
        repo.commit_more()
        self.assertTrue(self.verify(repo, revision=first).approved)

    def test_body_naming_a_different_candidate_is_refused(self):
        """Tag says promote/<A>, the signed body says B: approve A, promote B."""
        repo = self.repo()
        repo.sign_tag(
            CANDIDATE,
            body=approval_body(candidate=OTHER_SHA, revision=repo.head))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("names candidate", got.reason)

    def test_body_naming_different_evidence_is_refused(self):
        repo = self.repo()
        repo.sign_tag(body=approval_body(evidence=OTHER_SHA, revision=repo.head))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("signed against evidence", got.reason)

    def test_body_naming_a_different_source_revision_is_refused(self):
        """The tag object still points at the right commit; only the signed
        body disagrees. Both bindings are checked, not either one."""
        repo = self.repo()
        other = "d" * 40
        repo.sign_tag(body=approval_body(revision=other), target="HEAD")
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("body names revision", got.reason)

    def test_expired_approval_is_refused(self):
        repo = self.repo()
        repo.sign_tag(body=approval_body(revision=repo.head, expires=PAST))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("expired", got.reason)

    def test_control_an_unexpired_approval_is_approved(self):
        repo = self.repo()
        repo.sign_tag(body=approval_body(revision=repo.head, expires=FUTURE))
        self.assertTrue(self.verify(repo).approved)

    def test_expiry_is_evaluated_against_the_supplied_clock(self):
        """Not merely 'a past date fails' -- the boundary must honour a clock,
        so an approval that is valid now is refused after it lapses."""
        repo = self.repo()
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        repo.sign_tag(body=approval_body(revision=repo.head, expires=expires))
        later = datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertTrue(self.verify(repo).approved)
        self.assertFalse(self.verify(repo, now=later).approved)

    def test_naive_expiry_without_an_offset_is_refused(self):
        repo = self.repo()
        repo.sign_tag(body=approval_body(revision=repo.head,
                                         expires="2099-01-01T00:00:00"))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("explicit UTC offset", got.reason)

    # -------------------------------------------------------------- the body
    def test_wrong_schema_line_is_refused(self):
        repo = self.repo()
        repo.sign_tag(body=approval_body(revision=repo.head,
                                         schema="some-other-approval/9"))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("must begin with", got.reason)

    def test_missing_body_field_is_refused(self):
        for field in sorted(PA._REQUIRED_BODY_KEYS):
            with self.subTest(missing=field):
                repo = self.repo()
                repo.sign_tag(body=approval_body(revision=repo.head,
                                                 omit=(field,)))
                got = self.verify(repo)
                self.assertFalse(got.approved)
                self.assertIn("missing", got.reason)

    def test_unknown_body_field_is_refused(self):
        """The owner signed those bytes. A key the boundary does not verify is
        an assertion nobody checked, not a harmless extra."""
        repo = self.repo()
        repo.sign_tag(body=approval_body(revision=repo.head,
                                         extra={"also_promote": "everything"}))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("does not verify", got.reason)

    def test_malformed_nonce_is_refused(self):
        repo = self.repo()
        repo.sign_tag(body=approval_body(revision=repo.head, nonce="x"))
        got = self.verify(repo)
        self.assertFalse(got.approved)
        self.assertIn("nonce", got.reason)

    def test_empty_message_is_refused(self):
        repo = self.repo()
        repo.sign_tag(body="\n")
        got = self.verify(repo)
        self.assertFalse(got.approved)

    # ------------------------------------------------------- error = refusal
    def test_a_directory_that_is_not_a_repository_is_refused(self):
        plain = self._tmp / "not-a-repo"
        plain.mkdir()
        got = PA.verify_promotion_approval(
            plain, candidate_sha256=CANDIDATE, evidence_sha256=EVIDENCE,
            source_revision="e" * 40)
        self.assertFalse(got.approved)

    def test_a_missing_root_is_refused(self):
        got = PA.verify_promotion_approval(
            self._tmp / "nope", candidate_sha256=CANDIDATE,
            evidence_sha256=EVIDENCE, source_revision="e" * 40)
        self.assertFalse(got.approved)
        self.assertIn("does not exist", got.reason)

    def test_malformed_arguments_are_refused_not_raised(self):
        repo = self.repo()
        for kw in ({"candidate": "short"}, {"evidence": "short"},
                   {"revision": "zz"}):
            with self.subTest(**kw):
                got = self.verify(repo, **kw)
                self.assertFalse(got.approved)

    def test_verification_never_raises(self):
        """The boundary's contract: a caller that forgets a try/except must not
        be able to mistake an exception for anything."""
        for root in (None, 12, "", b"x"):
            with self.subTest(root=root):
                try:
                    got = PA.verify_promotion_approval(
                        root, candidate_sha256=CANDIDATE,
                        evidence_sha256=EVIDENCE, source_revision="e" * 40)
                except Exception as e:                       # noqa: BLE001
                    self.fail(f"verification raised {type(e).__name__}: {e}")
                self.assertFalse(got.approved)


@unittest.skipUnless(_ssh_signing_available(),
                     "needs ssh-keygen and git >= 2.34 for SSH signing")
class SingleUseTests(unittest.TestCase):
    """An approval authorises one promotion. Anything else is a standing
    authorisation, which is what invariant 5 exists to prevent."""

    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="promo-claim-"))
        self.addCleanup(_rmtree, self._tmp)
        self.spent = self._tmp / "spent"

    def test_control_a_fresh_approval_claims_once(self):
        repo = Repo(self._tmp)
        repo.sign_tag()
        verdict = PA.verify_promotion_approval(
            repo.root, candidate_sha256=CANDIDATE, evidence_sha256=EVIDENCE,
            source_revision=repo.head)
        claimed, reason = PA.claim_approval(repo.root, verdict,
                                            spent_root=self.spent)
        self.assertTrue(claimed, reason)

    def test_replaying_the_same_approval_is_refused(self):
        repo = Repo(self._tmp)
        repo.sign_tag()
        verdict = PA.verify_promotion_approval(
            repo.root, candidate_sha256=CANDIDATE, evidence_sha256=EVIDENCE,
            source_revision=repo.head)
        first, _ = PA.claim_approval(repo.root, verdict, spent_root=self.spent)
        second, reason = PA.claim_approval(repo.root, verdict,
                                           spent_root=self.spent)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn("already spent", reason)

    def test_an_unapproved_verdict_is_never_claimable(self):
        verdict = PA.ApprovalVerdict(
            approved=False, reason="refused", candidate_sha256=CANDIDATE,
            tag=PA.approval_tag_for(CANDIDATE))
        claimed, reason = PA.claim_approval(self._tmp, verdict,
                                            spent_root=self.spent)
        self.assertFalse(claimed)
        self.assertIn("unapproved", reason)

    def test_a_nonceless_approval_is_never_claimable(self):
        """Hand-built to be approved but nonceless -- the claim must not fall
        back to a shared key that two different approvals would collide on."""
        verdict = PA.ApprovalVerdict(
            approved=True, reason="hand-built", candidate_sha256=CANDIDATE,
            tag=PA.approval_tag_for(CANDIDATE), nonce=None)
        claimed, reason = PA.claim_approval(self._tmp, verdict,
                                            spent_root=self.spent)
        self.assertFalse(claimed)
        self.assertIn("nonce", reason)

    def test_an_unusable_ledger_refuses_rather_than_assuming_fresh(self):
        """A ledger that cannot be written cannot detect a replay, so the
        promotion must not proceed on the assumption that there was none."""
        verdict = PA.ApprovalVerdict(
            approved=True, reason="ok", candidate_sha256=CANDIDATE,
            tag=PA.approval_tag_for(CANDIDATE), nonce="nonce-00000001")
        blocker = self._tmp / "blocker"
        blocker.write_text("not a directory\n", encoding="utf-8")
        claimed, reason = PA.claim_approval(
            self._tmp, verdict, spent_root=blocker / "spent")
        self.assertFalse(claimed)
        self.assertIn("ledger unavailable", reason)

    def test_the_spend_ledger_lives_outside_the_checkout(self):
        """A candidate's declared write paths are repo-relative; a ledger
        inside the checkout would be within reach of the thing it constrains."""
        root = Path(tempfile.gettempdir()) / "some-checkout"
        self.assertFalse(
            str(PA._spent_root(root)).startswith(str(root) + os.sep),
            PA._spent_root(root))


class RegenerationVoidsApprovalTests(unittest.TestCase):
    """The owner's recorded decision: a candidate rebuilt after approval is
    unapproved, and returns to pending-owner."""

    def test_regeneration_produces_an_unapproved_verdict(self):
        got = PA.voided_by_regeneration(CANDIDATE, OTHER_SHA)
        self.assertFalse(got.approved)
        self.assertIn("void", got.reason)
        self.assertIn("pending-owner", got.reason)
        self.assertIsNone(got.owner_approval_ref)

    def test_the_verdict_names_the_regenerated_artifact(self):
        """It must not keep claiming to be about the artifact that WAS
        approved, or a report reads as though the approved one was handled."""
        got = PA.voided_by_regeneration(CANDIDATE, OTHER_SHA)
        self.assertEqual(got.candidate_sha256, OTHER_SHA)
        self.assertEqual(got.tag, PA.approval_tag_for(OTHER_SHA))

    @unittest.skipUnless(_ssh_signing_available(), "needs ssh-keygen and git >= 2.34")
    def test_a_regenerated_candidate_has_no_approval_end_to_end(self):
        """The mechanism, not just the message: an approval for A does not
        verify for the regenerated B, because the tag name is the sha."""
        tmp = Path(tempfile.mkdtemp(prefix="promo-regen-"))
        self.addCleanup(_rmtree, tmp)
        repo = Repo(tmp)
        repo.sign_tag(CANDIDATE)
        approved = PA.verify_promotion_approval(
            repo.root, candidate_sha256=CANDIDATE, evidence_sha256=EVIDENCE,
            source_revision=repo.head)
        regenerated = PA.verify_promotion_approval(
            repo.root, candidate_sha256=OTHER_SHA, evidence_sha256=EVIDENCE,
            source_revision=repo.head)
        self.assertTrue(approved.approved, approved.reason)
        self.assertFalse(regenerated.approved)


class ReceiptTests(unittest.TestCase):
    """`approval_assurance="authenticated"` may be set by the verifier and by
    nothing else."""

    LOCATOR = "artifact-locator:sha256:" + "1" * 64
    EVIDENCE_LOC = "artifact-locator:sha256:" + "2" * 64
    REVISION = "f" * 40
    CREATED = "2026-07-31T00:00:00+00:00"

    def build(self, verdict):
        return PA.promotion_receipt(
            verdict,
            promotion_id="promotion-1",
            nomination_receipt_sha256="3" * 64,
            candidate_artifact_locator=self.LOCATOR,
            evidence_packet_sha256=EVIDENCE,
            evidence_locator=self.EVIDENCE_LOC,
            source_revision=self.REVISION,
            target_revision="refs/heads/main",
            created_at=self.CREATED,
        )

    def approved_verdict(self):
        return PA.ApprovalVerdict(
            approved=True, reason="owner signature verified",
            candidate_sha256=CANDIDATE, tag=PA.approval_tag_for(CANDIDATE),
            owner_approval_ref="artifact-locator:sha256:" + "4" * 64,
            signer="owner@example", expires_at=FUTURE, nonce="nonce-00000001")

    def test_an_approved_verdict_yields_an_authenticated_receipt(self):
        receipt = self.build(self.approved_verdict())
        self.assertEqual(receipt.promotion_status, "approved")
        self.assertEqual(receipt.approval_assurance, "authenticated")
        self.assertEqual(receipt.candidate_artifact_sha256, CANDIDATE)

    def test_a_refused_verdict_yields_pending_owner(self):
        receipt = self.build(PA.ApprovalVerdict(
            approved=False, reason="no approval tag", candidate_sha256=CANDIDATE,
            tag=PA.approval_tag_for(CANDIDATE)))
        self.assertEqual(receipt.promotion_status, "pending-owner")
        self.assertEqual(receipt.approval_assurance, "not-applicable")
        self.assertIsNone(receipt.owner_approval_ref)

    def test_a_refusal_reason_survives_into_the_receipt(self):
        """A pending receipt that does not say why is not evidence."""
        receipt = self.build(PA.ApprovalVerdict(
            approved=False, reason="signature did not verify",
            candidate_sha256=CANDIDATE, tag=PA.approval_tag_for(CANDIDATE)))
        self.assertIn("signature did not verify", receipt.reasons)

    def test_an_approval_ref_without_approval_cannot_be_smuggled_in(self):
        """A verdict carrying a ref but approved=False must still produce
        pending-owner: the status comes from the verification, not from the
        presence of a locator a caller could have typed."""
        receipt = self.build(PA.ApprovalVerdict(
            approved=False, reason="expired",
            candidate_sha256=CANDIDATE, tag=PA.approval_tag_for(CANDIDATE),
            owner_approval_ref="artifact-locator:sha256:" + "4" * 64,
            nonce="nonce-00000001"))
        self.assertEqual(receipt.promotion_status, "pending-owner")
        self.assertIsNone(receipt.owner_approval_ref)

    def test_the_receipt_binds_the_approval_into_its_provenance(self):
        receipt = self.build(self.approved_verdict())
        self.assertIn("4" * 64, receipt.provenance.input_digests)


if __name__ == "__main__":
    unittest.main()
