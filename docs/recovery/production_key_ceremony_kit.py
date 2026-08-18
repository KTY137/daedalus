"""Production key ceremony kit — mint the runtime-fault column signing keys.

The whole runtime fault matrix is signed one column at a time, and each column
holds its own key so that a compromise of one collector cannot manufacture
trust for another's rows. A closure-grade verdict additionally requires those
keys to be *production* custody: material that has never been inside the
repository, never reached a candidate, and never been printed into a terminal
log.

This kit performs that ceremony. It is owner-run by design. Nothing in the
build path may create production key material, so no agent, collector or CI job
calls this file; the owner runs it once, and afterwards the live column run is
a single command that reads the keys from named environment variables.

Two facts worth stating plainly, because the word "keypair" invites the wrong
mental model:

* The attestation scheme is a symmetric HMAC. What is minted is a high-entropy
  *shared secret* per column, not an asymmetric keypair. Whoever can verify a
  bundle can also forge one, which is exactly why the material stays in owner
  custody and out of the repository.
* Declaring ``--key-class production`` does not make a key production-grade.
  The custody does. This kit is what makes the declaration true.

Usage (run from anywhere):

    python production_key_ceremony_kit.py selftest
    python production_key_ceremony_kit.py mint
    python production_key_ceremony_kit.py show

``selftest`` is hermetic: it mints throwaway secrets in the system temp dir,
drives a real collector run, attests it, and proves the signature both verifies
under the right key and fails under a wrong one. It writes nothing outside temp.

``mint`` creates the real keys outside the repository, locks the directory down
to the current user, and prints custody instructions plus the exact commands
that load the keys without echoing them.

``show`` prints fingerprints and custody state. It never prints secrets.

Rollback: delete the key directory. Nothing in the repository refers to the
material, so removing it cannot break a build -- it only invalidates bundles
already signed with those keys, which must then be re-attested from their
retained run directories. Rotating a key is the same operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# One key per collector column. The names are the contract between this
# ceremony and every run script; changing one means re-attesting that column.
COLUMN_KEY_ENV = {
    "live-runtime": "DAEDALUS_LIVE_FAULT_KEY",
    "linux-host": "DAEDALUS_HOST_FAULT_KEY",
    "deterministic-fixture": "DAEDALUS_FIXTURE_FAULT_KEY",
}
COLUMN_FILENAME = {
    "live-runtime": "live-runtime.key",
    "linux-host": "linux-host.key",
    "deterministic-fixture": "deterministic-fixture.key",
}
CUSTODY_FILENAME = "custody.json"

# 48 random bytes rendered url-safe is 64 characters, so the UTF-8 encoding is
# 64 bytes -- comfortably above the 32-byte floor the issuers enforce.
_SECRET_TOKEN_BYTES = 48
_MIN_SECRET_BYTES = 32

_SELFTEST_REVISION = "0" * 39 + "1"


def default_key_dir() -> Path:
    """Where production material lives: owner profile, never the project tree."""

    home = Path(os.path.expanduser("~"))
    return home / ".daedalus-keys" / "gate0-runtime-fault"


def find_repo_root(start: Path | None = None) -> Path | None:
    """The project root, so the kit can import the kernel and refuse to write into it."""

    here = (start or Path(__file__).resolve()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "daedalus").is_dir() and (candidate / "AGENTS.md").is_file():
            return candidate
    return None


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _has_git_ancestor(path: Path) -> Path | None:
    for candidate in (path.resolve(), *path.resolve().parents):
        if (candidate / ".git").exists():
            return candidate
    return None


class CeremonyRefusal(RuntimeError):
    """The requested key location or state is not safe for production material."""


def assert_safe_key_dir(key_dir: Path, repo_root: Path | None) -> None:
    """Refuse any location from which key material could reach the repository.

    This is the one guarantee the kit actually enforces rather than documents.
    A path inside the project tree, or inside any Git working tree, is refused
    before a single byte of entropy is written.
    """

    resolved = key_dir.resolve()
    if repo_root is not None and _is_inside(resolved, repo_root):
        raise CeremonyRefusal(
            f"key directory {resolved} is inside the project tree {repo_root}; "
            "production key material must never live in the repository"
        )
    git_root = _has_git_ancestor(resolved if resolved.exists() else resolved.parent)
    if git_root is not None:
        raise CeremonyRefusal(
            f"key directory {resolved} is inside the Git working tree {git_root}; "
            "choose a location outside version control"
        )


def _restrict_permissions(path: Path) -> tuple[bool, str]:
    """Lock a path down to the current user. Returns (ok, detail)."""

    if platform.system() == "Windows":
        user = os.environ.get("USERNAME")
        if not user:
            return False, "USERNAME is unset; cannot scope an ACL to the owner"
        domain = os.environ.get("USERDOMAIN")
        principal = f"{domain}\\{user}" if domain else user
        # (OI)(CI) are *inheritance* flags and are only meaningful on a
        # container. Applying them to a key file together with /inheritance:r
        # produces an ACL that denies the owner their own key -- the ceremony
        # would lock the owner out of the material it just minted.
        grant = f"{principal}:(OI)(CI)F" if path.is_dir() else f"{principal}:F"
        try:
            completed = subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    grant,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"icacls could not run: {exc}"
        if completed.returncode != 0:
            return False, f"icacls failed: {completed.stderr.strip()[:200]}"
        return True, f"ACL restricted to {principal}"
    try:
        if path.is_dir():
            path.chmod(stat.S_IRWXU)
        else:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        return False, f"chmod failed: {exc}"
    return True, "mode restricted to the owner"


def mint_secret() -> str:
    """One high-entropy column secret, as the text an environment variable holds."""

    token = secrets.token_urlsafe(_SECRET_TOKEN_BYTES)
    if len(token.encode("utf-8")) < _MIN_SECRET_BYTES:
        raise CeremonyRefusal("minted secret is below the issuer entropy floor")
    return token


def fingerprint(secret: str) -> str:
    """The public identity of a secret, exactly as bundles publish it."""

    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def write_keys(key_dir: Path, secrets_by_column: dict[str, str]) -> list[str]:
    """Write each column secret and lock it down. Returns permission notes."""

    key_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    ok, detail = _restrict_permissions(key_dir)
    notes.append(f"{'ok' if ok else 'WARN'}: directory {detail}")
    for column, secret in sorted(secrets_by_column.items()):
        path = key_dir / COLUMN_FILENAME[column]
        # No trailing newline: the file content is the secret verbatim, so a
        # loader that forgets to strip still gets the right bytes.
        path.write_text(secret, encoding="utf-8")
        ok, detail = _restrict_permissions(path)
        notes.append(f"{'ok' if ok else 'WARN'}: {path.name} {detail}")
    custody = {
        "schema": "daedalus-production-key-custody/1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": platform.node(),
        "key_class": "production",
        "columns": {
            column: {
                "env": COLUMN_KEY_ENV[column],
                "file": COLUMN_FILENAME[column],
                "key_sha256": fingerprint(secret),
            }
            for column, secret in sorted(secrets_by_column.items())
        },
    }
    custody_path = key_dir / CUSTODY_FILENAME
    custody_path.write_text(json.dumps(custody, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    ok, detail = _restrict_permissions(custody_path)
    notes.append(f"{'ok' if ok else 'WARN'}: {CUSTODY_FILENAME} {detail}")
    return notes


def load_secret(key_dir: Path, column: str) -> str:
    path = key_dir / COLUMN_FILENAME[column]
    if not path.is_file():
        raise CeremonyRefusal(f"no key for column {column} at {path}")
    return path.read_text(encoding="utf-8").strip()


def _loader_lines(key_dir: Path) -> list[str]:
    lines = ["  PowerShell:"]
    for column in sorted(COLUMN_KEY_ENV):
        path = key_dir / COLUMN_FILENAME[column]
        lines.append(
            f'    $env:{COLUMN_KEY_ENV[column]} = (Get-Content -Raw "{path}").Trim()'
        )
    lines.append("  bash:")
    for column in sorted(COLUMN_KEY_ENV):
        path = key_dir / COLUMN_FILENAME[column]
        lines.append(
            f"    export {COLUMN_KEY_ENV[column]}=\"$(tr -d '\\r\\n' < '{path}')\""
        )
    return lines


def _attest_roundtrip(root: Path, workspace: Path, secret: str, wrong_secret: str):
    """Drive a real collector run and prove the minted key authenticates it.

    This is the part that makes the selftest worth running. It does not check
    that a secret is long enough -- it checks that the exact issuer and verifier
    the gate uses accept this material, and reject a different one.
    """

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
    from daedalus.runtimes.fault_attestations import (
        verify_attested_runtime_fault_matrix,
    )
    from daedalus.runtimes.live_fault_attestation_issuer import (
        LiveFaultAttestationIssuer,
        build_matrix_from_live_run_directory,
        issue_live_run_directory,
    )
    from daedalus.runtimes.live_fault_collector import (
        retain_live_fault_run,
        run_live_fault_catalog,
    )
    from daedalus.runtimes.live_probe_drivers import build_live_probe_executors

    run_dir = workspace / "run"
    runs = run_live_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=_SELFTEST_REVISION,
        executors=build_live_probe_executors(),
    )
    for row in runs:
        retain_live_fault_run(run_dir, row)

    now = datetime.now(timezone.utc)
    issuer = LiveFaultAttestationIssuer(
        issuer_id="ceremony-selftest-live",
        key_id="ceremony-selftest-key",
        secret=secret.encode("utf-8"),
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=_SELFTEST_REVISION,
        validity=timedelta(hours=1),
    )
    bundle = issue_live_run_directory(
        run_dir, issuer=issuer, key_class="development", issued_at=now
    )
    matrix = build_matrix_from_live_run_directory(
        run_dir, catalog=RUNTIME_FAULT_CATALOG, source_revision=_SELFTEST_REVISION
    )

    def _refuses(active_secret: str) -> tuple[bool, str]:
        """Did the verifier refuse this key? Raising and blocking both count."""

        try:
            verification = verify_attested_runtime_fault_matrix(
                matrix,
                catalog=RUNTIME_FAULT_CATALOG,
                expected_source_revision=_SELFTEST_REVISION,
                attestations=bundle.attestations,
                keyring={
                    (row.issuer_id, row.key_id): active_secret.encode("utf-8")
                    for row in bundle.attestations
                },
                issuer_authorities={issuer.issuer_id: ("live-runtime",)},
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 - a raise is a refusal
            return True, type(exc).__name__
        untrusted = [
            blocker
            for blocker in verification.blockers
            if blocker.startswith("fault.untrusted-observation")
        ]
        if untrusted:
            return True, f"{len(untrusted)} untrusted-observation blocker(s)"
        return False, "every row trusted"

    return (
        len(runs),
        len(bundle.attestations),
        _refuses(secret),
        _refuses(wrong_secret),
    )


def selftest(key_dir: Path) -> bool:
    checks: list[tuple[str, bool, str]] = []
    root = find_repo_root()

    def record(label: str, good: bool, detail: str) -> None:
        checks.append((label, good, detail))
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: {detail}")

    print("selftest: entropy and identity")
    first, second = mint_secret(), mint_secret()
    record(
        "secret entropy",
        len(first.encode("utf-8")) >= _MIN_SECRET_BYTES,
        f"{len(first.encode('utf-8'))} bytes >= {_MIN_SECRET_BYTES}",
    )
    record("secrets are unique", first != second, "two mints differ")
    record(
        "fingerprint is the published identity",
        fingerprint(first) == hashlib.sha256(first.encode("utf-8")).hexdigest(),
        "sha256 over the exact env-var text",
    )

    print("selftest: the repository containment guard")
    if root is None:
        record("project root located", False, "could not find the project root")
    else:
        record("project root located", True, str(root))
        try:
            assert_safe_key_dir(root / "keys", root)
        except CeremonyRefusal as exc:
            record("in-repo key dir refused", True, str(exc)[:120])
        else:
            record(
                "in-repo key dir refused",
                False,
                "a path inside the project tree was accepted",
            )
        try:
            assert_safe_key_dir(key_dir, root)
        except CeremonyRefusal as exc:
            record("target key dir is outside version control", False, str(exc)[:160])
        else:
            record("target key dir is outside version control", True, str(key_dir))

    print("selftest: permissions on throwaway material")
    workspace = Path(tempfile.mkdtemp(prefix="daedalus-key-ceremony-"))
    try:
        scratch_keys = workspace / "keys"
        notes = write_keys(
            scratch_keys, {column: mint_secret() for column in COLUMN_KEY_ENV}
        )
        for note in notes:
            record("permission", note.startswith("ok:"), note)

        # Locking a key down is only half the requirement; the owner has to be
        # able to read it back afterwards. An over-broad ACL here would hand the
        # owner a directory of keys they cannot use.
        readable: dict[str, str] = {}
        try:
            for column in COLUMN_KEY_ENV:
                readable[column] = load_secret(scratch_keys, column)
        except (OSError, CeremonyRefusal) as exc:
            record("owner can still read the locked key", False, f"{type(exc).__name__}: {exc}")
        else:
            record(
                "owner can still read the locked key",
                len(readable) == len(COLUMN_KEY_ENV),
                f"{len(readable)} of {len(COLUMN_KEY_ENV)} keys readable after lockdown",
            )
        if readable:
            custody_text = (scratch_keys / CUSTODY_FILENAME).read_text("utf-8")
            record(
                "no secret in the custody record",
                all(secret not in custody_text for secret in readable.values()),
                "custody.json carries fingerprints only",
            )

        print("selftest: a minted key really attests a real run")
        if root is None:
            record("attestation round-trip", False, "no project root to import from")
        else:
            try:
                rows, attested, good, bad = _attest_roundtrip(
                    root,
                    workspace,
                    load_secret(scratch_keys, "live-runtime"),
                    mint_secret(),
                )
            except Exception as exc:  # noqa: BLE001 - selftest reports, never masks
                record("attestation round-trip", False, f"{type(exc).__name__}: {exc}")
            else:
                good_refused, good_detail = good
                bad_refused, bad_detail = bad
                record(
                    "collector produced the live rows",
                    rows > 0 and attested == rows,
                    f"{attested} of {rows} rows attested",
                )
                record(
                    "correct key authenticates every row",
                    not good_refused,
                    good_detail,
                )
                record(
                    "wrong key authenticates nothing",
                    bad_refused,
                    f"foreign key refused: {bad_detail}",
                )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    ok = all(good for _label, good, _detail in checks)
    print(f"selftest: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return ok


def mint(key_dir: Path, *, force: bool) -> int:
    root = find_repo_root()
    try:
        assert_safe_key_dir(key_dir, root)
    except CeremonyRefusal as exc:
        print(f"ABORT: {exc}")
        return 2

    existing = [
        name
        for name in (*COLUMN_FILENAME.values(), CUSTODY_FILENAME)
        if (key_dir / name).exists()
    ]
    if existing and not force:
        print(f"ABORT: {key_dir} already holds key material: {', '.join(sorted(existing))}")
        print("Refusing to overwrite. Bundles signed with those keys would stop verifying.")
        print("To rotate deliberately, re-run with --force and re-attest every column.")
        return 2

    secrets_by_column = {column: mint_secret() for column in COLUMN_KEY_ENV}
    notes = write_keys(key_dir, secrets_by_column)

    print(f"\nMINTED {len(secrets_by_column)} production column keys in {key_dir}\n")
    for note in notes:
        print(f"  {note}")
    print("\nFingerprints (safe to publish; they appear in every bundle):")
    for column, secret in sorted(secrets_by_column.items()):
        print(f"  {column:<24} key_sha256={fingerprint(secret)}")

    print("\nCUSTODY")
    print("  * This material is production custody. Keep it off the project tree,")
    print("    out of version control, out of chat, and out of CI logs.")
    print("  * The scheme is symmetric HMAC: whoever can verify can also forge.")
    print("    Treat a verifier copy of the key as a signer copy.")
    print("  * Back the directory up somewhere equally protected. Losing a key means")
    print("    re-attesting that column from its retained run directory.")
    print("  * Never print the files. Load them with the commands below, which put")
    print("    the value into the environment without echoing it.")

    print("\nLOAD (in the shell that will run the attestation)")
    for line in _loader_lines(key_dir):
        print(line)

    print("\nATTEST (the live column, once the run directory exists)")
    print("  python -m daedalus.runtimes.live_fault_attestation_issuer issue \\")
    print("    --run-dir runs/<run>/live --source-revision <head> \\")
    print("    --issuer-id <live-issuer-id> --key-id <live-key-id> \\")
    print(f"    --live-key-env {COLUMN_KEY_ENV['live-runtime']} \\")
    print("    --key-class production --output runs/<run>/live-attestations.json")
    print("\n  The other two columns take --host-key-env / --fixture-key-env with")
    print(
        f"  {COLUMN_KEY_ENV['linux-host']} and {COLUMN_KEY_ENV['deterministic-fixture']}."
    )

    print("\nROLLBACK")
    print(f"  Delete {key_dir}. Nothing in the repository points at it, so removal")
    print("  breaks no build; it only invalidates bundles already signed with these")
    print("  keys, which must then be re-attested from their retained run dirs.")
    return 0


def show(key_dir: Path) -> int:
    custody_path = key_dir / CUSTODY_FILENAME
    if not custody_path.is_file():
        print(f"no ceremony has been performed in {key_dir}")
        return 1
    payload = json.loads(custody_path.read_text(encoding="utf-8"))
    print(f"custody record: {custody_path}")
    print(f"  created_at: {payload.get('created_at')}")
    print(f"  host:       {payload.get('host')}")
    print(f"  key_class:  {payload.get('key_class')}")
    for column, row in sorted(payload.get("columns", {}).items()):
        present = (key_dir / row["file"]).is_file()
        state = "present" if present else "MISSING"
        matches = ""
        if present:
            actual = fingerprint(load_secret(key_dir, column))
            matches = " (fingerprint matches)" if actual == row["key_sha256"] else " (FINGERPRINT DRIFT)"
        print(f"  {column:<24} env={row['env']:<32} {state}{matches}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Owner-run ceremony that mints the production signing keys for the "
            "runtime fault matrix columns, outside the repository."
        )
    )
    parser.add_argument(
        "command", choices=("selftest", "mint", "show"), help="what to do"
    )
    parser.add_argument(
        "--key-dir",
        type=Path,
        default=default_key_dir(),
        help="where the production material lives (default: %(default)s)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rotate: overwrite existing material and accept the re-attestation cost",
    )
    args = parser.parse_args(argv)

    if args.command == "selftest":
        return 0 if selftest(args.key_dir) else 1
    if args.command == "mint":
        return mint(args.key_dir, force=args.force)
    return show(args.key_dir)


if __name__ == "__main__":
    raise SystemExit(main())
