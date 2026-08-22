"""Canonicalise one finished spine attempt into the Gate-0 contracts.

WHY THIS MODULE EXISTS
----------------------
``daedalus/schemas.py`` has carried ``AttemptContract``, ``EvidencePacket``,
``AttemptReceipt`` and ``PolicyDecision`` -- with adapters
(``from_task_spec``, ``from_attempt_result``) written specifically for the
legacy spine records -- and nothing on the live path ever called them. A
contract with no producer is a schema, not a kernel: Invariant 1 ("Mission,
Attempt, Evidence, Campaign, policy decisions, budgets and promotion status
have ONE canonical contract and event spine") was unmet exactly where it is
supposed to hold. This module is the missing call.

WHAT IT IS NOT
--------------
It is not a second kernel, a second event store, a second artifact identity, or
a promotion path. It has no state, opens no database, writes no file and starts
no effect. Every record it returns is inert data built from an attempt that has
ALREADY finished, using the adapters that already live in the schema. The
caller -- :class:`daedalus.spine.attempt.TaskAttempt` -- persists them into the
one existing spine ledger row it was already writing.

WHAT IT DELIBERATELY REFUSES
----------------------------
A canonical contract that cannot be built honestly is not built at all:

* a task with no declared ``target_paths`` gets no write-capable contract (the
  schema's own refusal -- an unbounded write cannot masquerade as bounded);
* an attempt with no content-addressed store gets no ``EvidencePacket``, because
  ``EvidenceItem`` requires a durable locator for the gate output and inventing
  one would be a fabricated evidence reference;
* an attempt whose gate output was never retained gets no evidence item.

Each refusal is REPORTED (``AttemptContractSet.error``), never swallowed and
never papered over with a placeholder digest.
"""
from __future__ import annotations

import os
import posixpath
import re
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, Mapping, Sequence

from daedalus.schemas import (
    AttemptContract,
    AttemptReceipt,
    ContractProvenance,
    EffectScope,
    EvidencePacket,
    MissionContract,
    PolicyDecision,
    ResourceBudget,
    ResourceUsage,
    RuntimeCapabilities,
    RuntimeManifest,
)


#: The effect-boundary row this spine is registered under. Its ``wiring`` is
#: CENTRAL. ``TaskAttempt.run`` enters ``begin_effect`` before the intent, the
#: worktree, the runner and the gate, so a boundary receipt EXISTS for this path
#: and :func:`attempt_policy_decision` takes it as its source: the reasons are
#: the receipt's own guard evidence and ``policy_sha256`` is the receipt's
#: registry digest, not a second independent read of the same registry. The
#: locally-derived reason list below stays as corroboration -- it names the
#: bounds this projection itself asserts (spend, wall time), which the boundary
#: does not decide.
ATTEMPT_ENTRYPOINT_ID = "python.attempt"

ATTEMPT_ORIGIN = "daedalus.spine.attempt.TaskAttempt"
ATTEMPT_RUNTIME_ID = "spine.attempt.harness"
ATTEMPT_KILL_SWITCH_REF = "daedalus.spine.killswitch"

#: The exact wording that travels INSIDE the PolicyDecision digest. Reasons are
#: part of the contract, so a limitation stated here cannot be lost between the
#: record and its reader -- which is the only reason it is a constant and not a
#: comment.
UNMETERED_SPEND_REASON = (
    "attempt spine does not meter model spend or tokens: usage.cost_microusd "
    "and usage.input_tokens/output_tokens are 0 because nothing measured them, "
    "not because zero was measured"
)
GATE_WALL_BOUND_REASON = (
    "budget.max_wall_time_s defaults to the GATE timeout and usage.wall_time_ms "
    "is the GATE's measured duration; the injected runner's wall time is "
    "outside this bound and is not counted against it"
)
SPEND_GRANT_REASON = (
    "effect_scope.max_cost_microusd is the spend THIS decision grants; the "
    "injected runner's own effect boundary (daedalus.offload) carries its lease "
    "and its spend, and this scope neither bounds nor meters that"
)
#: Replaces :data:`UNMETERED_SPEND_REASON` -- and ONLY that line -- for an
#: attempt that arrives with shed telemetry. The moment
#: ``usage.est_input_tokens``
#: stops being 0, the unmetered wording becomes a false statement inside a
#: digested contract, so the swap is not decoration: it is what keeps the record
#: honest. The replacement states the estimator by name, because an over-count
#: from cl100k is not a server-reported token count and must never be read as
#: one (Invariant 9, honest claims).
METERED_INPUT_REASON = (
    "usage.est_input_tokens is ESTIMATED for this attempt: it is the sum of the "
    "local lane's own pre-send prompt estimates (cl100k over-count of the exact "
    "prompt text, daedalus.providers.ollama), not a server-reported token "
    "count, and it is carried in est_input_tokens rather than input_tokens so "
    "no reader can mistake the estimate for a measurement; usage.input_tokens, "
    "usage.output_tokens and usage.cost_microusd remain 0 because nothing "
    "measured them, not because zero was measured"
)
#: Stated when shed telemetry arrived but some row it should have estimated
#: reports nothing. A covariate that is silently short is worse than an absent
#: one: the sum still looks like a total. This names the gap inside the digest
#: so the shortfall travels with the record instead of being averaged away.
UNDER_METERED_INPUT_REASON = (
    "usage.est_input_tokens UNDER-REPORTS this attempt: {missing} of {total} "
    "shed-telemetry row(s) reported est_in=0 while the brief was NOT shed, so "
    "the sum is a lower bound on the prompt text that actually reached the "
    "model, not an estimate of all of it"
)
#: Stated on the evidence-side qualification that :func:`evaluator_assurance`
#: derived. It travels inside the PolicyDecision digest because the assurance
#: string alone ("unverified") does not say WHICH seal failed, and a reader who
#: cannot tell a missing criterion from a criterion the gate never read cannot
#: act on the record.
ASSURANCE_REASON_PREFIX = "evaluator assurance"

#: The fields one shed-telemetry row must carry. ``rel`` names the file whose
#: full-file prompt was built; ``brief_shed`` is whether the structural brief
#: was dropped to fit the local context window; ``est_in`` is the token estimate
#: the shed decision was MADE on (brief still in the prompt), i.e. the treatment
#: assignment variable; ``brief_bytes`` is the UTF-8 size of the brief that
#: actually reached the model.
SHED_TELEMETRY_FIELDS = ("rel", "brief_shed", "est_in", "brief_bytes")


def normalise_shed_telemetry(rows: Any) -> tuple[dict[str, Any], ...]:
    """Validate the local lane's brief-shed rows into wire-safe records.

    WHY IT REFUSES INSTEAD OF COERCING. These rows become the covariate a
    graph-conditioning comparison is read against, and one of them fills
    ``usage.est_input_tokens`` inside a digested receipt. A row that cannot be
    trusted must not be silently repaired into a plausible number: the caller
    (:func:`canonicalise_attempt`) turns the refusal into a reported error on
    the contract set, which is visible, rather than into a measurement nobody
    can trace.
    """

    if rows is None:
        return ()
    if isinstance(rows, (str, bytes, Mapping)):
        raise ValueError("shed_telemetry must be a sequence of rows")
    normalised: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"shed_telemetry[{index}] must be an object")
        missing = [name for name in SHED_TELEMETRY_FIELDS if name not in row]
        if missing:
            raise ValueError(
                f"shed_telemetry[{index}] is missing {', '.join(missing)}"
            )
        shed = row["brief_shed"]
        if not isinstance(shed, bool):
            raise ValueError(f"shed_telemetry[{index}].brief_shed must be boolean")
        numbers: dict[str, int] = {}
        for name in ("est_in", "brief_bytes"):
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"shed_telemetry[{index}].{name} must be a non-negative integer"
                )
            numbers[name] = value
        # A shed brief reached the model as ZERO bytes, by construction. A row
        # claiming both is not a rounding error, it is two different runs mixed
        # into one record -- exactly the confound this telemetry exists to
        # prevent -- so it is refused rather than averaged.
        if shed and numbers["brief_bytes"]:
            raise ValueError(
                f"shed_telemetry[{index}] shed the brief and still reports "
                f"{numbers['brief_bytes']} injected brief bytes"
            )
        rel = str(row["rel"]).strip()
        if not rel:
            raise ValueError(f"shed_telemetry[{index}].rel must be a non-empty path")
        normalised.append(
            {
                "rel": rel,
                "brief_shed": shed,
                "est_in": numbers["est_in"],
                "brief_bytes": numbers["brief_bytes"],
            }
        )
    return tuple(normalised)


@lru_cache(maxsize=1)
def _policy_registry_sha256() -> str:
    """The declared effect-boundary registry digest, read lazily.

    Lazy because ``effect_boundary`` is a large module and this one is imported
    from the attempt hot path; cached because the registry is a module constant.
    """

    from daedalus.spine.effect_boundary import registry_sha256

    return registry_sha256()


def _identifier_fragment(text: str, fallback: str) -> str:
    cleaned = "".join(
        char if (char.isalnum() or char in "._:/-") else "-" for char in str(text)
    ).strip("-")
    while cleaned and not cleaned[0].isalnum():
        cleaned = cleaned[1:]
    return cleaned[:200] or fallback


def adapter_identity(runner: Any) -> str:
    """Name the injected runner as an adapter id, without importing it."""

    module = getattr(runner, "__module__", "") or ""
    qualname = getattr(runner, "__qualname__", "") or type(runner).__name__
    return _identifier_fragment(f"{module}.{qualname}", "unknown-adapter")


def attempt_runtime_manifest(
    *,
    source_revision: str,
    created_at: str,
    adapter_id: str,
    trace_id: str | None = None,
    runtime_id: str = ATTEMPT_RUNTIME_ID,
) -> RuntimeManifest:
    """Declare the harness the attempt actually ran in.

    ``assurance`` is "declared" and the schema allows nothing else here: these
    are the capabilities the attempt harness EXPRESSES, and a conformance
    receipt -- not this manifest -- is what would turn any of them into a
    measurement. The capabilities below are structural properties of
    :class:`~daedalus.spine.attempt.TaskAttempt`, not aspirations: it runs the
    candidate in a git worktree outside the primary checkout
    (``isolated-worktree``), kills its gate on a timeout, and honours a cancel
    predicate. It does not stream, does not emit provider-neutral tool events,
    does not parse structured output and does not report cost.
    """

    capabilities = RuntimeCapabilities(
        streaming=False,
        tool_events=False,
        structured_output=False,
        timeout=True,
        cancellation=True,
        workspace_isolation=True,
        cost_reporting=False,
        workspace_write=True,
    )
    return RuntimeManifest(
        runtime_id=runtime_id,
        runtime_version=(
            f"python-{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}"
        ),
        adapter_id=adapter_id,
        # The adapter's version IS the source revision it was read from: this
        # harness ships with the repository, so there is no separate release
        # number that could drift away from the code that ran.
        adapter_version=source_revision,
        source_revision=source_revision,
        assurance="declared",
        capabilities=capabilities,
        declared_tools=(),
        egress_transports=(),
        workspace_modes=("isolated-worktree", "read-only"),
        cost_model="unmetered",
        provenance=ContractProvenance(
            origin=ATTEMPT_ORIGIN,
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(),
            trace_id=trace_id,
        ),
    )


def attempt_policy_decision(
    *,
    decision_id: str,
    subject_id: str,
    subject_sha256: str,
    source_revision: str,
    created_at: str,
    verdict: str,
    reasons: Sequence[str],
    writable_paths: Sequence[str] = (),
    timeout_s: int | None = None,
    spend_grant_microusd: int = 0,
    trace_id: str | None = None,
    boundary_receipt: Any = None,
) -> PolicyDecision:
    """Record the decision the attempt spine itself made.

    THE BOUNDARY RECEIPT IS THE SOURCE WHEN THERE IS ONE. ``boundary_receipt``
    is the :class:`~daedalus.spine.effect_boundary.EffectStartReceipt` that
    ``TaskAttempt.run`` obtained from ``begin_effect`` before the first effect.
    When it is present, every guard decision it carries is written into
    ``reasons`` verbatim -- contract name and the evidence the contract itself
    produced -- and ``policy_sha256`` is the registry digest THAT RECEIPT was
    computed against, so the decision and the boundary can never name two
    different policy texts. The receipt's own ``receipt_sha256`` joins
    ``provenance.input_digests``, which is what lets a reader tie this record
    back to the exact start.

    ``None`` is still accepted and still produces a well-formed record: this
    function is also called for attempts refused before the boundary was
    reached, and by callers outside the spine. In that case the digest is read
    from the declared registry directly and the reasons are the caller's -- an
    honest, weaker record, distinguishable by the absence of the
    ``effect boundary:`` reason.

    The guards named in ``reasons`` are the ones that really run before the
    effect: the intent ledger write (no durable record, no effect), the storage
    watermark, the worktree isolation, the declared-scope check, and the
    primary-checkout write fence. Nothing here enforces anything -- the
    enforcement already happened; this is its record.
    """

    if verdict == "allow":
        scope = EffectScope(
            read_only=False,
            writable_paths=tuple(writable_paths),
            egress_endpoints=(),
            tools=(),
            secret_refs=(),
            max_cost_microusd=int(spend_grant_microusd),
            max_concurrency=1,
            timeout_s=timeout_s,
            kill_switch_ref=ATTEMPT_KILL_SWITCH_REF,
        )
    else:
        scope = EffectScope(read_only=True)
    all_reasons = list(reasons)
    digests = [subject_sha256]
    receipt_sha = str(getattr(boundary_receipt, "receipt_sha256", "") or "")
    registry_sha = str(getattr(boundary_receipt, "registry_sha256", "") or "")
    if receipt_sha and registry_sha:
        # THE RECEIPT DECIDES, and it decides first: its evidence leads the
        # reason list and its registry digest IS policy_sha256.
        all_reasons = [
            f"effect boundary: begin_effect({ATTEMPT_ENTRYPOINT_ID}) receipt "
            f"{receipt_sha}",
            *(
                f"{row.contract}: {row.evidence}"
                for row in getattr(boundary_receipt, "guard_decisions", ())
            ),
            *all_reasons,
        ]
        policy_sha = registry_sha
        digests.append(receipt_sha)
    else:
        policy_sha = _policy_registry_sha256()
    digests.append(policy_sha)
    return PolicyDecision(
        decision_id=decision_id,
        subject_id=subject_id,
        subject_sha256=subject_sha256,
        policy_version=f"effect-boundary:{ATTEMPT_ENTRYPOINT_ID}",
        policy_sha256=policy_sha,
        verdict=verdict,
        # DEDUPED, because ``PolicyDecision`` refuses a repeated reason and the
        # receipt's ``containment.attempt`` evidence can restate what the local
        # list already says. Losing the whole record to a collision between two
        # true statements would be absurd.
        reasons=tuple(dict.fromkeys(all_reasons)),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin=ATTEMPT_ORIGIN,
            source_revision=source_revision,
            created_at=created_at,
            # Same reason: on the pre-boundary path subject and policy digests
            # can coincide, and ContractProvenance refuses duplicates.
            input_digests=tuple(dict.fromkeys(digests)),
            trace_id=trace_id,
        ),
    )


def _fold_case(text: str) -> str:
    """Case-fold exactly when this host's path semantics do, keeping ``/``.

    Derived from :func:`os.path.normcase` rather than an unconditional
    ``lower()``: on a case-insensitive host ``Tests/Test_Gate.py`` and
    ``tests/test_gate.py`` ARE one file and must compare equal, while on a
    case-sensitive host they are two files and folding them together would
    refuse a genuinely disjoint criterion. ``normcase`` itself is not used
    directly because on Windows it also rewrites ``/`` to ``\\``, which would
    make the normal form uncomparable with the ``/``-spelled argv a gate
    actually ran.
    """

    return text.lower() if os.path.normcase("A") == "a" else text


def _collapse_tree_path(value: Any) -> str | None:
    """The declared path with its separators and ``.``/``..`` segments settled.

    ``None`` is not "empty", it is "this declaration has no honest normal form
    inside the tree" -- an absolute path, a drive-lettered path, or one whose
    ``..`` segments climb out of the root. Those are refused rather than
    normalised because a set-membership test between a declared write scope and
    a declared criterion is only meaningful when both name locations in the
    same tree; a path that escapes names something the scope check never
    bounded, and treating it as merely "not in the scope set" is exactly how a
    criterion inside the write scope reads as sealed.

    CASE IS DELIBERATELY NOT FOLDED HERE. This is the spelling handed to git,
    and git's trees are case-sensitive on every host, so folding first would
    make a legitimate criterion unfindable in the base revision.
    """

    text = str(value).strip().replace("\\", "/")
    if not text:
        return None
    if posixpath.isabs(text) or (len(text) > 1 and text[1] == ":"):
        return None
    collapsed = posixpath.normpath(text)
    if collapsed == "." or collapsed == ".." or collapsed.startswith("../"):
        return None
    return collapsed


def _normalise_tree_path(value: Any) -> str | None:
    """ONE canonical spelling for a repo-relative path, or ``None`` if refused.

    :func:`_collapse_tree_path` plus this host's case semantics -- the form two
    declarations are COMPARED in, as opposed to the form git is asked about.
    """

    collapsed = _collapse_tree_path(value)
    return None if collapsed is None else _fold_case(collapsed)


def criterion_probe_paths(task: Any) -> tuple[tuple[str, str], ...]:
    """``(comparison key, git-facing path)`` for each usable declared criterion.

    The seam between :func:`evaluator_assurance_detail`, which must COMPARE
    paths, and its caller, which must ASK GIT about them. Both spellings come
    out of one function so the key a presence map is written under cannot drift
    from the key the seal looks it up by -- the drift that would silently turn
    "measured present" back into "not knowable".

    A declaration with no normal form is skipped rather than probed: the seal
    refuses it on its own, with a reason naming the spelling, and asking git
    about an absolute or escaping path would be the read this module refuses to
    make on principle.
    """

    probes: list[tuple[str, str]] = []
    for raw in tuple(getattr(task, "gate_criterion_paths", ()) or ()):
        collapsed = _collapse_tree_path(raw)
        if collapsed is None:
            continue
        probes.append((_fold_case(collapsed), collapsed))
    return tuple(probes)


def _inside_scope(path: str, scope: Sequence[str]) -> bool:
    """True when ``path`` is a declared write target or lives under one.

    Prefix containment, not set membership. A task that declares ``tests/`` as
    its scope may write ``tests/test_gate.py``; comparing the two as opaque
    strings finds them disjoint and grants the criterion a seal the containment
    check never provided.
    """

    for target in scope:
        if path == target or path.startswith(target + "/"):
            return True
    return False


def containment_escapes(
    changed_paths: Sequence[Any], target_paths: Sequence[Any]
) -> tuple[tuple[str, ...], str | None]:
    """The changed paths a declared write scope does NOT cover, plus a refusal.

    THE OTHER HALF OF :func:`_inside_scope`, and it has to be the same half.
    The attempt spine's ``target-scope`` gate used to normalise with a bare
    ``.replace("\\\\", "/").removeprefix("./")`` and then test exact string
    membership against git's canonical ``changed_paths``. Two consequences, one
    silent in each direction:

    * a declaration naming a DIRECTORY (``tests``) matched nothing, so a task
      that scoped a directory had its entire patch rejected as escaped -- while
      :func:`_criterion_seal`, reading the same field through
      :func:`_inside_scope`, already treated that declaration as covering
      ``tests/test_gate.py``. One field, two meanings, and the receipt was
      written by the generous one;
    * a declaration git could never match (``C:/x``, ``../x``) simply failed to
      cover anything, which happened to be fail-closed but said nothing about
      WHY, so an operator read "changed path outside target_paths" for a patch
      that was inside the directory they meant to declare.

    Directories are therefore the accepted shape on BOTH sides, normalised by
    :func:`_normalise_tree_path` and compared on path SEGMENT boundaries: a
    declared ``tests`` covers ``tests/test_gate.py`` and never ``tests_evil.py``.
    Returns ``(escaped, declaration_error)``. A declaration with no normal form
    inside the tree yields every changed path as escaped AND a reason naming the
    spelling -- refusing the patch rather than pretending an unusable boundary
    bounded it. Escaped paths are reported in their ORIGINAL spelling, because
    that is what the operator has to go look at.
    """

    scope: list[str] = []
    for raw in target_paths:
        normalised = _normalise_tree_path(raw)
        if normalised is None:
            return (
                tuple(str(path) for path in changed_paths),
                f"declared target path {str(raw)!r} has no normal form inside "
                "the tree (absolute or root-escaping), so no changed path can "
                "be shown to be contained by it",
            )
        scope.append(normalised)
    escaped: list[str] = []
    for raw in changed_paths:
        path = _normalise_tree_path(raw)
        # A changed path with no normal form is escaped BY DEFINITION: git does
        # not produce one today, and a future producer that did must not be
        # able to slip past a boundary by spelling itself unrepresentably.
        if path is None or not _inside_scope(path, scope):
            escaped.append(str(raw))
    return tuple(escaped), None


#: Files whose presence CHANGES WHAT A CRITERION DOES without the criterion
#: naming them: pytest loads ``conftest.py`` from every directory on the
#: collection path (fixtures, hooks, collection filters, assertion rewriting),
#: reads its configuration out of the first ``pytest.ini``/``pyproject.toml``/
#: ``setup.cfg``/``tox.ini`` it finds, imports ``__init__.py`` for every package
#: directory it walks through, and CPython executes ``.pth`` files and
#: ``sitecustomize``/``usercustomize`` before any of it. A candidate allowed to
#: write one of these on the criterion's own path chain can skip the criterion,
#: monkeypatch what it asserts against, or replace the assertion machinery --
#: while the criterion file itself, which is all the seal used to look at, stays
#: byte-identical.
_EXECUTION_INFLUENCING_NAMES = frozenset({
    "conftest.py",
    "__init__.py",
    "pytest.ini",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "sitecustomize.py",
    "usercustomize.py",
})
_EXECUTION_INFLUENCING_SUFFIX = ".pth"


def _is_execution_influencing(name: str) -> bool:
    return (name in _EXECUTION_INFLUENCING_NAMES
            or name.endswith(_EXECUTION_INFLUENCING_SUFFIX))


def _chain_dirs(criterion: str) -> tuple[str, ...]:
    """Repo root down to the criterion's own directory, as normalised prefixes.

    ``"tests/unit/test_gate.py"`` yields ``("", "tests", "tests/unit")``. The
    empty string IS the repository root and is a real member: a root
    ``conftest.py`` or ``pyproject.toml`` reaches every test under it.
    """

    parts = criterion.split("/")[:-1]
    return tuple([""] + ["/".join(parts[: i + 1]) for i in range(len(parts))])


def _scope_reaches_criterion_execution(
    criterion: str, scope: Sequence[str]
) -> str | None:
    """``None`` when no scope entry can alter what ``criterion`` DOES.

    A scope entry naming an execution-influencing file that sits on the chain
    from the repository root down to the criterion's own directory -- a root
    ``pyproject.toml``, a ``tests/conftest.py`` beside the criterion, a
    ``__init__.py`` on its package path. Segment boundaries, via the same
    comparison :func:`_inside_scope` makes: ``tests`` is on the chain of
    ``tests/test_gate.py`` and ``tests_evil`` is not.

    THE OTHER HALF IS DELIBERATELY ABSENT, AND WAS MEASURED BEFORE IT WAS CUT.
    The obvious companion check -- "a scope entry that IS or CONTAINS a chain
    DIRECTORY lets the candidate create a conftest.py there" -- cannot fire.
    Every chain directory is an ancestor of the criterion, so a scope entry
    covering one covers the criterion itself, and check 2 of
    :func:`_criterion_seal` has already refused. Written, run, found to be
    unreachable on every input, and removed: a guard that can never fire reads
    like protection in a diff and provides none.
    """

    chain = set(_chain_dirs(criterion))
    for target in scope:
        head, _, name = target.rpartition("/")
        if head in chain and _is_execution_influencing(name):
            return (
                f"the declared write scope contains {target!r}, an "
                f"execution-influencing file on {criterion!r}'s own "
                "collection/import path, so the candidate can change what the "
                "criterion DOES without touching the criterion file"
            )
    return None


#: One import statement, cheaply. Deliberately a regex over lines and not an
#: ``ast`` parse: the criterion is untrusted-adjacent text read out of a git
#: blob, this runs on the receipt path of every attempt that declares one, and
#: the answer is only ever used to ADD a refusal -- so a line this misses leaves
#: the seal exactly as strong as it was before the check existed, while a parse
#: that raised on an unparseable blob would destroy a finished projection.
_IMPORT_LINE_RE = re.compile(
    r"^[ \t]*(?:"
    r"from[ \t]+(?P<pkg>\.*[A-Za-z_][A-Za-z0-9_.]*|\.+)[ \t]+import[ \t]+"
    r"(?P<names>[^#\n]*)"
    r"|import[ \t]+(?P<mods>[^#\n]*)"
    r")",
    re.MULTILINE,
)


def _tree_join(root: str, rel: str) -> str:
    return rel if not root else f"{root}/{rel}"


def _module_tree_paths(root: str, dotted: str) -> list[str]:
    """Every in-tree file importing ``dotted`` from ``root`` would EXECUTE.

    ``import a.b.c`` runs ``a/__init__.py`` and ``a/b/__init__.py`` on the way,
    so the whole prefix chain is named, not just the leaf. The leaf gets both
    spellings a module can have (``a/b/c.py`` and ``a/b/c/__init__.py``).
    """

    parts = [part for part in dotted.split(".") if part]
    if not parts:
        return []
    out = [
        _tree_join(root, "/".join(parts[: i + 1]) + "/__init__.py")
        for i in range(len(parts))
    ]
    out.append(_tree_join(root, "/".join(parts) + ".py"))
    return out


def criterion_import_probe_paths(
    source: str, criterion: str
) -> tuple[tuple[str, str], ...]:
    """``(comparison key, git-facing path)`` for what the criterion imports.

    Resolved against TWO roots -- the repository root and the criterion's own
    directory -- plus explicit relative imports, which are the three routes an
    in-tree helper module is reached by in practice. It does NOT model
    ``sys.path`` manipulation, ``src/`` layouts, installed distributions, or
    namespace packages, and saying so is the point: this is a cheap over-read
    whose hits the caller still has to confirm against the base tree, and whose
    misses cost nothing because a miss is simply the seal as it stood before.

    Same ``(key, path)`` seam as :func:`criterion_probe_paths`, for the same
    reason -- the caller asks git in the tree's spelling and the seal compares
    in this host's case semantics, and those two must not drift apart.
    """

    directory = criterion.rpartition("/")[0]
    candidates: list[str] = []
    for match in _IMPORT_LINE_RE.finditer(source):
        pkg, names, mods = match.group("pkg"), match.group("names"), match.group("mods")
        if mods is not None:
            for piece in mods.split(","):
                dotted = piece.strip().split(" as ")[0].strip()
                if not dotted or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", dotted):
                    continue
                for root in ("", directory):
                    candidates.extend(_module_tree_paths(root, dotted))
            continue
        dots = len(pkg) - len(pkg.lstrip("."))
        stem = pkg[dots:]
        if dots:
            # `from . import x` is this directory; every extra dot climbs one.
            climbed = directory
            for _ in range(dots - 1):
                if not climbed:
                    climbed = None
                    break
                climbed = climbed.rpartition("/")[0]
            if climbed is None:
                continue
            roots = (climbed,)
        else:
            roots = ("", directory)
        imported = []
        for piece in (names or "").replace("(", " ").replace(")", " ").split(","):
            name = piece.strip().split(" as ")[0].strip()
            if name and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                imported.append(name)
        for root in roots:
            base = _tree_join(root, stem.replace(".", "/")) if stem else root
            if stem:
                candidates.extend(_module_tree_paths(root, stem))
            for name in imported:
                candidates.extend(_module_tree_paths(base, name))
    probes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in candidates:
        collapsed = _collapse_tree_path(raw)
        if collapsed is None or collapsed in seen:
            continue
        seen.add(collapsed)
        probes.append((_fold_case(collapsed), collapsed))
    return tuple(probes)


def _gate_mentions(criterion: str, args: Sequence[Any]) -> bool:
    """Whether the gate that ran actually named this criterion path.

    MATCHED ON PATH BOUNDARIES, NOT AS A SUBSTRING. A bare ``in`` test grants
    the seal for a criterion named ``a.py`` whenever any argument contains
    ``data.py``, and a false grant here is a false ``deterministic`` -- the
    exact failure this whole check exists to prevent. Each argument is split on
    the characters that separate arguments in practice, the pytest node-id
    suffix is dropped, and what remains must equal the criterion or end with it
    at a directory boundary (a gate invoked with an absolute path into the
    worktree still names the same file).
    """

    for raw in args:
        text = _fold_case(str(raw).replace("\\", "/"))
        for piece in re.split(r"[\s=,;]+", text):
            head = piece.split("::", 1)[0]
            if not head:
                continue
            # normpath directly, not _normalise_tree_path: an absolute argument
            # is a legitimate way to name the file and is compared by suffix,
            # whereas an absolute DECLARATION has no normal form and is refused.
            settled = posixpath.normpath(head)
            if settled == criterion or settled.endswith("/" + criterion):
                return True
    return False


def evaluator_assurance_detail(
    result: Any,
    task: Any,
    *,
    criterion_present: Mapping[str, bool] | None = None,
    criterion_imports: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, str]:
    """How much the gate verdict is worth, and WHY -- derived, never asserted.

    ``deterministic`` is claimed ONLY when the criterion came from outside the
    candidate and the candidate ran behind a boundary that actually held:

    * a spine-authored gate (``target-scope``) reads the patch, never the
      candidate's own code, so no candidate can influence its verdict;
    * a declared ``gate_criterion_paths`` seal, which now has to survive six
      separate checks rather than one string-set intersection (below);
    * a FAIL_TO_PASS/PASS_TO_PASS gate carries a frozen, pre-verified receipt
      the candidate cannot author, but only counts when the measured
      containment attestation says the child was in fact contained.

    WHY THE CRITERION SEAL IS SIX CHECKS AND NOT ONE. The first version of
    this compared two raw string sets. Every one of ``tests/../tests/x.py``,
    ``.//tests/x.py`` and ``Tests/X.py`` therefore read as disjoint from a
    scope containing ``tests/x.py`` -- so a candidate allowed to write the very
    file that judged it produced a ``deterministic`` packet, which promotion
    accepts. Worse, a criterion naming a file that does not exist, and a scope
    that was never declared at all, both read as sealed. The seal now requires,
    and states in its reason when it cannot get:

    1. **one normal form on both sides** (:func:`_normalise_tree_path`), with
       absolute and root-escaping declarations refused outright;
    2. **an armed containment**: an empty ``target_paths`` means nothing bound
       the patch, so there is no boundary for the criterion to be outside OF;
    3. **the criterion exists as a regular file in the base revision tree**
       (``criterion_present``, measured by the caller against the frozen base,
       symlink and submodule entries excluded) -- a criterion the base does not
       contain was never outside the candidate's reach, it simply was not
       there;
    4. **the gate that ran actually named it**, in ``task.gate_argv`` or in the
       command the :class:`GateResult` recorded. A file the gate never reads
       seals nothing;
    5. **nothing on its execution path is writable**: no scope entry names a
       ``conftest.py``/``__init__.py``/config/``.pth``/``sitecustomize`` on the
       chain from the repository root down to the criterion's own directory,
       because those change what the criterion DOES while its bytes stay
       identical (checks 1-4 all measure it as a blob);
    6. **nothing it imports is writable**: no in-tree module the criterion
       imports, resolved and then CONFIRMED against the base revision tree,
       lies inside the scope. See :func:`_criterion_seal` for what this
       deliberately does not model.

    Where a check is not knowable -- no presence map, no measured imports, no
    recorded command -- the seal is NOT granted and the reason names the fact.
    Everything else is ``unverified``, including a plain pytest gate over the
    candidate's own worktree. That is not pessimism: a conclusive
    EvidencePacket may not rest on unverified evidence, so calling this
    "deterministic" by default would manufacture exactly the green the evidence
    boundary exists to refuse.
    """

    gate = getattr(result, "gates", None)
    if gate is None:
        return "unverified", "no gate ran, so there is no verdict to qualify"
    if str(getattr(gate, "name", "")) == "target-scope":
        return (
            "deterministic",
            "spine-authored target-scope gate: it reads the patch, not the "
            "candidate's code, so no candidate can influence its verdict",
        )

    criterion_raw = tuple(getattr(task, "gate_criterion_paths", ()) or ())
    frozen_criterion = bool(
        getattr(task, "fail_to_pass", ()) or getattr(task, "pass_to_pass", ())
    )
    containment = getattr(gate, "containment", None)
    contained = bool(getattr(containment, "contained", False))

    if criterion_raw:
        why = _criterion_seal(
            criterion_raw, task, gate,
            criterion_present=criterion_present,
            criterion_imports=criterion_imports,
        )
        if why is None:
            return (
                "deterministic",
                "declared gate criterion is outside the armed write scope, "
                "present in the base revision tree, reached by no "
                "execution-influencing file or in-tree import the scope "
                "covers, and named by the gate that ran",
            )
        if not (frozen_criterion and contained):
            return "unverified", why

    if frozen_criterion and contained:
        return (
            "deterministic",
            "frozen FAIL_TO_PASS/PASS_TO_PASS receipt the candidate cannot "
            "author, under a measured containment attestation",
        )
    if frozen_criterion:
        return (
            "unverified",
            "a frozen correctness criterion was declared but the containment "
            "attestation does not say the child was contained",
        )
    return (
        "unverified",
        "the gate ran over the candidate's own worktree with no criterion the "
        "candidate was barred from writing",
    )


def _criterion_seal(
    criterion_raw: Sequence[Any],
    task: Any,
    gate: Any,
    *,
    criterion_present: Mapping[str, bool] | None,
    criterion_imports: Mapping[str, Sequence[str]] | None = None,
) -> str | None:
    """``None`` when the declared criterion seals the verdict, else the reason.

    Split out of :func:`evaluator_assurance_detail` so each refusal returns a
    sentence naming the exact fact that was missing. A seal that fails silently
    into a boolean is a seal whose failures cannot be triaged from a receipt.

    THE CRITERION FILE IS NOT THE CRITERION. Checks 1-4 all measured the
    criterion as a BLOB: normal form, disjointness from the scope, presence in
    the base tree, and mention by the gate. A candidate that never touches that
    blob can still change what it DOES -- by adding or editing a ``conftest.py``
    (fixtures, hooks, assertion rewriting, ``collect_ignore``), a
    ``pytest.ini``/``pyproject.toml``/``setup.cfg``/``tox.ini``, an
    ``__init__.py`` on the package path, or a ``.pth``/``sitecustomize`` that
    runs before anything else -- anywhere on the criterion's own path chain, and
    by rewriting an in-tree module the criterion imports. Two more checks
    therefore ask about the criterion's EXECUTION, not its bytes:

    5. no scope entry is, contains, or names an execution-influencing file on
       the chain from the repository root down to the criterion's directory
       (:func:`_scope_reaches_criterion_execution`);
    6. no in-tree module the criterion imports lies inside the scope.

    Check 6 is deliberately conservative and deliberately incomplete. The
    caller resolves the import lines against the BASE TREE and passes only the
    files that really exist there, so a subject reached through a runtime
    ``sys.path`` insertion or a ``src/`` layout -- which is how the Gate-1
    conformance suite reaches ``ignition_app``, measured -- is not named and not
    refused. Where it DOES fire, it fires on a repair task whose criterion
    imports its own subject by an in-tree path; that is a downgrade to
    ``unverified``, never a false grant, and the honest reading of a gate whose
    judging code is partly candidate-authored.
    """

    scope_raw = tuple(getattr(task, "target_paths", ()) or ())
    if not scope_raw:
        return (
            "the task declares a gate criterion but NO target_paths, so "
            "containment was never armed and the criterion is not outside any "
            "boundary"
        )
    scope: list[str] = []
    for raw in scope_raw:
        normalised = _normalise_tree_path(raw)
        if normalised is None:
            return (
                f"declared target path {str(raw)!r} has no normal form inside "
                "the tree (absolute or root-escaping), so the write scope "
                "cannot be compared against the criterion"
            )
        scope.append(normalised)

    argv = tuple(getattr(task, "gate_argv", ()) or ())
    command = tuple(getattr(gate, "command", ()) or ())
    mentions = (*argv, *command)

    for raw in criterion_raw:
        criterion = _normalise_tree_path(raw)
        if criterion is None:
            return (
                f"declared gate criterion {str(raw)!r} has no normal form "
                "inside the tree (absolute or root-escaping)"
            )
        if _inside_scope(criterion, scope):
            return (
                f"declared gate criterion {criterion!r} is INSIDE the declared "
                "write scope, so the candidate was allowed to edit the thing "
                "that judged it"
            )
        reached = _scope_reaches_criterion_execution(criterion, scope)
        if reached is not None:
            return reached
        if criterion_present is None:
            return (
                "the criterion's presence in the base revision tree was not "
                "measured, so it cannot be shown the candidate had no reach "
                "over it"
            )
        if not criterion_present.get(criterion, False):
            return (
                f"declared gate criterion {criterion!r} is not a regular file "
                "in the base revision tree, so it sealed nothing"
            )
        if criterion_imports is None:
            return (
                f"the modules {criterion!r} imports were not resolved against "
                "the base revision tree, so it cannot be shown the candidate "
                "had no reach over the code that judges with it"
            )
        for imported in criterion_imports.get(criterion, ()) or ():
            if _inside_scope(str(imported), scope):
                return (
                    f"{criterion!r} imports {str(imported)!r}, which is INSIDE "
                    "the declared write scope, so the candidate was allowed to "
                    "author code the criterion executes"
                )
        if not mentions:
            return (
                "the gate recorded no command and the task declares no "
                "gate_argv, so whether the gate read the criterion is not "
                "knowable from this record"
            )
        if not _gate_mentions(criterion, mentions):
            return (
                f"the gate that ran never names {criterion!r} in its command, "
                "so the declared criterion is not what produced this verdict"
            )
    return None


def evaluator_assurance(
    result: Any,
    task: Any,
    *,
    criterion_present: Mapping[str, bool] | None = None,
    criterion_imports: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """The assurance string alone. See :func:`evaluator_assurance_detail`."""

    return evaluator_assurance_detail(
        result, task,
        criterion_present=criterion_present,
        criterion_imports=criterion_imports,
    )[0]


@dataclass(frozen=True)
class AttemptContractSet:
    """The canonical records for one finished attempt, or the reason there are none."""

    runtime: RuntimeManifest | None = None
    policy: PolicyDecision | None = None
    attempt: AttemptContract | None = None
    evidence: EvidencePacket | None = None
    receipt: AttemptReceipt | None = None
    error: str | None = None
    #: The local lane's brief-shed rows for this attempt, one per full-file
    #: prompt. ``est_in`` from these rows is what fills
    #: ``receipt.usage.est_input_tokens``; ``brief_shed`` and ``brief_bytes``
    #: have no home inside ResourceUsage's integers, so they ride the set --
    #: the record the ledger row is written from -- instead of being dropped.
    #: Empty is the default and means no shed decision was reported, never
    #: "no brief was shed".
    shed_telemetry: tuple[dict[str, Any], ...] = ()

    @property
    def complete(self) -> bool:
        return None not in (
            self.runtime,
            self.policy,
            self.attempt,
            self.evidence,
            self.receipt,
        )

    def to_dict(self) -> dict[str, Any]:
        """The wire view written to the spine ledger. Digests included."""

        body: dict[str, Any] = {"error": self.error}
        for name in ("runtime", "policy", "attempt", "evidence", "receipt"):
            contract = getattr(self, name)
            body[name] = None if contract is None else contract.to_dict()
            body[f"{name}_sha256"] = None if contract is None else contract.digest
        # Always written, empty list included. A covariate that is present only
        # when it is interesting cannot be read across attempts: an absent key
        # would be indistinguishable from a lane that never reported one.
        body["shed_telemetry"] = [dict(row) for row in self.shed_telemetry]
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptContractSet":
        """Read the set back out of a ledger row.

        The round trip goes through each contract's own ``from_dict``, so a
        record that was tampered with in the ledger fails to reconstruct rather
        than reappearing as a plausible object.
        """

        if not isinstance(payload, Mapping):
            raise ValueError("attempt contract set must be an object")
        readers = (
            ("runtime", RuntimeManifest),
            ("policy", PolicyDecision),
            ("attempt", AttemptContract),
            ("evidence", EvidencePacket),
            ("receipt", AttemptReceipt),
        )
        built: dict[str, Any] = {"error": payload.get("error")}
        for name, contract_cls in readers:
            raw = payload.get(name)
            built[name] = None if raw is None else contract_cls.from_dict(raw)
        # Same refusal as on the way in: a tampered covariate row does not come
        # back as a plausible object. A row written before this field existed is
        # absent, not malformed, and reads back as the empty default.
        built["shed_telemetry"] = normalise_shed_telemetry(payload.get("shed_telemetry"))
        cls._assert_mint_bindings(built)
        return cls(**built)

    @staticmethod
    def _assert_mint_bindings(built: Mapping[str, Any]) -> None:
        """Re-assert the bindings :func:`canonicalise_attempt` made at mint time.

        THE DOCSTRING ABOVE PROMISED THIS AND THE CODE DID NOT DO IT. Each
        contract's own ``from_dict`` validates that contract in isolation: an
        id is an identifier, a digest is 64 hex characters, a status is one of
        the allowed words. None of that notices when a row's five contracts are
        individually well-formed but do not belong together -- an evidence
        packet swapped in from another attempt, a receipt still naming the
        digest of the packet it was minted against while a different packet
        sits beside it, or a policy decision that decided about someone else.

        That gap matters exactly where the set is read rather than written:
        ``read_contract_set`` is what a promotion path uses to recover the
        record from the ledger, and a set whose parts were shuffled would
        reconstruct into a plausible object carrying someone else's green.
        The four bindings below are the ones the mint actually establishes, so
        they are the four that can be re-derived without inventing a rule the
        producer never followed:

        1. one ``attempt_id`` across attempt contract, evidence and receipt;
        2. ``receipt.evidence_packet_sha256`` IS the digest of the packet in
           the same row (and likewise for the attempt contract, runtime
           manifest and policy decision each of them names);
        3. the policy decision's ``subject_id`` is that attempt and its digest
           is the one the attempt contract and receipt bind;
        4. one ``mission_id`` across the three, and the ONE ``ResourceUsage``
           the mint handed to both the packet and the receipt.

        WHAT IS DELIBERATELY NOT CHECKED HERE: the candidate artifact digest.
        ``EvidencePacket.candidate_artifact_sha256`` is the only field in the
        set that carries it -- no second contract names it -- so there is
        nothing to cross-check it against without re-reading the artifact
        store, which is an effect this module does not have and must not
        acquire. That gap is named rather than papered over with a check that
        would only compare the field to itself.

        A partial set is NOT an error: the mint legitimately returns a runtime
        manifest and a reported reason when it refuses to go further, and every
        check below is skipped for the contracts that row does not carry.
        """

        runtime = built.get("runtime")
        policy = built.get("policy")
        attempt = built.get("attempt")
        evidence = built.get("evidence")
        receipt = built.get("receipt")

        def _bind(label: str, left: Any, right: Any) -> None:
            if left is None or right is None:
                return
            if left != right:
                raise ValueError(
                    f"attempt contract set is not internally bound: {label} "
                    f"({left!r} != {right!r})"
                )

        for field_name in ("attempt_id", "mission_id"):
            ids = [
                (f"attempt.{field_name}", getattr(attempt, field_name, None)),
                (f"evidence.{field_name}", getattr(evidence, field_name, None)),
                (f"receipt.{field_name}", getattr(receipt, field_name, None)),
            ]
            present = [(name, value) for name, value in ids if value is not None]
            for name, value in present[1:]:
                _bind(f"{present[0][0]} vs {name}", present[0][1], value)

        attempt_digest = None if attempt is None else attempt.digest
        runtime_digest = None if runtime is None else runtime.digest
        policy_digest = None if policy is None else policy.digest
        evidence_digest = None if evidence is None else evidence.digest

        for holder, holder_name in ((evidence, "evidence"), (receipt, "receipt")):
            if holder is None:
                continue
            _bind(
                f"{holder_name}.attempt_contract_sha256 vs attempt.digest",
                getattr(holder, "attempt_contract_sha256", None),
                attempt_digest,
            )
            _bind(
                f"{holder_name}.policy_decision_sha256 vs policy.digest",
                getattr(holder, "policy_decision_sha256", None),
                policy_digest,
            )
        if receipt is not None:
            _bind(
                "receipt.evidence_packet_sha256 vs evidence.digest",
                receipt.evidence_packet_sha256,
                evidence_digest,
            )
            _bind(
                "receipt.runtime_manifest_sha256 vs runtime.digest",
                receipt.runtime_manifest_sha256,
                runtime_digest,
            )
        if attempt is not None:
            _bind(
                "attempt.runtime_manifest_sha256 vs runtime.digest",
                attempt.runtime_manifest_sha256,
                runtime_digest,
            )
            _bind(
                "attempt.policy_decision_sha256 vs policy.digest",
                attempt.policy_decision_sha256,
                policy_digest,
            )
        if policy is not None and attempt is not None:
            _bind(
                "policy.subject_id vs attempt.attempt_id",
                policy.subject_id,
                attempt.attempt_id,
            )
            _bind(
                "policy.subject_sha256 vs attempt.task_sha256",
                policy.subject_sha256,
                attempt.task_sha256,
            )
        if evidence is not None and receipt is not None:
            _bind(
                "evidence.usage vs receipt.usage",
                evidence.usage,
                receipt.usage,
            )


def canonicalise_attempt(
    result: Any,
    *,
    task: Any,
    mission_id: str,
    attempt_id: str,
    base_revision: str,
    adapter_id: str,
    evidence_locator: str | None,
    budget: ResourceBudget,
    usage: ResourceUsage,
    created_at: str,
    locator_error: str | None = None,
    spend_grant_microusd: int = 0,
    campaign_id: str | None = None,
    trace_id: str | None = None,
    assurance: str | None = None,
    assurance_reason: str = "",
    criterion_present: Mapping[str, bool] | None = None,
    criterion_imports: Mapping[str, Sequence[str]] | None = None,
    boundary_receipt: Any = None,
    shed_telemetry: Any = None,
    mission_policy_sha256: str | None = None,
) -> AttemptContractSet:
    """Turn one finished :class:`AttemptResult` into the canonical records.

    Returns rather than raises: an attempt that already produced a patch and a
    gate verdict must not be destroyed because its canonical projection could
    not be built. The reason travels on the set and into the ledger, so a
    contract that silently stopped being produced is visible instead of absent.

    ``shed_telemetry`` is ADDITIVE and defaults to nothing, so every existing
    caller mints byte-identical records. When a lane does supply it (the local
    provider's ``report.handoff["shed_telemetry"]``), two things follow: the
    rows ride the set into the ledger row, and ``usage.est_input_tokens`` is
    filled from their ``est_in`` sum. It goes into ``est_input_tokens`` and NOT
    into ``input_tokens``: the sum is a cl100k over-count taken before the
    prompt was sent, and ``input_tokens`` means "the serving side counted this
    many". Writing an estimate there would make the receipt assert a
    measurement nobody made (Invariant 9), and no downstream reader could tell
    the two apart afterwards. The declared reason is swapped in the same
    breath, because a contract may not keep asserting "nothing measured them"
    once something estimated them -- and when rows arrive whose ``est_in`` is 0
    while the brief was NOT shed, the shortfall gets its own reason rather than
    disappearing into the sum.

    ``mission_policy_sha256`` is the digest the :class:`MissionContract` this
    attempt serves bound. It is compared against the policy digest the attempt's
    own decision carries -- the boundary receipt's registry digest when there
    was a boundary, the locally-read registry otherwise -- and a disagreement
    REFUSES the projection rather than minting a chain whose mission and
    attempt name two different policy texts (Invariant 1). Defaulting to the
    locally-read registry means the check is live for every caller today: it
    catches a registry that moved between the boundary start and this
    projection, which is the same failure with a shorter fuse.
    """

    runtime: RuntimeManifest | None = None
    policy: PolicyDecision | None = None
    attempt: AttemptContract | None = None
    evidence: EvidencePacket | None = None
    shed_rows: tuple[dict[str, Any], ...] = ()
    try:
        # FIRST, before any contract is built: a malformed covariate must not
        # reach a digest. The refusal is reported like every other one here.
        shed_rows = normalise_shed_telemetry(shed_telemetry)
        under_metered = 0
        if shed_rows and not usage.est_input_tokens:
            usage = replace(
                usage,
                est_input_tokens=sum(int(row["est_in"]) for row in shed_rows),
            )
            # A row that did not shed its brief had a full-file prompt built for
            # it, so an est_in of 0 is a missing estimate, not a measured zero.
            under_metered = sum(
                1
                for row in shed_rows
                if not row["brief_shed"] and not int(row["est_in"])
            )
        runtime = attempt_runtime_manifest(
            source_revision=base_revision,
            created_at=created_at,
            adapter_id=adapter_id,
            trace_id=trace_id,
        )
        target_paths = tuple(getattr(task, "target_paths", ()) or ())
        state = str(getattr(result, "state", ""))
        denied = state in {"storage_unavailable", "worktree_failed"}
        # THE REFUSAL IS RECORDED FIRST, and before the scope check. A deny
        # decision grants nothing, so it does not need a declared write scope to
        # be well-formed -- and an attempt the spine turned away is exactly the
        # case where a record is most worth having. Ordering this after the
        # target_paths refusal below would have thrown away every denial made
        # against a task that never declared a scope.
        if not denied and not target_paths:
            return AttemptContractSet(
                runtime=runtime,
                shed_telemetry=shed_rows,
                error=(
                    "task declares no target_paths; refusing to mint a canonical "
                    "attempt contract for an unbounded write scope"
                ),
            )
        reasons = [
            "spine.intent_ledger: intent committed before the effect",
            "containment.worktree: candidate ran in a git worktree outside the "
            "primary checkout",
            "containment.attempt: declared target_paths bound the accepted patch",
            "storage watermark checked before any record or worktree was created",
            SPEND_GRANT_REASON,
            UNMETERED_SPEND_REASON,
            GATE_WALL_BOUND_REASON,
        ]
        if denied:
            reasons = [
                f"attempt spine refused before the effect: state={state}",
                str(getattr(result, "error", "") or "no reason recorded"),
                UNMETERED_SPEND_REASON,
            ]
        if shed_rows and usage.est_input_tokens:
            # The wording travels INSIDE the PolicyDecision digest, so leaving
            # the unmetered line in place while est_input_tokens is nonzero
            # would sign a false statement. One line replaced, nothing else
            # touched.
            reasons = [
                METERED_INPUT_REASON if reason == UNMETERED_SPEND_REASON else reason
                for reason in reasons
            ]
        if under_metered:
            reasons.append(
                UNDER_METERED_INPUT_REASON.format(
                    missing=under_metered, total=len(shed_rows)
                )
            )
        if assurance_reason:
            reasons.append(
                f"{ASSURANCE_REASON_PREFIX} "
                f"{assurance or 'unverified'}: {assurance_reason}"
            )
        timeout_s = int(float(getattr(task, "gate_timeout_s", 0) or 0)) or None
        policy = attempt_policy_decision(
            decision_id=f"{attempt_id}:policy",
            subject_id=attempt_id,
            subject_sha256=str(getattr(task, "digest")),
            source_revision=base_revision,
            created_at=created_at,
            verdict="deny" if denied else "allow",
            reasons=reasons,
            writable_paths=target_paths,
            timeout_s=timeout_s,
            spend_grant_microusd=spend_grant_microusd,
            trace_id=trace_id,
            boundary_receipt=boundary_receipt,
        )
        if denied:
            return AttemptContractSet(
                runtime=runtime,
                policy=policy,
                shed_telemetry=shed_rows,
                error=(
                    "attempt was refused before any effect; the deny decision IS "
                    "the record and there is no evidence to bind"
                ),
            )
        # ONE POLICY TEXT PER CHAIN, checked rather than assumed. The mission
        # bound a registry digest when it was compiled; this decision bound the
        # one the effect boundary was started against. Nothing compared them,
        # so a registry edited between the two produced a mission and an
        # attempt that each named a different policy and neither noticed.
        declared_policy_sha = str(mission_policy_sha256 or "").strip() or (
            _policy_registry_sha256()
        )
        if declared_policy_sha != policy.policy_sha256:
            return AttemptContractSet(
                runtime=runtime,
                policy=policy,
                shed_telemetry=shed_rows,
                error=(
                    "policy digest disagreement: the mission this attempt serves "
                    f"binds {declared_policy_sha} and the attempt's own policy "
                    f"decision binds {policy.policy_sha256}; refusing to mint a "
                    "chain whose mission and attempt name two different policy "
                    "texts"
                ),
            )
        attempt = AttemptContract.from_task_spec(
            task,
            attempt_id=attempt_id,
            mission_id=mission_id,
            runtime_manifest_sha256=runtime.digest,
            policy_decision_sha256=policy.digest,
            budget=budget,
            base_revision=base_revision,
            campaign_id=campaign_id,
            provenance=ContractProvenance(
                origin=ATTEMPT_ORIGIN,
                source_revision=base_revision,
                created_at=created_at,
                # The policy TEXT digest joins the contract digests, so the
                # attempt contract itself carries the thing the mission was
                # compiled against -- a reader who has only this record can
                # still tell which policy it was decided under, instead of
                # having to trust that two contracts agreed at mint time.
                input_digests=tuple(
                    dict.fromkeys(
                        (
                            str(getattr(task, "digest")),
                            runtime.digest,
                            policy.digest,
                            declared_policy_sha,
                        )
                    )
                ),
                trace_id=trace_id,
            ),
        )
        if not evidence_locator:
            return AttemptContractSet(
                runtime=runtime,
                policy=policy,
                attempt=attempt,
                shed_telemetry=shed_rows,
                error=(
                    locator_error
                    or (
                        "gate output has no content-addressed locator; refusing "
                        "to mint an evidence packet that points at nothing"
                    )
                ),
            )
        packet_assurance = assurance or evaluator_assurance(
            result, task,
            criterion_present=criterion_present,
            criterion_imports=criterion_imports,
        )
        evidence = EvidencePacket.from_attempt_result(
            result,
            attempt=attempt,
            packet_id=f"{attempt_id}:evidence",
            usage=usage,
            provenance=EvidencePacket.attempt_provenance(
                result,
                attempt=attempt,
                evidence_locator=evidence_locator,
                origin=ATTEMPT_ORIGIN,
                created_at=created_at,
                trace_id=trace_id,
            ),
            evidence_locator=evidence_locator,
            evaluator_assurance=packet_assurance,
        )
        receipt = AttemptReceipt.from_attempt_result(
            result,
            attempt=attempt,
            evidence=evidence,
            receipt_id=f"{attempt_id}:receipt",
            usage=usage,
            provenance=ContractProvenance(
                origin=ATTEMPT_ORIGIN,
                source_revision=base_revision,
                created_at=created_at,
                input_digests=tuple(
                    sorted(
                        {
                            attempt.digest,
                            runtime.digest,
                            policy.digest,
                            evidence.digest,
                        }
                    )
                ),
                trace_id=trace_id,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - reported, never fatal to an attempt
        return AttemptContractSet(
            runtime=runtime,
            policy=policy,
            attempt=attempt,
            evidence=evidence,
            shed_telemetry=shed_rows,
            error=f"{type(exc).__name__}: {exc}",
        )
    return AttemptContractSet(
        runtime=runtime,
        policy=policy,
        attempt=attempt,
        evidence=evidence,
        receipt=receipt,
        shed_telemetry=shed_rows,
    )


def mission_contract_for_candidate(
    candidate: Any,
    *,
    source_revision: str,
    created_at: str,
    budget: ResourceBudget,
    mission_id: str | None = None,
    trace_id: str | None = None,
) -> MissionContract:
    """Compile one picked candidate into the mission the attempt serves.

    THE PRODUCER SHIPS HERE, THE CALL SITE DOES NOT. The picker
    (``daedalus.spine.picker``) is the only live code that decides "this is the
    next thing to work on", so it -- and nothing else -- is where a
    MissionContract can honestly be minted per iteration. That file is outside
    this change's boundary, so the six-line call site is delivered as a diff
    instead of applied. Until it is applied, MissionContract has a producer
    function and no live caller, and this docstring is the place that says so
    rather than a status page that could quietly go stale.

    ``policy_sha256`` binds the declared effect-boundary registry, the same
    policy digest :func:`attempt_policy_decision` binds, so a mission and the
    attempts under it name one policy and not two.
    """

    task_id = _identifier_fragment(str(getattr(candidate, "task_id")), "candidate")
    reason = str(getattr(candidate, "reason", "") or "")
    policy_sha = _policy_registry_sha256()
    return MissionContract(
        mission_id=mission_id or f"mission-{task_id}",
        objective=str(getattr(candidate, "instruction", "") or reason or task_id),
        source_revision=source_revision,
        work_item_ids=(task_id,),
        success_criteria=(
            reason or "the declared gate passes on the candidate patch",
        ),
        policy_sha256=policy_sha,
        budget=budget,
        provenance=ContractProvenance(
            origin="daedalus.spine.picker",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(policy_sha,),
            trace_id=trace_id,
        ),
    )


def mission_contract_for_build_session(
    session: Any,
    *,
    source_revision: str,
    created_at: str,
    budget: ResourceBudget,
    success_criteria: Sequence[str] | None = None,
    trace_id: str | None = None,
) -> MissionContract:
    """Compile ONE ``daedalus.build.BuildSession`` into the mission it runs.

    The build path's second half of the same wiring
    :func:`mission_contract_for_candidate` does for the picker: a build session
    is one feature carried across waves, which is exactly one mission carried
    across an ordered batch of work items (plan §7). ``BuildSession`` binds its
    own ``mission_id`` and one deterministic ``work_item_id`` per task; this
    function only reads them, so the id a receipt names and the id the mission
    claims cannot be minted twice and disagree.

    DUCK-TYPED ON PURPOSE. ``daedalus.build`` is a planning module that imports
    the router and the scheduler; importing it from the spine would drag that
    graph into the attempt hot path and invert the layering. The session is read
    through ``getattr`` exactly as ``mission_contract_for_candidate`` reads a
    candidate.

    ``policy_sha256`` binds the same effect-boundary registry digest the
    candidate mission and :func:`attempt_policy_decision` bind, so a build's
    mission and the attempts under it name one policy and not two.

    An unbound session is refused rather than papered over: without work item
    ids there is no WorkItem layer, and a mission that names none is not a
    mission the chain can hang attempts off.
    """

    mission_id = str(getattr(session, "mission_id", "") or "")
    if not mission_id:
        raise ValueError(
            "build session has no mission_id; it was constructed outside "
            "BuildSession.__post_init__ and is not bound to a mission"
        )
    tasks = list(session.tasks())
    if not tasks:
        raise ValueError("build session plans no work items")
    work_item_ids: list[str] = []
    for index, task in enumerate(tasks):
        work_item_id = str(getattr(task, "work_item_id", "") or "")
        if not work_item_id:
            raise ValueError(
                f"build task {index} has no work_item_id; the session was not bound"
            )
        work_item_ids.append(work_item_id)

    feature = str(getattr(session, "feature", "") or "")
    if not feature.strip():
        raise ValueError("build session has no feature to state as an objective")

    policy_sha = _policy_registry_sha256()
    return MissionContract(
        mission_id=mission_id,
        objective=feature,
        source_revision=source_revision,
        # Duplicates are NOT filtered here. MissionContract refuses them, and
        # a duplicate means two build tasks claim one work item -- a planning
        # defect that must surface, not be de-duplicated into silence.
        work_item_ids=tuple(work_item_ids),
        success_criteria=tuple(success_criteria) if success_criteria else (
            "every work item in this build reaches status 'landed' under its "
            "wave's effect lease",
        ),
        policy_sha256=policy_sha,
        budget=budget,
        provenance=ContractProvenance(
            origin="daedalus.build",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(policy_sha,),
            trace_id=trace_id,
        ),
    )


def read_contract_set(result_body: Any) -> AttemptContractSet | None:
    """Recover the canonical set from a spine ledger row's ``result`` detail.

    The consumer half of the wiring: what the attempt wrote is read back as
    contracts, not as a dict a caller then interprets by hand. ``None`` means
    the row predates the canonical projection -- an absence, deliberately
    distinguishable from an empty set carrying an error.
    """

    if not isinstance(result_body, Mapping):
        return None
    payload = result_body.get("contracts")
    if payload is None:
        return None
    return AttemptContractSet.from_dict(payload)


__all__ = [
    "ATTEMPT_ENTRYPOINT_ID",
    "ATTEMPT_KILL_SWITCH_REF",
    "ATTEMPT_ORIGIN",
    "ATTEMPT_RUNTIME_ID",
    "ASSURANCE_REASON_PREFIX",
    "GATE_WALL_BOUND_REASON",
    "METERED_INPUT_REASON",
    "AttemptContractSet",
    "SHED_TELEMETRY_FIELDS",
    "SPEND_GRANT_REASON",
    "UNDER_METERED_INPUT_REASON",
    "UNMETERED_SPEND_REASON",
    "adapter_identity",
    "normalise_shed_telemetry",
    "attempt_policy_decision",
    "attempt_runtime_manifest",
    "read_contract_set",
    "canonicalise_attempt",
    "containment_escapes",
    "criterion_import_probe_paths",
    "criterion_probe_paths",
    "evaluator_assurance",
    "evaluator_assurance_detail",
    "mission_contract_for_build_session",
    "mission_contract_for_candidate",
]
