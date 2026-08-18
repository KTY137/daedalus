"""Git-signed-tag trust root for the sealed owner approval.

This is the option-B trust root from ``docs/GATE0_SEALED_OWNER_APPROVAL.md``
§4: the owner signs an annotated tag with their own Git signing key, and the
promotion boundary verifies it with ``git verify-tag`` against an allowed
signers list that lives in the repository. It adds no Python dependency and no
second approval vocabulary -- the signed body is checked against the existing
:class:`daedalus.kernel.approvals.ApprovalExpectation`.

Three properties carry the whole design, and each exists because the naive
version of it was measured and failed:

**The signers list is not a parameter, but it is not beyond the caller's
reach either.** Verifying an attacker-signed tag against an attacker-supplied
signers file returns "Good signature" and exit 0. Nothing in this module
accepts a signers path, a signers blob, a keyring or a public key from its
caller. The list is read from one fixed repository path, at a pinned revision,
as the committed object rather than the working-tree file, because a process
that can write the working tree would otherwise be able to name itself a
principal.

The honest limit of that, measured rather than assumed: ``repo_root`` IS a
caller parameter and ``ALLOWED_SIGNERS_REVISION`` is ``"HEAD"``, so whoever
controls HEAD of the repository handed to this module controls the trust root
completely -- a single commit that writes ``configs/owner-allowed-signers``
becomes the new root, and the pins in the receipt then faithfully report the
attacker's OIDs. Hardening the API surface does not close that; only binding
the expected signer-set digest to an artifact the amendment protocol controls
does. Until that binding exists, read every claim in this module as
"...given that HEAD of ``repo_root`` is trustworthy".

**Signing capability is never inherited.** This module runs ``git show``,
``git rev-parse``, ``git tag -l`` and ``git verify-tag``. It never runs
``git tag -s``, never reads a private key, and never touches repository
config. Signing is an owner action in the owner's own shell; see
``docs/OWNER_SEALED_APPROVAL_HOWTO.md``.

**A signature authorizes one purpose.** The signed body carries an explicit
``purpose`` and ``operation``. A tag the owner signed to mark a release, or
under any other domain, cannot be replayed as a promotion approval even though
it verifies perfectly as a signature.

This module authenticates a capability. It does not promote, does not consume,
and does not decide -- ``daedalus.kernel.promotion`` remains the single
authorization boundary and ``daedalus.kernel.approvals.ApprovalLedger`` remains
the single one-use consumption authority.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.kernel.approvals import ApprovalExpectation, _parse_utc
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.attempt import _git_env as _canonical_git_env

# The trust root. Both are module constants and neither is a parameter of any
# public function in this module: the allowed-signers path is exactly as
# security-critical as the signatures it validates.
OWNER_ALLOWED_SIGNERS_PATH = "configs/owner-allowed-signers"
ALLOWED_SIGNERS_REVISION = "HEAD"

# Where the EXPECTED signer-set digest lives, and under which key.
#
# This is the answer to the hole that hardening the API surface cannot close:
# `ALLOWED_SIGNERS_REVISION` is "HEAD", so a single commit that rewrites
# `configs/owner-allowed-signers` IS the new trust root, and every pin this
# module reports would faithfully describe the attacker's own file. Moving the
# signers file "somewhere protected" does not help either -- whoever can commit
# can commit there too.
#
# The amendment ledger is different in kind: it is hash-chained -- each record
# carries ``record_sha256`` over its own canonical body and
# ``previous_record_sha256`` over its predecessor's -- and section 15 of the
# master plan requires owner approval to append. Binding the expected digest
# there makes rotating the owner's keys an AMENDMENT rather than a commit.
#
# HONEST BOUND, and it is narrower than the sentence that used to stand here.
# The chain is tamper-EVIDENT, not tamper-PROOF.
#
# What was MEASURED, in order:
#   * No chain check at all: a rogue signers file plus an appended "accepted"
#     record naming its digest, in ONE commit, was accepted -- and so was a
#     single-line ledger with no chain fields whatsoever.
#   * Chain walk only: the sloppy forgery is refused, but a WELL-FORMED
#     appended record -- correct ``previous_record_sha256``, correct
#     ``record_sha256``, correct sequence, correct revisions -- was still
#     accepted. Anyone who can commit can append correctly. The chain walk
#     alone stopped bad spelling, not the attack.
#   * Chain walk plus the plan binding below: the head of the chain must also
#     describe the master plan blob committed beside it, digest and revision
#     header. The forgery now has to rewrite the constitutional document in
#     the same commit, which is the artifact an owner and CODEOWNERS review.
#
# It still does NOT defeat an attacker with commit rights who recomputes the
# ENTIRE chain from the pinned genesis forward and rewrites the plan to match:
# every link would be internally consistent and nothing in this repository
# would notice. The only thing that would notice is an anchor held out of
# band -- a signed ledger tag, a published digest, or the owner's own copy of
# the last ``record_sha256``. This module does not have one, so it does not
# claim one. What it claims is: a forgery now has to rewrite history and the
# plan, rather than append one line.
#
# An earlier revision of this module read this file and checked NO chain field
# whatsoever -- ``status == "accepted"`` plus a well-formed digest was enough.
# Two forgeries were executed against that: a one-commit file+pin, and a
# single-line ledger containing nothing but a status and a digest. The
# comment claimed the chain; the code never read it.
AMENDMENT_LEDGER_PATH = "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl"
TRUST_ROOT_DIGEST_FIELD = "owner_allowed_signers_sha256"

# The genesis link, pinned in code. Without it a chain that is internally
# consistent but rooted in the attacker's own first record verifies perfectly:
# "record 1 has no predecessor" is trivially satisfiable by anyone who writes
# record 1. This digest is the ``record_sha256`` of the adoption record of
# ``daedalus-master-plan``. Changing it is an amendment, not an edit.
AMENDMENT_GENESIS_RECORD_SHA256 = (
    "3ccedd9a36e21d1764d16766431450e422628129faa9e7a68684bfeccf3793ea"
)

# The chain rules are NOT re-implemented here. They are the guard's, loaded
# from the verifier's own checkout -- not from the repository being inspected,
# whose ``tools/`` an attacker with commit rights also controls. A second copy
# of a security check is the defect this lane already had to fix once.
_IRON_PLAN_GUARD_REL = "tools/iron_plan_guard.py"

# Domain separation. A signature is only an approval inside this purpose.
APPROVAL_PURPOSE = "daedalus.promotion-approval"
APPROVAL_OPERATION = "promote-candidate"
APPROVAL_TAG_NAMESPACE = "owner-approval/"

APPROVAL_BODY_FIELDS = (
    "purpose",
    "operation",
    "approval_mechanism_sha256",
    "nomination_receipt_sha256",
    "candidate_artifact_sha256",
    "evidence_packet_sha256",
    "base_revision",
    "target_ref",
    "expected_target_revision",
    "nonce",
    "expires_at",
)

_GIT_TIMEOUT_S = 30.0

# Additions this verifier needs on top of the canonical environment. They are
# additions only: nothing here re-enables anything the canonical env removed.
# ``_git_env`` asserts that, so the overlay cannot quietly become a second and
# weaker answer to "what is a safe environment to run git in".
_EXTRA_SCRUBBED_GIT_ENV = (
    # Command-line ``-c`` was measured to win over both of these on git 2.38.1
    # (probe, 2026-08-18), so this is defence in depth rather than the thing
    # that holds. It is kept because the precedence is a git implementation
    # detail and this module's pins are load-bearing.
    "GIT_CONFIG_PARAMETERS",
    "GIT_ALLOW_PROTOCOL",
)


def _artifact_locator_for(digest: str) -> str:
    return f"artifact-locator:sha256:{digest}"


class SignedApprovalError(RuntimeError):
    """Fail-closed refusal of a git-signed owner approval."""


class SignedApprovalRootError(SignedApprovalError):
    """The committed trust root is missing, unreadable or empty."""


class SignedApprovalSignatureError(SignedApprovalError):
    """The tag is unsigned, or signed by a principal that is not allowed."""


class SignedApprovalPurposeError(SignedApprovalError):
    """The signature is valid but was not made for promotion approval."""


class SignedApprovalBindingMismatch(SignedApprovalError):
    """The signed body names a different subject than the one being promoted."""


class SignedApprovalExpired(SignedApprovalError):
    """The signed approval is outside its validity window."""


class SignedApprovalMechanismMismatch(SignedApprovalError):
    """The approval was signed against a different allowed-signers generation."""


@dataclass(frozen=True)
class SignedApprovalBody:
    """The exact canonical object the owner signs.

    Serialisation is deliberately one compact line with sorted keys. The owner
    tool prints precisely these bytes, and precisely these bytes become the tag
    message, so what the owner reads is what the owner signs.
    """

    purpose: str
    operation: str
    approval_mechanism_sha256: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    base_revision: str
    target_ref: str
    expected_target_revision: str
    nonce: str
    expires_at: str

    def __post_init__(self) -> None:
        if self.purpose != APPROVAL_PURPOSE:
            raise SignedApprovalPurposeError(
                f"approval purpose must be {APPROVAL_PURPOSE!r}, got {self.purpose!r}"
            )
        if self.operation != APPROVAL_OPERATION:
            raise SignedApprovalPurposeError(
                f"approval operation must be {APPROVAL_OPERATION!r}, "
                f"got {self.operation!r}"
            )
        try:
            for name in (
                "approval_mechanism_sha256",
                "nomination_receipt_sha256",
                "candidate_artifact_sha256",
                "evidence_packet_sha256",
            ):
                object.__setattr__(self, name, _sha256(getattr(self, name), name))
            object.__setattr__(
                self, "base_revision", _revision(self.base_revision, "base_revision")
            )
            object.__setattr__(
                self,
                "expected_target_revision",
                _revision(self.expected_target_revision, "expected_target_revision"),
            )
            object.__setattr__(
                self, "target_ref", _identifier(self.target_ref, "target_ref")
            )
            object.__setattr__(self, "nonce", _identifier(self.nonce, "nonce"))
        except (TypeError, ValueError) as exc:
            raise SignedApprovalBindingMismatch(
                f"signed approval body is not canonical: {exc}"
            ) from exc
        try:
            _parse_utc(self.expires_at, "expires_at")
        except Exception as exc:  # noqa: BLE001 - malformed body fails closed
            raise SignedApprovalBindingMismatch(
                f"signed approval expires_at is not a UTC timestamp: {exc}"
            ) from exc

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in APPROVAL_BODY_FIELDS}

    def canonical_bytes(self) -> bytes:
        """The exact bytes that are signed."""
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @classmethod
    def from_json(cls, text: str) -> "SignedApprovalBody":
        try:
            payload = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise SignedApprovalBindingMismatch(
                f"signed approval body is not JSON: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise SignedApprovalBindingMismatch("signed approval body must be an object")
        actual = set(payload)
        expected = set(APPROVAL_BODY_FIELDS)
        if actual != expected:
            raise SignedApprovalBindingMismatch(
                "signed approval body fields mismatch: "
                f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
            )
        for key, value in payload.items():
            if not isinstance(value, str):
                raise SignedApprovalBindingMismatch(
                    f"signed approval field {key} must be a string"
                )
        return cls(**{name: payload[name] for name in APPROVAL_BODY_FIELDS})


# Held by this module and passed only by :func:`verify_signed_approval`. It
# makes "I hold a VerifiedSignedApproval" mean "verification ran", so the
# ordinary way to obtain one is to earn it rather than to type it. See the
# honesty note on :class:`VerifiedSignedApproval` for what this does NOT claim.
_CONSTRUCTION_TOKEN = object()


@dataclass(frozen=True)
class VerifiedSignedApproval:
    """Proof that one allowed owner principal signed one exact approval body.

    ``owner_approval_ref`` is the content-addressed locator of the signed tag
    object itself -- the bytes that were verified, not a description of them.
    It is what a :class:`~daedalus.schemas.PromotionReceipt` cites, so the
    receipt points at material a reader can re-verify rather than at this
    module's opinion of it.

    Construction requires a token this module holds, so the class cannot be
    instantiated by a caller that would simply like to be approved. That is an
    interlock against accident and casual misuse, **not** a security boundary:
    Python has no private state, and in-process code that reaches into this
    module's globals can still fabricate an instance. What actually stops a
    forged approval is ``git verify-tag`` against the committed signer set --
    never the existence of this object.

    The token is a real ``init`` field, and that is exactly as leaky as it
    sounds. ``dataclasses.replace(verified, ...)`` -- ONE stdlib call, no
    module globals touched -- re-runs ``__init__`` with the token carried over
    and every other field chosen by the caller; that was executed and produced
    ``status=approved assurance=authenticated`` under an attacker's principal.
    ``copy.deepcopy`` produces an instance whose ``_token`` is ``None``, which
    ``__post_init__`` never sees because deepcopy does not call it.

    So the token is not the identity. :func:`verify_signed_approval` also
    stamps ``_minted`` on the instance through ``object.__setattr__`` AFTER
    construction, which ``dataclasses.replace`` cannot carry (it copies fields,
    and this is not one) and ``deepcopy`` cannot preserve by identity (it
    copies the sentinel). :func:`promotion_receipt` checks that stamp. The
    honest bound is unchanged: code that reaches into this module's globals can
    stamp an object itself. The bound that moved is that it now takes reaching
    into this module -- not one stdlib call.
    """

    tag_name: str
    tag_object_sha1: str
    tag_target_oid: str
    signer_principal: str
    body: SignedApprovalBody
    owner_approval_ref: str
    trust_root_commit_oid: str
    trust_root_blob_oid: str
    _token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _CONSTRUCTION_TOKEN:
            raise SignedApprovalSignatureError(
                "a VerifiedSignedApproval is produced by verify_signed_approval() "
                "and cannot be constructed directly; declaring that a signature "
                "was checked does not check one"
            )

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body.canonical_bytes()).hexdigest()


# The attribute name the mint stamps. Not a dataclass field, on purpose:
# ``dataclasses.replace`` reconstructs from fields and therefore cannot carry
# it, which is what closes the one-stdlib-call forgery.
_MINT_ATTR = "_minted"


def _mint(verified: "VerifiedSignedApproval") -> "VerifiedSignedApproval":
    """Stamp an instance as one THIS module produced by actually verifying."""
    object.__setattr__(verified, _MINT_ATTR, _CONSTRUCTION_TOKEN)
    return verified


def _is_minted(candidate: object) -> bool:
    return getattr(candidate, _MINT_ATTR, None) is _CONSTRUCTION_TOKEN


def approval_tag_for(candidate_artifact_sha256: str) -> str:
    """The conventional tag name for approving a given candidate.

    This is a NAMING CONVENTION for the owner tool, not a check. Deriving the
    name from the candidate digest keeps approvals legible and collision-free,
    but :func:`verify_signed_approval` does not require a tag to match it -- it
    only requires the approval namespace prefix.

    What actually stops candidate A's approval from promoting candidate B is
    :func:`_require_binding`, which compares the SIGNED body against the
    expectation. That is the real check, and it does not depend on what the ref
    happens to be called. Do not read this function as a binding.
    """
    return f"{APPROVAL_TAG_NAMESPACE}{_sha256(candidate_artifact_sha256, 'candidate_artifact_sha256')}"


def canonical_approval_body(
    *,
    expectation: ApprovalExpectation,
    nonce: str,
    expires_at: str,
    approval_mechanism_sha256: str,
) -> SignedApprovalBody:
    """Build the body an owner is about to sign, from a checked expectation.

    The owner tool uses this so that the bytes it displays are produced by the
    same code path that later verifies them.
    """
    if not isinstance(expectation, ApprovalExpectation):
        raise SignedApprovalBindingMismatch(
            "a signed approval body requires an ApprovalExpectation"
        )
    return SignedApprovalBody(
        purpose=APPROVAL_PURPOSE,
        operation=expectation.operation,
        approval_mechanism_sha256=approval_mechanism_sha256,
        nomination_receipt_sha256=expectation.nomination_receipt_sha256,
        candidate_artifact_sha256=expectation.candidate_artifact_sha256,
        evidence_packet_sha256=expectation.evidence_packet_sha256,
        base_revision=expectation.base_revision,
        target_ref=expectation.target_ref,
        expected_target_revision=expectation.current_target_revision,
        nonce=nonce,
        expires_at=expires_at,
    )


def _git_env() -> dict[str, str]:
    """The canonical hardened git environment, plus this module's additions.

    The environment is NOT reinvented here. It comes from
    :func:`daedalus.spine.attempt._git_env`, which has its own proof suite in
    ``tests/test_git_is_a_process_launcher.py``. An earlier version of this
    module grew a second, weaker copy that failed to drop ``GIT_DIR``,
    ``GIT_WORK_TREE`` and ``GIT_INDEX_FILE``, and that *popped*
    ``GIT_CONFIG_GLOBAL`` instead of pointing it at ``os.devnull`` -- popping
    restores the real per-user config rather than removing it. An inherited
    ``GIT_DIR`` then redirected every call in this module into an attacker's
    object store, where all eight pins agreed with each other because they came
    from the same foreign repository.

    Only additions are permitted on top, and the check below enforces it.

    That check used to be a bare ``assert`` over the WHOLE baseline, snapshotted
    after the canonical environment was built -- so the baseline contained
    ``GIT_CONFIG_PARAMETERS`` and ``GIT_ALLOW_PROTOCOL`` whenever they happened
    to be set in the ambient environment, and this function's own deliberate
    ``pop`` of them then tripped its own guard. Measured: with either variable
    set, every verification raised an ``AssertionError`` from outside the
    :class:`SignedApprovalError` taxonomy, so a caller written to
    ``except SignedApprovalError`` crashed instead of refusing. Under
    ``python -O`` the guard did not run at all, and the test that watched it
    passed only because those variables were unset on the box it ran on.

    So: compare only the keys this overlay does not deliberately remove, and
    raise a :class:`SignedApprovalError` -- which ``-O`` cannot strip.
    """
    env = _canonical_git_env()
    baseline = dict(env)

    for name in _EXTRA_SCRUBBED_GIT_ENV:
        env.pop(name, None)
    # A shallow or partial clone must fail closed rather than reach out for the
    # object it is missing. Lazy fetching would turn "this repository cannot
    # show me the signed bytes" into a network call whose answer an attacker
    # may control.
    env["GIT_NO_LAZY_FETCH"] = "1"

    # The overlay may remove more and pin more; it may never restore a variable
    # the canonical environment removed, nor change one it set. The variables
    # this overlay removes on purpose are excluded from the comparison --
    # removing them is the addition, not a weakening of it.
    deliberately_removed = frozenset(_EXTRA_SCRUBBED_GIT_ENV)
    for name, value in baseline.items():
        if name in deliberately_removed:
            continue
        if env.get(name) != value:
            raise SignedApprovalError(
                f"the signed-approval git environment weakened {name}: "
                f"canonical {value!r} became {env.get(name)!r}. Refusing to "
                "run git in an environment weaker than the canonical one."
            )
    for name in deliberately_removed:
        if name in env:
            raise SignedApprovalError(
                f"the signed-approval git environment still carries {name}, "
                "which it exists to remove"
            )
    return env


def _git(
    repo_root: Path,
    args: list[str],
    *,
    label: str,
    check: bool = True,
) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            env=_git_env(),
            capture_output=True,
            text=True,
            # Explicit, because ``text=True`` alone decodes with the platform's
            # preferred locale codec. On this box that is cp1252: reading the
            # master plan blob -- which is UTF-8 and contains characters cp1252
            # has no mapping for -- killed the reader thread and returned
            # ``stdout=None``, which then crashed the caller with an
            # AttributeError from outside this module's taxonomy. What a digest
            # is taken over must not depend on the machine's locale.
            encoding="utf-8",
            errors="strict",
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise SignedApprovalError(f"{label} could not run: {exc}") from exc
    if completed.stdout is None or completed.stderr is None:
        raise SignedApprovalError(
            f"{label} produced no readable output; refusing rather than "
            "guessing what git said"
        )
    if check and completed.returncode != 0:
        raise SignedApprovalError(
            f"{label} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed


@dataclass(frozen=True)
class TrustRoot:
    """The pinned trust policy: which commit, which blob, which signer set.

    The commit OID and the blob OID are resolved and reported independently on
    purpose. A blob digest alone does not say which reviewed commit introduced
    it, and a commit OID alone does not say the policy file inside it is the
    one that was read. Recording both makes a trust-root swap describable after
    the fact instead of merely detectable.

    ``digest`` is the SHA-256 of the signer set as fed to ssh-keygen. It is the
    mechanism generation an approval binds itself to, so rotating the owner's
    keys invalidates approvals signed under the previous set rather than
    silently carrying them forward.
    """

    commit_oid: str
    blob_oid: str
    content: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.normalised().encode("utf-8")).hexdigest()

    def normalised(self) -> str:
        return self.content.replace("\r\n", "\n").replace("\r", "\n")

    def principals(self) -> tuple[str, ...]:
        return tuple(
            line.strip()
            for line in self.normalised().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )


def resolve_trust_root(repo_root: str | Path) -> TrustRoot:
    """Pin the trust policy commit and the signer blob independently."""
    root = Path(repo_root).resolve()
    commit = _git(
        root,
        ["rev-parse", "--verify", "--quiet", f"{ALLOWED_SIGNERS_REVISION}^{{commit}}"],
        label="pinning the trust-policy commit",
        check=False,
    )
    commit_oid = commit.stdout.strip()
    if commit.returncode != 0 or not commit_oid:
        raise SignedApprovalRootError(
            f"no commit at {ALLOWED_SIGNERS_REVISION} to pin the trust policy to"
        )
    blob = _git(
        root,
        [
            "rev-parse",
            "--verify",
            "--quiet",
            f"{commit_oid}:{OWNER_ALLOWED_SIGNERS_PATH}",
        ],
        label="pinning the allowed-signers blob",
        check=False,
    )
    blob_oid = blob.stdout.strip()
    if blob.returncode != 0 or not blob_oid:
        raise SignedApprovalRootError(
            f"no committed {OWNER_ALLOWED_SIGNERS_PATH} at {commit_oid[:12]}"
        )
    content = _git(
        root,
        ["cat-file", "blob", blob_oid],
        label="reading the pinned allowed-signers blob",
        check=False,
    )
    if content.returncode != 0:
        raise SignedApprovalRootError(
            f"allowed-signers blob {blob_oid[:12]} is unreadable; refusing "
            "rather than fetching it"
        )
    trust_root = TrustRoot(
        commit_oid=commit_oid, blob_oid=blob_oid, content=content.stdout
    )
    if not trust_root.principals():
        raise SignedApprovalRootError(
            f"committed {OWNER_ALLOWED_SIGNERS_PATH} names no owner principal; "
            "promotion stays refused until the owner commits their public key"
        )

    # The binding that makes the pins above mean something. Read from the SAME
    # commit as the signers blob, so the policy and the digest that authorises
    # it are one revision and cannot be mixed.
    expected = _amendment_pinned_signers_digest(root, commit_oid)
    if trust_root.digest != expected:
        raise SignedApprovalRootError(
            f"committed {OWNER_ALLOWED_SIGNERS_PATH} hashes to "
            f"{trust_root.digest[:12]}, but the amendment chain pins the owner "
            f"signer set to {expected[:12]}. Either this signer set was not "
            "approved, or the owner rotated keys without an amendment. "
            "Rotating the trust root is an amendment, not a commit; see "
            "section 15 of the master plan."
        )
    return trust_root


@lru_cache(maxsize=1)
def _iron_plan_guard():
    """The amendment-chain rules, loaded once from the verifier's own checkout.

    Deliberately NOT loaded from the repository under inspection: an attacker
    who can commit ``configs/owner-allowed-signers`` can commit
    ``tools/iron_plan_guard.py`` too, and a rules file the attacker supplies is
    not a rule. The path is resolved from this module's own location, which is
    the same code the caller already trusted enough to run.
    """
    guard_path = Path(__file__).resolve().parents[2] / _IRON_PLAN_GUARD_REL
    try:
        spec = importlib.util.spec_from_file_location(
            "daedalus_signed_approval_iron_plan_guard", guard_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"no loader for {guard_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError, ValueError) as exc:
        raise SignedApprovalRootError(
            f"the amendment-chain rules at {_IRON_PLAN_GUARD_REL} could not be "
            f"loaded ({exc}); the trust root cannot be checked, so promotion "
            "stays refused"
        ) from exc
    for name in (
        "canonical_record_sha256",
        "parse_ledger_text",
        "normalized_text",
        "parse_plan_header",
        "SCHEMA",
        "PLAN_ID",
        "PLAN_REL",
        "SHA256",
    ):
        if not hasattr(module, name):
            raise SignedApprovalRootError(
                f"{_IRON_PLAN_GUARD_REL} does not expose {name}; refusing to "
                "fall back to a private copy of the chain rules"
            )
    return module


def _verify_amendment_chain(records: Sequence[Mapping[str, Any]]) -> None:
    """Walk the hash chain with the guard's rules, and fail closed on any gap.

    Every predicate below mirrors ``tools/iron_plan_guard.py`` ``verify()``,
    and the digest is computed by the guard's own
    ``canonical_record_sha256`` -- so the two cannot disagree about what a
    record hashes to. ``tests/kernel/test_signed_approval_trust_root.py``
    holds them to the same verdict on a corpus of tampered ledgers, which is
    the thing that notices if the guard's rules move and this does not.

    The guard collects errors and reports them all; this raises on the first,
    because there is nothing useful to do with the second reason a trust root
    is not trustworthy.
    """
    guard = _iron_plan_guard()
    if not records:
        raise SignedApprovalRootError(
            f"{AMENDMENT_LEDGER_PATH} holds no records, so no amendment pins "
            "the owner signer set; promotion stays refused"
        )

    def refuse(index: int, detail: str) -> SignedApprovalRootError:
        return SignedApprovalRootError(
            f"{AMENDMENT_LEDGER_PATH} record {index}: {detail}. The amendment "
            "chain is the authority for the owner signer set; a ledger that "
            "does not verify pins nothing."
        )

    previous: Mapping[str, Any] | None = None
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise refuse(index, "record must be an object")
        if record.get("schema") != guard.SCHEMA:
            raise refuse(index, "unexpected schema")
        if record.get("plan_id") != guard.PLAN_ID:
            raise refuse(index, "unexpected plan_id")
        if record.get("status") != "accepted":
            raise refuse(index, "status must be accepted")
        if record.get("sequence") != index:
            raise refuse(index, f"sequence must be {index}")
        for field_name in ("base_plan_sha256", "result_plan_sha256", "record_sha256"):
            if not guard.SHA256.fullmatch(str(record.get(field_name) or "")):
                raise refuse(index, f"{field_name} must be lowercase sha256")
        if record.get("record_sha256") != guard.canonical_record_sha256(dict(record)):
            raise refuse(index, "record_sha256 mismatch")
        if not str(record.get("approval_ref") or "").strip():
            raise refuse(index, "approval_ref is required")
        base_revision = record.get("base_revision")
        result_revision = record.get("result_revision")
        if not isinstance(base_revision, int) or result_revision != base_revision + 1:
            raise refuse(index, "revision must increase by exactly one")
        if previous is None:
            if record.get("previous_record_sha256") is not None:
                raise refuse(index, "first previous_record_sha256 must be null")
            # The anchor. Without it, "I am record 1" is a claim anyone who
            # writes record 1 can make, and a self-consistent chain rooted in
            # the attacker's own genesis verifies perfectly.
            if record.get("record_sha256") != AMENDMENT_GENESIS_RECORD_SHA256:
                raise refuse(
                    index,
                    "genesis record_sha256 "
                    f"{str(record.get('record_sha256'))[:12]} is not the "
                    f"pinned {AMENDMENT_GENESIS_RECORD_SHA256[:12]}; this "
                    "chain starts from a different history",
                )
        else:
            if record.get("previous_record_sha256") != previous.get("record_sha256"):
                raise refuse(index, "previous-record hash chain is broken")
            if record.get("base_plan_sha256") != previous.get("result_plan_sha256"):
                raise refuse(index, "plan digest chain is broken")
            if base_revision != previous.get("result_revision"):
                raise refuse(index, "plan revision chain is broken")
        previous = record


def _verify_ledger_head_matches_plan(
    root: Path, commit_oid: str, head: Mapping[str, Any]
) -> None:
    """The head of the chain must describe the plan committed beside it.

    The guard makes the same demand of the working tree; here it is made of
    the pinned commit, so the two artifacts cannot be read from different
    revisions. This is the check that turns "append a well-formed record" into
    "rewrite the master plan and its revision header in the same commit" --
    the plan being the CODEOWNERS-protected document an owner actually reads.

    It is still not tamper-PROOF. See the note above ``AMENDMENT_LEDGER_PATH``.
    """
    guard = _iron_plan_guard()
    blob = _git(
        root,
        ["rev-parse", "--verify", "--quiet", f"{commit_oid}:{guard.PLAN_REL}"],
        label="pinning the master plan blob",
        check=False,
    )
    blob_oid = blob.stdout.strip()
    if blob.returncode != 0 or not blob_oid:
        raise SignedApprovalRootError(
            f"no committed {guard.PLAN_REL} at {commit_oid[:12]}; the "
            "amendment chain describes a plan this revision does not have"
        )
    content = _git(
        root,
        ["cat-file", "blob", blob_oid],
        label="reading the pinned master plan",
        check=False,
    )
    if content.returncode != 0:
        raise SignedApprovalRootError(
            f"master plan blob {blob_oid[:12]} is unreadable; refusing rather "
            "than fetching it"
        )
    normalised = guard.normalized_text(content.stdout)
    plan_digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    if head.get("result_plan_sha256") != plan_digest:
        raise SignedApprovalRootError(
            f"the amendment chain ends at plan digest "
            f"{str(head.get('result_plan_sha256'))[:12]}, but {guard.PLAN_REL} "
            f"at {commit_oid[:12]} hashes to {plan_digest[:12]}. A ledger that "
            "does not describe the plan committed beside it pins nothing."
        )
    revision, _version, _gate = guard.parse_plan_header(normalised)
    if revision != head.get("result_revision"):
        raise SignedApprovalRootError(
            f"{guard.PLAN_REL} declares revision {revision}, but the amendment "
            f"chain ends at revision {head.get('result_revision')}"
        )


def _amendment_pinned_signers_digest(root: Path, commit_oid: str) -> str:
    """The signer-set digest the amendment chain declares authoritative.

    Fails closed when the chain pins nothing: a repository that has never
    amended in an owner signer set cannot promote. That is the correct state
    for a repository whose trust root nobody has approved, and it is the state
    this repository is in until the owner runs
    ``docs/recovery/amendment_007_kit.py``.
    """
    blob = _git(
        root,
        ["rev-parse", "--verify", "--quiet", f"{commit_oid}:{AMENDMENT_LEDGER_PATH}"],
        label="pinning the amendment ledger blob",
        check=False,
    )
    blob_oid = blob.stdout.strip()
    if blob.returncode != 0 or not blob_oid:
        raise SignedApprovalRootError(
            f"no committed {AMENDMENT_LEDGER_PATH} at {commit_oid[:12]}, so no "
            "amendment pins the owner signer set; promotion stays refused"
        )
    content = _git(
        root,
        ["cat-file", "blob", blob_oid],
        label="reading the pinned amendment ledger",
        check=False,
    )
    if content.returncode != 0:
        raise SignedApprovalRootError(
            f"amendment ledger blob {blob_oid[:12]} is unreadable; refusing "
            "rather than fetching it"
        )

    guard = _iron_plan_guard()
    try:
        records = guard.parse_ledger_text(content.stdout, AMENDMENT_LEDGER_PATH)
    except ValueError as exc:
        raise SignedApprovalRootError(
            f"{AMENDMENT_LEDGER_PATH} is not a readable ledger ({exc}); "
            "refusing to guess which signer set was approved"
        ) from exc

    # THE binding step. Reading a digest out of this file without walking the
    # chain is what let a rogue signers file and its own pin land in one
    # commit, and what let a one-line ledger with no chain fields at all be
    # accepted. Both are executed attacks, not hypotheses.
    _verify_amendment_chain(records)
    # ...and the chain alone is not enough. Walking it refuses a MALFORMED
    # appended record; it does not refuse a well-formed one, because an
    # attacker with commit rights can chain onto the real last record
    # correctly. That was measured: attack B2, a well-formed one-motion
    # forgery, was accepted by the chain walk alone. Tying the head of the
    # chain to the committed plan blob is what makes the forgery have to
    # rewrite the constitutional document itself, in the same commit.
    _verify_ledger_head_matches_plan(root, commit_oid, records[-1])

    pinned: str | None = None
    for number, record in enumerate(records, start=1):
        declared = record.get(TRUST_ROOT_DIGEST_FIELD)
        if declared is None:
            continue
        try:
            # The last record that names one wins, so a later amendment
            # rotates the trust root forward.
            pinned = _sha256(declared, TRUST_ROOT_DIGEST_FIELD)
        except (TypeError, ValueError) as exc:
            raise SignedApprovalRootError(
                f"{AMENDMENT_LEDGER_PATH}:{number} declares a malformed "
                f"{TRUST_ROOT_DIGEST_FIELD} ({exc})"
            ) from exc
    if pinned is None:
        raise SignedApprovalRootError(
            f"no accepted amendment declares {TRUST_ROOT_DIGEST_FIELD}, so no "
            "owner signer set has been approved through the amendment "
            "protocol; promotion stays refused"
        )
    return pinned


def read_committed_allowed_signers(repo_root: str | Path) -> str:
    """The committed signer set, normalised. Thin view over the pinned root."""
    return resolve_trust_root(repo_root).normalised()


def _check_tag_signature(
    root: Path, tag_object: str, trust_root: TrustRoot
) -> tuple[bool, str, str]:
    """Run the one signature check. Returns ``(ok, principal, detail)``.

    Extracted so the owner's read-before-signing tool and the promotion
    boundary cannot drift apart: an inspector that checks signatures a little
    differently from the verifier is a way to be shown one thing and approve
    another.
    """
    handle, signers_path = tempfile.mkstemp(prefix="daedalus-allowed-signers-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            # ssh-keygen's allowed-signers parser is line-oriented and a
            # carriage return becomes part of the key blob, so a checkout on a
            # CRLF platform would silently stop matching any principal.
            normalised = trust_root.normalised()
            stream.write(normalised.replace("\r\n", "\n").replace("\r", "\n"))
        verified = _git(
            root,
            [
                "-c",
                "gpg.format=ssh",
                "-c",
                f"gpg.ssh.allowedSignersFile={signers_path}",
                # The verifier itself is pinned. MEASURED 2026-08-18: with
                # gpg.ssh.program set in a config git still reads, an
                # attacker-signed tag verifies "Good signature" and exit 0,
                # because the substituted program decides the answer. The
                # repository's OWN config is such a place, and no environment
                # variable closes it -- only this pin does.
                "-c",
                "gpg.ssh.program=ssh-keygen",
                "verify-tag",
                "--raw",
                # NB: the pinned OID, never a tag name. A name is a mutable ref.
                tag_object,
            ],
            label="verifying the approval tag signature",
            check=False,
        )
    finally:
        try:
            os.unlink(signers_path)
        except OSError:
            pass
    output = verified.stderr or verified.stdout
    if verified.returncode != 0:
        return False, "", (output.strip() or "no principal matched")
    return True, _signer_principal(output), output.strip()


def describe_signed_tag(repo_root: str | Path, tag_name: str) -> dict[str, str]:
    """Describe a tag for the owner's read-before-signing step. Grants nothing.

    Returns plain strings and never a :class:`VerifiedSignedApproval`. It runs
    the SAME signature check as the promotion boundary but performs none of the
    purpose, binding, generation or expiry checks, so it can describe a tag and
    can never authorise one.

    ``verified`` is ``"yes"`` only when the signature checked out against the
    committed signer set. The body is returned either way, because the owner
    needs to see what a tag holds -- but a caller that prints it MUST print the
    verification state with it. Showing a tag body under a heading that implies
    provenance, without saying whether the signature checked out, is how an
    owner gets talked into signing an attacker's bytes.
    """
    root = Path(repo_root).resolve()
    result = {
        "tag_name": tag_name,
        "tag_object": "",
        "verified": "no",
        "principal": "",
        "detail": "",
        "body": "",
    }
    resolved = _git(
        root,
        ["rev-parse", "--verify", "--quiet", f"refs/tags/{tag_name}^{{tag}}"],
        label="resolving the tag object",
        check=False,
    )
    tag_object = resolved.stdout.strip()
    if resolved.returncode != 0 or not tag_object:
        result["detail"] = (
            f"{tag_name} is not an annotated tag object in this repository; "
            "a lightweight tag carries no signature"
        )
        return result
    result["tag_object"] = tag_object

    raw = _git(
        root, ["cat-file", "tag", tag_object],
        label="reading the tag object", check=False,
    )
    if raw.returncode != 0:
        result["detail"] = f"tag object {tag_object[:12]} is unreadable"
        return result
    try:
        result["body"] = _strip_signature(_tag_message(raw.stdout))
    except SignedApprovalError as exc:
        result["detail"] = str(exc)

    try:
        trust_root = resolve_trust_root(root)
    except SignedApprovalError as exc:
        result["detail"] = str(exc)
        return result

    ok, principal, detail = _check_tag_signature(root, tag_object, trust_root)
    result["verified"] = "yes" if ok and principal else "no"
    result["principal"] = principal
    if result["verified"] == "yes":
        result["detail"] = (
            f"signature verified against allowed-signers blob "
            f"{trust_root.blob_oid} committed at {trust_root.commit_oid}"
        )
    else:
        result["detail"] = detail or "no principal matched"
    return result


def verify_signed_approval(
    repo_root: str | Path,
    tag_name: str,
    *,
    expectation: ApprovalExpectation,
    now: datetime | None = None,
) -> VerifiedSignedApproval:
    """Authenticate one owner-signed approval tag against the committed root.

    Every refusal happens before the caller learns anything it could use: this
    function performs no promotion effect, creates no ref, and writes nothing
    into the repository.
    """
    if not isinstance(expectation, ApprovalExpectation):
        raise SignedApprovalBindingMismatch(
            "signed approval verification requires an ApprovalExpectation"
        )
    if not isinstance(tag_name, str) or not tag_name:
        raise SignedApprovalSignatureError("approval tag name must be a string")
    if not tag_name.startswith(APPROVAL_TAG_NAMESPACE):
        raise SignedApprovalPurposeError(
            f"approval tag must live under {APPROVAL_TAG_NAMESPACE!r}; "
            f"{tag_name!r} is outside the approval namespace"
        )
    if any(character.isspace() for character in tag_name):
        raise SignedApprovalSignatureError("approval tag name must not contain spaces")

    root = Path(repo_root).resolve()
    trust_root = resolve_trust_root(root)

    # An annotated/signed tag is a real object; a lightweight tag is only a ref
    # to a commit and carries no signature at all.
    resolved = _git(
        root,
        ["rev-parse", "--verify", "--quiet", f"refs/tags/{tag_name}^{{tag}}"],
        label="resolving the approval tag object",
        check=False,
    )
    tag_object = resolved.stdout.strip()
    if resolved.returncode != 0 or not tag_object:
        raise SignedApprovalSignatureError(
            f"{tag_name} is not an annotated tag object; "
            "a lightweight tag carries no signature"
        )

    signature_ok, principal, detail = _check_tag_signature(root, tag_object, trust_root)
    if not signature_ok:
        raise SignedApprovalSignatureError(
            f"{tag_name} is not signed by an allowed owner principal: {detail}"
        )
    if not principal:
        raise SignedApprovalSignatureError(
            f"{tag_object[:12]} verified, but git named no principal for the "
            "signature; refusing an approval whose signer cannot be recorded"
        )

    # The signed bytes, read as the object Git actually holds, so the digest a
    # receipt cites is a digest of the material that was verified -- and so the
    # body parsed here belongs to the object that was verified. Reading it by
    # tag NAME instead would reopen a TOCTOU: a ref moved between the signature
    # check and this read would pair tag A's signature with tag B's body.
    raw = _git(
        root,
        ["cat-file", "tag", tag_object],
        label="reading the approval tag object",
    )
    approval_ref = _artifact_locator_for(
        hashlib.sha256(raw.stdout.encode("utf-8")).hexdigest()
    )
    body = SignedApprovalBody.from_json(_strip_signature(_tag_message(raw.stdout)))

    # The approval binds the signer-set generation it was made under, so
    # rotating the owner's keys invalidates approvals signed against the
    # previous set instead of silently carrying them across the swap.
    if body.approval_mechanism_sha256 != trust_root.digest:
        raise SignedApprovalMechanismMismatch(
            f"{tag_name} was signed against allowed-signers generation "
            f"{body.approval_mechanism_sha256[:12]}, but the committed trust "
            f"root is now {trust_root.digest[:12]}; re-approve under the "
            "current signer set"
        )

    _require_binding(body, expectation)
    moment = now or datetime.now(timezone.utc)
    if moment >= _parse_utc(body.expires_at, "expires_at"):
        raise SignedApprovalExpired(
            f"signed approval {tag_name} expired at {body.expires_at}"
        )

    # A tag name is a mutable ref. Resolving what the signed tag object points
    # at pins the approval to an immutable object graph, so re-pointing the
    # name at a different object after signing cannot silently redirect a
    # promotion that already looked authorised.
    target = _git(
        root,
        ["rev-parse", "--verify", "--quiet", f"{tag_object}^{{}}"],
        label="pinning the approval tag target",
        check=False,
    )
    tag_target = target.stdout.strip()
    if target.returncode != 0 or not tag_target:
        raise SignedApprovalSignatureError(
            f"{tag_name} does not resolve to an object this repository holds; "
            "refusing rather than fetching it"
        )

    return _mint(
        VerifiedSignedApproval(
            tag_name=tag_name,
            tag_object_sha1=tag_object,
            tag_target_oid=tag_target,
            signer_principal=principal,
            body=body,
            owner_approval_ref=approval_ref,
            trust_root_commit_oid=trust_root.commit_oid,
            trust_root_blob_oid=trust_root.blob_oid,
            _token=_CONSTRUCTION_TOKEN,
        )
    )


def _strip_signature(contents: str) -> str:
    for marker in ("-----BEGIN SSH SIGNATURE-----", "-----BEGIN PGP SIGNATURE-----"):
        index = contents.find(marker)
        if index != -1:
            contents = contents[:index]
    text = contents.strip()
    if not text:
        raise SignedApprovalBindingMismatch("approval tag carries no body")
    if "\n" in text:
        raise SignedApprovalBindingMismatch(
            "approval tag body must be exactly one canonical line"
        )
    return text


def _tag_message(raw: str) -> str:
    """The message of a raw tag object, without its headers.

    ``git cat-file tag`` emits ``object``/``type``/``tag``/``tagger`` headers,
    a blank line, then the message. Only the message is signed content as far
    as this module is concerned; the headers are Git's framing.
    """
    separator = raw.find("\n\n")
    if separator == -1:
        raise SignedApprovalBindingMismatch(
            "approval tag object has no message separated from its headers"
        )
    return raw[separator + 2:]


# git's ssh backend reports a matched principal as:
#   Good "git" signature for <principal> with <keytype> key SHA256:<fp>
# The "for <principal>" clause is present only when a principal in the allowed
# signers matched. The principal-less form ("Good ... signature with ...") is
# the untrusted-key case, which exits non-zero and never reaches here.
_GOOD_SIGNATURE_FOR = 'Good "git" signature for '


def _signer_principal(output: str) -> str:
    """The principal git matched, or ``""`` when it named none.

    Returning the whole log line (the previous behaviour) put a human sentence
    into a receipt field an auditor reads as an identity, and returning
    ``"unknown-principal"`` let verification succeed while the signer stayed
    anonymous. The caller now refuses on an empty result.
    """
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_GOOD_SIGNATURE_FOR):
            continue
        remainder = stripped[len(_GOOD_SIGNATURE_FOR):]
        principal, separator, _key = remainder.rpartition(" with ")
        if separator and principal.strip():
            return principal.strip()
    return ""


def _require_binding(
    body: SignedApprovalBody, expectation: ApprovalExpectation
) -> None:
    comparisons: dict[str, tuple[Any, Any]] = {
        "operation": (body.operation, expectation.operation),
        "nomination_receipt_sha256": (
            body.nomination_receipt_sha256,
            expectation.nomination_receipt_sha256,
        ),
        "candidate_artifact_sha256": (
            body.candidate_artifact_sha256,
            expectation.candidate_artifact_sha256,
        ),
        "evidence_packet_sha256": (
            body.evidence_packet_sha256,
            expectation.evidence_packet_sha256,
        ),
        "base_revision": (body.base_revision, expectation.base_revision),
        "target_ref": (body.target_ref, expectation.target_ref),
        "expected_target_revision": (
            body.expected_target_revision,
            expectation.current_target_revision,
        ),
    }
    mismatches = sorted(
        name for name, (signed, actual) in comparisons.items() if signed != actual
    )
    if mismatches:
        raise SignedApprovalBindingMismatch(
            "signed approval names a different subject: " + ", ".join(mismatches)
        )


def _spent_root() -> Path:
    """One ledger per user -- NOT one per checkout.

    Namespacing this directory by checkout path made an approval spendable once
    PER PATH. MEASURED: the same signed approval was claimed again from a second
    worktree of the same repository, and both calls returned "claimed". This
    project works through worktrees routinely, so that was reachable in ordinary
    use and not only under attack.

    Single use is a property of the APPROVAL, so the ledger is keyed by the
    approval's identity (the signed nonce and candidate, see
    :func:`claim_signed_approval`) and lives at one place per user. It stays
    outside every checkout: a candidate's declared write paths must not be able
    to erase the record of its own approval having been spent.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        base = Path(local_appdata)
    else:
        try:
            base = Path.home() / ".local" / "state"
        except RuntimeError:  # no resolvable home; still checkout-external
            base = Path(tempfile.gettempdir())
    return base / "daedalus-kernel" / "promotion" / "spent"


def claim_signed_approval(
    repo_root: str | Path,
    verified: VerifiedSignedApproval,
    *,
    spent_root: Path | None = None,
) -> tuple[bool, str]:
    """Spend a verified approval exactly once. Returns ``(claimed, reason)``.

    An approval that stays valid after it has been used is a standing
    authorisation with extra steps. The claim is an atomic
    ``O_CREAT | O_EXCL`` file creation keyed by the signed nonce and candidate,
    so on both Windows and POSIX exactly one caller wins -- including two
    concurrent promotions of the same candidate.

    ``repo_root`` does NOT select the ledger. It used to, and that made one
    approval spendable once per checkout path; see :func:`_spent_root`. It is
    retained only so call sites read symmetrically with the rest of the module.

    Fails closed in both directions: a filesystem error is a refusal, never an
    assumed-fresh approval.

    Honest bound: ``spent_root`` exists for tests, and an in-process caller that
    passes a fresh directory on every call defeats single use. Like the
    construction token on :class:`VerifiedSignedApproval`, this resists accident
    and ordinary misuse, not code that is trying. The durable protection is that
    the default ledger is outside every checkout and shared across worktrees.
    """
    if not isinstance(verified, VerifiedSignedApproval):
        return False, "only a verified owner signature can be claimed"
    root = Path(spent_root) if spent_root is not None else _spent_root()
    key = hashlib.sha256(
        f"{verified.body.nonce}\n{verified.body.candidate_artifact_sha256}".encode(
            "utf-8"
        )
    ).hexdigest()
    marker = root / f"{key}.claimed"
    # Creating the ledger directory is kept out of the block below on purpose.
    # `mkdir(parents=True)` raises FileExistsError when a path component is an
    # ordinary file, which would otherwise be reported as "already spent" -- a
    # refusal either way, but only one of the two is true.
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, (
            f"single-use ledger unavailable ({type(exc).__name__}: {exc}); "
            "refusing to promote on an approval whose reuse cannot be detected"
        )
    try:
        handle = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False, (
            f"approval {verified.tag_name} was already spent; an approval "
            "authorises one promotion, not a standing right to promote"
        )
    except OSError as exc:
        return False, (
            f"single-use ledger unavailable ({type(exc).__name__}: {exc}); "
            "refusing to promote on an approval whose reuse cannot be detected"
        )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(f"{verified.tag_name}\n{verified.owner_approval_ref}\n")
    except OSError:
        # The marker existing is what makes the approval spent; failing to
        # annotate it costs an audit note, not the guarantee.
        pass
    return True, f"approval {verified.tag_name} claimed for a single promotion"


def regeneration_voids_approval(
    candidate_artifact_sha256: str, regenerated_sha256: str
) -> str:
    """The refusal reason for a candidate rebuilt after it was approved.

    The recorded decision is that regeneration VOIDS the approval and the
    candidate returns to ``pending-owner``. Verification would refuse the
    regenerated artifact anyway -- a different digest resolves a different tag
    name, which does not exist -- but reporting that as "no approval tag"
    would describe the symptom and hide the cause from whoever reads it.
    """
    return (
        f"approval for candidate {str(candidate_artifact_sha256)[:12]} is void: "
        f"the candidate was regenerated as {str(regenerated_sha256)[:12]} "
        "against a moved base, and no owner approved that artifact; "
        "returning to pending-owner"
    )


def promotion_receipt(
    verified: VerifiedSignedApproval | None,
    *,
    promotion_id: str,
    nomination_receipt_sha256: str,
    candidate_artifact_sha256: str,
    candidate_artifact_locator: str,
    evidence_packet_sha256: str,
    evidence_locator: str,
    source_revision: str,
    target_revision: str,
    created_at: str,
    reasons: tuple[str, ...] = (),
    origin: str = "kernel.signed_approval",
):
    """Build the canonical :class:`~daedalus.schemas.PromotionReceipt`.

    ``approval_assurance="authenticated"`` is set here and only here, and only
    from the presence of a :class:`VerifiedSignedApproval` -- never from an
    argument. There is no parameter that asks for an approved receipt.

    ``isinstance`` alone is NOT enough to decide that, and this function used
    to think it was. ``dataclasses.replace(verified, ...)`` yields a genuine
    ``VerifiedSignedApproval`` whose construction token was carried across by
    the stdlib while every other field is the caller's -- executed, and it
    produced an approved, authenticated receipt naming an attacker's
    principal. So the object must also carry the mint stamp
    :func:`verify_signed_approval` applies after construction, which
    ``replace`` cannot copy and ``deepcopy`` cannot preserve by identity.

    An object that claims the type but not the stamp is refused loudly rather
    than downgraded to ``pending-owner``: it is evidence of tampering, not a
    missing approval.

    The strength of that is bounded by how hard the presented object is to
    obtain, and the honest bound is stated on :class:`VerifiedSignedApproval`:
    the interlock stops accident, casual misuse and the one-stdlib-call
    forgery -- not in-process code determined to reach into this module. The
    authentication a reader should rely on is the signature check recorded in
    ``reasons`` and the pins recorded in the provenance, which can be
    re-verified against the repository. Passing ``None`` yields
    ``pending-owner`` with no approval reference, which is the shape the schema
    already enforces.
    """
    from daedalus.schemas import ContractProvenance, PromotionReceipt

    if isinstance(verified, VerifiedSignedApproval) and not _is_minted(verified):
        raise SignedApprovalSignatureError(
            "this VerifiedSignedApproval was not produced by "
            "verify_signed_approval(); it carries the type but not the "
            "verification. dataclasses.replace() and copy.deepcopy() both "
            "yield such an object, and neither one checked a signature."
        )
    approved = _is_minted(verified) and isinstance(verified, VerifiedSignedApproval)
    if approved and verified.body.candidate_artifact_sha256 != candidate_artifact_sha256:
        raise SignedApprovalBindingMismatch(
            "receipt candidate does not match the signed approval"
        )
    digests = [
        nomination_receipt_sha256,
        candidate_artifact_sha256,
        candidate_artifact_locator.rsplit(":", 1)[-1],
        evidence_packet_sha256,
        evidence_locator.rsplit(":", 1)[-1],
    ]
    extra_reasons: tuple[str, ...] = ()
    if approved:
        digests.append(verified.owner_approval_ref.rsplit(":", 1)[-1])
        # The signer-set generation the approval was made under. It is the one
        # trust-root pin that is already a sha256, so it belongs with the
        # digests; the git object IDs are SHA-1 and go into reasons instead.
        digests.append(verified.body.approval_mechanism_sha256)
        # An auditor asks three questions of an authenticated receipt: signed
        # by whom, checked against which list, and which commit put that list
        # there. Verification knows all three; dropping them left the receipt
        # saying only "against the committed list" without saying which one.
        default_reason = (
            f"owner signature on {verified.tag_name} (tag object "
            f"{verified.tag_object_sha1}) verified as principal "
            f"{verified.signer_principal!r} against allowed-signers blob "
            f"{verified.trust_root_blob_oid} committed at "
            f"{verified.trust_root_commit_oid}"
        )
        extra_reasons = (
            f"trust-root commit: {verified.trust_root_commit_oid}",
            f"trust-root allowed-signers blob: {verified.trust_root_blob_oid}",
            f"signer principal: {verified.signer_principal}",
            f"signer-set generation: {verified.body.approval_mechanism_sha256}",
        )
    else:
        default_reason = "no verified owner signature; awaiting owner approval"

    return PromotionReceipt(
        promotion_id=promotion_id,
        nomination_receipt_sha256=nomination_receipt_sha256,
        candidate_artifact_sha256=candidate_artifact_sha256,
        candidate_artifact_locator=candidate_artifact_locator,
        evidence_packet_sha256=evidence_packet_sha256,
        evidence_locator=evidence_locator,
        source_revision=source_revision,
        target_revision=target_revision,
        promotion_status="approved" if approved else "pending-owner",
        owner_approval_ref=verified.owner_approval_ref if approved else None,
        approval_assurance="authenticated" if approved else "not-applicable",
        reasons=tuple(sorted({default_reason, *extra_reasons, *reasons})),
        provenance=ContractProvenance(
            origin=origin,
            source_revision=source_revision,
            created_at=created_at,
                # Deduplicated: a locator's digest is the artifact digest it
            # names, so the two coincide by construction and
            # ContractProvenance rejects a repeated input.
            input_digests=tuple(sorted(set(digests))),
        ),
    )


__all__ = [
    "APPROVAL_OPERATION",
    "APPROVAL_PURPOSE",
    "APPROVAL_TAG_NAMESPACE",
    "OWNER_ALLOWED_SIGNERS_PATH",
    "SignedApprovalBindingMismatch",
    "SignedApprovalBody",
    "SignedApprovalError",
    "SignedApprovalExpired",
    "SignedApprovalPurposeError",
    "SignedApprovalMechanismMismatch",
    "SignedApprovalRootError",
    "SignedApprovalSignatureError",
    "TrustRoot",
    "VerifiedSignedApproval",
    "resolve_trust_root",
    "approval_tag_for",
    "canonical_approval_body",
    "claim_signed_approval",
    "describe_signed_tag",
    "promotion_receipt",
    "read_committed_allowed_signers",
    "regeneration_voids_approval",
    "verify_signed_approval",
]
