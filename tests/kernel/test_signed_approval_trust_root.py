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
import shutil
import subprocess
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
    SignedApprovalRootError,
    SignedApprovalSignatureError,
    canonical_approval_body,
    read_committed_allowed_signers,
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


def _body_json(**changes: str) -> str:
    body = {
        "purpose": APPROVAL_PURPOSE,
        "operation": "promote-candidate",
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
    signers.write_text(
        f"owner@daedalus {owner_key.with_suffix('.pub').read_text().strip()}\n",
        encoding="utf-8",
    )
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

    return {
        "repo": repo,
        "owner_key": owner_key,
        "attacker_key": attacker_key,
        "sign_tag": sign_tag,
    }


def test_owner_signed_tag_verifies_against_the_committed_root(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json())

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
        _body_json(),
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
        "owner-approval/promotion-1", _body_json(), key=attacker_key
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
        "owner-approval/promotion-1", _body_json(purpose="daedalus.release")
    )

    with pytest.raises(SignedApprovalPurposeError):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_tag_outside_the_approval_namespace_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("v1.0.0", _body_json())

    with pytest.raises(SignedApprovalPurposeError):
        verify_signed_approval(repo, "v1.0.0", expectation=_expectation())


def test_signed_body_naming_another_candidate_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"](
        "owner-approval/promotion-1", _body_json(candidate_artifact_sha256="d" * 64)
    )

    with pytest.raises(SignedApprovalBindingMismatch):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_signed_body_naming_a_moved_target_head_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json())

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
        repo, "tag", "-a", "-m", _body_json(), "owner-approval/promotion-1"
    ).returncode == 0

    with pytest.raises(SignedApprovalSignatureError):
        verify_signed_approval(
            repo, "owner-approval/promotion-1", expectation=_expectation()
        )


def test_expired_approval_is_refused(signing_repo) -> None:
    repo = signing_repo["repo"]
    signing_repo["sign_tag"]("owner-approval/promotion-1", _body_json())

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

    with pytest.raises(SignedApprovalRootError):
        read_committed_allowed_signers(repo)


def test_repository_ships_a_principal_free_trust_root() -> None:
    """The real committed file must not name a principal nobody reviewed."""
    shipped = Path(__file__).resolve().parents[2] / OWNER_ALLOWED_SIGNERS_PATH
    assert shipped.exists()
    principals = [
        line
        for line in shipped.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert principals == []


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
    """The tool prints what to sign; it must never be able to sign it."""
    tool = (
        Path(__file__).resolve().parents[2] / "scripts" / "owner_approval_request.py"
    )
    argvs = _subprocess_argv_literals(tool.read_text(encoding="utf-8"))

    assert argvs, "expected the tool to run at least one git command"
    for argv in argvs:
        assert "-s" not in argv, f"owner tool creates a signature: {argv}"
        assert not any(
            argument.startswith("user.signingkey") for argument in argv
        ), f"owner tool passes a signing key: {argv}"
        if "tag" in argv:
            assert "-l" in argv, f"owner tool uses tag for more than reading: {argv}"


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
        expectation=expectation, nonce="nonce-e2e", expires_at=_future()
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
        expectation=_expectation(), nonce="nonce-1", expires_at=_future()
    )
    retyped = json.dumps(body.to_dict(), indent=2, sort_keys=True)
    signing_repo["sign_tag"]("owner-approval/retyped", retyped)

    with pytest.raises(SignedApprovalBindingMismatch):
        verify_signed_approval(
            repo, "owner-approval/retyped", expectation=_expectation()
        )


def test_canonical_body_round_trips_the_exact_signed_bytes() -> None:
    body = canonical_approval_body(
        expectation=_expectation(), nonce="nonce-1", expires_at=_future()
    )
    restored = SignedApprovalBody.from_json(body.canonical_bytes().decode("utf-8"))
    assert restored == body
    assert b"\n" not in body.canonical_bytes()
