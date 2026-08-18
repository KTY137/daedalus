"""Fault injection for the git-signed-tag owner approval trust root.

Every test here drives a real repository, a real SSH signing key and a real
``git verify-tag``. Nothing is mocked, because the property under test is
exactly whether Git accepts a signature -- a stubbed verifier would prove
nothing about the trust root.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.approvals import ApprovalExpectation
from daedalus.kernel.signed_approval import (
    APPROVAL_PURPOSE,
    OWNER_ALLOWED_SIGNERS_PATH,
    SignedApprovalBindingMismatch,
    SignedApprovalBody,
    SignedApprovalExpired,
    SignedApprovalPurposeError,
    SignedApprovalMechanismMismatch,
    SignedApprovalRootError,
    SignedApprovalSignatureError,
    approval_tag_for,
    canonical_approval_body,
    claim_signed_approval,
    promotion_receipt,
    read_committed_allowed_signers,
    regeneration_voids_approval,
    resolve_trust_root,
    verify_signed_approval,
)

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("ssh-keygen") is None,
    reason="git and ssh-keygen are required to exercise the signing trust root",
)

NOMINATION = "a" * 64
CANDIDATE = "b" * 64
EVIDENCE = "c" * 64
BASE = "1" * 40
TARGET_HEAD = "2" * 40


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-c", "user.name=probe", "-c", "user.email=owner@daedalus", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    return completed


def _signers_digest(text: str) -> str:
    """The digest exactly as :class:`TrustRoot` computes it."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


REPO_ROOT = Path(__file__).resolve().parents[2]


def _guard():
    """The same chain rules the verifier uses. One implementation, one import."""
    from daedalus.kernel.signed_approval import _iron_plan_guard

    return _iron_plan_guard()


def _real_genesis_record() -> dict:
    """Record 1 of THIS repository's owner-approved ledger, verbatim.

    The fixture cannot invent a genesis: ``AMENDMENT_GENESIS_RECORD_SHA256``
    is pinned in code precisely so that a chain rooted anywhere else is
    refused. Building test ledgers on the real adoption record is what makes
    the fixture exercise the production rule rather than a relaxed one.
    """
    from daedalus.kernel.signed_approval import (
        AMENDMENT_GENESIS_RECORD_SHA256,
        AMENDMENT_LEDGER_PATH,
    )

    text = (REPO_ROOT / AMENDMENT_LEDGER_PATH).read_text(encoding="utf-8")
    genesis = _guard().parse_ledger_text(text, AMENDMENT_LEDGER_PATH)[0]
    assert genesis["record_sha256"] == AMENDMENT_GENESIS_RECORD_SHA256, (
        "the pinned genesis digest no longer matches record 1 of the real "
        "ledger; rotating it is an amendment, not a fixture change"
    )
    return genesis


def _chained_record(previous: dict, **fields) -> dict:
    """An accepted record that chains correctly onto ``previous``."""
    record = {
        "schema": _guard().SCHEMA,
        "plan_id": _guard().PLAN_ID,
        "sequence": previous["sequence"] + 1,
        "status": "accepted",
        "approval_ref": "test-fixture",
        "owner": "repository-owner",
        "previous_record_sha256": previous["record_sha256"],
        "base_plan_sha256": previous["result_plan_sha256"],
        "result_plan_sha256": "d" * 64,
        "base_revision": previous["result_revision"],
        "result_revision": previous["result_revision"] + 1,
    }
    record.update(fields)
    record["record_sha256"] = _guard().canonical_record_sha256(record)
    return record


def _write_ledger(repo: Path, records: list[dict]) -> list[dict]:
    """Write the ledger AND a master plan the head of the chain describes.

    The head record is tied to the plan blob committed beside it, so a fixture
    that writes only a ledger describes a plan that is not there. The plan is
    the real one with its ``Revision:`` header rewritten to the revision the
    chain ends at; the head's ``result_plan_sha256`` is then its digest.
    """
    import re

    from daedalus.kernel.signed_approval import AMENDMENT_LEDGER_PATH

    guard = _guard()
    records = [dict(record) for record in records]
    head = records[-1]

    plan_text = (REPO_ROOT / guard.PLAN_REL).read_text(encoding="utf-8")
    plan_text = re.sub(
        r"(?m)^Revision:\s*\d+\s*$",
        f"Revision: {head['result_revision']}",
        plan_text,
        count=1,
    )
    plan = repo / guard.PLAN_REL
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(plan_text, encoding="utf-8")
    head["result_plan_sha256"] = hashlib.sha256(
        guard.normalized_text(plan_text).encode("utf-8")
    ).hexdigest()
    head["record_sha256"] = guard.canonical_record_sha256(head)

    ledger = repo / AMENDMENT_LEDGER_PATH
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return records


def _pin_signers_in_ledger(repo: Path, signers_text: str) -> str:
    """Write a VALID amendment chain whose last record pins this signer set.

    The previous version of this helper wrote a single record with no
    ``record_sha256``, no ``previous_record_sha256`` and no revision fields,
    and every test in this file asserted that it was accepted. That fixture
    encoded the F3 defect as intended behaviour: it is exactly the shape an
    attacker writes when they change the signers file and its pin in one
    motion, and two forged approvals were executed through it.
    """
    from daedalus.kernel.signed_approval import TRUST_ROOT_DIGEST_FIELD

    digest = _signers_digest(signers_text)
    genesis = _real_genesis_record()
    pin = _chained_record(genesis, **{TRUST_ROOT_DIGEST_FIELD: digest})
    _write_ledger(repo, [genesis, pin])
    return digest


def _expectation(**changes: str) -> ApprovalExpectation:
    body = {
        "operation": "promote-candidate",
        "nomination_receipt_sha256": NOMINATION,
        "candidate_artifact_sha256": CANDIDATE,
        "evidence_packet_sha256": EVIDENCE,
        "base_revision": BASE,
        "target_ref": "experimental",
        "current_target_revision": TARGET_HEAD,
    }
    body.update(changes)
    return ApprovalExpectation(**body)


def _future() -> str:
    return (
        (datetime.now(timezone.utc) + timedelta(hours=2))
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _body_json(mechanism: str, **changes: str) -> str:
    body = {
        "purpose": APPROVAL_PURPOSE,
        "operation": "promote-candidate",
        "approval_mechanism_sha256": mechanism,
        "nomination_receipt_sha256": NOMINATION,
        "candidate_artifact_sha256": CANDIDATE,
        "evidence_packet_sha256": EVIDENCE,
        "base_revision": BASE,
        "target_ref": "experimental",
        "expected_target_revision": TARGET_HEAD,
        "nonce": "nonce-1",
        "expires_at": _future(),
    }
    body.update(changes)
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


@pytest.fixture()
def signing_repo(tmp_path: Path) -> dict[str, object]:
    """A repository whose committed allowed-signers names exactly one owner."""
    repo = tmp_path / "repo"
    repo.mkdir()
    keys = tmp_path / "keys"
    keys.mkdir()

    owner_key = keys / "owner"
    attacker_key = keys / "attacker"
    for path, comment in ((owner_key, "owner@daedalus"), (attacker_key, "evil@x")):
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(path), "-N", "", "-C", comment],
            check=True,
            capture_output=True,
        )

    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    signers = repo / OWNER_ALLOWED_SIGNERS_PATH
    signers.parent.mkdir(parents=True, exist_ok=True)
    signers_text = f"owner@daedalus {owner_key.with_suffix('.pub').read_text().strip()}\n"
    signers.write_text(signers_text, encoding="utf-8")
    # The signer set only counts once an accepted amendment pins its digest.
    _pin_signers_in_ledger(repo, signers_text)
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "seed").returncode == 0

    def sign_tag(tag: str, body: str, *, key: Path | None = None) -> None:
        signing = key or owner_key
        result = _git(
            repo,
            "-c",
            "gpg.format=ssh",
            "-c",
            f"user.signingkey={signing}",
            "tag",
            "-s",
            "-m",
            body,
            tag,
        )
        assert result.returncode == 0, result.stderr

    from daedalus.kernel.signed_approval import resolve_trust_root

    mechanism = resolve_trust_root(repo).digest

    return {
        "repo": repo,
        "mechanism": mechanism,
        "owner_key": owner_key,
        "attacker_key": attacker_key,
        "sign_tag": sign_tag,
    }


def test_owner_signed_tag_verifies_against_the_committed_root(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))

    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    assert verified.tag_name == "owner-approval/promotion-1"
    assert verified.body.candidate_artifact_sha256 == CANDIDATE
    assert len(verified.tag_object_sha1) == 40


def test_foreign_signature_is_refused(signing_repo) -> None:
    """A perfectly valid signature from a key the committed root does not name."""
    repo = signing_repo["repo"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1",
        _body_json(signing_repo["mechanism"]),
        key=signing_repo["attacker_key"],
    )

    with pytest.raises(SignedApprovalSignatureError):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_rogue_worktree_signers_file_grants_nothing(signing_repo) -> None:
    """The measured attack: the trust root is the committed blob, not the file.

    Verifying an attacker-signed tag against an attacker-written signers file
    returns exit 0 from `git verify-tag`. This test proves the verifier never
    reaches that state, because it reads the root from `git show HEAD:...`.
    """
    repo: Path = signing_repo["repo"]
    attacker_key: Path = signing_repo["attacker_key"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1", _body_json(signing_repo["mechanism"]), key=attacker_key
    )

    # The candidate rewrites the checked-out trust root to name its own key.
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(
        f"evil@x {attacker_key.with_suffix('.pub').read_text().strip()}\n",
        encoding="utf-8",
    )

    with pytest.raises(SignedApprovalSignatureError):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_wrong_purpose_cannot_be_replayed_as_an_approval(signing_repo) -> None:
    """A tag the owner really signed, for a different domain."""
    repo = signing_repo["repo"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1", _body_json(signing_repo["mechanism"], purpose="daedalus.release")
    )

    with pytest.raises(SignedApprovalPurposeError):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_tag_outside_the_approval_namespace_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("v1.0.0", _body_json(signing_repo["mechanism"]))

    with pytest.raises(SignedApprovalPurposeError):
        verify_signed_approval(repo, "v1.0.0", expectation=_expectation())


def test_signed_body_naming_another_candidate_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1", _body_json(signing_repo["mechanism"], candidate_artifact_sha256="d" * 64)
    )

    with pytest.raises(SignedApprovalBindingMismatch):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_signed_body_naming_a_moved_target_head_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))

    with pytest.raises(SignedApprovalBindingMismatch):
        verify_signed_approval(
            repo,
            "owner-approval/promotion-1",
            expectation=_expectation(current_target_revision="9" * 40),
        )


def test_lightweight_tag_carries_no_signature(signing_repo) -> None:
    """Refused for being the wrong kind of object, before any signature check.

    ``git verify-tag`` also rejects a lightweight tag, so this asserts the
    *reason*: without the annotated-tag guard the refusal still happens but
    arrives from the signature check, and the diagnostic stops telling the
    owner what is actually wrong with their tag.
    """
    repo: Path = signing_repo["repo"]
    assert _git(repo, "tag", "owner-approval/promotion-1").returncode == 0

    with pytest.raises(
        SignedApprovalSignatureError, match="not an annotated tag object"
    ):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_unsigned_annotated_tag_is_refused(signing_repo) -> None:
    repo: Path = signing_repo["repo"]
    assert _git(
        repo, "tag", "-a", "-m", _body_json(signing_repo["mechanism"]), "owner-approval/promotion-1"
    ).returncode == 0

    with pytest.raises(SignedApprovalSignatureError):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_expired_approval_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))

    with pytest.raises(SignedApprovalExpired):
        verify_signed_approval(
            repo,
            "owner-approval/promotion-1",
            expectation=_expectation(),
            now=datetime.now(timezone.utc) + timedelta(days=2),
        )


def test_missing_committed_root_refuses(tmp_path: Path) -> None:
    repo = tmp_path / "bare"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    (repo / "seed.txt").write_text("x", encoding="utf-8")
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "seed").returncode == 0

    with pytest.raises(SignedApprovalRootError):
        read_committed_allowed_signers(repo)


def test_committed_root_without_principals_refuses(tmp_path: Path) -> None:
    """The shipped default: comments only, so promotion stays refused."""
    repo = tmp_path / "commented"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    signers = repo / OWNER_ALLOWED_SIGNERS_PATH
    signers.parent.mkdir(parents=True, exist_ok=True)
    signers.write_text("# no principals yet\n\n", encoding="utf-8")
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "seed").returncode == 0

    # Named, not merely typed: this repository ALSO has no amendment ledger,
    # so an untyped `raises` still passed with the principals check deleted.
    # The mutation campaign found that; the assertion now says which refusal.
    with pytest.raises(SignedApprovalRootError, match="names no owner principal"):
        read_committed_allowed_signers(repo)


def test_the_shipped_trust_root_names_nobody_the_owner_did_not_approve() -> None:
    """The real committed file must not name a principal nobody reviewed.

    This used to assert the file is EMPTY, which made it fail the moment the
    owner did the intended thing and committed their key -- measured on a
    throwaway copy 2026-08-18, where it rolled the amendment kit back. The
    property that is true before AND after the owner's key lands is the one
    asserted here: any principal in the shipped file is exactly the set an
    accepted amendment approved.
    """
    from daedalus.kernel.signed_approval import (
        AMENDMENT_LEDGER_PATH,
        TRUST_ROOT_DIGEST_FIELD,
    )

    here = Path(__file__).resolve().parents[2]
    shipped = here / OWNER_ALLOWED_SIGNERS_PATH
    assert shipped.exists()
    text = shipped.read_text(encoding="utf-8")
    named = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not named:
        return  # nothing approved yet: the state this repository ships in

    pinned = [
        record.get(TRUST_ROOT_DIGEST_FIELD)
        for line in (here / AMENDMENT_LEDGER_PATH).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
        for record in [json.loads(line)]
        if record.get("status") == "accepted" and record.get(TRUST_ROOT_DIGEST_FIELD)
    ]
    assert pinned, (
        "the shipped allowed-signers names a principal, but no accepted "
        "amendment approves any signer set"
    )
    assert pinned[-1] == _signers_digest(text), (
        "the shipped allowed-signers is not the set the amendment chain pins"
    )


def test_caller_cannot_supply_the_trust_root() -> None:
    """Structural: no public entry point accepts a signers path or a keyring."""
    for function in (verify_signed_approval, read_committed_allowed_signers):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {
            "keyring",
            "owner_keyring",
            "allowed_signers",
            "allowed_signers_file",
            "signers_path",
            "public_key",
            "trust_root",
        }, f"{function.__name__} lets its caller choose the trust root"


def test_verifier_never_inherits_signing_capability() -> None:
    import daedalus.kernel.signed_approval as module

    source = inspect.getsource(module)
    assert '"tag", "-s"' not in source
    assert "'tag', '-s'" not in source
    assert "-c user.signingkey" not in source
    assert "user.signingkey" not in source


def _subprocess_argv_literals(source: str) -> list[list[str]]:
    """Every literal argv this module hands to subprocess.

    Read from the AST rather than the text, because the tool legitimately
    *prints* the string ``user.signingkey=<YOUR KEY>`` for the owner to copy.
    What matters is what it executes, not what it displays.
    """
    tree = ast.parse(source)
    argvs: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "run":
            continue
        first = node.args[0]
        if isinstance(first, (ast.List, ast.Tuple)):
            argvs.append(
                [
                    element.value
                    for element in first.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
            )
    return argvs


def test_owner_tool_executes_no_signing_command() -> None:
    """The tool prints what to sign; it must never be able to sign it.

    This used to require the tool to run at least one git command, because it
    spawned git itself. Since F6 it runs NONE -- every repository read goes
    through the kernel's scrubbed choke point -- so the premise was inverted:
    the tool must hold no signing capability in any form, spawned or not.
    """
    tool = (
        Path(__file__).resolve().parents[2] / "scripts" / "owner_approval_request.py"
    )
    source = tool.read_text(encoding="utf-8")

    for argv in _subprocess_argv_literals(source):
        assert "-s" not in argv, f"owner tool creates a signature: {argv}"
        assert not any(
            argument.startswith("user.signingkey") for argument in argv
        ), f"owner tool passes a signing key: {argv}"
        if "tag" in argv:
            assert "-l" in argv, f"owner tool uses tag for more than reading: {argv}"

    # Signing verbs must not appear as executable literals at all. They remain
    # legal inside the printed instructions the OWNER runs in their own shell,
    # which is the whole point of the split, so only call arguments are scanned.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and argument.value == "tag -s":
                    raise AssertionError("owner tool invokes a signing command")


def test_verifier_executes_no_signing_command() -> None:
    import daedalus.kernel.signed_approval as module

    for argv in _subprocess_argv_literals(inspect.getsource(module)):
        assert "-s" not in argv
        assert not any(
            argument.startswith("user.signingkey") for argument in argv
        )


def test_owner_flow_end_to_end(signing_repo) -> None:
    """The documented loop: build a body, sign exactly it, verify it."""
    repo = signing_repo["repo"]
    expectation = _expectation()
    body = canonical_approval_body(
        expectation=expectation,
        nonce="nonce-e2e",
        expires_at=_future(),
        approval_mechanism_sha256=signing_repo["mechanism"],
    )

    # The owner pastes precisely the bytes the tool printed.
    signing_repo["sign_tag"](
        "owner-approval/e2e", body.canonical_bytes().decode("utf-8")
    )

    verified = verify_signed_approval(
        repo, "owner-approval/e2e", expectation=expectation
    )
    assert verified.body == body
    assert (
        verified.body_sha256
        == hashlib.sha256(body.canonical_bytes()).hexdigest()
    )


def test_a_retyped_body_is_a_different_body(signing_repo) -> None:
    """Pretty-printing the body breaks it, exactly as the HOWTO warns."""
    repo = signing_repo["repo"]
    body = canonical_approval_body(
        expectation=_expectation(),
        nonce="nonce-1",
        expires_at=_future(),
        approval_mechanism_sha256=signing_repo["mechanism"],
    )
    retyped = json.dumps(body.to_dict(), indent=2, sort_keys=True)
    signing_repo["sign_tag"]("owner-approval/retyped", retyped)

    with pytest.raises(SignedApprovalBindingMismatch):
        verify_signed_approval(
            repo, "owner-approval/retyped", expectation=_expectation()
        )


def test_approval_ref_is_the_digest_of_the_verified_tag_object(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))

    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    raw = subprocess.run(
        ["git", "cat-file", "tag", verified.tag_object_sha1],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert verified.owner_approval_ref == (
        "artifact-locator:sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
    )


def test_approval_tag_name_is_a_function_of_the_candidate() -> None:
    assert approval_tag_for(CANDIDATE) == f"owner-approval/{CANDIDATE}"
    assert approval_tag_for(CANDIDATE) != approval_tag_for("d" * 64)


def test_an_approval_can_be_spent_only_once(signing_repo, tmp_path) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))
    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )
    spent = tmp_path / "spent"

    first, first_reason = claim_signed_approval(repo, verified, spent_root=spent)
    second, second_reason = claim_signed_approval(repo, verified, spent_root=spent)

    assert first is True, first_reason
    assert second is False
    assert "already spent" in second_reason


def test_a_broken_single_use_ledger_refuses_rather_than_assumes_fresh(
    signing_repo, tmp_path
) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))
    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    claimed, reason = claim_signed_approval(
        repo, verified, spent_root=blocker / "spent"
    )

    assert claimed is False
    assert "ledger unavailable" in reason


def test_regeneration_voids_the_approval_and_says_why() -> None:
    reason = regeneration_voids_approval(CANDIDATE, "d" * 64)

    assert "void" in reason
    assert "pending-owner" in reason
    assert CANDIDATE[:12] in reason


def test_receipt_is_authenticated_only_from_a_verified_signature(
    signing_repo,
) -> None:
    """The first production construction of the canonical PromotionReceipt."""
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))
    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    receipt = promotion_receipt(
        verified,
        promotion_id="promotion-1",
        nomination_receipt_sha256=NOMINATION,
        candidate_artifact_sha256=CANDIDATE,
        candidate_artifact_locator=f"artifact-locator:sha256:{CANDIDATE}",
        evidence_packet_sha256=EVIDENCE,
        evidence_locator=f"artifact-locator:sha256:{EVIDENCE}",
        source_revision=BASE,
        target_revision=TARGET_HEAD,
        created_at="2026-08-18T12:00:00Z",
    )

    assert receipt.promotion_status == "approved"
    assert receipt.approval_assurance == "authenticated"
    assert receipt.owner_approval_ref == verified.owner_approval_ref
    assert receipt.CONTRACT_TYPE == "daedalus.promotion"


def test_receipt_without_a_signature_cannot_claim_authentication() -> None:
    receipt = promotion_receipt(
        None,
        promotion_id="promotion-1",
        nomination_receipt_sha256=NOMINATION,
        candidate_artifact_sha256=CANDIDATE,
        candidate_artifact_locator=f"artifact-locator:sha256:{CANDIDATE}",
        evidence_packet_sha256=EVIDENCE,
        evidence_locator=f"artifact-locator:sha256:{EVIDENCE}",
        source_revision=BASE,
        target_revision=TARGET_HEAD,
        created_at="2026-08-18T12:00:00Z",
    )

    assert receipt.promotion_status == "pending-owner"
    assert receipt.approval_assurance == "not-applicable"
    assert receipt.owner_approval_ref is None


def test_receipt_takes_no_status_or_assurance_argument() -> None:
    """Structural: a caller cannot ask for a stronger claim than it holds."""
    parameters = set(inspect.signature(promotion_receipt).parameters)

    assert not parameters & {
        "promotion_status",
        "approval_assurance",
        "approved",
        "authenticated",
    }


def test_receipt_refuses_a_signature_for_another_candidate(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))
    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    with pytest.raises(SignedApprovalBindingMismatch):
        promotion_receipt(
            verified,
            promotion_id="promotion-1",
            nomination_receipt_sha256=NOMINATION,
            candidate_artifact_sha256="d" * 64,
            candidate_artifact_locator=f"artifact-locator:sha256:{'d' * 64}",
            evidence_packet_sha256=EVIDENCE,
            evidence_locator=f"artifact-locator:sha256:{EVIDENCE}",
            source_revision=BASE,
            target_revision=TARGET_HEAD,
            created_at="2026-08-18T12:00:00Z",
        )


def test_a_commit_alone_cannot_rotate_the_trust_root(signing_repo) -> None:
    """F2: the pin DESCRIBED the root instead of BINDING it.

    ALLOWED_SIGNERS_REVISION is "HEAD", so one commit writing a new
    allowed-signers file simply WAS the new trust root, and commit_oid/blob_oid
    -- being outputs of resolution rather than inputs to it -- reported the
    attacker's own OIDs back as if they were evidence. The expected digest now
    comes from the amendment chain, so an unamended rotation is refused.
    """
    repo: Path = signing_repo["repo"]
    owner_key: Path = signing_repo["owner_key"]
    attacker_key: Path = signing_repo["attacker_key"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1", _body_json(signing_repo["mechanism"])
    )

    # A single commit adds a second principal. No amendment accompanies it.
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(
        f"owner@daedalus {owner_key.with_suffix('.pub').read_text().strip()}\n"
        f"evil@x {attacker_key.with_suffix('.pub').read_text().strip()}\n",
        encoding="utf-8",
    )
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "rotate signers").returncode == 0

    with pytest.raises(SignedApprovalRootError, match="amendment"):
        resolve_trust_root(repo)

    # And the attacker cannot use their newly self-granted principal either.
    attacker_tag = "owner-approval/attacker-self-granted"
    assert _git(
        repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={attacker_key}",
        "tag", "-s", "-m", _body_json(signing_repo["mechanism"]), attacker_tag,
    ).returncode == 0
    with pytest.raises(SignedApprovalRootError):
        verify_signed_approval(repo, attacker_tag, expectation=_expectation())


def test_an_amended_rotation_works_and_voids_old_approvals(signing_repo) -> None:
    """Rotation is allowed -- through an amendment -- and does not carry approvals."""
    repo: Path = signing_repo["repo"]
    owner_key: Path = signing_repo["owner_key"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1", _body_json(signing_repo["mechanism"])
    )

    # A second owner key joins, and an accepted amendment pins the new set.
    second = owner_key.parent / "owner2"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(second), "-N", "",
         "-C", "owner2@daedalus"],
        check=True, capture_output=True,
    )
    rotated = (
        f"owner@daedalus {owner_key.with_suffix('.pub').read_text().strip()}\n"
        f"owner2@daedalus {second.with_suffix('.pub').read_text().strip()}\n"
    )
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rotated, encoding="utf-8")
    _pin_signers_in_ledger(repo, rotated)
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "amend signers").returncode == 0

    # The rotation is accepted...
    assert resolve_trust_root(repo).digest == _signers_digest(rotated)
    # ...and the approval signed under the OLD generation does not survive it.
    with pytest.raises(SignedApprovalMechanismMismatch):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_a_repository_with_no_amendment_pin_refuses(signing_repo) -> None:
    """F3 fail-closed: no approved signer set means no promotion."""
    from daedalus.kernel.signed_approval import AMENDMENT_LEDGER_PATH

    repo: Path = signing_repo["repo"]
    (repo / AMENDMENT_LEDGER_PATH).unlink()
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "drop the ledger").returncode == 0

    with pytest.raises(SignedApprovalRootError, match="no amendment|no committed"):
        resolve_trust_root(repo)


def test_a_ledger_that_pins_nothing_refuses(signing_repo) -> None:
    """A VALID amendment chain that declares no signer set authorises nothing.

    The chain here verifies end to end -- real genesis, correct link, correct
    ``record_sha256`` -- so the refusal can only come from the absence of the
    declared digest. Before, this test wrote a chainless record and was
    satisfied by the same message, which meant it never distinguished "the
    chain says nothing about signers" from "there is no chain".
    """
    repo: Path = signing_repo["repo"]
    genesis = _real_genesis_record()
    _write_ledger(repo, [genesis, _chained_record(genesis)])
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "ledger without a pin").returncode == 0

    with pytest.raises(SignedApprovalRootError, match="no accepted amendment"):
        resolve_trust_root(repo)


def test_a_pin_in_an_unaccepted_record_does_not_count(signing_repo) -> None:
    """Only ACCEPTED amendments move the trust root."""
    from daedalus.kernel.signed_approval import TRUST_ROOT_DIGEST_FIELD

    repo: Path = signing_repo["repo"]
    attacker_key: Path = signing_repo["attacker_key"]
    rogue = f"evil@x {attacker_key.with_suffix('.pub').read_text().strip()}\n"
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rogue, encoding="utf-8")
    # Everything about this record is correct except its status: it chains
    # onto the real genesis and its own digest is right, so the refusal is
    # about acceptance and nothing else.
    genesis = _real_genesis_record()
    proposal = _chained_record(
        genesis, status="proposed", **{TRUST_ROOT_DIGEST_FIELD: _signers_digest(rogue)}
    )
    _write_ledger(repo, [genesis, proposal])
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "propose a rotation").returncode == 0

    with pytest.raises(SignedApprovalRootError, match="status must be accepted"):
        resolve_trust_root(repo)


def test_the_shipped_repository_resolves_only_an_amended_trust_root() -> None:
    """Before the kit runs this refuses; after it runs it must agree with the chain.

    Asserting only "it refuses" would fail the moment the owner legitimately
    lands amendment 007, so the assertion follows the state instead of freezing
    it.
    """
    here = Path(__file__).resolve().parents[2]
    try:
        trust_root = resolve_trust_root(here)
    except SignedApprovalRootError:
        return  # no approved signer set yet: promotion stays refused
    from daedalus.kernel.signed_approval import _amendment_pinned_signers_digest

    assert trust_root.digest == _amendment_pinned_signers_digest(
        here, trust_root.commit_oid
    )


def test_trust_root_pins_commit_and_blob_independently(signing_repo) -> None:
    repo = signing_repo["repo"]
    root = resolve_trust_root(repo)

    assert len(root.commit_oid) == 40
    assert len(root.blob_oid) == 40
    assert root.commit_oid != root.blob_oid
    assert len(root.principals()) == 1
    assert root.digest == hashlib.sha256(
        root.normalised().encode("utf-8")
    ).hexdigest()


def test_verification_reports_the_pins_it_used(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))
    root = resolve_trust_root(repo)

    verified = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    assert verified.trust_root_commit_oid == root.commit_oid
    assert verified.trust_root_blob_oid == root.blob_oid
    assert len(verified.tag_target_oid) == 40
    # The signed tag object and what it points at are different objects.
    assert verified.tag_target_oid != verified.tag_object_sha1


def test_moving_the_tag_name_changes_the_pinned_object(signing_repo) -> None:
    """A tag name is mutable; the pins are what an approval is anchored to."""
    repo: Path = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))
    first = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    (repo / "moved.txt").write_text("moved", encoding="utf-8")
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "move").returncode == 0
    assert _git(repo, "tag", "-d", "owner-approval/promotion-1").returncode == 0
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json(signing_repo["mechanism"]))

    second = verify_signed_approval(
        repo, "owner-approval/promotion-1", expectation=_expectation()
    )

    assert second.tag_object_sha1 != first.tag_object_sha1
    assert second.tag_target_oid != first.tag_target_oid
    assert second.owner_approval_ref != first.owner_approval_ref


def test_lazy_fetch_is_disabled_for_every_git_call() -> None:
    import daedalus.kernel.signed_approval as module

    env = module._git_env()
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    for scrubbed in ("GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND"):
        assert scrubbed not in env
    # NOT "GIT_CONFIG_GLOBAL not in env". Popping it restores the real
    # ~/.gitconfig; the canonical environment points it at os.devnull, which is
    # what actually removes the per-user config from the lookup. The previous
    # assertion here asserted the weaker of the two behaviours.
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull


def test_the_git_environment_is_the_canonical_one_not_a_second_copy() -> None:
    """F1: two answers to "what is a safe git environment" is one too many.

    The spine's ``_git_env`` is the canonical answer and carries its own proof
    suite. This module may add to it and may never weaken it.
    """
    import daedalus.kernel.signed_approval as module
    from daedalus.spine.attempt import _git_env as canonical

    base = canonical()
    env = module._git_env()
    for name, value in base.items():
        assert env.get(name) == value, f"{name} was weakened to {env.get(name)!r}"
    for leaky in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                  "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "GIT_PROXY_COMMAND",
                  "GIT_CONFIG", "GIT_CONFIG_COUNT"):
        assert leaky not in env, f"{leaky} survives into the verifier"


def test_an_inherited_GIT_DIR_cannot_redirect_the_verifier(
    signing_repo: dict[str, object], tmp_path: Path, monkeypatch
) -> None:
    """Cerberus' F1 attack, rebuilt: a foreign object store answers everything.

    With ``GIT_DIR`` inherited from the environment, every git call this module
    makes -- rev-parse, the signers blob, cat-file, verify-tag -- resolves
    inside the attacker's repository instead of the one being promoted. All the
    pins then agree with each other, because they all came from the same
    foreign store, and the result is "Good signature", exit 0, authenticated.
    """
    repo = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    trust_root = resolve_trust_root(repo)
    tag = approval_tag_for(CANDIDATE)
    sign_tag(tag, _body_json(trust_root.digest))

    # A wholly separate repository the caller controls.
    rogue = tmp_path / "rogue"
    rogue.mkdir()
    assert _git(rogue, "init", "-q", "-b", "main").returncode == 0

    monkeypatch.setenv("GIT_DIR", str(rogue / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(rogue))

    # The honest repository still verifies: the hostile variables are dropped.
    verified = verify_signed_approval(repo, tag, expectation=_expectation())
    assert verified.trust_root_commit_oid == trust_root.commit_oid
    assert verified.trust_root_blob_oid == trust_root.blob_oid


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_a_substituted_ssh_verifier_cannot_forge_a_good_signature(
    signing_repo: dict[str, object], tmp_path: Path
) -> None:
    """F1b, MEASURED: gpg.ssh.program in the repo's own config forges a pass.

    Probe 2026-08-18, git 2.38.1.windows.1: an attacker-signed tag verified
    with exit 0 when gpg.ssh.program pointed at a wrapper that rewrote the
    allowed-signers path to one naming the attacker. GIT_CONFIG_NOSYSTEM and
    GIT_CONFIG_GLOBAL=devnull do NOT close the repository-local config -- only
    the command-line pin does. So this is driven through the real product path
    rather than asserted against its source text.
    """
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    attacker_key: Path = signing_repo["attacker_key"]  # type: ignore[assignment]
    trust_root = resolve_trust_root(repo)
    tag = approval_tag_for(CANDIDATE)

    # A tag signed by a key the committed root does not name.
    assert _git(
        repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={attacker_key}",
        "tag", "-s", "-m", _body_json(trust_root.digest), tag,
    ).returncode == 0

    rogue_signers = tmp_path / "rogue-allowed-signers"
    rogue_signers.write_text(
        f"owner@daedalus {attacker_key.with_suffix('.pub').read_text().strip()}\n",
        encoding="utf-8",
    )
    swap = tmp_path / "swap.sh"
    swap.write_text(
        "#!/bin/sh\n"
        'new=""\nskip=0\nfor a in "$@"; do\n'
        '  if [ "$skip" = "1" ]; then skip=0; continue; fi\n'
        '  if [ "$a" = "-f" ]; then\n'
        f'    new="$new -f {rogue_signers.as_posix()}"\n'
        "    skip=1\n    continue\n  fi\n"
        '  new="$new $a"\ndone\nexec ssh-keygen $new\n',
        encoding="utf-8",
        newline="\n",
    )
    os.chmod(swap, 0o755)

    # The vector: the repository's OWN config, which no env var removes.
    assert _git(repo, "config", "gpg.ssh.program", swap.as_posix()).returncode == 0

    with pytest.raises(SignedApprovalSignatureError):
        verify_signed_approval(repo, tag, expectation=_expectation())


# --- F8: the mutable tag NAME must not be re-resolved after the signature ---


def test_moving_the_ref_mid_verification_cannot_swap_the_body(
    signing_repo: dict[str, object], monkeypatch
) -> None:
    """F8, raced for real: tag A's signature must never pair with tag B's body.

    The ref is re-pointed at a DIFFERENT signed tag in the window between the
    signature check and the body read. If any step still resolves the name, the
    body that comes back is the other tag's and names another candidate.
    """
    import daedalus.kernel.signed_approval as module

    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]

    tag = "owner-approval/raced"
    sign_tag(tag, _body_json(mechanism))

    # A second, equally well-signed tag approving a DIFFERENT candidate.
    other = "owner-approval/decoy"
    sign_tag(other, _body_json(mechanism, candidate_artifact_sha256="9" * 64))
    decoy_oid = _git(repo, "rev-parse", "--verify", f"refs/tags/{other}^{{tag}}").stdout.strip()
    assert decoy_oid

    real_git = module._git
    swapped = {"done": False}

    def racing_git(root, args, **kwargs):
        result = real_git(root, args, **kwargs)
        # The instant the signature has been checked, move the name.
        if not swapped["done"] and "verify-tag" in args:
            swapped["done"] = True
            assert _git(repo, "update-ref", f"refs/tags/{tag}", decoy_oid).returncode == 0
        return result

    monkeypatch.setattr(module, "_git", racing_git)

    verified = verify_signed_approval(repo, tag, expectation=_expectation())

    assert swapped["done"], "the race never fired; the test proved nothing"
    # The body came from the pinned object, not from the moved name.
    assert verified.body.candidate_artifact_sha256 == CANDIDATE
    assert verified.tag_object_sha1 != decoy_oid


def test_the_body_is_never_read_through_the_tag_name() -> None:
    """The structural companion to the race: no `git tag -l` body read."""
    import daedalus.kernel.signed_approval as module

    source = inspect.getsource(module.verify_signed_approval)
    assert "--format=%(contents)" not in source, (
        "the body is being read through the mutable ref again"
    )


# --- F7: the signer principal is an identity, not a log line ----------------


def test_the_signer_principal_is_parsed_not_echoed() -> None:
    import daedalus.kernel.signed_approval as module

    good = 'Good "git" signature for owner@daedalus with ED25519 key SHA256:abc\n'
    assert module._signer_principal(good) == "owner@daedalus"
    # The principal-less form names nobody, and must not be reported as one.
    assert module._signer_principal(
        'Good "git" signature with ED25519 key SHA256:abc\n'
    ) == ""
    assert module._signer_principal("something else entirely") == ""


def test_a_signature_git_cannot_attribute_is_refused(
    signing_repo: dict[str, object], monkeypatch
) -> None:
    """Verification used to succeed while recording "unknown-principal"."""
    import daedalus.kernel.signed_approval as module

    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    tag = "owner-approval/anonymous"
    sign_tag(tag, _body_json(mechanism))

    monkeypatch.setattr(module, "_signer_principal", lambda output: "")
    with pytest.raises(SignedApprovalSignatureError, match="no principal"):
        verify_signed_approval(repo, tag, expectation=_expectation())


def test_a_real_verification_records_a_bare_principal(
    signing_repo: dict[str, object]
) -> None:
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    tag = "owner-approval/named"
    sign_tag(tag, _body_json(mechanism))

    verified = verify_signed_approval(repo, tag, expectation=_expectation())
    assert verified.signer_principal == "owner@daedalus"
    assert "Good " not in verified.signer_principal


# --- F5: the receipt must say WHICH list and WHOSE signature ----------------


def test_an_authenticated_receipt_names_the_signer_and_the_trust_root(
    signing_repo: dict[str, object]
) -> None:
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    tag = approval_tag_for(CANDIDATE)
    sign_tag(tag, _body_json(mechanism))

    verified = verify_signed_approval(repo, tag, expectation=_expectation())
    receipt = promotion_receipt(
        verified,
        promotion_id="promotion-1",
        nomination_receipt_sha256=NOMINATION,
        candidate_artifact_sha256=CANDIDATE,
        candidate_artifact_locator="artifact-locator:sha256:" + CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        evidence_locator="artifact-locator:sha256:" + EVIDENCE,
        source_revision=BASE,
        target_revision=TARGET_HEAD,
        created_at="2026-01-01T00:00:00Z",
    )
    blob = "\n".join(receipt.reasons)
    assert verified.trust_root_commit_oid in blob, "receipt does not say which commit"
    assert verified.trust_root_blob_oid in blob, "receipt does not say which list"
    assert verified.signer_principal in blob, "receipt does not say whose signature"
    # The signer-set generation is a sha256, so it is a first-class input.
    assert mechanism in receipt.provenance.input_digests


# --- F9: a docstring must not credit a check that does not run --------------


def test_the_tag_name_helper_does_not_claim_to_bind() -> None:
    """`verify_signed_approval` checks the namespace prefix, not this name."""
    import daedalus.kernel.signed_approval as module

    doc = module.approval_tag_for.__doc__ or ""
    assert "a caller cannot point the boundary at some other tag" not in doc
    assert "not a check" in doc or "NAMING CONVENTION" in doc

    # And the claim really is unenforced, which is why the text had to change.
    source = inspect.getsource(module.verify_signed_approval)
    assert "approval_tag_for(" not in source


def test_the_ledger_comment_credits_only_checks_that_actually_run() -> None:
    """N4: the third docstring in this module to outrun its own code.

    The note above ``AMENDMENT_LEDGER_PATH`` used to say the ledger is
    "hash-chained, each record commits to the previous one ... the one link an
    attacker holding commit rights cannot quietly mutate along with everything
    else" -- while the module read the file and verified no chain field
    whatsoever. Same class as F7 and F9, and it was the load-bearing claim of
    the commit that introduced it.

    This test holds both halves: the chain fields really are read, and the
    claim is bounded to what that buys.
    """
    import daedalus.kernel.signed_approval as module

    source = inspect.getsource(module._verify_amendment_chain)
    for field_name in (
        "previous_record_sha256",
        "record_sha256",
        "canonical_record_sha256",
        "AMENDMENT_GENESIS_RECORD_SHA256",
    ):
        assert field_name in source, (
            f"the chain walk no longer reads {field_name}; the comment above "
            "AMENDMENT_LEDGER_PATH would then be crediting a check that does "
            "not run"
        )

    # The plan binding is what makes a WELL-FORMED appended record fail, and
    # it too must actually run.
    plan_source = inspect.getsource(module._verify_ledger_head_matches_plan)
    assert "result_plan_sha256" in plan_source
    assert "parse_plan_header" in plan_source

    module_source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
    # Comments are wrapped and prefixed, so compare on collapsed prose.
    collapsed = " ".join(module_source.replace("#", " ").split())
    for phrase in (
        "tamper-EVIDENT, not tamper-PROOF",
        "recomputes the ENTIRE chain",
        "anchor held out of band",
        "rewrite history and the plan",
    ):
        assert phrase in collapsed, f"the honest bound no longer states: {phrase!r}"
    # The overclaim itself must not come back.
    assert "cannot quietly mutate along with everything else" not in collapsed


# --- O1: single use belongs to the approval, not to the directory -----------


def _verified(signing_repo: dict[str, object], tag: str = "owner-approval/spend"):
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    sign_tag(tag, _body_json(mechanism))
    return repo, verify_signed_approval(repo, tag, expectation=_expectation())


def test_an_approval_cannot_be_spent_once_per_worktree(
    signing_repo: dict[str, object], tmp_path: Path, monkeypatch
) -> None:
    """O1, executed by Odysseus: the ledger was keyed on the checkout PATH.

    The same signed approval was claimed again from a second worktree path and
    both calls returned "claimed". This repository is worked through worktrees
    as a matter of course, so this was reachable without an attacker.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    repo, verified = _verified(signing_repo)

    claimed_once, _ = claim_signed_approval(repo, verified)
    assert claimed_once is True

    # A second checkout of the same repository -- a different path entirely.
    other_worktree = tmp_path / "another-worktree"
    other_worktree.mkdir()
    claimed_twice, reason = claim_signed_approval(other_worktree, verified)

    assert claimed_twice is False, "the approval was spent a second time"
    assert "already spent" in reason


def test_the_ledger_location_does_not_depend_on_the_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    import daedalus.kernel.signed_approval as module

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    assert inspect.signature(module._spent_root).parameters == {}
    root = module._spent_root()
    assert root.is_absolute()
    # Outside any checkout: a candidate's write roots must not reach it.
    assert str(tmp_path / "state") in str(root)


# --- O2: Odysseus' forged receipt, rebuilt so it cannot come back -----------


def test_odysseus_forged_approval_cannot_produce_an_approved_receipt() -> None:
    """The exact forgery Odysseus executed before the construction token.

    It produced promotion_status="approved", approval_assurance="authenticated"
    and signer_principal="TOTALLY FORGED" without any signature existing.
    """
    from daedalus.kernel.signed_approval import VerifiedSignedApproval

    body = canonical_approval_body(
        expectation=_expectation(),
        nonce="nonce-1",
        expires_at=_future(),
        approval_mechanism_sha256="e" * 64,
    )
    with pytest.raises(SignedApprovalSignatureError):
        VerifiedSignedApproval(
            tag_name="owner-approval/forged",
            tag_object_sha1="0" * 40,
            tag_target_oid="1" * 40,
            signer_principal="TOTALLY FORGED",
            body=body,
            owner_approval_ref="artifact-locator:sha256:" + "f" * 64,
            trust_root_commit_oid="2" * 40,
            trust_root_blob_oid="3" * 40,
        )


# --- O3: guards that shipped without a test --------------------------------


@pytest.mark.parametrize(
    "field, replacement",
    [
        ("evidence_packet_sha256", "9" * 64),
        ("nomination_receipt_sha256", "8" * 64),
        ("candidate_artifact_sha256", "7" * 64),
        ("base_revision", "9" * 40),
        ("expected_target_revision", "8" * 40),
        ("target_ref", "some-other-branch"),
    ],
)
def test_every_bound_field_is_actually_compared(
    signing_repo: dict[str, object], field: str, replacement: str
) -> None:
    """O3(a): removing the evidence comparison left all 34 checks green.

    Each bound field gets its own case, so a deleted comparison fails loudly
    instead of being covered incidentally by another field's mismatch.
    """
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]

    tag = f"owner-approval/bound-{field}"
    sign_tag(tag, _body_json(mechanism, **{field: replacement}))

    with pytest.raises(SignedApprovalBindingMismatch) as caught:
        verify_signed_approval(repo, tag, expectation=_expectation())
    # The refusal must name the field that actually differed.
    expected_name = "candidate_artifact_sha256" if field == "candidate_artifact_sha256" else field
    assert expected_name in str(caught.value)


def test_a_tag_name_with_whitespace_is_refused(signing_repo: dict[str, object]) -> None:
    """O3(d): the whitespace check shipped untested."""
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    with pytest.raises(SignedApprovalSignatureError, match="must not contain spaces"):
        verify_signed_approval(
            repo, "owner-approval/has space", expectation=_expectation()
        )


def test_an_approval_expiring_exactly_now_is_refused(
    signing_repo: dict[str, object]
) -> None:
    """O3(e): the boundary between `>=` and `>` shipped untested."""
    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]

    expires = "2030-01-01T00:00:00Z"
    tag = "owner-approval/at-the-boundary"
    sign_tag(tag, _body_json(mechanism, expires_at=expires))
    moment = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(SignedApprovalExpired):
        verify_signed_approval(repo, tag, expectation=_expectation(), now=moment)

    # One second earlier it is still valid, which is what makes this a boundary.
    verified = verify_signed_approval(
        repo, tag, expectation=_expectation(), now=moment - timedelta(seconds=1)
    )
    assert verified.body.expires_at == expires


def test_a_tag_object_the_repository_does_not_hold_is_refused(
    signing_repo: dict[str, object], monkeypatch
) -> None:
    """O3(c): the "refusing rather than fetching" branch shipped untested."""
    import daedalus.kernel.signed_approval as module

    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    tag = "owner-approval/dangling"
    sign_tag(tag, _body_json(mechanism))

    real_git = module._git

    def failing_target_pin(root, args, **kwargs):
        # Only the final target pin fails: the object cannot be resolved.
        if args and args[0] == "rev-parse" and args[-1].endswith("^{}"):
            return subprocess.CompletedProcess(args, 1, "", "missing object")
        return real_git(root, args, **kwargs)

    monkeypatch.setattr(module, "_git", failing_target_pin)
    with pytest.raises(SignedApprovalSignatureError, match="refusing rather than fetching"):
        verify_signed_approval(repo, tag, expectation=_expectation())


# --- F6: the owner reads before signing, so that read must be honest --------


def test_the_owner_tool_marks_an_unverified_body_as_unverified(
    signing_repo: dict[str, object]
) -> None:
    """F6: `inspect` printed "body held by <tag>" with NO signature check.

    The HOWTO sends the owner there as the read-before-signing step, so an
    attacker-signed tag was displayed exactly like an owner-signed one.
    """
    from daedalus.kernel.signed_approval import describe_signed_tag

    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    attacker_key: Path = signing_repo["attacker_key"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]

    tag = "owner-approval/attacker-signed"
    assert _git(
        repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={attacker_key}",
        "tag", "-s", "-m", _body_json(mechanism), tag,
    ).returncode == 0

    described = describe_signed_tag(repo, tag)
    assert described["verified"] == "no"
    assert described["principal"] == ""
    # The body is still shown -- the owner needs to see it -- but never as fact.
    assert described["body"], "the owner still needs to see what the tag holds"


def test_the_owner_tool_confirms_a_genuine_signature(
    signing_repo: dict[str, object]
) -> None:
    from daedalus.kernel.signed_approval import describe_signed_tag

    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    tag = "owner-approval/genuine"
    sign_tag(tag, _body_json(mechanism))

    described = describe_signed_tag(repo, tag)
    assert described["verified"] == "yes"
    assert described["principal"] == "owner@daedalus"
    assert json.loads(described["body"])["candidate_artifact_sha256"] == CANDIDATE


def test_describing_a_tag_never_yields_a_capability(
    signing_repo: dict[str, object]
) -> None:
    """It reports; it must not be able to authorise."""
    from daedalus.kernel.signed_approval import (
        VerifiedSignedApproval,
        describe_signed_tag,
    )

    repo: Path = signing_repo["repo"]  # type: ignore[assignment]
    sign_tag = signing_repo["sign_tag"]  # type: ignore[assignment]
    mechanism: str = signing_repo["mechanism"]  # type: ignore[assignment]
    tag = "owner-approval/described"
    sign_tag(tag, _body_json(mechanism))

    described = describe_signed_tag(repo, tag)
    assert isinstance(described, dict)
    assert all(isinstance(value, str) for value in described.values())
    assert not isinstance(described, VerifiedSignedApproval)


def test_the_owner_tool_runs_no_bare_subprocess() -> None:
    """F6: `inspect` called git directly, bypassing the scrubbed environment."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "owner_approval_request.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    offenders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"run", "Popen", "call", "check_output"}
        and isinstance(node.value, ast.Name)
        and node.value.id == "subprocess"
    ]
    assert not offenders, (
        "the owner tool spawns git outside the kernel's scrubbed choke point"
    )


def test_canonical_body_round_trips_the_exact_signed_bytes() -> None:
    body = canonical_approval_body(
        expectation=_expectation(),
        nonce="nonce-1",
        expires_at=_future(),
        approval_mechanism_sha256="e" * 64,
    )
    restored = SignedApprovalBody.from_json(body.canonical_bytes().decode("utf-8"))
    assert restored == body
    assert b"\n" not in body.canonical_bytes()


# --- F4: the type must not be a free-floating claim of authentication -------


def test_a_caller_cannot_construct_its_own_verified_approval() -> None:
    """The gap Cerberus found: a public constructor on the "proof" object.

    Before the construction token, any in-process caller could build a
    VerifiedSignedApproval out of thin air and hand it to promotion_receipt(),
    which would stamp approval_assurance="authenticated" on it. No signature,
    no tag, no owner.
    """
    from daedalus.kernel.signed_approval import VerifiedSignedApproval

    body = canonical_approval_body(
        expectation=_expectation(),
        nonce="nonce-1",
        expires_at=_future(),
        approval_mechanism_sha256="e" * 64,
    )
    with pytest.raises(SignedApprovalSignatureError, match="cannot be constructed"):
        VerifiedSignedApproval(
            tag_name=approval_tag_for(CANDIDATE),
            tag_object_sha1="d" * 40,
            tag_target_oid="e" * 40,
            signer_principal="owner@daedalus",
            body=body,
            owner_approval_ref="artifact-locator:sha256:" + "f" * 64,
            trust_root_commit_oid="0" * 40,
            trust_root_blob_oid="1" * 40,
        )


def test_a_forged_approval_cannot_reach_an_authenticated_receipt() -> None:
    """The same gap, at the boundary that actually mints the claim."""
    from daedalus.kernel.signed_approval import VerifiedSignedApproval

    class NotVerified:
        """What a caller can still build: something that merely looks right."""

        tag_name = "owner-approval/forged"
        owner_approval_ref = "artifact-locator:sha256:" + "f" * 64

    receipt = promotion_receipt(
        NotVerified(),  # type: ignore[arg-type]
        promotion_id="promotion-forged",
        nomination_receipt_sha256=NOMINATION,
        candidate_artifact_sha256=CANDIDATE,
        candidate_artifact_locator="artifact-locator:sha256:" + CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        evidence_locator="artifact-locator:sha256:" + EVIDENCE,
        source_revision=BASE,
        target_revision=TARGET_HEAD,
        created_at="2026-01-01T00:00:00Z",
    )
    assert receipt.promotion_status == "pending-owner"
    assert receipt.approval_assurance == "not-applicable"
    assert receipt.owner_approval_ref is None
    assert not isinstance(NotVerified(), VerifiedSignedApproval)


def test_the_module_does_not_claim_an_unforgeable_receipt() -> None:
    """F4: the docstring promised more than the type can deliver.

    The removed sentence read "A caller cannot ask for an approved receipt; it
    can only present a verification that an owner signature produced." A
    guarantee a reviewer will rely on must not overstate a Python dataclass.
    """
    import daedalus.kernel.signed_approval as module

    doc = module.promotion_receipt.__doc__ or ""
    assert "it can only present a verification" not in doc
    # ...and the honest bound is stated where the object is defined.
    class_doc = module.VerifiedSignedApproval.__doc__ or ""
    assert "not** a security boundary" in class_doc or "not a security boundary" in class_doc


# --------------------------------------------------------------------------
# F3: the trust root is bound by the amendment CHAIN, not by the last commit.
#
# Two forgeries were executed against the previous version of this module, in
# which the ledger was read but no chain field was ever checked. Both are
# reproduced here verbatim. Remove the chain walk and these go red by name.
# --------------------------------------------------------------------------


def _rogue_signers(signing_repo) -> str:
    attacker_key: Path = signing_repo["attacker_key"]
    return f"attacker@evil {attacker_key.with_suffix('.pub').read_text().strip()}\n"


def test_rotating_the_signers_and_its_pin_in_one_commit_is_refused(
    signing_repo,
) -> None:
    """Attack B, executed: the file and the pin change in ONE motion.

    The original finding predicted this in advance and it worked: the rogue
    signers file plus an appended 'accepted' record naming its digest, with a
    deliberately broken ``previous_record_sha256`` and an approval reference
    that names nothing. ``resolve_trust_root`` accepted it and a forged
    approval came back ``principal='attacker@evil' status=approved
    assurance=authenticated``.
    """
    from daedalus.kernel.signed_approval import (
        AMENDMENT_LEDGER_PATH,
        TRUST_ROOT_DIGEST_FIELD,
    )

    repo: Path = signing_repo["repo"]
    rogue = _rogue_signers(signing_repo)
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rogue, encoding="utf-8")
    ledger = repo / AMENDMENT_LEDGER_PATH
    forged = {
        "schema": "daedalus-master-plan-amendment/1",
        "plan_id": "daedalus-master-plan",
        "sequence": 3,
        "status": "accepted",
        "approval_ref": "no-such-approval",
        "previous_record_sha256": "0" * 64,
        "base_plan_sha256": "9" * 64,
        "result_plan_sha256": "9" * 64,
        TRUST_ROOT_DIGEST_FIELD: _signers_digest(rogue),
    }
    ledger.write_text(
        ledger.read_text(encoding="utf-8")
        + json.dumps(forged, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    assert _git(repo, "add", "-A").returncode == 0
    assert (
        _git(
            repo, "commit", "-q", "-m", "rotate signers AND self-amend in one motion"
        ).returncode
        == 0
    )

    with pytest.raises(SignedApprovalRootError, match="record 3"):
        resolve_trust_root(repo)


def test_a_bare_record_with_no_chain_fields_is_refused(signing_repo) -> None:
    """Attack C, executed and worse: one line, a status and a digest.

    No ``plan_id``, no ``sequence``, no ``record_sha256``, no chain at all.
    The previous version accepted it, because its only predicates were
    ``status == "accepted"`` and "the digest parses as a sha256".
    """
    from daedalus.kernel.signed_approval import (
        AMENDMENT_LEDGER_PATH,
        TRUST_ROOT_DIGEST_FIELD,
    )

    repo: Path = signing_repo["repo"]
    rogue = _rogue_signers(signing_repo)
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rogue, encoding="utf-8")
    bare = {"status": "accepted", TRUST_ROOT_DIGEST_FIELD: _signers_digest(rogue)}
    (repo / AMENDMENT_LEDGER_PATH).write_text(
        json.dumps(bare, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert _git(repo, "add", "-A").returncode == 0
    assert (
        _git(repo, "commit", "-q", "-m", "ledger with one bare record").returncode == 0
    )

    with pytest.raises(SignedApprovalRootError, match="record 1"):
        resolve_trust_root(repo)


def test_a_well_formed_appended_record_is_still_refused(signing_repo) -> None:
    """Attack B2: the same one-motion forgery, by an attacker who is not sloppy.

    Attack B failed only on ``sequence``. Anyone who can commit can append a
    record that chains onto the real last record CORRECTLY -- right
    ``previous_record_sha256``, right ``record_sha256``, right revisions --
    and the chain walk alone accepted exactly that. Measured, before the plan
    binding: ``principal='attacker@evil' status=approved
    assurance=authenticated``.

    What refuses it now is that the head of the chain must also describe the
    master plan blob committed beside it. The forgery has to rewrite the
    constitutional document in the same commit.
    """
    from daedalus.kernel.signed_approval import (
        AMENDMENT_LEDGER_PATH,
        TRUST_ROOT_DIGEST_FIELD,
    )

    repo: Path = signing_repo["repo"]
    rogue = _rogue_signers(signing_repo)
    guard = _guard()
    records = guard.parse_ledger_text(
        (repo / AMENDMENT_LEDGER_PATH).read_text(encoding="utf-8"),
        AMENDMENT_LEDGER_PATH,
    )
    last = records[-1]
    forged = {
        "schema": guard.SCHEMA,
        "plan_id": guard.PLAN_ID,
        "sequence": last["sequence"] + 1,
        "status": "accepted",
        "approval_ref": "conversation-that-never-happened",
        "owner": "repository-owner",
        "previous_record_sha256": last["record_sha256"],
        "base_plan_sha256": last["result_plan_sha256"],
        "result_plan_sha256": "a" * 64,
        "base_revision": last["result_revision"],
        "result_revision": last["result_revision"] + 1,
        TRUST_ROOT_DIGEST_FIELD: _signers_digest(rogue),
    }
    forged["record_sha256"] = guard.canonical_record_sha256(forged)

    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rogue, encoding="utf-8")
    (repo / AMENDMENT_LEDGER_PATH).write_text(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in (*records, forged)
        ),
        encoding="utf-8",
    )
    assert _git(repo, "add", "-A").returncode == 0
    assert (
        _git(repo, "commit", "-q", "-m", "a well-formed one-motion forgery").returncode
        == 0
    )

    # The chain itself is intact -- that is the uncomfortable part.
    _guard_chain_is_intact = guard.parse_ledger_text(
        (repo / AMENDMENT_LEDGER_PATH).read_text(encoding="utf-8"),
        AMENDMENT_LEDGER_PATH,
    )
    from daedalus.kernel.signed_approval import _verify_amendment_chain

    _verify_amendment_chain(_guard_chain_is_intact)

    with pytest.raises(SignedApprovalRootError, match="does not describe the plan"):
        resolve_trust_root(repo)


def test_a_self_consistent_chain_from_a_foreign_genesis_is_refused(
    signing_repo,
) -> None:
    """The anchor. An attacker who writes record 1 is not the owner.

    Every link here is internally correct -- real digests, correct
    ``previous_record_sha256``, monotone revisions. The only thing wrong is
    that the history starts somewhere the code does not recognise. Without
    ``AMENDMENT_GENESIS_RECORD_SHA256`` this chain verifies perfectly, which
    is why walking the chain alone would not have been enough.
    """
    from daedalus.kernel.signed_approval import TRUST_ROOT_DIGEST_FIELD

    repo: Path = signing_repo["repo"]
    rogue = _rogue_signers(signing_repo)
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rogue, encoding="utf-8")

    genesis = {
        "schema": _guard().SCHEMA,
        "plan_id": _guard().PLAN_ID,
        "sequence": 1,
        "status": "accepted",
        "approval_ref": "attacker-writes-history",
        "previous_record_sha256": None,
        "base_plan_sha256": "1" * 64,
        "result_plan_sha256": "2" * 64,
        "base_revision": 0,
        "result_revision": 1,
    }
    genesis["record_sha256"] = _guard().canonical_record_sha256(genesis)
    pin = _chained_record(genesis, **{TRUST_ROOT_DIGEST_FIELD: _signers_digest(rogue)})
    _write_ledger(repo, [genesis, pin])
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "a whole private history").returncode == 0

    with pytest.raises(SignedApprovalRootError, match="different history"):
        resolve_trust_root(repo)


def test_a_mid_chain_insertion_is_refused(signing_repo) -> None:
    """Attack D: a record spliced into the middle of an otherwise real chain."""
    from daedalus.kernel.signed_approval import TRUST_ROOT_DIGEST_FIELD

    repo: Path = signing_repo["repo"]
    rogue = _rogue_signers(signing_repo)
    (repo / OWNER_ALLOWED_SIGNERS_PATH).write_text(rogue, encoding="utf-8")

    genesis = _real_genesis_record()
    legitimate = _chained_record(genesis)
    spliced = {
        key: value for key, value in legitimate.items() if key != "record_sha256"
    }
    spliced[TRUST_ROOT_DIGEST_FIELD] = _signers_digest(rogue)
    # The splice keeps its OWN digest honest, so only the successor's
    # previous-record hash still points at the record it replaced.
    spliced["record_sha256"] = _guard().canonical_record_sha256(spliced)
    successor = _chained_record(legitimate)
    _write_ledger(repo, [genesis, spliced, successor])
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "splice").returncode == 0

    with pytest.raises(SignedApprovalRootError, match="chain is broken"):
        resolve_trust_root(repo)


def test_the_chain_rules_are_the_guard_s_and_not_a_second_copy() -> None:
    """The anti-drift pin: one set of rules, held to one verdict.

    ``_verify_amendment_chain`` mirrors the walk in the repository guard and
    computes digests with the guard's own ``canonical_record_sha256``. A
    second, independently maintained copy of a security check is precisely the
    defect this lane already had to fix once, so the two are held to the same
    accept/reject verdict on a corpus of tampered ledgers. If the guard's
    rules move and this module's do not, this test goes red.

    The agreement is on the CHAIN rules only. The trust root deliberately adds
    two demands the guard does not make -- the code-pinned genesis and the
    plan binding -- so those cases are not in this corpus; they have named
    tests of their own.
    """
    import tempfile as _tempfile

    from daedalus.kernel.signed_approval import (
        AMENDMENT_LEDGER_PATH,
        _verify_amendment_chain,
    )

    guard = _guard()
    genesis = _real_genesis_record()
    good = _chained_record(genesis)

    def broken(*, reseal: bool = True, **fields):
        record = dict(good)
        record.update(fields)
        if reseal:
            # Re-seal, so the ONLY defect is the field under test. Without
            # this every case also breaks ``record_sha256`` and the corpus
            # cannot tell one predicate from another -- which is exactly how
            # the sequence check survived its first mutation.
            record["record_sha256"] = guard.canonical_record_sha256(record)
        return [genesis, record]

    corpus: dict[str, list[dict]] = {
        "clean": [genesis, good],
        "bad-schema": broken(schema="something/else"),
        "bad-plan-id": broken(plan_id="other-plan"),
        "not-accepted": broken(status="proposed"),
        "bad-sequence": broken(sequence=9),
        "body-changed-under-its-digest": broken(
            reseal=False, result_plan_sha256="e" * 64
        ),
        "broken-link": broken(previous_record_sha256="0" * 64),
        "no-approval-ref": broken(approval_ref=""),
        "revision-jump": broken(result_revision=99),
        "malformed-digest": broken(reseal=False, record_sha256="nope"),
    }

    disagreements: list[str] = []
    for label, records in corpus.items():
        text = "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        )
        try:
            _verify_amendment_chain(guard.parse_ledger_text(text, "ledger"))
            module_rejects = False
        except SignedApprovalRootError:
            module_rejects = True

        # The guard reads the ledger from disk, so give it one. Errors about
        # unrelated artifacts are expected in a scratch directory and are
        # filtered out; only the ledger-record verdict is compared.
        scratch = Path(_tempfile.mkdtemp(prefix="chain-agreement-"))
        (scratch / AMENDMENT_LEDGER_PATH).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / guard.PLAN_REL, scratch / guard.PLAN_REL)
        (scratch / AMENDMENT_LEDGER_PATH).write_text(text, encoding="utf-8")
        guard_errors = [
            error
            for error in guard.verify(scratch)
            if error.startswith(f"{guard.LEDGER_REL} record")
        ]
        shutil.rmtree(scratch, ignore_errors=True)

        if module_rejects != bool(guard_errors):
            disagreements.append(
                f"{label}: module_rejects={module_rejects} "
                f"guard_rejects={bool(guard_errors)} ({guard_errors})"
            )

    assert disagreements == [], (
        "the trust root and the guard disagree about what a valid amendment "
        f"chain is: {disagreements}. They must not drift apart; there is one "
        "set of chain rules."
    )


# --------------------------------------------------------------------------
# N1: the additions-only guard was a bare assert, and it was inverted.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("variable", ["GIT_CONFIG_PARAMETERS", "GIT_ALLOW_PROTOCOL"])
def test_the_scrubbed_variables_being_set_does_not_break_verification(
    variable: str, signing_repo, monkeypatch
) -> None:
    """Measured: setting either one turned every verification into a crash.

    ``baseline`` was snapshotted AFTER the canonical environment, so it held
    whichever of these was ambiently set, and this module's own deliberate
    ``pop`` then tripped its own assertion. The result was an
    ``AssertionError`` from outside the ``SignedApprovalError`` taxonomy: a
    caller written to ``except SignedApprovalError`` crashed instead of
    refusing. The test that was supposed to watch the environment passed only
    because these variables happened to be unset on this box.
    """
    import daedalus.kernel.signed_approval as module

    # Signed before the variable is set: the fixture's own git is a plain
    # subprocess and would choke on a bogus value, which is separately the
    # reason this module scrubs it.
    repo: Path = signing_repo["repo"]
    signing_repo["sign_tag"](
        "owner-approval/env", _body_json(signing_repo["mechanism"])
    )

    monkeypatch.setenv(variable, "x")

    env = module._git_env()
    assert variable not in env, "the overlay exists to remove this variable"
    assert env["GIT_NO_LAZY_FETCH"] == "1"

    # And the whole path still works, rather than raising outside the taxonomy.
    verified = verify_signed_approval(
        repo, "owner-approval/env", expectation=_expectation()
    )
    assert verified.signer_principal == "owner@daedalus"


def test_the_environment_guard_still_runs_under_python_O() -> None:
    """An ``assert`` is not a guard: ``-O`` deletes it.

    The docstring said the check "enforces" additions-only. Under ``python -O``
    or ``PYTHONOPTIMIZE`` it did not execute at all, so a weakened environment
    would have been used silently. This runs the check in a real ``-O``
    interpreter and requires a refusal inside the module's own taxonomy.
    """
    program = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "import daedalus.kernel.signed_approval as m;"
        "assert sys.flags.optimize >= 1, 'not running optimised';"
        # The canonical environment claims a value the overlay then changes:
        # exactly the weakening the check exists to catch.
        "m._canonical_git_env = lambda: {'GIT_NO_LAZY_FETCH': '0'};"
        "\ntry:\n"
        "    m._git_env()\n"
        "    print('NOT-REFUSED')\n"
        "except m.SignedApprovalError as exc:\n"
        "    print('REFUSED')\n"
        "except AssertionError:\n"
        "    print('ASSERTION')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-O", "-c", program],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "REFUSED", (
        "the additions-only check did not fire under python -O: "
        f"{completed.stdout.strip()!r}. A bare assert is not a guard."
    )


def test_the_environment_guard_is_not_an_assert() -> None:
    """Pins the mechanism, so it cannot quietly become an ``assert`` again."""
    import daedalus.kernel.signed_approval as module

    tree = ast.parse(inspect.getsource(module._git_env))
    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert asserts == [], (
        "the additions-only check is an assert again; `python -O` removes it "
        "and the docstring's word 'enforces' becomes false"
    )


# --------------------------------------------------------------------------
# N3: one stdlib call carried the construction token.
# --------------------------------------------------------------------------


def _receipt_from(verified):
    return promotion_receipt(
        verified,
        promotion_id="promotion-launder",
        nomination_receipt_sha256=NOMINATION,
        candidate_artifact_sha256=CANDIDATE,
        candidate_artifact_locator="artifact-locator:sha256:" + CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        evidence_locator="artifact-locator:sha256:" + EVIDENCE,
        source_revision=BASE,
        target_revision=TARGET_HEAD,
        created_at="2026-01-01T00:00:00Z",
    )


def test_dataclasses_replace_cannot_launder_an_approval(signing_repo) -> None:
    """Executed: ONE stdlib call, no module globals, an approved receipt.

    ``_token`` is a real ``init`` field, so ``dataclasses.replace`` carried it
    forward while every other field was attacker-chosen. The result was
    ``status=approved assurance=authenticated`` under
    ``signer_principal='attacker@evil'`` with the trust-root pins zeroed.
    """
    import dataclasses

    _, verified = _verified(signing_repo, "owner-approval/launder")
    evil_body = SignedApprovalBody.from_json(
        _body_json(
            signing_repo["mechanism"],
            candidate_artifact_sha256="d" * 64,
            nonce="attacker",
        )
    )
    forged = dataclasses.replace(
        verified,
        signer_principal="attacker@evil",
        body=evil_body,
        trust_root_commit_oid="0" * 40,
        trust_root_blob_oid="0" * 40,
        owner_approval_ref="artifact-locator:sha256:" + "f" * 64,
    )
    # The type check the old code relied on still passes -- that is the point.
    assert isinstance(forged, VerifiedSignedApprovalType())
    assert forged._token is not None

    with pytest.raises(SignedApprovalSignatureError, match="not produced by"):
        _receipt_from(forged)


def test_deepcopy_cannot_launder_an_approval(signing_repo) -> None:
    """``copy.deepcopy`` skips ``__post_init__`` and copies the sentinel."""
    import copy

    _, verified = _verified(signing_repo, "owner-approval/deepcopy")
    clone = copy.deepcopy(verified)

    assert isinstance(clone, VerifiedSignedApprovalType())
    with pytest.raises(SignedApprovalSignatureError, match="not produced by"):
        _receipt_from(clone)


def test_a_real_verification_still_produces_an_approved_receipt(
    signing_repo,
) -> None:
    """The mint must not break the legitimate path it is protecting."""
    _, verified = _verified(signing_repo, "owner-approval/genuine")
    receipt = promotion_receipt(
        verified,
        promotion_id="promotion-genuine",
        nomination_receipt_sha256=NOMINATION,
        candidate_artifact_sha256=CANDIDATE,
        candidate_artifact_locator="artifact-locator:sha256:" + CANDIDATE,
        evidence_packet_sha256=EVIDENCE,
        evidence_locator="artifact-locator:sha256:" + EVIDENCE,
        source_revision=BASE,
        target_revision=TARGET_HEAD,
        created_at="2026-01-01T00:00:00Z",
    )
    assert receipt.promotion_status == "approved"
    assert receipt.approval_assurance == "authenticated"


def test_the_honest_bound_names_dataclasses_replace() -> None:
    """The stated bound understated the exposure; it must name the real one."""
    import daedalus.kernel.signed_approval as module

    doc = module.VerifiedSignedApproval.__doc__ or ""
    assert "dataclasses.replace" in doc, (
        "the honest bound said only 'code that reaches into this module's "
        "globals', which understated a one-stdlib-call forgery"
    )
    assert "deepcopy" in doc


def VerifiedSignedApprovalType():
    from daedalus.kernel.signed_approval import VerifiedSignedApproval

    return VerifiedSignedApproval
