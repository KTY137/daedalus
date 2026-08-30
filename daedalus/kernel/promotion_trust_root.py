# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""D5: the sealed-promotion trust root -- hybrid, with B as the root.

WHAT THIS MODULE IS. Owner decision D5 chose ``hybrid with B as root``:

  * **B (the root)** is an asymmetric, git-signed tag ``promote/<candidate>``
    verified with ``git verify-tag`` against an allowed-signers file read from
    the COMMITTED tree. Forging one needs the owner's private signing key.
    The verifier is ported from the checkpoint line's
    ``daedalus/spine/promotion_approval.py`` (commit ``a83db1f5``), where it
    scored 23 PASS / 0 FAIL in the Phase-0 adversarial suite but had **zero
    production callers**. On this trunk it has exactly one.

  * **HMAC (the second factor)** is the trunk's symmetric env-secret approval
    ledger in :mod:`daedalus.kernel.approvals`. It scored 19 PASS / 5 FAIL in
    the same suite. It is demoted here: it may add a receipt line, it may never
    grant. "Advisory for the verdict, mandatory for the record."

THE TRUTH TABLE IS THE SPEC (giga plan, ``### D5 acceptance truth table``).
Its four cells were precommitted before this implementation existed:

    B valid   + HMAC valid   -> PROMOTE, both factors ledgered
    B valid   + HMAC invalid -> PROMOTE, and the HMAC divergence is written to
                                the ledger as a second-factor mismatch --
                                never silently dropped
    B invalid + HMAC valid   -> REJECT: a valid HMAC never substitutes for the
                                root
    B invalid + HMAC invalid -> REJECT

Every REJECT emits a deny receipt naming the failing factor. :data:`TRUTH_TABLE`
is that table as data, and :func:`evaluate_promotion_trust` reads its verdict
out of it rather than re-deriving it, so a test can compare the code's table to
the committed one cell by cell.

WHAT "MANDATORY FOR THE RECORD" MEANS MECHANICALLY. The second-factor outcome
is appended to a checkout-external, append-only JSONL ledger before any verdict
is returned. If that append fails, the decision is REJECT -- a promotion whose
divergence cannot be recorded is a promotion that does not happen. That is the
only way "mandatory" differs from "advisory" in an implementation.

THE FIVE CASES THE HMAC ROOT FAILED (Phase-0 ``trust_root_report.json``), and
what closes each here:

  A10  an ordinary child holding the env secret mints an approval the verifier
       accepts. Closed structurally: the root verifies against PUBLIC keys in
       the committed tree; the signing key never enters this process, so
       holding the environment mints nothing.
  A10b that self-minted approval is consumed through the real ledger. Closed by
       demotion: ledger consumption is no longer authority, so consuming a
       forged approval produces a recorded second-factor line and no grant.
  A12  a spent approval re-authenticates against a SECOND, caller-supplied
       ledger holding a copied consumption row. Closed by
       :data:`REPLAY_KEY_SPEC`: the root's replay state lives at ONE canonical
       location derived from the repository identity, and
       :func:`evaluate_promotion_trust` takes no spent-root parameter at all,
       so no caller can point the uniqueness check at its own database.
  A9a  a plain child of the verifier reads the approval-secret env var. Closed
       here by needing no secret to verify, and by :func:`scrubbed_child_env`,
       which the attempt path uses to strip every approval secret out of a
       child environment.
  A9c1 the attempt path classified an unreachable Docker engine as a COMPLETED
       attempt. Closed in :mod:`daedalus.kernel.sandbox` (engine-unreachable is
       now ``refused-before-start``), not here.

WHAT THIS MODULE IS NOT. It is not a security boundary against an attacker who
already holds the owner's signing key, and it does not claim to be (plan §1).
It performs no repository mutation. It decides; the caller promotes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from daedalus.spine.killswitch import profile_root_disagreement

#: Which of D5's three options this module implements. A test pins it, so an
#: implementation cannot quietly become option A or option B-without-record.
TRUST_ROOT_MODE = "hybrid-b-as-root"

#: First line of the signed tag body. A body that does not open with exactly
#: this is refused before any field is read: an approval must declare which
#: contract it is speaking, or a future format change silently means something
#: different to the verifier than it did to the owner who signed it.
APPROVAL_BODY_SCHEMA = "daedalus-promotion-approval/1"

#: D5 value 1 -- THE SIGNER ALLOWLIST. Repository-relative, read from the
#: COMMITTED tree at HEAD, never from the working copy.
ALLOWED_SIGNERS_REL = ".agentenv/promotion_allowed_signers"

#: D5 value 2 -- THE REVOCATION AUTHORITY. Removing a principal line from the
#: allowed-signers file and committing it. There is no cache and no other
#: revocation channel: verification re-reads HEAD every time, so a revocation
#: takes effect at the next promotion attempt and is visible in history.
REVOCATION_AUTHORITY = (
    "a commit that removes the principal line from "
    f"{ALLOWED_SIGNERS_REL} at HEAD; re-read on every verification, no cache"
)

TAG_PREFIX = "promote/"

#: D5 value 3 -- THE MAXIMUM APPROVAL AGE. An approval may not authorise for
#: longer than this measured from the moment the owner signed it (the tag's
#: tagger date), and an already-expired approval is refused. This matches the
#: 24-hour Gate-0 ceiling the HMAC factor already enforces
#: (``approvals._MAX_APPROVAL_TTL``), so the two factors cannot disagree about
#: how long a decision lives.
MAX_APPROVAL_AGE = timedelta(hours=24)

#: D5 value 4 -- THE ARTIFACT-BINDING FIELDS. Each closes a distinct replay:
#:
#:     tag NAME    -> candidate artifact sha256  (approve A, promote B)
#:     tag TARGET  -> source revision            (approve on one base, land on another)
#:     tag BODY    -> evidence packet sha256     (approve on E, promote on weaker E')
#:     tag BODY    -> expiry + nonce             (a standing authorisation)
ARTIFACT_BINDING_FIELDS = (
    "candidate_sha256",
    "evidence_sha256",
    "source_revision",
    "expires_at",
    "nonce",
)

#: D5 value 5 -- THE REPLAY KEY. ``sha256(nonce + "\n" + candidate_sha256)``,
#: spent under a checkout-external root namespaced by the resolved repository
#: path. NOT a parameter: see the A12 note in the module docstring.
REPLAY_KEY_SPEC = 'sha256(f"{nonce}\\n{candidate_sha256}")'

#: D5 value 6 -- THE REPLAY-STATE RETENTION. Permanent. Nothing in this module
#: deletes a spent marker, and an unreachable replay store is a refusal rather
#: than an assumed-fresh approval, so pruning cannot become a replay window.
REPLAY_STATE_RETENTION = "permanent; never pruned by this module"

#: THE PRECOMMITTED TRUTH TABLE, as data. Keyed ``(root_valid, hmac_valid)``.
TRUTH_TABLE: dict[tuple[bool, bool], str] = {
    (True, True): "PROMOTE",
    (True, False): "PROMOTE",
    (False, True): "REJECT",
    (False, False): "REJECT",
}

#: The record note each cell must carry, so "ledgered" is checkable and not a
#: claim in prose.
TRUTH_TABLE_RECORD: dict[tuple[bool, bool], str] = {
    (True, True): "both-factors-ledgered",
    (True, False): "second-factor-mismatch-ledgered",
    (False, True): "root-invalid-second-factor-cannot-substitute",
    (False, False): "both-factors-invalid",
}

_REQUIRED_BODY_KEYS = frozenset(ARTIFACT_BINDING_FIELDS)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")
_NONCE_RE = re.compile(r"^[0-9A-Za-z._:/-]{8,200}$")
_SIGNER_RE = re.compile(r"signature for (\S+) with", re.IGNORECASE)
_TAGGER_RE = re.compile(r"^tagger .*? (\d{1,12}) ([+-]\d{4})\s*$", re.MULTILINE)

#: Pinned on the command line, where it outranks repository-local config.
#: Without this, a writable ``.git/config`` chooses the allowed-signers file
#: and the program that "verifies" the signature.
_GIT_VERIFY_CONFIG = (
    "gpg.ssh.program=ssh-keygen",
    "gpg.program=gpg",
)

#: Environment names a child must never inherit. The root needs none of them --
#: that is the point of an asymmetric root -- but the HMAC second factor still
#: reads one, and A9a measured a plain child reading it verbatim.
SECRET_ENV_PREFIXES = (
    "DAEDALUS_OWNER_APPROVAL_SECRET",
    "DAEDALUS_APPROVAL_SECRET",
    "DAEDALUS_PROMOTION_SECRET",
)


class PromotionTrustRootError(RuntimeError):
    """A promotion the trust root refuses. Carries the deny receipt."""

    def __init__(self, message: str, *, deny_receipt: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.deny_receipt = dict(deny_receipt or {})


class _Refused(Exception):
    """Internal control flow. Never escapes this module -- every entry point
    converts it to a refusal verdict, because a promotion boundary that can
    raise is a promotion boundary a caller can accidentally treat as a pass by
    forgetting a ``try``."""


# --------------------------------------------------------------------------- #
# B: the root verifier (ported from checkpoint a83db1f5)                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ApprovalVerdict:
    """The resolved answer, and the evidence for it.

    ``approved`` is the only field a caller may branch on. ``owner_approval_ref``
    is populated ONLY on an approval and is the content-addressed locator of the
    signed tag object itself -- the bytes that were verified, not a description
    of them.
    """

    approved: bool
    reason: str
    candidate_sha256: str
    tag: str
    owner_approval_ref: str | None = None
    signer: str | None = None
    expires_at: str | None = None
    nonce: str | None = None
    evidence_sha256: str | None = None
    source_revision: str | None = None
    signed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "candidate_sha256": self.candidate_sha256,
            "tag": self.tag,
            "owner_approval_ref": self.owner_approval_ref,
            "signer": self.signer,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "evidence_sha256": self.evidence_sha256,
            "source_revision": self.source_revision,
            "signed_at": self.signed_at,
            "security_boundary_claimed": False,
        }


def approval_tag_for(candidate_sha256: str) -> str:
    return f"{TAG_PREFIX}{candidate_sha256}"


def scrubbed_child_env(base: Mapping[str, str] | None = None) -> dict:
    """A child environment with every promotion secret removed (A9a).

    The Phase-0 suite measured a plain child of the verifier reading
    ``DAEDALUS_OWNER_APPROVAL_SECRET_CANARY`` verbatim out of an inherited
    environment. The asymmetric root does not need a secret at all, so the
    correct state for any child is that no promotion secret is reachable
    through it, whatever the second factor happens to be configured with.

    Prefix matching, not exact names: a canary, a ``_FILE`` variant or a
    per-owner suffix are all the same secret wearing a different name.
    """
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if any(upper.startswith(prefix) for prefix in SECRET_ENV_PREFIXES):
            del env[name]
    return env


def _hardened_env() -> dict:
    """System and global config are disabled so that ONLY the pinned
    command-line settings and the repository's own config are in play, and the
    pinned settings outrank the latter. Promotion secrets are removed on top
    (A9a): the root verifies with public keys, so a child of the verifier has
    no business seeing any signing material at all."""
    env = scrubbed_child_env()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    for leaky in (
        "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_PROXY_COMMAND",
        "GIT_ASKPASS", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
    ):
        env.pop(leaky, None)
    return env


def _git(root: Path, args: list[str], *, extra_config: tuple[str, ...] = (),
         timeout: int = 60) -> subprocess.CompletedProcess:
    pre: list[str] = []
    for kv in (*_GIT_VERIFY_CONFIG, *extra_config):
        pre += ["-c", kv]
    try:
        return subprocess.run(
            ["git", *pre, *args], cwd=str(root), capture_output=True,
            timeout=timeout, env=_hardened_env(), check=False)
    except (OSError, subprocess.SubprocessError) as e:
        # git absent, unrunnable, or hung. An approval that cannot be checked
        # is an approval that does not exist.
        raise _Refused(f"git {' '.join(args[:2])} could not run: "
                       f"{type(e).__name__}: {e}") from e


def _out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.decode("utf-8", "replace").strip()


def _err(proc: subprocess.CompletedProcess) -> str:
    return proc.stderr.decode("utf-8", "replace").strip()


def _committed_allowed_signers(root: Path, rel: str) -> bytes:
    """The allowed-signers file AS COMMITTED AT HEAD.

    Not the working copy. Anything able to write the checkout can drop its own
    public key into a working-tree file; it cannot do so at HEAD without making
    a commit, which is exactly the reviewable, attributable act D5 asks for.
    """
    proc = _git(root, ["show", f"HEAD:{rel}"])
    if proc.returncode != 0:
        raise _Refused(
            f"allowed-signers file {rel!r} is not committed at HEAD "
            f"({_err(proc) or 'no such path'}); promotion cannot be authorised "
            "against an uncommitted trust root")
    blob = proc.stdout
    if not blob.strip():
        raise _Refused(f"committed allowed-signers file {rel!r} is empty")
    return blob


def _tag_message(raw: bytes) -> str:
    """The MESSAGE of a tag object, without its headers.

    ``git cat-file tag`` emits ``object``/``type``/``tag``/``tagger`` lines,
    then one blank line, then the message the owner wrote -- with the signature
    block appended to it, which is why a tag's signature covers the message.
    Only the message is the approval body; feeding the headers to the field
    parser would make every approval fail for the wrong reason.
    """
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    head, sep, message = text.partition("\n\n")
    if not sep:
        raise _Refused("tag object has no message; there is no approval body")
    return message


def _tag_signed_at(raw: bytes) -> datetime:
    """When the owner signed, from the tag's own ``tagger`` header.

    The maximum approval age is measured from here rather than from the body,
    because the body is written by whoever composes the approval and the header
    is written by git at signing time. A body claiming a year-long window is
    refused against this instant, not against itself.
    """
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    head, sep, _ = text.partition("\n\n")
    match = _TAGGER_RE.search(head if sep else text)
    if not match:
        raise _Refused("tag object carries no parseable tagger date")
    try:
        epoch = int(match.group(1))
    except ValueError as e:                                      # pragma: no cover
        raise _Refused("tag tagger date is not an epoch instant") from e
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _parse_body(text: str) -> dict:
    """The signed body -> a validated mapping, or a refusal.

    Strict on purpose: exact schema line, no duplicate keys, no unknown keys,
    no missing keys. Everything here was inside the signature, so anything this
    parser tolerates is something the owner signed and the boundary ignored.
    """
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise _Refused("signed tag carries no approval body")
    if lines[0] != APPROVAL_BODY_SCHEMA:
        raise _Refused(
            f"approval body must begin with {APPROVAL_BODY_SCHEMA!r}, "
            f"found {lines[0][:60]!r}")

    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.startswith("-----BEGIN "):
            break  # the signature block git leaves in the raw object
        if ":" not in line:
            raise _Refused(f"approval body line is not 'key: value': {line[:60]!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key in fields:
            raise _Refused(f"approval body repeats {key!r}")
        fields[key] = value

    unknown = sorted(set(fields) - _REQUIRED_BODY_KEYS)
    if unknown:
        raise _Refused(
            "approval body carries key(s) this boundary does not verify: "
            + ", ".join(unknown))
    missing = sorted(_REQUIRED_BODY_KEYS - set(fields))
    if missing:
        raise _Refused("approval body is missing: " + ", ".join(missing))

    for key in ("candidate_sha256", "evidence_sha256"):
        if not _SHA256_RE.fullmatch(fields[key]):
            raise _Refused(f"approval body {key} is not a sha256 digest")
    if not _REVISION_RE.fullmatch(fields["source_revision"]):
        raise _Refused("approval body source_revision is not an exact revision")
    if not _NONCE_RE.fullmatch(fields["nonce"]):
        raise _Refused("approval body nonce is missing or malformed")
    return fields


def _expiry(value: str, now: datetime, signed_at: datetime) -> str:
    """An approval with no usable expiry is a standing authorisation, which is
    the thing invariant 5 exists to prevent. Unparseable is refused, not
    treated as far-future. The window is additionally capped at
    :data:`MAX_APPROVAL_AGE` measured from the signing instant, which is D5
    value 3."""
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise _Refused(
            f"approval expires_at is not an ISO-8601 instant: {text[:40]!r}") from e
    if parsed.tzinfo is None:
        raise _Refused("approval expires_at must carry an explicit UTC offset")
    if parsed <= now:
        raise _Refused(f"approval expired at {text} (now {now.isoformat()})")
    if parsed - signed_at > MAX_APPROVAL_AGE:
        raise _Refused(
            f"approval window {parsed - signed_at} exceeds the maximum approval "
            f"age {MAX_APPROVAL_AGE} measured from the signing instant "
            f"{signed_at.isoformat()}")
    if now - signed_at > MAX_APPROVAL_AGE:
        raise _Refused(
            f"approval was signed {now - signed_at} ago, beyond the maximum "
            f"approval age {MAX_APPROVAL_AGE}")
    return text


def verify_promotion_approval(
    repo_root: str | Path,
    *,
    candidate_sha256: str,
    evidence_sha256: str,
    source_revision: str,
    now: datetime | None = None,
    allowed_signers_rel: str = ALLOWED_SIGNERS_REL,
) -> ApprovalVerdict:
    """Resolve and authenticate an owner approval for ONE candidate.

    Returns a verdict; never raises. Every failure -- no tag, an unsigned tag,
    a signature from a key outside the committed allowed-signers file, a tag
    pointing at a different revision, a body naming a different candidate or
    different evidence, an expired approval, a git that will not run -- is
    ``approved=False`` with a reason.

    ``git verify-tag``'s EXIT CODE is the only authority. Its human output is
    not, and this is not a stylistic preference -- it is a measured trap. A
    signature by a key that is NOT in the allowed-signers file still prints
    ``Good "git" signature with ED25519 key SHA256:...`` on stderr and only
    adds ``No principal matched.`` So a check for "Good" in the output accepts
    a signature from any key in the world. Nothing here reads that text for a
    verdict; the principal is captured for the audit trail only.

    The caller supplies what it believes it is promoting; this function proves
    the owner signed exactly that. It performs no mutation and consumes
    nothing: see :func:`claim_approval` for single use.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    tag = approval_tag_for(str(candidate_sha256))
    try:
        if not _SHA256_RE.fullmatch(str(candidate_sha256)):
            raise _Refused("candidate_sha256 is not a sha256 digest")
        if not _SHA256_RE.fullmatch(str(evidence_sha256)):
            raise _Refused("evidence_sha256 is not a sha256 digest")
        if not _REVISION_RE.fullmatch(str(source_revision)):
            raise _Refused("source_revision is not an exact revision")

        root = Path(repo_root).resolve()
        if not root.is_dir():
            raise _Refused(f"repository root {root} does not exist")

        signers = _committed_allowed_signers(root, allowed_signers_rel)

        # FULL REF PATH, never the bare name. `promote/<sha>` as a short name
        # is resolved by git's ref-precedence rules, which consider
        # `refs/heads/` among others; tags currently win, but an approval must
        # not depend on a precedence rule staying the way it is. Only a real
        # tag can answer here.
        ref = f"refs/tags/{tag}"
        kind = _git(root, ["cat-file", "-t", ref])
        if kind.returncode != 0:
            raise _Refused(
                f"no approval tag {tag!r} in this repository; the candidate is "
                "unapproved")
        if _out(kind) != "tag":
            # A lightweight tag is a name pointing straight at a commit: there
            # is no tag object, so there is nothing signed.
            raise _Refused(
                f"{tag!r} is a {_out(kind)!r}, not an annotated tag object; an "
                "approval must be a signed tag")

        # The signed bytes, captured BEFORE verification so the thing hashed
        # into owner_approval_ref is the thing that was verified.
        raw = _git(root, ["cat-file", "tag", ref])
        if raw.returncode != 0:
            raise _Refused(f"approval tag {tag!r} could not be read: {_err(raw)}")
        tag_bytes = raw.stdout
        approval_ref = (
            "artifact-locator:sha256:" + hashlib.sha256(tag_bytes).hexdigest()
        )

        # THE SIGNATURE. Written to a temp file outside the repository so no
        # working-tree path participates, and deleted in `finally` whatever
        # happens.
        fd, signers_path = tempfile.mkstemp(prefix="promotion-signers-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(signers)
            verified = _git(
                root, ["verify-tag", "--", ref],
                extra_config=(f"gpg.ssh.allowedSignersFile={signers_path}",))
        finally:
            try:
                os.unlink(signers_path)
            except OSError:
                pass

        if verified.returncode != 0:
            raise _Refused(
                f"signature on {tag!r} did not verify against the committed "
                f"allowed-signers file: {_err(verified) or 'no detail'}")
        signer_match = _SIGNER_RE.search(_err(verified))
        signer = signer_match.group(1) if signer_match else None

        # THE TAG TARGET. Binds the approval to the base it was reviewed
        # against, so an approval cannot be replayed onto a moved tree.
        target = _git(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
        if target.returncode != 0:
            raise _Refused(f"approval tag {tag!r} resolves to no commit")
        target_sha = _out(target)
        if not target_sha.startswith(str(source_revision)[:40]) and \
                not str(source_revision).startswith(target_sha[:40]):
            raise _Refused(
                f"approval tag points at {target_sha[:12]}, but promotion is "
                f"against {str(source_revision)[:12]}")

        signed_at = _tag_signed_at(tag_bytes)
        body = _parse_body(_tag_message(tag_bytes))

        if body["candidate_sha256"] != str(candidate_sha256):
            raise _Refused(
                f"approval body names candidate {body['candidate_sha256'][:12]}, "
                f"tag name says {str(candidate_sha256)[:12]}")
        if body["evidence_sha256"] != str(evidence_sha256):
            raise _Refused(
                f"approval was signed against evidence "
                f"{body['evidence_sha256'][:12]}, promotion presents "
                f"{str(evidence_sha256)[:12]}")
        if body["source_revision"] != str(source_revision):
            raise _Refused(
                f"approval body names revision {body['source_revision'][:12]}, "
                f"promotion is against {str(source_revision)[:12]}")
        expires_at = _expiry(body["expires_at"], now, signed_at)

        return ApprovalVerdict(
            approved=True,
            reason=(
                f"owner signature on {tag} verified against committed allowed "
                "signers"
            ),
            candidate_sha256=str(candidate_sha256),
            tag=tag,
            owner_approval_ref=approval_ref,
            signer=signer,
            expires_at=expires_at,
            nonce=body["nonce"],
            evidence_sha256=body["evidence_sha256"],
            source_revision=body["source_revision"],
            signed_at=signed_at.isoformat(),
        )
    except _Refused as e:
        return ApprovalVerdict(
            approved=False, reason=str(e),
            candidate_sha256=str(candidate_sha256), tag=tag)
    except Exception as e:                                       # noqa: BLE001
        # The catch-all is the point, not a lapse: an unanticipated failure
        # while checking an authorisation must read as "not authorised".
        return ApprovalVerdict(
            approved=False,
            reason=f"approval verification raised: {type(e).__name__}: {e}",
            candidate_sha256=str(candidate_sha256), tag=tag)


def voided_by_regeneration(candidate_sha256: str, regenerated_sha256: str,
                           ) -> ApprovalVerdict:
    """The refusal for a candidate that was rebuilt after it was approved.

    The owner's recorded decision: regeneration VOIDS the approval and the
    candidate returns to ``pending-owner``. Verification would refuse the
    regenerated artifact anyway -- it has a different sha, so it has no signed
    tag -- but reporting that as "no approval tag" would describe the symptom
    and hide the cause from whoever reads the report.
    """
    return ApprovalVerdict(
        approved=False,
        reason=(
            f"approval for candidate {str(candidate_sha256)[:12]} is void: the "
            f"candidate was regenerated as {str(regenerated_sha256)[:12]} "
            "against a moved base, and no owner approved that artifact; "
            "returning to pending-owner"),
        candidate_sha256=str(regenerated_sha256),
        tag=approval_tag_for(str(regenerated_sha256)))


# --------------------------------------------------------------------------- #
# replay state and the second-factor record                                    #
# --------------------------------------------------------------------------- #
def _promotion_state_root(repo_root: str | Path) -> Path:
    """Checkout-external, namespaced by checkout identity.

    Same placement rule as the gated-candidate artifact archive, for the same
    reason: replay state must not live anywhere a candidate's declared write
    paths can reach. It is DERIVED, never passed: A12 measured a replay
    accepted because the uniqueness store was a caller-supplied parameter, and
    the fix is that the live path has no parameter to supply.

    INHERITED, not re-derived. It used to compute its own
    ``%LOCALAPPDATA%/daedalus-kernel/promotion/<digest>``; the kill switch
    computed its own ``%LOCALAPPDATA%/daedalus/control/<digest>``; the lease
    ledger a third. All three were silently redirected by Microsoft-Store
    Python's filesystem virtualisation (MEASURED -- see
    :mod:`daedalus.spine.killswitch`), which meant the spent-approval ledger
    was PER INTERPRETER: a promotion run under a different python could not see
    that the approval had been spent. One control root, one place to fix, and
    :func:`daedalus.spine.killswitch.verify_control_root` refuses when it is
    not the directory this process thinks it is.
    """
    from daedalus.spine.killswitch import control_root

    return control_root(repo_root) / "promotion"


def _legacy_promotion_state_root(repo_root: str | Path) -> Path | None:
    """Where the promotion state used to live, or ``None`` when inapplicable."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    digest = hashlib.sha256(
        str(Path(repo_root).resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(local_appdata) / "daedalus-kernel" / "promotion" / digest


def _legacy_promotion_state(repo_root: str | Path) -> tuple[Path, list[str]] | None:
    """Pre-migration promotion state that still exists, if any.

    A fresh spent-ledger beside a populated old one is a replay window: every
    approval the old ledger recorded as spent reads as unspent in the new one.
    So this is surfaced as a REFUSAL rather than migrated automatically --
    moving an operator's approval ledger is the operator's decision.
    """
    legacy = _legacy_promotion_state_root(repo_root)
    if legacy is None:
        return None
    found: list[str] = []
    for name in ("spent", CLAIM_LEDGER_NAME, "second_factor.jsonl"):
        try:
            os.stat(legacy / name)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            found.append(f"{name} (unreadable)")
        else:
            found.append(name)
    return (legacy, found) if found else None


def replay_key(nonce: str, candidate_sha256: str) -> str:
    """D5 value 5, as code. See :data:`REPLAY_KEY_SPEC`."""
    return hashlib.sha256(
        f"{nonce}\n{candidate_sha256}".encode("utf-8")).hexdigest()


#: The hash-chained companion to the single-use marker files. See
#: :func:`claim_approval` for what each of the two answers and why one is not
#: enough.
CLAIM_LEDGER_NAME = "claims.jsonl"


def claim_ledger_path(repo_root: str | Path) -> Path:
    """The append-only, hash-chained record of every spent approval."""
    return _promotion_state_root(repo_root) / CLAIM_LEDGER_NAME


def _canonical(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _read_claim_chain(repo_root: str | Path,
                      ) -> tuple[str, str | None, str, set[str]]:
    """``(status, problem, head_sha256, spent_keys)``. Never raises.

    ``status`` is ``ok``, ``broken`` (the chain does not link, or a line is not
    a record) or ``unreadable``. Both non-ok statuses are refusals upstream:
    a uniqueness ledger this code cannot read is one it cannot use to say an
    approval is fresh.
    """
    path = claim_ledger_path(repo_root)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return "ok", None, "", set()
    except OSError as e:
        return "unreadable", (
            f"the claim ledger at {path} could not be read "
            f"({type(e).__name__}: {e})"), "", set()
    except Exception as e:                                       # noqa: BLE001
        return "unreadable", (
            f"the claim ledger at {path} could not be read "
            f"({type(e).__name__}: {e})"), "", set()
    spent: set[str] = set()
    head = ""
    for n, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            return "broken", f"claim ledger line {n} is not JSON", head, spent
        if not isinstance(record, dict):
            return "broken", f"claim ledger line {n} is not a record", head, spent
        if str(record.get("prev_sha256") or "") != head:
            return "broken", (
                f"claim ledger line {n} does not follow line {n - 1}: it "
                f"names prev_sha256={str(record.get('prev_sha256'))[:12]!r} "
                f"but the chain head is {head[:12]!r} -- a line was removed, "
                "reordered or rewritten"), head, spent
        head = hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()
        key = str(record.get("replay_key") or "")
        if key:
            spent.add(key)
    return "ok", None, head, spent


def _append_claim(repo_root: str | Path, record: Mapping[str, Any],
                  head: str) -> str:
    """Append one chained claim and return its sha256, or raise ``OSError``."""
    payload = dict(record)
    payload["prev_sha256"] = head
    line = _canonical(payload)
    path = claim_ledger_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _claim_marker_present(marker: Path) -> tuple[bool, str | None]:
    """``(present, unreadable_reason)``, fail-closed like the kill switch.

    NOT ``Path.exists()``: that answers False for "denied" and "the volume is
    gone" as readily as for "absent", and here False means "this approval has
    not been spent yet".
    """
    try:
        os.stat(marker)
    except (FileNotFoundError, NotADirectoryError):
        return False, None
    except OSError as e:
        return True, (
            f"the single-use marker could not be examined "
            f"({type(e).__name__}: {e}); an approval whose reuse cannot be "
            "detected is not promotable")
    return True, None


def claim_approval(repo_root: str | Path, verdict: ApprovalVerdict,
                   ) -> tuple[bool, str]:
    """Spend a verified approval exactly once. ``(claimed, reason)``.

    An approval that stays valid after it has been used is a standing
    authorisation with extra steps, so the promotion boundary must consume one.
    The claim is an atomic ``O_CREAT | O_EXCL`` file creation keyed by
    :func:`replay_key`: on both Windows and POSIX exactly one caller can win,
    including two concurrent promotions of the same candidate.

    Fails closed in both directions: an unapproved verdict is never claimable,
    and a filesystem error is a refusal rather than an assumed-fresh approval.

    The checkpoint original accepted a ``spent_root`` override. It is gone: an
    overridable uniqueness store is exactly the A12 finding, one layer up.

    TWO RECORDS, BECAUSE THE MARKER ALONE ANSWERS ONLY ONE QUESTION.
    ---------------------------------------------------------------
    A bare ``O_EXCL`` marker file is the right race arbiter and the wrong
    ledger. MEASURED against this module (Odysseus probe 2, reproduced): the
    nonce is public -- it is in the owner's signed tag -- so
    :func:`replay_key` is computable by anyone who can read the tag, and the
    marker path is therefore predictable. Two attacks followed from one file:

      * **pre-create** the marker and the owner's approval can never be spent
        -- a permanent, silent denial of promotion that looks exactly like
        "you already used this";
      * **unlink** the marker and the approval is fresh again -- replay.

    The chained ``claims.jsonl`` beside it turns both into a REFUSAL WITH A
    NAME, because the two records now have to agree:

      | marker | chain   | verdict                                        |
      | absent | unspent | claim (create marker, then append)              |
      | absent | spent   | REJECT "ledger says spent" -- the unlink attack |
      | present| unspent | REJECT "marker without ledger" -- the pre-create|
      | present| spent   | REJECT "already spent" -- the ordinary reuse    |

    WHAT THIS IS NOT. The chain is tamper-EVIDENT, not tamper-PROOF, and the
    difference matters: both records live under the same control root at the
    same integrity level, so an attacker who can unlink the marker can also
    rewrite the chain, and rewriting it is cheap (recompute the following
    hashes). What the chain buys is that the two attacks above stop being
    single-file edits, that an accidental or partial deletion is detected, and
    that a contained candidate -- which the kernel denies write access to the
    control root -- cannot reach either. The real boundary is the filesystem
    ACL on that root; this is the detector, and it does not claim to be a
    security boundary.
    """
    if not verdict.approved:
        return False, "an unapproved verdict cannot be claimed"
    if not verdict.nonce:
        return False, "approved verdict carries no nonce; refusing to claim"

    legacy = _legacy_promotion_state(repo_root)
    if legacy is not None:
        legacy_root, found = legacy
        return False, (
            f"a pre-migration promotion state still holds {', '.join(found)} "
            f"at {legacy_root} (which resolves to "
            f"{os.path.realpath(str(legacy_root))}). Spending approvals into a "
            f"fresh ledger at {_promotion_state_root(repo_root)} would read "
            "every approval the old one recorded as spent as unspent again -- "
            "a replay window. Move or delete the old state deliberately.")

    # Guard: profile root must not be relocated in-process before accessing
    # the promotion state ledger outside the repository.
    profile_disagreement = profile_root_disagreement()
    if profile_disagreement:
        return False, f"profile.root_relocated: {profile_disagreement}"

    root = _promotion_state_root(repo_root) / "spent"
    key = replay_key(verdict.nonce, verdict.candidate_sha256)
    marker = root / f"{key}.claimed"
    # Creating the ledger DIRECTORY is kept out of the block below on purpose.
    # `mkdir(parents=True)` raises FileExistsError when a path component is an
    # ordinary file, which would otherwise be reported as "already spent" -- a
    # refusal either way, but one that tells whoever reads it that the owner
    # already used this approval when in fact the ledger is broken. Both fail
    # closed; only one of them is true.
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, (
            f"single-use ledger unavailable ({type(e).__name__}: {e}); refusing "
            "to promote on an approval whose reuse cannot be detected")

    status, problem, head, spent = _read_claim_chain(repo_root)
    if status != "ok":
        return False, (
            f"the claim ledger is not trustworthy ({problem}); refusing to "
            "promote on an approval whose reuse cannot be detected")
    present, unreadable = _claim_marker_present(marker)
    if unreadable is not None:
        return False, unreadable

    if key in spent:
        # Authoritative over the marker's absence, which is the point: the
        # marker is the thing an attacker deletes.
        return False, (
            f"ledger says spent: {claim_ledger_path(repo_root)} records "
            f"approval {verdict.tag} as already claimed"
            + ("" if present else
               " while its single-use marker is MISSING -- the marker was "
               "removed after the claim, which is a replay attempt or a "
               "damaged control root; either way this approval is finished"))
    if present:
        return False, (
            f"marker without ledger: {marker} exists but "
            f"{claim_ledger_path(repo_root)} has no claim for approval "
            f"{verdict.tag}. The replay key is derived from a nonce that is "
            "public in the signed tag, so a marker nobody claimed is a "
            "planted one, and honouring it would be a silent denial of the "
            "owner's approval. Remove that marker deliberately to proceed.")

    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Lost the race to a concurrent promotion between the read above and
        # here. Still the right refusal: one of us claimed it.
        return False, (
            f"approval {verdict.tag} was already spent; an approval authorises "
            "one promotion, not a standing right to promote")
    except OSError as e:
        return False, (
            f"single-use ledger unavailable ({type(e).__name__}: {e}); refusing "
            "to promote on an approval whose reuse cannot be detected")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{verdict.tag}\n{verdict.owner_approval_ref}\n")
    except OSError:
        # The marker exists, which is what makes the approval spent; failing to
        # annotate it costs an audit note, not the guarantee.
        pass

    # MARKER FIRST, THEN CHAIN, and the order is load-bearing: the marker is
    # the atomic race arbiter, so it must be taken before anything slow. A
    # crash in between leaves marker-present + chain-unspent, which the table
    # above reads as "marker without ledger" -- a refusal. Fail-closed in the
    # only direction a promotion boundary may fail.
    try:
        record_sha = _append_claim(repo_root, {
            "event": "approval-claimed",
            "replay_key": key,
            "tag": verdict.tag,
            "candidate_sha256": verdict.candidate_sha256,
            "owner_approval_ref": verdict.owner_approval_ref or "",
            "signer": verdict.signer or "",
            "at": datetime.now(timezone.utc).isoformat(),
        }, head)
    except Exception as e:                                       # noqa: BLE001
        return False, (
            f"the claim could not be written to {claim_ledger_path(repo_root)} "
            f"({type(e).__name__}: {e}). The single-use marker was already "
            "created, so this approval is spent and no promotion may use it; "
            "the owner must issue a new approval.")
    return True, (
        f"approval {verdict.tag} claimed for a single promotion "
        f"(claim ledger record {record_sha[:12]})")


def second_factor_ledger_path(repo_root: str | Path) -> Path:
    """Where the demoted HMAC factor is written down. Append-only JSONL."""
    return _promotion_state_root(repo_root) / "second_factor.jsonl"


def _append_record(repo_root: str | Path, line: Mapping[str, Any]) -> str:
    """Append one record and return its sha256, or raise.

    MANDATORY FOR THE RECORD: the caller turns a failure here into a REJECT.
    A promotion whose second-factor divergence cannot be written down is a
    promotion that leaves no trace of the divergence, which is precisely what
    "never silently dropped" forbids.
    """
    path = second_factor_ledger_path(repo_root)
    payload = json.dumps(line, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(payload + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return digest


# --------------------------------------------------------------------------- #
# the HMAC second factor                                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SecondFactorOutcome:
    """What the demoted HMAC factor said. Never a grant."""

    valid: bool
    reason: str
    consumption_sha256: str | None = None
    approval_sha256: str | None = None
    owner_id: str | None = None
    key_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "factor": "hmac-env-secret",
            "authority": "second-factor-record-only",
            "valid": self.valid,
            "reason": self.reason,
            "consumption_sha256": self.consumption_sha256,
            "approval_sha256": self.approval_sha256,
            "owner_id": self.owner_id,
            "key_id": self.key_id,
        }


def evaluate_second_factor(
    *,
    approval_ledger: Any,
    owner_keyring: Mapping[tuple[str, str], bytes | str] | None,
    consumed_approval: Any,
) -> SecondFactorOutcome:
    """Re-authenticate the persisted HMAC consumption. Never raises.

    This is the trunk root demoted. It still runs, and its answer still lands
    in the record, but nothing branches on it for the verdict -- see
    :func:`evaluate_promotion_trust`.
    """
    from daedalus.kernel.approvals import ApprovalLedger, ConsumedOwnerApproval

    if not isinstance(approval_ledger, ApprovalLedger):
        return SecondFactorOutcome(
            valid=False,
            reason="second factor absent: no ApprovalLedger supplied",
        )
    if not isinstance(owner_keyring, Mapping) or not owner_keyring:
        return SecondFactorOutcome(
            valid=False,
            reason="second factor absent: no owner keyring supplied",
        )
    if not isinstance(consumed_approval, ConsumedOwnerApproval):
        return SecondFactorOutcome(
            valid=False,
            reason="second factor absent: no ConsumedOwnerApproval supplied",
        )
    try:
        persisted = approval_ledger.verify_consumption(
            consumed_approval, keyring=dict(owner_keyring)
        )
    except Exception as exc:                                     # noqa: BLE001
        return SecondFactorOutcome(
            valid=False,
            reason=f"second factor rejected: {type(exc).__name__}: {exc}",
            consumption_sha256=getattr(
                consumed_approval, "consumption_sha256", None),
        )
    if persisted != consumed_approval:
        return SecondFactorOutcome(
            valid=False,
            reason="second factor returned a different consumption capability",
            consumption_sha256=consumed_approval.consumption_sha256,
        )
    verified = persisted.verified
    return SecondFactorOutcome(
        valid=True,
        reason="persisted HMAC consumption re-authenticated",
        consumption_sha256=persisted.consumption_sha256,
        approval_sha256=verified.approval_sha256,
        owner_id=verified.owner_id,
        key_id=verified.key_id,
    )


# --------------------------------------------------------------------------- #
# the decision                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PromotionTrustDecision:
    """One evaluated cell of the D5 truth table."""

    promote: bool
    cell: tuple[bool, bool]
    outcome: str
    record_note: str
    root: ApprovalVerdict
    second_factor: SecondFactorOutcome
    stage: str
    record_sha256: str | None = None
    claimed: bool = False
    claim_reason: str | None = None
    seams_used: tuple[str, ...] = field(default_factory=tuple)
    deny_reason: str | None = None

    @property
    def failing_factors(self) -> tuple[str, ...]:
        failing = []
        if not self.root.approved:
            failing.append("root:git-signed-tag")
        if not self.second_factor.valid:
            failing.append("second-factor:hmac-env-secret")
        return tuple(failing)

    def deny_receipt(self) -> dict:
        return {
            "trust_root_mode": TRUST_ROOT_MODE,
            "outcome": self.outcome,
            "stage": self.stage,
            "failing_factors": list(self.failing_factors),
            "reason": self.deny_reason or self.root.reason,
            "root": self.root.to_dict(),
            "second_factor": self.second_factor.to_dict(),
            "record_sha256": self.record_sha256,
            "security_boundary_claimed": False,
        }

    def to_dict(self) -> dict:
        return {
            "trust_root_mode": TRUST_ROOT_MODE,
            "outcome": self.outcome,
            "cell": {"root_valid": self.cell[0], "hmac_valid": self.cell[1]},
            "record_note": self.record_note,
            "stage": self.stage,
            "record_sha256": self.record_sha256,
            "claimed": self.claimed,
            "claim_reason": self.claim_reason,
            "failing_factors": list(self.failing_factors),
            "seams_used": list(self.seams_used),
            "root": self.root.to_dict(),
            "second_factor": self.second_factor.to_dict(),
        }


PREAUTHORIZATION_STAGE = "preauthorization"
SEALED_STAGE = "sealed"

#: The complete set. There is no third stage, and an unrecognised one is not a
#: milder stage -- see :func:`_unknown_stage_decision`.
PROMOTION_STAGES: tuple[str, ...] = (SEALED_STAGE, PREAUTHORIZATION_STAGE)


def _unknown_stage_decision(stage: str, candidate_sha256: str,
                            ) -> PromotionTrustDecision:
    """REJECT for a stage the trust root does not recognise.

    MEASURED (Odysseus probe 2, reproduced): ``stage`` was only ever compared
    with ``== SEALED_STAGE``, so ``'SEALED'``, ``'sealed '`` or a plain typo
    took the *not-sealed* branch -- which SKIPS the single-use claim -- and the
    function still returned ``promote=True, claimed=False``. A misspelling was
    therefore an unlimited-use approval: the strictest path in the module was
    selected by exact string equality against caller-supplied text, and every
    other string failed OPEN.

    Refused BEFORE the root verifier runs. There is no git call, no record and
    no claim, because a stage this module cannot interpret is not a promotion
    to evaluate -- it is a caller bug, and the deny receipt the caller raises
    is where it belongs in the record.
    """
    reason = (
        f"unknown promotion stage {stage!r}: the trust root evaluates only "
        f"{SEALED_STAGE!r} (which spends the approval's single use) and "
        f"{PREAUTHORIZATION_STAGE!r} (which does not). An unrecognised stage "
        "used to take the preauthorization branch and skip the single-use "
        "claim while still promoting, so it is refused here rather than "
        "guessed at.")
    return PromotionTrustDecision(
        promote=False,
        cell=(False, False),
        outcome="REJECT",
        record_note="unknown-promotion-stage",
        root=ApprovalVerdict(
            approved=False,
            reason=reason,
            candidate_sha256=str(candidate_sha256),
            tag=approval_tag_for(str(candidate_sha256))),
        second_factor=SecondFactorOutcome(valid=False, reason=reason),
        stage=stage,
        deny_reason=reason)


def evaluate_promotion_trust(
    *,
    repo_root: str | Path,
    candidate_artifact_sha256: str,
    evidence_packet_sha256: str,
    source_revision: str,
    approval_ledger: Any = None,
    owner_keyring: Mapping[tuple[str, str], bytes | str] | None = None,
    consumed_approval: Any = None,
    stage: str = SEALED_STAGE,
    now: datetime | None = None,
    _root_verifier: Callable[..., ApprovalVerdict] | None = None,
    _second_factor: SecondFactorOutcome | None = None,
    _record_sink: Callable[[Mapping[str, Any]], str] | None = None,
) -> PromotionTrustDecision:
    """THE D5 TRUST ROOT. One decision, read out of the precommitted table.

    Never raises: a promotion boundary that can raise is one a caller can
    accidentally treat as a pass by forgetting a ``try``. The caller branches
    on ``decision.promote`` and on nothing else.

    Order of operations, and why it is this order:

    1. **The root answers first.** ``promote`` is ``root.approved`` and only
       that. The second factor is evaluated afterwards so that no code path
       exists in which an HMAC result was consulted before the verdict.
    2. **Both factors are recorded before the verdict is returned.** If the
       record cannot be written, the decision flips to REJECT regardless of
       what either factor said. Advisory for the verdict, mandatory for the
       record.
    3. **The single-use claim happens only in the sealed stage.** The live path
       calls this twice -- once effect-free before the promotion lock, once
       inside it -- and an approval must be spent exactly once, by the call
       that is about to mutate the repository.

    The three underscore-prefixed parameters are test seams for the truth-table
    suite, which cannot mint a real owner signature. Any decision that used one
    carries it in ``seams_used``, and the production caller refuses such a
    decision outright, so a seam cannot become a promotion.
    """
    stage = str(stage)
    # BEFORE ANYTHING ELSE. The stage selects whether the single use is spent,
    # so an unvalidated stage is an unvalidated promotion. See
    # :func:`_unknown_stage_decision`.
    if stage not in PROMOTION_STAGES:
        return _unknown_stage_decision(stage, candidate_artifact_sha256)
    seams: list[str] = []
    verify = verify_promotion_approval
    if _root_verifier is not None:
        verify = _root_verifier
        seams.append("_root_verifier")

    root = verify(
        repo_root,
        candidate_sha256=str(candidate_artifact_sha256),
        evidence_sha256=str(evidence_packet_sha256),
        source_revision=str(source_revision),
        now=now,
    )

    if _second_factor is not None:
        second = _second_factor
        seams.append("_second_factor")
    else:
        second = evaluate_second_factor(
            approval_ledger=approval_ledger,
            owner_keyring=owner_keyring,
            consumed_approval=consumed_approval,
        )

    cell = (bool(root.approved), bool(second.valid))
    outcome = TRUTH_TABLE[cell]
    record_note = TRUTH_TABLE_RECORD[cell]

    record = {
        "trust_root_mode": TRUST_ROOT_MODE,
        "stage": stage,
        "candidate_artifact_sha256": str(candidate_artifact_sha256),
        "evidence_packet_sha256": str(evidence_packet_sha256),
        "source_revision": str(source_revision),
        "root_valid": cell[0],
        "root_reason": root.reason,
        "root_tag": root.tag,
        "root_signer": root.signer,
        "root_owner_approval_ref": root.owner_approval_ref,
        "hmac_valid": cell[1],
        "hmac_reason": second.reason,
        "hmac_consumption_sha256": second.consumption_sha256,
        "table_outcome": outcome,
        "record_note": record_note,
        "seams_used": sorted(seams),
        "recorded_at": (
            now or datetime.now(timezone.utc)
        ).astimezone(timezone.utc).isoformat(),
    }
    sink = _record_sink
    if sink is not None:
        seams.append("_record_sink")
        record["seams_used"] = sorted(set(record["seams_used"]) | {"_record_sink"})
    record_sha: str | None = None
    record_error: str | None = None
    try:
        record_sha = (
            sink(record) if sink is not None else _append_record(repo_root, record)
        )
    except Exception as exc:                                     # noqa: BLE001
        record_error = (
            "second-factor record could not be written "
            f"({type(exc).__name__}: {exc}); the HMAC factor is advisory for "
            "the verdict but mandatory for the record, so promotion refuses"
        )

    promote = outcome == "PROMOTE" and record_error is None
    deny_reason: str | None = None
    if record_error is not None:
        deny_reason = record_error
    elif not promote:
        deny_reason = (
            "sealed promotion refused by the D5 trust root ("
            + ", ".join(
                f"{name} invalid"
                for name in (
                    ["root:git-signed-tag"] if not cell[0] else []
                ) + (
                    ["second-factor:hmac-env-secret"] if not cell[1] else []
                )
            )
            + f"): {root.reason}"
        )
        if cell[1] and not cell[0]:
            deny_reason += (
                " -- the HMAC second factor authenticated and does not "
                "substitute for the root"
            )

    claimed = False
    claim_reason: str | None = None
    if promote and stage == SEALED_STAGE:
        claimed, claim_reason = claim_approval(repo_root, root)
        if not claimed:
            promote = False
            deny_reason = f"single-use claim refused: {claim_reason}"

    return PromotionTrustDecision(
        promote=promote,
        cell=cell,
        outcome="PROMOTE" if promote else "REJECT",
        record_note=record_note,
        root=root,
        second_factor=second,
        stage=stage,
        record_sha256=record_sha,
        claimed=claimed,
        claim_reason=claim_reason,
        seams_used=tuple(sorted(set(seams))),
        deny_reason=deny_reason,
    )


__all__ = [
    "ALLOWED_SIGNERS_REL",
    "APPROVAL_BODY_SCHEMA",
    "ARTIFACT_BINDING_FIELDS",
    "ApprovalVerdict",
    "MAX_APPROVAL_AGE",
    "CLAIM_LEDGER_NAME",
    "PREAUTHORIZATION_STAGE",
    "PROMOTION_STAGES",
    "PromotionTrustDecision",
    "PromotionTrustRootError",
    "claim_ledger_path",
    "REPLAY_KEY_SPEC",
    "REPLAY_STATE_RETENTION",
    "REVOCATION_AUTHORITY",
    "SEALED_STAGE",
    "SECRET_ENV_PREFIXES",
    "SecondFactorOutcome",
    "TAG_PREFIX",
    "TRUST_ROOT_MODE",
    "TRUTH_TABLE",
    "TRUTH_TABLE_RECORD",
    "approval_tag_for",
    "claim_approval",
    "evaluate_promotion_trust",
    "evaluate_second_factor",
    "replay_key",
    "scrubbed_child_env",
    "second_factor_ledger_path",
    "verify_promotion_approval",
    "voided_by_regeneration",
]
