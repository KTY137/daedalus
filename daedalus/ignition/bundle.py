# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
import importlib.metadata
import json
import os
import platform
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

SCHEMA = "daedalus-gate1-evaluator-bundle/2"


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


def _pytest_plugins() -> tuple[list[dict[str, str]] | None, str | None]:
    """Installed pytest plugins, by distribution name and version.

    Read via the ``pytest11`` entry-point group -- the mechanism pytest itself
    uses to discover plugins -- rather than by importing pytest and inspecting
    a live PluginManager, so this is a fact about what is INSTALLED and does
    not require a pytest run to already be underway.

    Returns ``(plugins, error)``. ``plugins`` is ``None``, not ``[]``, when the
    query itself failed, so an environment with zero plugins reads as
    "measured: none installed" and a broken query reads as "could not
    measure" -- conflating the two is the exact defect this project has hit
    before (dominance analysis reading ``declared: 0`` as an answer instead of
    a limit). An empty ``[]`` is therefore a real, trustworthy measurement.
    """

    try:
        eps = importlib.metadata.entry_points(group="pytest11")
    except Exception as exc:  # noqa: BLE001 - a metadata failure is a fact to report
        return None, f"{type(exc).__name__}: {exc}"
    plugins: dict[str, str] = {}
    for ep in eps:
        try:
            dist = ep.dist
            name = dist.name if dist is not None else ep.name
            version = dist.version if dist is not None else "unknown"
        except Exception:  # noqa: BLE001 - one bad entry point must not blank the rest
            name, version = ep.name, "unknown"
        plugins[name] = version
    ordered = [{"name": name, "version": plugins[name]} for name in sorted(plugins)]
    return ordered, None


def _conftest_candidates(start: Path, rel_target: str) -> list[Path]:
    """Directories pytest walks for ``conftest.py`` while collecting one file.

    Every directory from ``start`` (the invocation root) down through each
    path segment of ``rel_target``, inclusive -- the part of pytest's conftest
    discovery that is stable across pytest versions and does not depend on
    ini-file/rootdir inference. This project's criterion is one flat file one
    directory below the invocation root, so this is the part of pytest's rule
    that actually varies here; it does not reimplement pytest's full
    rootdir/confcutdir search (ini-file discovery, cwd-vs-arg common
    ancestor), and does not claim to.
    """

    parts = Path(rel_target).parts[:-1]
    out = [start]
    cur = start
    for part in parts:
        cur = cur / part
        out.append(cur)
    return out


def _conftest_chain(root: Path, rel_target: str) -> dict[str, Any]:
    """The conftest.py discovery path for one criterion, named and hashed.

    A conftest.py is never reached by :func:`import_closure` -- pytest loads it
    by directory position, not by any ``import`` statement an evaluator module
    writes -- so it is invisible to the rest of this module by construction.
    This is the part that makes it visible: which directories were checked,
    which exist, and the digest of any ``conftest.py`` found there.

    A directory that does not exist on ``root`` is recorded as such rather than
    as "checked, no conftest.py found" -- for the real Gate-1 fixture, the
    ``tests/`` directory in the source template does not exist until
    :func:`daedalus.ignition.gate1.prepare_ignition_repo` creates it and writes
    exactly one file into it, so "does not exist here" is not a gap in this
    check; it is the same fact the check would report after that directory is
    created, since nothing else ever writes into it.
    """

    entries: list[dict[str, Any]] = []
    for directory in _conftest_candidates(root, rel_target):
        try:
            rel_dir = directory.relative_to(root).as_posix() or "."
        except ValueError:
            rel_dir = str(directory)
        if not directory.is_dir():
            entries.append({"dir": rel_dir, "exists": False, "conftest_sha256": None})
            continue
        conftest = directory / "conftest.py"
        sha: str | None = None
        if conftest.is_file():
            try:
                sha = _sha256_bytes(conftest.read_bytes())
            except OSError:
                sha = None
        entries.append({"dir": rel_dir, "exists": True, "conftest_sha256": sha})
    return {"target": rel_target, "candidates": entries}


def _environment_fingerprint(fixture_root: Path, criterion_path: str) -> dict[str, Any]:
    """Everything about the RUNNING environment a Gate-1 verdict depends on
    besides python and pytest's own version (:func:`_toolchain` already names
    those): installed pytest plugins, ``PYTHONPATH``, the conftest.py
    discovery path for the criterion, and the OS/platform -- the exact axis
    the CRLF bug (2026-08-23) moved along, measured here rather than assumed
    stable.
    """

    plugins, plugins_error = _pytest_plugins()
    conftest_chain = _conftest_chain(fixture_root, criterion_path)
    body: dict[str, Any] = {
        "schema": "daedalus-gate1-environment-fingerprint/1",
        "platform": platform.platform(),
        "python_version": sys.version,
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "pytest_plugins": plugins,
        "pytest_plugins_measured": plugins is not None,
        "pytest_plugins_error": plugins_error,
        "conftest_chain": conftest_chain,
    }
    body["digest"] = canonical_sha({
        "schema": body["schema"],
        "platform": body["platform"],
        "python_version": body["python_version"],
        "pythonpath": body["pythonpath"],
        "pytest_plugins": body["pytest_plugins"],
        "conftest_chain": body["conftest_chain"],
    })
    return body


def bundle_digest_from_body(body: Mapping[str, Any]) -> str:
    """The bundle digest, as a function of a stored BODY alone.

    :func:`evaluator_bundle` calls this exact function to MINT the digest, and
    a reader who holds only a retrieved bundle artifact -- no live tree, no git
    call, nothing beyond the artifact's own JSON -- calls it again to verify
    one. One formula, used both times, rather than two formulas trusted to
    keep agreeing.
    """

    identity_evaluators = {
        rel: {"blob_sha1": row.get("blob_sha1")}
        for rel, row in (body.get("evaluators") or {}).items()
    }
    return canonical_sha({
        "schema": body.get("schema"),
        "criterion": body.get("criterion"),
        "nodes": body.get("nodes"),
        "evaluators": identity_evaluators,
        "closure_digest": (body.get("closure") or {}).get("digest"),
        "toolchain": body.get("toolchain"),
        "environment_fingerprint_digest": (
            (body.get("environment_fingerprint") or {}).get("digest")
        ),
    })


def write_bundle_artifact(bundle: Mapping[str, Any], out_dir: str | Path) -> Path:
    """Write the bundle as ONE retrievable, content-addressed file.

    Closes the third named gap: until this, a bundle's identity was computed
    and asserted at run time, with no artifact a reader could fetch and hold
    that IS the bundle, as opposed to re-deriving it against a live tree. The
    filename carries the digest; :func:`bundle_digest_from_body` recomputes it
    from the file's own parsed content, so a caller can verify the artifact
    names itself without touching git or the working tree at all.
    """

    digest = bundle.get("digest")
    if not digest:
        raise ValueError("cannot write an artifact for a bundle with no digest")
    directory = Path(out_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"evaluator-bundle-{digest}.json"
    path.write_text(
        json.dumps(dict(bundle), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_bundle_artifact(path: str | Path) -> dict[str, Any]:
    """Read a bundle artifact back. The only I/O :func:`bundle_digest_from_body`
    needs is this -- everything after is pure computation over the parsed
    JSON."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluator_bundle(
    repo_root: str | Path,
    *,
    criterion_path: str,
    criterion_source: str,
    node_ids: Mapping[str, Sequence[str]],
    modules: Sequence[str] = EVALUATOR_MODULES,
    fixture_root: str | Path | None = None,
) -> dict[str, Any]:
    """Everything that decides a Gate-1 verdict, with its digest.

    The returned mapping is the record; ``bundle["digest"]`` is its identity.
    Nothing here reads the candidate or the fixture: a bundle describes the
    JUDGE, and mixing the judged into it would make every candidate its own
    bundle and the comparison meaningless.

    ``fixture_root`` names where the criterion's conftest.py discovery path is
    rooted (see :func:`_conftest_chain`); it defaults to ``repo_root`` for
    every caller that has no separate fixture tree -- every existing test
    repo in this module's own suite included -- and Gate-1 passes the real
    fixture source directory explicitly.
    """

    root = Path(repo_root).resolve()
    fixture_dir = Path(fixture_root).resolve() if fixture_root is not None else root
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
    environment_fingerprint = _environment_fingerprint(fixture_dir, criterion_path)
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
        "environment_fingerprint": environment_fingerprint,
    }
    # THE DIGEST IS OVER CONTENT IDENTITY ONLY -- the criterion, the node
    # selection, the evaluators' git blob shas, the toolchain and the
    # environment fingerprint. The raw-byte digests and the uncommitted flags
    # are recorded but excluded: they move with the checkout and with the
    # developer's working tree, and a bundle identity that changes when nobody
    # changed a judge is an identity nobody can compare against. The
    # environment fingerprint's own digest IS included -- a different plugin
    # set or a different conftest.py chain changed what actually judged, the
    # same way a different evaluator module would.
    #
    # Computed by :func:`bundle_digest_from_body`, the SAME function a reader
    # of a stored artifact calls to verify one -- not a second formula kept in
    # sync with this one by hand. It only reads ``identity_evaluators``, not
    # the fuller ``evaluators`` block by that name, which is why it is
    # substituted in below rather than looked up.
    body["digest"] = bundle_digest_from_body({**body, "evaluators": identity_evaluators})
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

    An unmeasurable environment fingerprint (the plugin query itself failed) is
    refused the same way an unreadable evaluator is: a bundle that cannot name
    the environment it ran in must say so rather than silently omit the field,
    per the same rule an empty measurement and a failed one must stay
    distinguishable everywhere in this project.
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
    environment = bundle.get("environment_fingerprint") or {}
    if environment and environment.get("pytest_plugins_measured") is False:
        out.append(
            "the evaluator bundle could not measure installed pytest plugins ("
            + str(environment.get("pytest_plugins_error")) + "); an environment "
            "the bundle cannot name is not pinned"
        )
    if not bundle.get("digest"):
        out.append("the evaluator bundle has no digest; nothing identifies what judged")
    return out


__all__ = [
    "EVALUATOR_MODULES",
    "import_closure",
    "SCHEMA",
    "bundle_blockers",
    "bundle_digest_from_body",
    "evaluator_bundle",
    "load_bundle_artifact",
    "write_bundle_artifact",
]
