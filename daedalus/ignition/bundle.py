"""The Gate-1 evaluator bundle: everything that decides, named by its bytes.

WHAT THIS CLOSES
----------------
Two Codex reviews of the ignition slice (2026-08-23) ended INCONCLUSIVE for the
same structural reason twice:

    the seal authenticates a PATH, not a proposition
    report_sha256 omits the evaluator's own revision, so evaluator drift can
    masquerade as stability

Both are the same gap wearing two hats. The receipt could say "the criterion is
outside the candidate's write scope" and "the two runs agree", and both
statements stayed true while the thing doing the judging was quietly replaced.
Every one of the spine's six seal checks measures the criterion as a blob at a
path; none of them measures WHAT it asserts, and nothing measured the evaluator
code at all.

A bundle does not solve the halting problem -- no in-tree check can read a
criterion's intent, and this module does not claim to. What it does is make
every replacement VISIBLE and every comparison scoped to one identity:

* the criterion source, by digest and by length;
* which nodes each gate is required to turn green;
* the evaluator modules that produce the verdicts, by git's content digest --
  checkout-stable, so the bundle identity does not move when a checkout rewrites
  line endings -- beside the committed blob, so an uncommitted edit to an
  evaluator is a named difference rather than an invisible one, and beside the
  raw bytes that actually executed, marked platform-dependent;
* the toolchain that executed them.

The bundle digest then binds into the receipt and into the replay comparison:
two runs are a replay only under one bundle. A changed bundle is reported like
a changed criterion -- named, and refused as a replay -- rather than averaged
into "stable".

WHAT A BUNDLE IS NOT
--------------------
It is not an approval. Pinning is not owner sign-off, and this module mints no
policy: it computes an identity and says what went into it. Whether a given
bundle digest is the APPROVED one is a decision above this code, and the
receipt carries the digest so that decision has something to name.

It is also not a security boundary. Anything that can edit the evaluators can
edit this module; the bundle makes the edit loud, not impossible.
"""
from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.spine.envelope import canonical_sha

#: The modules whose bytes decide a Gate-1 verdict. Deliberately explicit
#: rather than "everything imported": a list derived from imports would grow
#: with every refactor and make the bundle digest churn for reasons that have
#: nothing to do with judging. These are the files that produce or gate a
#: verdict; a reviewer can check the list against the receipt's evaluator names.
EVALUATOR_MODULES: tuple[str, ...] = (
    "daedalus/ignition/checks.py",        # pytest / schema / link evaluators
    "daedalus/ignition/gate1.py",         # the gates, the derivations, the receipt
    "daedalus/ignition/runner.py",        # the graph delta and behaviour readings
    "daedalus/ignition/bundle.py",        # this file: it names the others
    "daedalus/twin/reference_compiler.py",  # the cross-plane verifier
    "daedalus/spine/receipts.py",         # evaluator_assurance and the seal
)

SCHEMA = "daedalus-gate1-evaluator-bundle/1"


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _blob_shas(repo_root: Path, rel: str) -> tuple[str | None, str | None]:
    """(working-tree blob sha, committed blob sha) -- GIT's digests, not raw
    file digests, and the difference is load-bearing on this platform.

    ``git hash-object`` applies the same filters ``git add`` would, so a
    checkout that rewrote line endings produces the SAME blob sha as the commit
    it came from. Hashing raw bytes instead reported every evaluator as
    "uncommitted" on a clean Windows checkout (measured 2026-08-23: autocrlf
    gives the working file CRLF while ``git show HEAD:`` yields LF), which is a
    signal that fires always and therefore says nothing.

    The raw bytes still get recorded, separately and marked platform-dependent:
    they are what actually executed, and the ignition fixture's CRLF defect was
    exactly a case where raw bytes and git content disagreed.
    """

    working = _git(repo_root, "hash-object", "--", rel)
    committed = _git(repo_root, "rev-parse", f"HEAD:{rel}")
    return working, committed


def _module_to_rel(root: Path, module: str) -> str | None:
    """The in-repo file a dotted module name refers to, or None when it is not
    in this repository (stdlib, site-packages, a name that is not a module)."""

    parts = module.split(".")
    for candidate in (root.joinpath(*parts).with_suffix(".py"),
                      root.joinpath(*parts, "__init__.py")):
        if candidate.is_file():
            try:
                return candidate.relative_to(root).as_posix()
            except ValueError:
                return None
    return None


def _imports_of(root: Path, rel: str) -> set[str]:
    """Dotted names imported by one file, read from its AST rather than by
    importing it: hashing must not execute the code it is about to describe."""

    try:
        tree = ast.parse((root / rel).read_text(encoding="utf-8"), filename=rel)
    except (OSError, SyntaxError, UnicodeError):
        return set()
    names: set[str] = set()
    package = rel[: -len("/__init__.py")] if rel.endswith("__init__.py") else rel[: -len(".py")]
    package_parts = package.split("/")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # level 1 means "the package this file lives in". For a module
                # that is parts minus the module itself; for an __init__ the
                # package IS the file's directory, so one fewer is stripped.
                # Measured 2026-08-23: the first version had these the wrong way
                # round and silently dropped `from ._reference_claims import ...`
                # -- the exact module Codex named as escaping the digest.
                strip = node.level - (1 if rel.endswith("__init__.py") else 0)
                base = package_parts[: len(package_parts) - strip] if strip >= 0 else package_parts
                prefix = ".".join(base)
            else:
                prefix = ""
            module = ".".join(part for part in (prefix, node.module or "") if part)
            if module:
                names.add(module)
                # `from x import y` may name a submodule rather than an object
                names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def import_closure(root: Path, roots: Sequence[str]) -> tuple[str, ...]:
    """Every in-repo module reachable by import from the evaluator roots.

    WHY THE CLOSURE AND NOT THE ROOTS. Codex round 3, 2026-08-23: the roots are
    wrappers. ``reference_compiler`` delegates the actual cross-plane verdict to
    ``_reference_claims.verify_claims``; changing THAT could accept an invalid
    Fourfold while every root's digest stayed put. A judge is its transitive
    code, so the identity has to be too.

    MEASURED on this tree: the closure is 124 modules, essentially the daedalus
    package. That is not a mistake in the measurement -- the evaluators really
    do reach that far -- and it is why the closure is recorded as its own digest
    beside the roots rather than replacing them: a reviewer reads the six roots,
    and the digest still moves when anything they reach changes.
    """

    seen: set[str] = {rel for rel in roots if (root / rel).is_file()}
    queue = list(seen)
    while queue:
        rel = queue.pop()
        for module in _imports_of(root, rel):
            target = _module_to_rel(root, module)
            if target and target not in seen:
                seen.add(target)
                queue.append(target)
    return tuple(sorted(seen))


def _blob_shas_bulk(repo_root: Path, rels: Sequence[str]) -> dict[str, str | None]:
    """``git hash-object`` for many paths in one call.

    124 separate subprocesses cost more than the rest of the bundle put
    together on this platform; --stdin-paths answers them all at once.
    """

    if not rels:
        return {}
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "hash-object", "--stdin-paths"],
            input="\n".join(rels) + "\n", capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return {rel: None for rel in rels}
    if proc.returncode != 0:
        return {rel: None for rel in rels}
    lines = proc.stdout.split()
    if len(lines) != len(rels):
        return {rel: None for rel in rels}
    return dict(zip(rels, lines))


def _toolchain() -> dict[str, str]:
    try:
        import pytest  # noqa: PLC0415 - read at bundle time on purpose

        pytest_version = str(pytest.__version__)
    except Exception:  # noqa: BLE001 - an absent pytest is a fact, not a crash
        pytest_version = "unavailable"
    return {
        "python": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "pytest": pytest_version,
    }


def evaluator_bundle(
    repo_root: str | Path,
    *,
    criterion_path: str,
    criterion_source: str,
    node_ids: Mapping[str, Sequence[str]],
    modules: Sequence[str] = EVALUATOR_MODULES,
) -> dict[str, Any]:
    """Everything that decides a Gate-1 verdict, with its digest.

    The returned mapping is the record; ``bundle["digest"]`` is its identity.
    Nothing here reads the candidate or the fixture: a bundle describes the
    JUDGE, and mixing the judged into it would make every candidate its own
    bundle and the comparison meaningless.
    """

    root = Path(repo_root).resolve()
    criterion_bytes = criterion_source.encode("utf-8")
    evaluators: dict[str, Any] = {}
    for rel in sorted(modules):
        path = root / rel
        try:
            raw = _sha256_bytes(path.read_bytes())
        except OSError:
            raw = None
        working, committed = _blob_shas(root, rel)
        evaluators[rel] = {
            # git's content identity: checkout-stable, so the bundle digest is
            # the same on any machine at the same revision
            "blob_sha1": working,
            "committed_blob_sha1": committed,
            # the bytes that actually executed. NOT part of the identity
            # (line-ending translation would move it per checkout) and recorded
            # because the fixture's CRLF defect was exactly a disagreement
            # between raw bytes and git content.
            "running_bytes_sha256": raw,
            "platform_dependent": True,
            # THE ONE THAT MATTERS FOR A REVIEWER. During development an
            # uncommitted evaluator is normal; what is not normal is a receipt
            # that reads as pinned while the code that judged is not the code
            # anyone can fetch.
            # A MISSING COMMITTED SHA IS NOT A CLEAN ONE. Outside git, in an
            # unborn repository, or for an untracked evaluator, `rev-parse
            # HEAD:path` fails while `hash-object` still answers -- and the
            # first version read that as committed (Codex round 3, 2026-08-23).
            "uncommitted": bool(working and working != committed),
            "unreadable": raw is None or working is None,
        }

    closure_rels = import_closure(root, tuple(modules))
    closure_shas = _blob_shas_bulk(root, closure_rels)
    closure = {
        "count": len(closure_rels),
        "modules": closure_shas,
        "unreadable": sorted(rel for rel, sha in closure_shas.items() if sha is None),
    }
    closure["digest"] = canonical_sha(
        {"schema": "daedalus-gate1-evaluator-closure/1", "modules": closure_shas}
    )
    identity_evaluators = {
        rel: {"blob_sha1": row["blob_sha1"]} for rel, row in evaluators.items()
    }
    body = {
        "schema": SCHEMA,
        "criterion": {
            "path": criterion_path,
            "sha256": _sha256_bytes(criterion_bytes),
            "bytes": len(criterion_bytes),
            # the canonical digest the slice already reported, kept so a reader
            # can tie the bundle to the receipt's before_state without arithmetic
            "canonical_sha256": canonical_sha({"source": criterion_source}),
        },
        "nodes": {gate: list(ids) for gate, ids in sorted(node_ids.items())},
        "evaluators": evaluators,
        "closure": closure,
        "toolchain": _toolchain(),
    }
    # THE DIGEST IS OVER CONTENT IDENTITY ONLY -- the criterion, the node
    # selection, the evaluators' git blob shas and the toolchain. The raw-byte
    # digests and the uncommitted flags are recorded but excluded: they move
    # with the checkout and with the developer's working tree, and a bundle
    # identity that changes when nobody changed a judge is an identity nobody
    # can compare against.
    body["digest"] = canonical_sha({
        "schema": SCHEMA,
        "criterion": body["criterion"],
        "nodes": body["nodes"],
        "evaluators": identity_evaluators,
        "closure_digest": closure["digest"],
        "toolchain": body["toolchain"],
    })
    body["fully_committed"] = (
        not any(row["uncommitted"] or row["unreadable"] for row in evaluators.values())
        and not closure["unreadable"]
    )
    return body


def bundle_blockers(bundle: Mapping[str, Any]) -> list[str]:
    """What about this bundle stops a receipt from claiming a pinned evaluator.

    An unreadable evaluator is refused: a verdict produced by code the bundle
    could not read is not a pinned verdict. An UNCOMMITTED evaluator is NOT
    refused -- that is the normal state of a working tree, and blocking it would
    make the slice unrunnable during the very development it exists to serve --
    but it is named, so nothing downstream may read the receipt as pinned.
    """

    out: list[str] = []
    unreadable = sorted(
        rel for rel, row in (bundle.get("evaluators") or {}).items() if row.get("unreadable")
    ) + list((bundle.get("closure") or {}).get("unreadable") or ())
    if unreadable:
        out.append(
            "the evaluator bundle could not read " + ", ".join(unreadable)
            + "; a verdict produced by code the bundle cannot name is not pinned"
        )
    if not bundle.get("digest"):
        out.append("the evaluator bundle has no digest; nothing identifies what judged")
    return out


__all__ = [
    "EVALUATOR_MODULES",
    "import_closure",
    "SCHEMA",
    "bundle_blockers",
    "evaluator_bundle",
]
