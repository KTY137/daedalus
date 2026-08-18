"""Show the owner exactly what they are about to sign, and what they signed.

This tool holds no capability. It cannot sign, it never reads a private key,
and it never creates a tag -- it prints the canonical body and the exact
command line, and the owner runs that command themselves in their own shell.
That split is the point: the signing capability stays with the person, and
nothing that can run this script gains the ability to approve a promotion.

What-you-see-is-what-you-sign: ``show`` prints the byte-exact body that will
become the tag message, together with its SHA-256, and ``inspect`` prints the
byte-exact body read back out of a tag object. The two digests must match, and
the body is produced by the same code the verifier uses, so there is no second
serialisation that could disagree with it.

  Prepare:  python scripts/owner_approval_request.py show --help
  Confirm:  python scripts/owner_approval_request.py inspect --tag owner-approval/...
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.kernel.approvals import ApprovalExpectation  # noqa: E402
from daedalus.kernel.signed_approval import (  # noqa: E402
    APPROVAL_TAG_NAMESPACE,
    OWNER_ALLOWED_SIGNERS_PATH,
    SignedApprovalBody,
    canonical_approval_body,
    read_committed_allowed_signers,
    resolve_trust_root,
)

MAX_TTL_HOURS = 24


def _rule(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 66 - len(title)))


def _show(args: argparse.Namespace) -> int:
    if args.ttl_hours <= 0 or args.ttl_hours > MAX_TTL_HOURS:
        raise SystemExit(f"--ttl-hours must be within 1..{MAX_TTL_HOURS}")
    expires = datetime.now(timezone.utc) + timedelta(hours=args.ttl_hours)
    expectation = ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=args.nomination_sha256,
        candidate_artifact_sha256=args.candidate_sha256,
        evidence_packet_sha256=args.evidence_sha256,
        base_revision=args.base_revision,
        target_ref=args.target_ref,
        current_target_revision=args.target_revision,
    )
    try:
        trust_root = resolve_trust_root(args.repo_root)
    except Exception as exc:  # noqa: BLE001 - this tool only reports
        raise SystemExit(
            f"{type(exc).__name__}: {exc}\n\n"
            "Nothing can be approved until the owner commits a public key. "
            "See docs/OWNER_SEALED_APPROVAL_HOWTO.md section 0."
        ) from exc
    body = canonical_approval_body(
        expectation=expectation,
        nonce=args.nonce or f"nonce-{secrets.token_hex(8)}",
        expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        approval_mechanism_sha256=trust_root.digest,
    )
    raw = body.canonical_bytes()
    tag = args.tag or f"{APPROVAL_TAG_NAMESPACE}{args.candidate_sha256[:12]}"

    _rule("what you are approving")
    print(f"  candidate artifact : {body.candidate_artifact_sha256}")
    print(f"  evidence packet    : {body.evidence_packet_sha256}")
    print(f"  nomination receipt : {body.nomination_receipt_sha256}")
    print(f"  candidate base     : {body.base_revision}")
    print(f"  target             : {body.target_ref} at {body.expected_target_revision}")
    print(f"  valid until        : {body.expires_at}  ({args.ttl_hours}h)")
    print(f"  signer set         : {trust_root.digest[:16]}... "
          f"(blob {trust_root.blob_oid[:12]} in commit {trust_root.commit_oid[:12]})")

    _rule("the exact bytes that will be signed")
    print(raw.decode("utf-8"))
    print(f"\n  sha256 : {hashlib.sha256(raw).hexdigest()}")
    print(f"  length : {len(raw)} bytes, one line, no trailing newline")

    _rule("run this yourself, in your own shell")
    print("  git -c gpg.format=ssh -c user.signingkey=<YOUR KEY> \\")
    print(f"      tag -s -m '{raw.decode('utf-8')}' \\")
    print(f"      {tag}")

    _rule("then confirm what the repository actually holds")
    print(f"  python scripts/owner_approval_request.py inspect --tag {tag}")
    print()
    return 0


def _inspect(args: argparse.Namespace) -> int:
    repo = Path(args.repo_root).resolve()
    import subprocess

    completed = subprocess.run(
        ["git", "tag", "-l", "--format=%(contents)", args.tag],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise SystemExit(f"no tag {args.tag} in {repo}")
    contents = completed.stdout
    for marker in ("-----BEGIN SSH SIGNATURE-----", "-----BEGIN PGP SIGNATURE-----"):
        index = contents.find(marker)
        if index != -1:
            contents = contents[:index]
    text = contents.strip()

    _rule(f"body held by {args.tag}")
    print(text)
    print(f"\n  sha256 : {hashlib.sha256(text.encode('utf-8')).hexdigest()}")

    try:
        body = SignedApprovalBody.from_json(text)
    except Exception as exc:  # noqa: BLE001 - this tool only reports
        _rule("this is not a well-formed approval body")
        print(f"  {type(exc).__name__}: {exc}")
        return 1
    _rule("parsed")
    for key, value in body.to_dict().items():
        print(f"  {key:26} : {value}")

    _rule("trust root")
    try:
        signers = read_committed_allowed_signers(repo)
    except Exception as exc:  # noqa: BLE001 - this tool only reports
        print(f"  {type(exc).__name__}: {exc}")
        print("\n  Promotion approval is refused until a principal is committed.")
        return 1
    principals = [
        line
        for line in signers.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    print(f"  committed {OWNER_ALLOWED_SIGNERS_PATH} names {len(principals)} principal(s):")
    for line in principals:
        print(f"    {line.strip()[:96]}")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="owner_approval_request",
        description="Show what to sign, and what was signed. Never signs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="print the canonical body and the tag command")
    show.add_argument("--candidate-sha256", required=True)
    show.add_argument("--evidence-sha256", required=True)
    show.add_argument("--nomination-sha256", required=True)
    show.add_argument("--base-revision", required=True)
    show.add_argument("--target-ref", required=True)
    show.add_argument("--target-revision", required=True)
    show.add_argument("--ttl-hours", type=int, default=2)
    show.add_argument("--nonce", default=None)
    show.add_argument("--tag", default=None)
    show.add_argument("--repo-root", default=".")
    show.set_defaults(handler=_show)

    inspect_parser = sub.add_parser("inspect", help="print the body a tag holds")
    inspect_parser.add_argument("--tag", required=True)
    inspect_parser.add_argument("--repo-root", default=".")
    inspect_parser.set_defaults(handler=_inspect)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
