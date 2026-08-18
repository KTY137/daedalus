"""Git-signed-tag trust root for the sealed owner approval.

This is the option-B trust root from ``docs/GATE0_SEALED_OWNER_APPROVAL.md``
§4: the owner signs an annotated tag with their own Git signing key, and the
promotion boundary verifies it with ``git verify-tag`` against an allowed
signers list that lives in the repository. It adds no Python dependency and no
second approval vocabulary -- the signed body is checked against the existing
:class:`daedalus.kernel.approvals.ApprovalExpectation`.

Three properties carry the whole design, and each exists because the naive
version of it was measured and failed:

**The signers list is the trust root, so the caller may not choose it.**
Verifying an attacker-signed tag against an attacker-supplied signers file
returns "Good signature" and exit 0. Nothing in this module accepts a signers
path, a signers blob, a keyring or a public key from its caller. The list is
read from one fixed repository path, at a pinned revision, through
``git show`` -- the committed object, never the working-tree file, because a
process that can write the working tree would otherwise be able to name itself
a principal.

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
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from daedalus.kernel.approvals import ApprovalExpectation, _parse_utc
from daedalus.schemas import _identifier, _revision, _sha256
from daedalus.spine.attempt import _git_env as _canonical_git_env

# The trust root. Both are module constants and neither is a parameter of any
# public function in this module: the allowed-signers path is exactly as
# security-critical as the signatures it validates.
OWNER_ALLOWED_SIGNERS_PATH = "configs/owner-allowed-signers"
ALLOWED_SIGNERS_REVISION = "HEAD"

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


def approval_tag_for(candidate_artifact_sha256: str) -> str:
    """The one tag name that can approve a given candidate.

    Deriving the name from the candidate digest means an owner cannot approve
    candidate A under a name the boundary will later resolve for candidate B,
    and a caller cannot point the boundary at some other tag it happens to
    like: the name is a function of the artifact being promoted.
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

    Only additions are permitted on top, and the assertion below enforces it.
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
    # the canonical environment removed, nor change one it set.
    for name, value in baseline.items():
        assert env.get(name) == value, (
            f"the signed-approval git environment weakened {name}: "
            f"canonical {value!r} became {env.get(name)!r}"
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
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SignedApprovalError(f"{label} could not run: {exc}") from exc
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
    return trust_root


def read_committed_allowed_signers(repo_root: str | Path) -> str:
    """The committed signer set, normalised. Thin view over the pinned root."""
    return resolve_trust_root(repo_root).normalised()


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
    allowed_signers = trust_root.normalised()

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

    handle, signers_path = tempfile.mkstemp(prefix="daedalus-allowed-signers-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            # ssh-keygen's allowed-signers parser is line-oriented and a
            # carriage return becomes part of the key blob, so a checkout on a
            # CRLF platform would silently stop matching any principal.
            stream.write(allowed_signers.replace("\r\n", "\n").replace("\r", "\n"))
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
                tag_name,
            ],
            label="verifying the approval tag signature",
            check=False,
        )
    finally:
        try:
            os.unlink(signers_path)
        except OSError:
            pass

    if verified.returncode != 0:
        raise SignedApprovalSignatureError(
            f"{tag_name} is not signed by an allowed owner principal: "
            f"{verified.stderr.strip() or verified.stdout.strip() or 'no principal matched'}"
        )
    principal = _signer_principal(verified.stderr or verified.stdout)

    contents = _git(
        root,
        ["tag", "-l", "--format=%(contents)", tag_name],
        label="reading the approval tag body",
    ).stdout
    body = SignedApprovalBody.from_json(_strip_signature(contents))

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

    # The signed bytes, read as the object Git actually holds, so the digest
    # cited by a receipt is a digest of the material that was verified.
    raw = _git(
        root,
        ["cat-file", "tag", tag_object],
        label="reading the approval tag object",
    )
    approval_ref = _artifact_locator_for(
        hashlib.sha256(raw.stdout.encode("utf-8")).hexdigest()
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

    return VerifiedSignedApproval(
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


def _signer_principal(output: str) -> str:
    for line in output.splitlines():
        if "GOODSIG" in line or "Good " in line:
            return line.strip()
    return "unknown-principal"


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


def _spent_root(repo_root: str | Path) -> Path:
    """Checkout-external, namespaced by checkout identity.

    The single-use ledger must not live anywhere a candidate's declared write
    paths can reach, or the candidate could erase the record of its own
    approval having been spent.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path(tempfile.gettempdir())
    digest = hashlib.sha256(
        str(Path(repo_root).resolve()).encode("utf-8")
    ).hexdigest()[:12]
    return base / "daedalus-kernel" / "promotion" / digest / "spent"


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

    Fails closed in both directions: a filesystem error is a refusal, never an
    assumed-fresh approval.
    """
    if not isinstance(verified, VerifiedSignedApproval):
        return False, "only a verified owner signature can be claimed"
    root = Path(spent_root) if spent_root is not None else _spent_root(repo_root)
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

    The strength of that is bounded by how hard the presented object is to
    obtain, and the honest bound is stated on :class:`VerifiedSignedApproval`:
    its construction token stops accident and casual misuse, not in-process
    code determined to reach into this module. The authentication a reader
    should rely on is the signature check recorded in ``reasons`` and the pins
    recorded in the provenance, which can be re-verified against the
    repository. Passing ``None`` yields ``pending-owner`` with no approval
    reference, which is the shape the schema already enforces.
    """
    from daedalus.schemas import ContractProvenance, PromotionReceipt

    approved = isinstance(verified, VerifiedSignedApproval)
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
    if approved:
        digests.append(verified.owner_approval_ref.rsplit(":", 1)[-1])
        default_reason = (
            f"owner signature on {verified.tag_name} verified against the "
            "committed allowed-signers list"
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
        reasons=tuple(sorted({default_reason, *reasons})),
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
    "promotion_receipt",
    "read_committed_allowed_signers",
    "regeneration_voids_approval",
    "verify_signed_approval",
]
