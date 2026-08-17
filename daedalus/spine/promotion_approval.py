"""Sealed promotion: the owner-approval verifier.

WHAT THIS CLOSES. ``PromotionReceipt`` (``daedalus.schemas``) has always
modelled an authenticated owner decision -- ``promotion_status``,
``owner_approval_ref``, ``approval_assurance`` -- and its own docstring names
the boundary it does not cross: "This schema does not authenticate the owner;
the guarded promotion boundary must resolve and authenticate the approval
locator before any merge/deploy." Nothing resolved it. This module is that
resolver.

THE TRUST ROOT IS THE OWNER'S CHOICE, NOT AN IMPLEMENTER'S. Recorded in
``docs/GATE0_SEALED_OWNER_APPROVAL.md`` (option B, with option A -- a detached
signature over a canonical body -- as the migration): an approval is a
GIT-SIGNED TAG named ``promote/<candidate_sha256>``, verified with
``git verify-tag`` against an allowed-signers file read from the COMMITTED
tree, never from the working copy. Forging one requires the owner's signing
key. The receipt shape is deliberately unchanged, so moving to option A later
changes this module and nothing downstream of it.

WHAT AN APPROVAL IS BOUND TO. Four bindings, each closing a distinct replay:

    tag NAME       -> candidate artifact sha256   (approve A, promote B)
    tag TARGET     -> source revision             (approve on one base, land on another)
    tag BODY       -> evidence packet sha256      (approve on E, promote on weaker E')
    tag BODY       -> expiry + nonce              (a standing authorisation)

The signature binds all four to the owner at once: the body is inside the
signed payload, so editing any line invalidates the tag.

FAIL-CLOSED IS THE WHOLE POINT. Every path in this module that cannot prove an
approval returns a REFUSAL, and an error while verifying is a refusal, not a
pass. There is no exception that escapes ``verify_promotion_approval`` and no
argument that makes it return ``approved=True`` without a signature that
verified. In particular:

  * ``git verify-tag``'s EXIT CODE is the only authority. Its human output is
    not, and this is not a stylistic preference -- it is a measured trap. A
    signature by a key that is NOT in the allowed-signers file still prints
    ``Good "git" signature with ED25519 key SHA256:...`` on stderr and only
    adds ``No principal matched.`` So a check for "Good" in the output accepts
    a signature from any key in the world. Nothing here reads that text for a
    verdict; the principal is captured for the audit trail only, and never
    opens anything.

  * The allowed-signers file is read with ``git show HEAD:<path>`` and handed
    to git as a temporary file OUTSIDE the repository. A working-tree edit
    therefore cannot influence verification at all; changing who may approve a
    promotion means making a commit, which is visible in history.

  * git is invoked with system/global config disabled and with
    ``gpg.ssh.allowedSignersFile``, ``gpg.ssh.program`` and ``gpg.program``
    pinned on the command line, where they outrank repository-local config.
    Otherwise a writable ``.git/config`` could redirect verification at an
    attacker-chosen allowed-signers file or an attacker-chosen "verifier"
    binary that exits 0 unconditionally.

REGENERATION VOIDS AN APPROVAL. ``kairos.gated_writes``' promotion path can
re-run a candidate mid-flight when the base has moved, and the regenerated
artifact is NOT the artifact the owner signed: its diff sha changes, so does
the evidence it was gated on. The owner's decision is the conservative one --
the approval is void and the candidate returns to ``pending-owner``. That
needs no special case here: an approval names one exact candidate sha, so a
regenerated candidate simply has no approval. :func:`voided_by_regeneration`
exists to make the resulting refusal say so in words rather than the generic
"no signed tag" that would otherwise be reported for the same event.

WHAT THIS MODULE IS NOT. It is not a security boundary against an attacker who
already holds the owner's signing key, and it does not claim to be (plan §1).
It is not wired into the promotion callable yet -- ``gated_writes.py`` is a
protected policy artifact, and connecting the two is an owner-approved
amendment, not ordinary work. See ``tests/test_promotion_approval_wiring.py``,
which holds the inventory honest about exactly that gap in both directions.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: First line of the signed tag body. A body that does not open with exactly
#: this is refused before any field is read: an approval must declare which
#: contract it is speaking, or a future format change silently means something
#: different to the verifier than it did to the owner who signed it.
APPROVAL_BODY_SCHEMA = "daedalus-promotion-approval/1"

#: Repository-relative path of the allowed-signers file, read from the
#: COMMITTED tree. Kept out of ``.git/`` on purpose -- it must be reviewable
#: and diffable like any other policy change -- and placed beside the
#: mechanical veto policy, because that is what it is: the list of keys whose
#: signature the promotion boundary will accept. The amendment that wires this
#: module into the promotion callable should add this path to the guard's
#: protected set; until then it is an ordinary tracked file.
ALLOWED_SIGNERS_REL = ".agentenv/promotion_allowed_signers"

TAG_PREFIX = "promote/"

#: Every field the body must carry, and nothing else. An UNKNOWN key is a
#: refusal rather than something to ignore: the owner signed those bytes, so a
#: key this verifier does not understand means the approval asserts something
#: the promotion boundary is not checking.
_REQUIRED_BODY_KEYS = frozenset(
    {"candidate_sha256", "evidence_sha256", "source_revision", "expires_at", "nonce"}
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")
_NONCE_RE = re.compile(r"^[0-9A-Za-z._:/-]{8,200}$")
_SIGNER_RE = re.compile(r'signature for (\S+) with', re.IGNORECASE)

#: Pinned on the command line, where it outranks repository-local config. See
#: the module docstring: without this, a writable ``.git/config`` chooses the
#: allowed-signers file and the program that "verifies" the signature.
_GIT_VERIFY_CONFIG = (
    "gpg.ssh.program=ssh-keygen",
    "gpg.program=gpg",
)


class _Refused(Exception):
    """Internal control flow. Never escapes this module -- every entry point
    converts it to a refusal verdict, because a promotion boundary that can
    raise is a promotion boundary a caller can accidentally treat as a pass by
    forgetting a ``try``."""


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
            "security_boundary_claimed": False,
        }


def approval_tag_for(candidate_sha256: str) -> str:
    return f"{TAG_PREFIX}{candidate_sha256}"


def _hardened_env() -> dict:
    """Same shape as ``kairos.gated_writes._hardened_env`` (independently
    written; that one is private to a protected module this file does not
    own). System and global config are disabled so that ONLY the pinned
    command-line settings and the repository's own config are in play, and the
    pinned settings outrank the latter."""
    env = dict(os.environ)
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
    a commit, which is exactly the reviewable, attributable act the owner's
    decision asks for.
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


def _expiry(value: str, now: datetime) -> str:
    """An approval with no usable expiry is a standing authorisation, which is
    the thing invariant 5 exists to prevent. Unparseable is refused, not
    treated as far-future."""
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise _Refused(f"approval expires_at is not an ISO-8601 instant: {text[:40]!r}") from e
    if parsed.tzinfo is None:
        raise _Refused("approval expires_at must carry an explicit UTC offset")
    if parsed <= now:
        raise _Refused(f"approval expired at {text} (now {now.isoformat()})")
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
            # EXIT CODE ONLY. See the module docstring: the output says
            # `Good "git" signature ...` even for a key that matched no
            # principal, so the text is evidence for humans and never a verdict.
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
        expires_at = _expiry(body["expires_at"], now)

        return ApprovalVerdict(
            approved=True,
            reason=f"owner signature on {tag} verified against committed allowed signers",
            candidate_sha256=str(candidate_sha256),
            tag=tag,
            owner_approval_ref=approval_ref,
            signer=signer,
            expires_at=expires_at,
            nonce=body["nonce"],
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
# single use                                                                   #
# --------------------------------------------------------------------------- #
def _spent_root(repo_root: str | Path) -> Path:
    """Checkout-external, namespaced by checkout identity -- the same placement
    rule as the gated-candidate artifact archive, for the same reason: it must
    not live anywhere a candidate's declared write paths can reach."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path(tempfile.gettempdir())
    digest = hashlib.sha256(
        str(Path(repo_root).resolve()).encode("utf-8")).hexdigest()[:12]
    return base / "daedalus-kernel" / "promotion" / digest / "spent"


def claim_approval(repo_root: str | Path, verdict: ApprovalVerdict,
                   *, spent_root: Path | None = None) -> tuple[bool, str]:
    """Spend a verified approval exactly once. ``(claimed, reason)``.

    An approval that stays valid after it has been used is a standing
    authorisation with extra steps, so the promotion boundary must consume one.
    The claim is an atomic ``O_CREAT | O_EXCL`` file creation keyed by the
    approval's nonce: on both Windows and POSIX exactly one caller can win,
    including two concurrent promotions of the same candidate.

    Fails closed in both directions: an unapproved verdict is never claimable,
    and a filesystem error is a refusal rather than an assumed-fresh approval.
    """
    if not verdict.approved:
        return False, "an unapproved verdict cannot be claimed"
    if not verdict.nonce:
        return False, "approved verdict carries no nonce; refusing to claim"
    root = Path(spent_root) if spent_root is not None else _spent_root(repo_root)
    key = hashlib.sha256(
        f"{verdict.nonce}\n{verdict.candidate_sha256}".encode("utf-8")).hexdigest()
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
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
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
    return True, f"approval {verdict.tag} claimed for a single promotion"


# --------------------------------------------------------------------------- #
# the receipt                                                                  #
# --------------------------------------------------------------------------- #
def promotion_receipt(
    verdict: ApprovalVerdict,
    *,
    promotion_id: str,
    nomination_receipt_sha256: str,
    candidate_artifact_locator: str,
    evidence_packet_sha256: str,
    evidence_locator: str,
    source_revision: str,
    target_revision: str,
    created_at: str,
    origin: str = "spine.promotion_approval",
    extra_reasons: tuple[str, ...] = (),
):
    """Build the ``PromotionReceipt`` for a verdict.

    ``approval_assurance="authenticated"`` is set HERE and only here, from
    ``verdict.approved`` -- never from an argument. A caller cannot ask for an
    approved receipt; it can only present a verdict that a signature produced.
    An unapproved verdict yields ``pending-owner`` with no approval reference,
    which is the shape the schema already enforces.
    """
    from daedalus.schemas import ContractProvenance, PromotionReceipt

    approved = bool(verdict.approved)
    digests = [
        nomination_receipt_sha256,
        verdict.candidate_sha256,
        candidate_artifact_locator.rsplit(":", 1)[-1],
        evidence_packet_sha256,
        evidence_locator.rsplit(":", 1)[-1],
    ]
    if approved and verdict.owner_approval_ref:
        digests.append(verdict.owner_approval_ref.rsplit(":", 1)[-1])

    return PromotionReceipt(
        promotion_id=promotion_id,
        nomination_receipt_sha256=nomination_receipt_sha256,
        candidate_artifact_sha256=verdict.candidate_sha256,
        candidate_artifact_locator=candidate_artifact_locator,
        evidence_packet_sha256=evidence_packet_sha256,
        evidence_locator=evidence_locator,
        source_revision=source_revision,
        target_revision=target_revision,
        promotion_status="approved" if approved else "pending-owner",
        owner_approval_ref=verdict.owner_approval_ref if approved else None,
        approval_assurance="authenticated" if approved else "not-applicable",
        reasons=tuple(sorted({verdict.reason, *extra_reasons})),
        provenance=ContractProvenance(
            origin=origin,
            source_revision=source_revision,
            created_at=created_at,
            input_digests=tuple(digests),
        ),
    )
