"""The Gate-1 ignition slice, wired through the canonical kernel.

WHAT THIS IS
------------
Plan §10 Gate 1 in one runnable sentence: propagate ``Event.voltage`` ->
``bias_voltage`` across Python, Markdown and CSV; Ikarus produces ONE
MissionContract; the four planes produce TWO typed WorkItems; attempts run in
isolation; restart/replay works; tests, schema checks and link checks produce
an EvidencePacket; nothing is promoted.

WHAT IT DOES NOT ADD
--------------------
No contract, no store, no ledger and no promotion path is minted here:

* the mission is :func:`daedalus.spine.receipts.mission_contract_for_build_session`
  over a real :class:`daedalus.build.BuildSession`;
* the two WorkItems are :class:`daedalus.build.BuildTask` objects whose ids come
  from :func:`daedalus.schemas.derive_work_item_id`, bound by the session;
* each attempt is one :class:`daedalus.spine.attempt.TaskAttempt`, so it crosses
  the ``python.attempt`` effect boundary and produces the AttemptContract,
  PolicyDecision, EvidencePacket and AttemptReceipt that path already mints;
* the Gate-1 packet is
  :func:`daedalus.kernel.fourfold_evidence.assemble_fourfold_evidence_packet`;
* the checks are :mod:`daedalus.ignition.checks`.

The one thing this module owns is the ORDER, plus the receipt that records it.

THE TARGET PROJECT IS A PREPARED COPY, NEVER THE FIXTURE IN PLACE.
``prepare_ignition_repo`` copies ``tests/fixtures/ignition/voltage`` into a
scratch directory, seeds the conformance suite, and makes ONE commit with a
frozen author, committer and date -- so the base revision is a pure function of
the tree and replay produces the same 40-hex sha on any machine. The fixture in
the repository is never written, and its tree digest is compared before and
after to prove it.

PROMOTION. The receipt says ``nominated, not promoted`` and this module imports
nothing from :mod:`daedalus.kernel.promotion`. There is no code path here that
applies a patch to anything but the scratch candidate tree it built itself.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.build import BuildSession, BuildTask, Wave
from daedalus.ignition import checks as ignition_checks
from daedalus.ignition.runner import (
    IgnitionError,
    IgnitionGraphDelta,
    candidate_behavior,
    fourfold_graph_delta,
    tree_digest,
)
from daedalus.kernel.fourfold_evidence import assemble_fourfold_evidence_packet
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    MissionContract,
    ResourceBudget,
    ResourceUsage,
)
from daedalus.spine.attempt import GateResult, RunnerContext, TaskAttempt, TaskSpec
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.receipts import mission_contract_for_build_session
from daedalus.storage import ArtifactStore
from daedalus.twin import compile_reference_project

ROOT = Path(__file__).resolve().parents[2]

#: The fixture that plays the target project.
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "ignition" / "voltage"

#: Where receipts land. One directory per mission, so a replay overwrites the
#: receipt it is a replay OF instead of accumulating look-alikes.
DEFAULT_RECEIPT_ROOT = ROOT / "runs" / "ignition"

RETIRED_SYMBOL = "voltage"
RENAMED_SYMBOL = "bias_voltage"

SESSION_SLUG = "gate1-voltage-ignition"
FEATURE = (
    "propagate the Event.voltage -> Event.bias_voltage rename across the code, "
    "type, data and knowledge planes of the ignition target project"
)

#: Frozen git identity for the prepared target repository. The base revision is
#: a git sha, and a git sha is a function of the tree PLUS these five strings;
#: freezing them is what makes ``base_revision`` replayable.
FROZEN_GIT_ENV = {
    "GIT_AUTHOR_NAME": "daedalus-ignition",
    "GIT_AUTHOR_EMAIL": "ignition@daedalus.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_NAME": "daedalus-ignition",
    "GIT_COMMITTER_EMAIL": "ignition@daedalus.invalid",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
}
FROZEN_COMMIT_MESSAGE = "ignition target project base revision"

#: The mission id :func:`daedalus.build.mission_id_for_session` derives for this
#: session. Named as a constant so the receipt directory can be resolved BEFORE
#: the session exists, and asserted against the real mission afterwards -- a
#: constant that silently disagreed with the derivation would put the store
#: somewhere the receipt does not point.
SESSION_MISSION_ID = f"mission-{SESSION_SLUG}"

_WORD = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(RETIRED_SYMBOL)}(?![A-Za-z0-9_])")

#: The only two directory names an artifact store root may contain. Anything
#: else and :func:`_reset_evidence_store` refuses to delete it.
_STORE_ENTRIES = {"blobs", "locators"}


def _reset_evidence_store(store_root: Path) -> Path:
    """Empty this mission's evidence store, refusing anything that is not one.

    A recursive delete of a caller-named path is exactly the operation that must
    not be convenient. It proceeds only when the directory contains nothing but
    the two subdirectories :class:`daedalus.storage.ArtifactStore` creates; a
    directory holding anything else is left alone and reused, so pointing
    ``--receipts`` at a populated directory cannot erase it.
    """

    if store_root.exists():
        entries = {child.name for child in store_root.iterdir()}
        if entries <= _STORE_ENTRIES:
            shutil.rmtree(store_root, ignore_errors=True)
    store_root.mkdir(parents=True, exist_ok=True)
    return store_root


# --------------------------------------------------------------------------- #
# 1. the four planes produce two typed work items                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PlannedWorkItem:
    """One work item as the manifest implies it, before a session binds an id."""

    key: str
    planes: tuple[str, ...]
    objective: str
    paths: tuple[str, ...]


def plan_work_items(
    project_root: str | Path,
    *,
    manifest_name: str = "fourfold.json",
    symbol: str = RETIRED_SYMBOL,
) -> tuple[PlannedWorkItem, ...]:
    """Derive the two WorkItems from the four-plane manifest, not from a list.

    THE PLANES DECIDE THE SPLIT. ``fourfold.json`` classifies every declared
    file into code (which also carries the type plane), data, or knowledge; a
    file joins a work item when it actually contains the retired symbol. The
    manifest itself joins the data/knowledge item because its ``claims`` name
    the symbol as a type/csv/schema field -- a rename that left the manifest
    behind would compile a candidate Fourfold that still claims the old field.

    The previous hand-written ``WORK_ITEMS`` constant in
    :mod:`daedalus.ignition.runner` named the same six paths. It named them as
    literals, so it could not go wrong loudly: a fixture that grew a seventh
    file carrying the symbol would have been renamed nowhere and reported
    nothing. This derivation refuses that silence -- a plane whose files carry
    the symbol but which produced no work item raises.
    """

    root = Path(project_root).resolve()
    manifest_rel = str(manifest_name)
    manifest = json.loads((root / manifest_rel).read_text(encoding="utf-8"))
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")

    def carries(rel: str) -> bool:
        try:
            return bool(pattern.search((root / rel).read_text(encoding="utf-8")))
        except OSError:
            return False

    code = tuple(rel for rel in manifest.get("code_files", ()) if carries(rel))
    data = tuple(rel for rel in manifest.get("data_files", ()) if carries(rel))
    knowledge = tuple(rel for rel in manifest.get("knowledge_files", ()) if carries(rel))
    manifest_carries = carries(manifest_rel)

    if not code:
        raise IgnitionError(
            f"no declared code file carries {symbol!r}; there is no code/type work item"
        )
    if not (data or knowledge):
        raise IgnitionError(
            f"no declared data or knowledge file carries {symbol!r}; there is no "
            "data/knowledge work item"
        )

    data_knowledge = tuple(sorted({*data, *knowledge, *((manifest_rel,) if manifest_carries else ())}))
    return (
        PlannedWorkItem(
            key="rename-code-type",
            planes=("code", "type"),
            objective=(
                f"rename {symbol} to {RENAMED_SYMBOL} in the code and type planes "
                f"({', '.join(sorted(code))})"
            ),
            paths=tuple(sorted(code)),
        ),
        PlannedWorkItem(
            key="rename-data-knowledge",
            planes=("data", "knowledge"),
            objective=(
                f"rename {symbol} to {RENAMED_SYMBOL} in the data and knowledge "
                f"planes ({', '.join(data_knowledge)})"
            ),
            paths=data_knowledge,
        ),
    )


def ignition_session(
    project_root: str | Path,
    planned: Sequence[PlannedWorkItem],
) -> BuildSession:
    """Wrap the planned items in one real BuildSession, which binds the ids.

    ``created=""`` on purpose: :func:`daedalus.build.mission_id_for_session`
    appends a timestamp when it is given one, and a mission id that moves with
    the clock cannot be replayed. The identity that makes THIS mission
    distinguishable is its slug plus the work item digests underneath it, both
    of which are functions of the manifest.
    """

    tasks = [
        BuildTask(
            objective=item.objective,
            agent="daedalus.ignition",
            category="renovation",
            lane="deterministic",
            tier="none",
            builder="daedalus.ignition.rename_operator",
            frontier=False,
            paths=list(item.paths),
        )
        for item in planned
    ]
    return BuildSession(
        feature=FEATURE,
        repo_root=str(Path(project_root).resolve()),
        project="daedalus/ignition-field-fixture",
        waves=[Wave(index=0, tasks=tasks)],
        slug=SESSION_SLUG,
        created="",
        max_workers=1,
    )


def ignition_mission(
    session: BuildSession,
    *,
    base_revision: str,
    created_at: str,
    gate_timeout_s: int = 300,
) -> MissionContract:
    """The one MissionContract, minted by the kernel's own producer."""

    return mission_contract_for_build_session(
        session,
        source_revision=base_revision,
        created_at=created_at,
        budget=ResourceBudget(max_wall_time_s=int(gate_timeout_s) * 2),
        success_criteria=(
            f"no declared file still carries the retired symbol {RETIRED_SYMBOL!r}",
            "the candidate Fourfold snapshot differs from the base in all four planes' bindings",
            "the conformance suite, the schema check and the link check all pass on the composed candidate",
            "the candidate is nominated and never promoted",
        ),
        trace_id="gate1-voltage-ignition",
    )


# --------------------------------------------------------------------------- #
# 2. the target project                                                        #
# --------------------------------------------------------------------------- #
def _git(args: Sequence[str], *, cwd: Path) -> str:
    env = dict(os.environ)
    env.update(FROZEN_GIT_ENV)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise IgnitionError(
            f"git {' '.join(args)} failed in {cwd}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def prepare_ignition_repo(
    fixture_root: str | Path,
    destination: str | Path,
) -> tuple[Path, str]:
    """Copy the fixture into a scratch git repository and freeze its base commit.

    Returns ``(repo_path, base_revision)``. The conformance suite is seeded here
    -- BEFORE the base commit and therefore before any work item exists -- so it
    is part of the base revision every attempt branches from and is outside
    every declared ``target_paths``.
    """

    fixture = Path(fixture_root).resolve()
    repo = Path(destination).resolve()
    if repo.exists():
        raise IgnitionError("ignition target repository must not already exist")
    shutil.copytree(fixture, repo)
    test_file = repo / ignition_checks.CONFORMANCE_TEST_PATH
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(ignition_checks.CONFORMANCE_TEST_SOURCE, encoding="utf-8")

    _git(["init", "--quiet", "-b", "ignition-base"], cwd=repo)
    _git(["config", "user.name", FROZEN_GIT_ENV["GIT_AUTHOR_NAME"]], cwd=repo)
    _git(["config", "user.email", FROZEN_GIT_ENV["GIT_AUTHOR_EMAIL"]], cwd=repo)
    _git(["config", "core.autocrlf", "false"], cwd=repo)
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "--quiet", "-m", FROZEN_COMMIT_MESSAGE], cwd=repo)
    return repo, _git(["rev-parse", "HEAD"], cwd=repo)


# --------------------------------------------------------------------------- #
# 3. the operator and the two gates                                            #
# --------------------------------------------------------------------------- #
def rename_operator(paths: Sequence[str], *, symbol: str = RETIRED_SYMBOL,
                    replacement: str = RENAMED_SYMBOL):
    """A deterministic rename operator over one work item's declared paths.

    Declares its preconditions the way plan §9 requires an operator to: it
    writes ONLY the paths it was given, and it refuses a path that does not
    carry the retired symbol rather than silently producing no change (an empty
    patch would reach the attempt spine as ``no_change``, which is a weaker and
    later signal than the refusal here).
    """

    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")

    def _run(ctx: RunnerContext) -> dict[str, Any]:
        edited: dict[str, int] = {}
        for rel in paths:
            target = ctx.worktree / rel
            text = target.read_text(encoding="utf-8")
            replaced, count = pattern.subn(replacement, text)
            if count == 0:
                raise IgnitionError(
                    f"rename precondition failed: {rel} does not carry {symbol!r}"
                )
            target.write_text(replaced, encoding="utf-8", newline="")
            edited[rel] = count
        return {
            "operator": "daedalus.ignition.rename_operator",
            "symbol": symbol,
            "replacement": replacement,
            "occurrences": edited,
        }

    _run.__module__ = "daedalus.ignition.gate1"
    _run.__qualname__ = "rename_operator"
    return _run


def code_type_gate(sink: dict[str, ignition_checks.CheckReport], *, timeout_s: float = 120.0):
    """Attempt gate for the code/type work item: the conformance node it owns."""

    def _gate(ctx: RunnerContext) -> GateResult:
        started = time.monotonic()
        report = ignition_checks.pytest_check(
            ctx.worktree, ignition_checks.CODE_TYPE_NODE_IDS, timeout_s=timeout_s,
            label="pytest-code-type",
        )
        sink["code-type"] = report
        return GateResult(
            passed=report.passed,
            name="ignition-code-type",
            command=tuple(str(part) for part in report.detail.get("argv", ())),
            returncode=report.detail.get("returncode"),
            output=report.output,
            duration_s=time.monotonic() - started,
        )

    return _gate


def data_knowledge_gate(sink: dict[str, ignition_checks.CheckReport], *, timeout_s: float = 120.0):
    """Attempt gate for the data/knowledge work item: the conformance nodes it
    owns, plus the schema and link measurements.

    THE VERDICT COMES FROM THE ANCHORED NODES, THE OTHER TWO ARE MEASUREMENTS.
    Until 2026-08-23 this gate returned schema-and-link, whose criterion is
    code in :mod:`daedalus.ignition.checks` rather than a file in the judged
    tree; the attempt could therefore declare no ``gate_criterion_paths`` and
    ``evaluator_assurance`` refused to call it deterministic -- the receipt's
    own ``remaining_gap``. Running :data:`~daedalus.ignition.checks.
    DATA_KNOWLEDGE_NODE_IDS` puts a criterion the candidate may not write in
    front of the verdict, and the pytest argv names the file, which is what the
    spine's seal requires (check 4).

    The schema and link reports still run and still land in the sink -- they are
    the composed candidate's evidence and the cross-plane reading that catches a
    half-finished rename the node ids do not model. They no longer decide this
    attempt on their own: a gate whose criterion the candidate authors is
    exactly what the evidence boundary refuses to call conclusive.
    """

    def _gate(ctx: RunnerContext) -> GateResult:
        started = time.monotonic()
        conformance = ignition_checks.pytest_check(
            ctx.worktree, ignition_checks.DATA_KNOWLEDGE_NODE_IDS, timeout_s=timeout_s,
            label="pytest-data-knowledge",
        )
        schema = ignition_checks.schema_check(ctx.worktree)
        links = ignition_checks.link_check(ctx.worktree)
        sink["data-knowledge"] = conformance
        sink["schema"] = schema
        sink["link"] = links
        # ALL THREE, and the reason is measured: with the verdict resting on the
        # conformance nodes alone, dropping schemas/event.schema.json from the
        # work item's paths left the CSV renamed and the schema behind, the
        # nodes still passed, and only the Fourfold compile downstream noticed
        # (tests/test_ignition_gate1.py::test_a_half_finished_rename_is_refused
        # went red). The node ids model the CSV header and the wiki page; they
        # do not model the schema/CSV field-set equality, which is exactly the
        # half-finished rename this slice exists to catch. The seal comes from
        # the anchored nodes, the discrimination from all three.
        return GateResult(
            passed=conformance.passed and schema.passed and links.passed,
            name="ignition-data-knowledge",
            # The argv NAMES the criterion file, which the spine's seal
            # requires (check 4); the two module-authored checks ride along in
            # the command so the record says what actually ran.
            command=tuple(str(part) for part in conformance.detail.get("argv", ()))
            + ("ignition-schema-check", "ignition-link-check"),
            # pytest's own code when the anchored nodes decided it; 1 when they
            # passed and a cross-plane reading did not.
            returncode=(
                conformance.detail.get("returncode")
                if not conformance.passed
                else 0 if (schema.passed and links.passed) else 1
            ),
            output=ignition_checks.render_reports((conformance, schema, links)),
            duration_s=time.monotonic() - started,
        )

    return _gate


# --------------------------------------------------------------------------- #
# 4. composing the candidate from the attempts' own artifacts                  #
# --------------------------------------------------------------------------- #
def compose_candidate(
    repo: Path,
    patches: Sequence[bytes],
    destination: Path,
) -> Path:
    """Build the candidate tree by APPLYING the attempts' patches, not by redoing them.

    The whole point of running the work items through the attempt spine is that
    the artifact is the product. Re-executing the rename here to produce the
    candidate would make the attempts decorative: the tree the Fourfold compiles
    and the checks judge would be one this module wrote, not one the attempts
    did. So the base tree is exported and every captured patch is applied to it.
    """

    if destination.exists():
        raise IgnitionError("candidate root must not already exist")
    destination.mkdir(parents=True)
    archive = destination.parent / f"{destination.name}.tar"
    try:
        with archive.open("wb") as handle:
            completed = subprocess.run(
                ["git", "archive", "--format=tar", "HEAD"],
                cwd=str(repo),
                stdout=handle,
                stderr=subprocess.PIPE,
            )
        if completed.returncode != 0:
            raise IgnitionError(
                f"git archive failed: {completed.stderr.decode('utf-8', 'replace').strip()}"
            )
        shutil.unpack_archive(str(archive), str(destination), format="tar")
    finally:
        archive.unlink(missing_ok=True)

    for index, diff in enumerate(patches):
        if not diff:
            raise IgnitionError(f"work item {index} produced an empty patch")
        patch_file = destination.parent / f"patch-{index}.diff"
        patch_file.write_bytes(diff)
        try:
            _git(["apply", "--whitespace=nowarn", str(patch_file)], cwd=destination)
        finally:
            patch_file.unlink(missing_ok=True)
    return destination


def old_symbol_occurrences(root: Path, paths: Sequence[str]) -> tuple[str, ...]:
    hits = []
    for rel in sorted(set(paths)):
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        if _WORD.search(text):
            hits.append(rel)
    return tuple(hits)


# --------------------------------------------------------------------------- #
# 5. evidence                                                                  #
# --------------------------------------------------------------------------- #
def _store_check(
    store: ArtifactStore,
    report: ignition_checks.CheckReport,
    *,
    source_revision: str,
    created_at: str,
    trace_id: str | None,
) -> str:
    """Put a check's RAW output in the content-addressed store, return its locator.

    ``EvidenceItem.evidence_locator`` has to be re-readable later, which is the
    whole reason the schema demands an ``artifact-locator:sha256:`` URI. The
    pre-existing ignition items synthesised that URI from the digest of their
    own details dict -- shape-valid, and pointing at nothing that was ever
    stored. These bytes are stored.
    """

    locator = store.put_bytes(
        report.output_bytes,
        media_type="text/plain",
        metadata={
            "kind": "ignition_check_output",
            "check_kind": report.kind,
            "evaluator": report.evaluator,
            "passed": report.passed,
            "filename_hint": f"{report.evaluator}.log",
        },
        provenance=ContractProvenance(
            origin="daedalus.ignition.gate1",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=(report.output_sha256,),
            trace_id=trace_id,
        ).to_dict(),
    )
    return locator.locator_uri


def check_evidence_item(
    report: ignition_checks.CheckReport,
    *,
    evidence_id: str,
    locator: str,
    source_revision: str,
    collected_at: str,
    assurance: str,
    assurance_reason: str,
    extra_detail: Mapping[str, Any] | None = None,
) -> EvidenceItem:
    """One check as evidence, with the reason for its assurance IN the record."""

    from daedalus.schemas import _locator_sha256  # local: private validator reuse

    detail = {
        **report.to_dict(),
        "assurance_reason": assurance_reason,
        **dict(extra_detail or {}),
    }
    return EvidenceItem(
        evidence_id=evidence_id,
        evaluator=report.evaluator,
        assurance=assurance,
        verdict="passed" if report.passed else "failed",
        output_sha256=report.output_sha256,
        evidence_locator=locator,
        collected_at=collected_at,
        provenance=ContractProvenance(
            origin="daedalus.ignition.gate1",
            source_revision=source_revision,
            created_at=collected_at,
            input_digests=(report.output_sha256, _locator_sha256(locator)),
            trace_id="gate1-voltage-ignition",
        ),
        details=detail,
    )


def _plain_item(
    *,
    evidence_id: str,
    evaluator: str,
    output_sha256: str,
    locator: str,
    source_revision: str,
    collected_at: str,
    details: Mapping[str, Any],
    verdict: str = "passed",
    assurance: str = "deterministic",
) -> EvidenceItem:
    from daedalus.schemas import _locator_sha256

    return EvidenceItem(
        evidence_id=evidence_id,
        evaluator=evaluator,
        assurance=assurance,
        verdict=verdict,
        output_sha256=output_sha256,
        evidence_locator=locator,
        collected_at=collected_at,
        provenance=ContractProvenance(
            origin="daedalus.ignition.gate1",
            source_revision=source_revision,
            created_at=collected_at,
            input_digests=(output_sha256, _locator_sha256(locator)),
            trace_id="gate1-voltage-ignition",
        ),
        details=dict(details),
    )


# --------------------------------------------------------------------------- #
# 6. the slice                                                                 #
# --------------------------------------------------------------------------- #
@dataclass
class IgnitionSliceResult:
    mission: MissionContract
    work_item_ids: tuple[str, ...]
    attempt_ids: tuple[str, ...]
    packet: EvidencePacket | None
    receipt: dict[str, Any]
    receipt_path: Path
    graph_delta: IgnitionGraphDelta
    blockers: tuple[str, ...]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_gate1_ignition(
    *,
    fixture_root: str | Path = DEFAULT_FIXTURE,
    receipt_root: str | Path = DEFAULT_RECEIPT_ROOT,
    workspace: str | Path | None = None,
    collected_at: str | None = None,
    gate_timeout_s: int = 300,
    keep_workspace: bool = False,
) -> IgnitionSliceResult:
    """Run the Gate-1 ignition slice once and write its receipt."""

    collected_at = collected_at or _now()
    fixture = Path(fixture_root).resolve()
    fixture_digest_before = tree_digest(fixture)
    receipt_dir = Path(receipt_root).resolve()
    # ONE MISSION, ONE RECEIPT, ONE STORE. The receipt is overwritten by a
    # replay, so a store shared across runs would keep evidence blobs no
    # surviving receipt points at -- and pytest output carries its own duration,
    # so every run adds new ones forever. Resetting it here keeps the store and
    # the receipt describing the same run.
    store_root = _reset_evidence_store(receipt_dir / SESSION_MISSION_ID / "store")
    blockers: list[str] = []

    scratch = Path(workspace) if workspace else Path(
        tempfile.mkdtemp(prefix="daedalus-ignition-")
    )
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        repo, base_revision = prepare_ignition_repo(fixture, scratch / "target")

        # -- the four planes produce two typed work items ------------------- #
        planned = plan_work_items(repo)
        if len(planned) != 2:
            raise IgnitionError(
                f"Gate 1 requires exactly two work items; the manifest produced {len(planned)}"
            )
        session = ignition_session(repo, planned)
        mission = ignition_mission(
            session, base_revision=base_revision, created_at=collected_at,
            gate_timeout_s=gate_timeout_s,
        )
        if mission.mission_id != SESSION_MISSION_ID:
            raise IgnitionError(
                f"mission id {mission.mission_id!r} does not match the constant "
                f"{SESSION_MISSION_ID!r} the evidence store was placed under; "
                "the store and the receipt would describe different missions"
            )
        tasks = session.tasks()
        work_item_ids = session.work_item_ids()

        # -- the base Fourfold, and the before-state of the criterion ------- #
        base_compile = compile_reference_project(
            repo, source_revision=base_revision, created_at=collected_at,
            trace_id="gate1-voltage-base",
        )
        base_pytest = ignition_checks.pytest_check(
            repo, timeout_s=float(gate_timeout_s), label="pytest-base",
        )
        if base_pytest.passed:
            blockers.append(
                "the conformance suite already passes on the base revision; the "
                "criterion does not discriminate and the Gate-1 result would be vacuous"
            )

        # -- two attempts, each through the attempt spine -------------------- #
        reports: dict[str, ignition_checks.CheckReport] = {}
        gates = (code_type_gate(reports, timeout_s=float(gate_timeout_s)),
                 data_knowledge_gate(reports, timeout_s=float(gate_timeout_s)))
        attempts: list[Any] = []
        attempt_results: list[Any] = []
        for index, (planned_item, task, gate) in enumerate(zip(planned, tasks, gates)):
            spec = TaskSpec(
                task_id=task.work_item_id,
                instruction=task.objective,
                base_revision=base_revision,
                target_paths=tuple(task.paths),
                # Where each gate's criterion lives INSIDE the candidate
                # tree. BOTH gates now run the seeded conformance suite, which
                # no work item may write, so both verdicts are sealed from the
                # candidate (93489855 for the API; the data/knowledge nodes
                # landed 2026-08-23, closing this receipt's own remaining_gap).
                # The schema and link checks still run under the data/knowledge
                # gate, but as measurements: their criterion is module code, not
                # a tree file, so naming them here would seal nothing.
                gate_criterion_paths=(ignition_checks.CONFORMANCE_TEST_PATH,),
                # DECLARED, BECAUSE IT IS TRUE AND WAS PREVIOUSLY UNSAID. The
                # conformance suite inserts <root>/src on sys.path and imports
                # ignition_app, whose package reaches src/ignition_app/models.py
                # and repository.py -- the very files this work item writes.
                # That is what a FAIL_TO_PASS conformance test DOES, and the
                # slice used to seal only because the seal's import reader could
                # not see through the sys.path insertion. Saying it here keeps
                # the seal and moves the fact into the task digest and the
                # receipt's reason, where a reader can see how much of what
                # judged the candidate the candidate wrote. The criterion FILE
                # and everything on its collection path stay outside the scope,
                # so the candidate still cannot change what the gate ASKS.
                # TRUE FOR THE CODE/TYPE ITEM ONLY, and measured rather
                # than assumed for the other: the code/type nodes import
                # ignition_app from src/, which that item writes. The
                # data/knowledge nodes read the CSV and the wiki page through
                # pathlib and never import the candidate's package, so nothing
                # that item writes is on their execution path.
                gate_reads_scope=bool(
                    "code" in planned_item.planes or "type" in planned_item.planes
                ),
                gate_timeout_s=float(gate_timeout_s),
                metadata={
                    "mission_id": mission.mission_id,
                    "work_item_id": task.work_item_id,
                    "planes": list(planned_item.planes),
                    "operator": "daedalus.ignition.rename_operator",
                },
            )
            attempt = TaskAttempt(
                spec,
                runner=rename_operator(task.paths),
                gate=gate,
                repo_root=repo,
                ledger_path=scratch / "spine.sqlite3",
                artifact_dir=store_root,
                mission_id=mission.mission_id,
                budget=ResourceBudget(max_wall_time_s=int(gate_timeout_s)),
            )
            result = attempt.run()
            attempts.append(attempt)
            attempt_results.append(result)
            task.mark("landed" if result.ok else "bounced", dict(result.to_dict()))
            if not result.ok:
                blockers.append(
                    f"work item {task.work_item_id} did not produce a gated candidate: "
                    f"state={result.state} error={result.error}"
                )

        contract_sets = [result.contract_set() for result in attempt_results]
        for work_item_id, result, contracts in zip(work_item_ids, attempt_results, contract_sets):
            if contracts is None or not contracts.complete:
                blockers.append(
                    f"work item {work_item_id} produced no complete canonical contract "
                    f"set: {getattr(contracts, 'error', None) or result.contracts_error}"
                )

        # -- the candidate, composed from the attempts' own patches ---------- #
        patches = [
            result.artifact.diff_bytes if result.artifact is not None else b""
            for result in attempt_results
        ]
        candidate_root = compose_candidate(repo, patches, scratch / "candidate")
        candidate_digest = tree_digest(candidate_root)
        declared = tuple(path for item in planned for path in item.paths)
        stragglers = old_symbol_occurrences(candidate_root, declared)
        if stragglers:
            blockers.append(
                "old trusted symbol remains in the composed candidate: "
                + ", ".join(stragglers)
            )

        # A CANDIDATE WHOSE FOURFOLD DOES NOT COMPILE IS A GATE-1 RESULT, not an
        # exception. Measured: dropping schemas/event.schema.json from the data
        # work item makes the manifest claim a schema field the schema does not
        # have, and ``verify_claims`` refuses the snapshot -- the cross-plane
        # verifier catching the half-finished rename one layer before the schema
        # check does. Letting that escape would destroy the receipt that says so.
        try:
            candidate_compile = compile_reference_project(
                candidate_root, source_revision=candidate_digest,
                created_at=collected_at, trace_id="gate1-bias-voltage-candidate",
            )
        except Exception as exc:  # noqa: BLE001 - recorded as a blocker
            blockers.append(
                f"the candidate Fourfold does not compile: {type(exc).__name__}: {exc}"
            )
            receipt_path, receipt = write_receipt(
                _refused_receipt(
                    mission=mission,
                    work_item_ids=work_item_ids,
                    base_revision=base_revision,
                    candidate_revision=candidate_digest,
                    base_compile=base_compile,
                    binding=_attempt_binding(
                        mission, work_item_ids, attempts, attempt_results,
                        contract_sets, reports,
                    ),
                    base_pytest=base_pytest,
                    fixture_digest=fixture_digest_before,
                    collected_at=collected_at,
                    blockers=blockers,
                ),
                receipt_dir,
            )
            return IgnitionSliceResult(
                mission=mission, work_item_ids=work_item_ids,
                attempt_ids=tuple(a.attempt_id for a in attempts),
                packet=None, receipt=receipt, receipt_path=receipt_path,
                graph_delta=IgnitionGraphDelta((), (), (), ()),
                blockers=tuple(blockers),
            )
        delta = fourfold_graph_delta(base_compile.snapshot, candidate_compile.snapshot)
        if not delta.added_nodes or not delta.removed_nodes:
            blockers.append("rename produced no observable Fourfold node delta")
        try:
            behavior = dict(candidate_behavior(candidate_root))
        except Exception as exc:  # noqa: BLE001 - recorded as a blocker, not raised
            behavior = {"error": f"{type(exc).__name__}: {exc}"}
            blockers.append(f"candidate behavior could not be measured: {behavior['error']}")
        behavior_ok = (
            behavior.get("has_old_voltage_attribute") is False
            and behavior.get("bias_voltage") == 125.0
        )
        if not behavior_ok:
            blockers.append("candidate behavior does not satisfy the rename contract")

        # -- the three checks over the composed candidate -------------------- #
        composed_pytest = ignition_checks.pytest_check(
            candidate_root, timeout_s=float(gate_timeout_s), label="pytest-composed",
        )
        composed_schema = ignition_checks.schema_check(candidate_root)
        composed_link = ignition_checks.link_check(candidate_root)
        composed = (composed_pytest, composed_schema, composed_link)
        for report in composed:
            if not report.passed:
                blockers.append(
                    f"the {report.kind} check failed on the composed candidate: "
                    f"{report.detail.get('problems') or report.detail.get('output_tail')}"
                )
        anchored_node_roles = measure_anchored_node_roles(
            repo, gate_timeout_s=float(gate_timeout_s)
        )
        discrimination = _measure_discrimination(
            candidate_root, repo, base_pytest, scratch / "controls",
            gate_timeout_s=float(gate_timeout_s),
        )
        for name, observed in discrimination.items():
            if observed.get("passed") is not False:
                blockers.append(
                    f"negative control {name} did not go red; the {name.split('.')[0]} "
                    "check does not discriminate"
                )
        blockers.extend(criterion_discrimination_blockers(anchored_node_roles))

        # -- one EvidencePacket ---------------------------------------------- #
        store = ArtifactStore(store_root)
        assurance, assurance_reason, assurance_problem = _derive_assurance(composed, declared)
        if assurance_problem:
            blockers.append(assurance_problem)

        items: list[EvidenceItem] = []
        for report, evidence_id in zip(
            composed,
            ("gate1-check-pytest", "gate1-check-schema", "gate1-check-links"),
        ):
            items.append(
                check_evidence_item(
                    report,
                    evidence_id=evidence_id,
                    locator=_store_check(
                        store, report, source_revision=candidate_digest,
                        created_at=collected_at, trace_id="gate1-voltage-ignition",
                    ),
                    source_revision=candidate_digest,
                    collected_at=collected_at,
                    assurance=assurance,
                    assurance_reason=assurance_reason,
                    extra_detail={
                        "negative_control": {
                            key: value for key, value in discrimination.items()
                            if key.startswith(report.kind)
                        },
                        # Named explicitly so the reader of this item can see
                        # exactly how much of what it judged the candidate
                        # wrote, instead of inferring it from two other fields.
                        "subject_paths_in_candidate_write_scope": sorted(
                            set(report.subject_paths) & set(declared)
                        ),
                        "criterion_paths_in_candidate_write_scope": sorted(
                            set(report.criterion_paths) & set(declared)
                        ),
                    },
                )
            )

        behavior_report = ignition_checks.CheckReport(
            kind="behavior", evaluator="ignition-behavior", passed=behavior_ok,
            criterion_paths=("daedalus/ignition/gate1.py",),
            subject_paths=("src/ignition_app",),
            detail=dict(behavior), output=json.dumps(behavior, sort_keys=True),
        )
        delta_report = ignition_checks.CheckReport(
            kind="graph-delta", evaluator="ignition-graph-delta",
            passed=bool(delta.added_nodes and delta.removed_nodes),
            criterion_paths=("daedalus/twin/reference_compiler.py",),
            subject_paths=("fourfold.json",),
            detail=delta.to_dict(), output=json.dumps(delta.to_dict(), sort_keys=True),
        )
        for report, evidence_id in (
            (behavior_report, "gate1-behavior"),
            (delta_report, "gate1-graph-delta"),
        ):
            items.append(
                check_evidence_item(
                    report,
                    evidence_id=evidence_id,
                    locator=_store_check(
                        store, report, source_revision=candidate_digest,
                        created_at=collected_at, trace_id="gate1-voltage-ignition",
                    ),
                    source_revision=candidate_digest,
                    collected_at=collected_at,
                    assurance="deterministic",
                    assurance_reason=assurance_reason,
                )
            )

        binding = _attempt_binding(
            mission, work_item_ids, attempts, attempt_results, contract_sets, reports,
        )
        binding_report = ignition_checks.CheckReport(
            kind="attempt-binding", evaluator="ignition-attempt-binding",
            passed=all(row["gate_passed"] for row in binding["attempts"]),
            criterion_paths=("daedalus/spine/receipts.py",),
            subject_paths=tuple(work_item_ids),
            detail=binding, output=json.dumps(binding, sort_keys=True, indent=2),
        )
        items.append(
            check_evidence_item(
                binding_report,
                evidence_id="gate1-attempt-binding",
                locator=_store_check(
                    store, binding_report, source_revision=candidate_digest,
                    created_at=collected_at, trace_id="gate1-voltage-ignition",
                ),
                source_revision=candidate_digest,
                collected_at=collected_at,
                assurance="deterministic",
                assurance_reason=(
                    "the bound records are the attempt spine's own AttemptContract, "
                    "PolicyDecision, EvidencePacket and AttemptReceipt digests, read "
                    "back through AttemptContractSet.from_dict; this item asserts "
                    "only that they exist and what they say"
                ),
            )
        )

        # THE PACKET IS ASSEMBLED FAIL-SOFT, and the receipt is written either
        # way. ``assemble_fourfold_evidence_packet`` mints a PASSED packet, and
        # ``EvidencePacket`` refuses a passed packet that contains a failed or
        # unverified item -- so a red check does not produce a red packet, it
        # produces NO packet. Letting that exception escape would destroy the
        # receipt that says why, which is the one artifact a failed Gate-1 run
        # is actually for.
        packet: EvidencePacket | None = None
        packet_error: str | None = None
        try:
            packet = assemble_fourfold_evidence_packet(
                snapshot=candidate_compile.snapshot,
                candidate_artifact_sha256=candidate_compile.source_bundle_sha256,
                candidate_artifact_locator=(
                    f"artifact-locator:sha256:{candidate_compile.source_bundle_sha256}"
                ),
                packet_id="gate1-voltage-evidence",
                mission_id=mission.mission_id,
                attempt_id=_packet_attempt_id(attempts),
                attempt_contract_sha256=_attempt_chain_digest(contract_sets, "attempt"),
                policy_decision_sha256=_attempt_chain_digest(contract_sets, "policy"),
                collected_at=collected_at,
                usage=ResourceUsage(wall_time_ms=binding["total_gate_ms"]),
                trace_id="gate1-voltage-ignition",
                extra_items=tuple(items),
                # The mission's own store, so the snapshot bytes land beside
                # the six check outputs already in it and
                # `receipt_path.parent / "store"` resolves every locator in
                # this packet rather than six of seven.
                store=store,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never silent
            packet_error = f"{type(exc).__name__}: {exc}"
            blockers.append(f"no EvidencePacket could be assembled: {packet_error}")

        fixture_digest_after = tree_digest(fixture)
        if fixture_digest_before != fixture_digest_after:
            raise IgnitionError("the fixture tree changed while the slice ran")

        receipt = _build_receipt(
            mission=mission,
            work_item_ids=work_item_ids,
            base_revision=base_revision,
            candidate_revision=candidate_digest,
            base_compile=base_compile,
            candidate_compile=candidate_compile,
            packet=packet,
            packet_error=packet_error,
            binding=binding,
            checks=composed,
            base_pytest=base_pytest,
            discrimination=discrimination,
            anchored_nodes=anchored_node_roles,
            delta=delta,
            fixture_digest=fixture_digest_before,
            collected_at=collected_at,
            blockers=blockers,
        )
        receipt_path, receipt = write_receipt(receipt, receipt_dir)
        return IgnitionSliceResult(
            mission=mission,
            work_item_ids=work_item_ids,
            attempt_ids=tuple(attempt.attempt_id for attempt in attempts),
            packet=packet,
            receipt=receipt,
            receipt_path=receipt_path,
            graph_delta=delta,
            blockers=tuple(blockers),
        )
    finally:
        if not keep_workspace and workspace is None:
            shutil.rmtree(scratch, ignore_errors=True)


def _derive_assurance(
    reports: Sequence[ignition_checks.CheckReport],
    declared_write_scope: Sequence[str],
) -> tuple[str, str, str | None]:
    """Decide what the Gate-1 checks are worth, from what they read.

    Two conditions, both necessary, and the reason travels into every evidence
    item's ``details`` so a reader never has to trust this function's word:

    1. **No criterion may sit in the candidate's write scope.** A test file a
       work item is allowed to edit is a verdict the candidate can author.
    2. **At least one check must be ANCHORED** -- must state its criterion in a
       tree file that is provably outside every work item's ``target_paths``.
       The schema and link checks compare two candidate-written artefacts
       against a rule in :mod:`daedalus.ignition.checks`; that rule cannot be
       reached by a candidate, but it also cannot tell a correct rename from a
       consistent WRONG one (renaming the field to ``foo`` in both the CSV and
       the schema passes the schema check). The frozen conformance suite is
       what refuses that, so a run where it is absent gets no deterministic
       assurance no matter how green the other two are.

    This mirrors :func:`daedalus.spine.receipts.evaluator_assurance`'s standard
    -- "the criterion came from outside the candidate" -- applied to a
    criterion set the attempt spine cannot see (see the blocker note in the
    receipt).
    """

    scope = {str(path).replace("\\", "/") for path in declared_write_scope}
    criteria = {path for report in reports for path in report.criterion_paths}
    overlap = sorted(criteria & scope)
    anchors = sorted(
        path for report in reports for path in report.criterion_paths if path not in scope
    )
    if overlap:
        return (
            "unverified",
            "criterion path(s) inside a work item's declared target_paths "
            f"({', '.join(overlap)}); the candidate could have authored its own verdict",
            "check criterion overlaps candidate write scope: " + ", ".join(overlap),
        )
    if not anchors:
        return (
            "unverified",
            "no check states its criterion in a tree file outside the candidate's "
            "write scope; every verdict rests on rules that cannot distinguish a "
            "correct rename from a consistently wrong one",
            "no anchored check: the Gate-1 checks have no frozen in-tree criterion",
        )
    return (
        "deterministic",
        "criteria are authored outside the candidate: the evaluators live in "
        "daedalus.ignition.checks and the anchoring criterion "
        f"({', '.join(anchors)}) is part of the base revision and outside every "
        "work item's declared target_paths, which the attempt spine's target-scope "
        "containment enforced (each attempt's changed_paths is a subset of its "
        "target_paths, recorded in gate1-attempt-binding). The schema and link "
        "checks judge candidate-written artefacts against rules in that module; "
        "they are cross-plane consistency checks, and the anchoring suite is what "
        "makes a consistent-but-wrong rename fail. Each check's negative control "
        "is recorded beside it.",
        None,
    )


def _measure_discrimination(
    candidate: Path,
    repo: Path,
    base_pytest: ignition_checks.CheckReport,
    control_root: Path,
    *,
    gate_timeout_s: float,
) -> dict[str, Any]:
    """Show each check going RED, so a green one means something.

    A check that has never been observed to fail is a check nobody has measured.
    Each control below is the SMALLEST edit that should break exactly one check:
    the base revision for pytest, a half-finished rename for the schema check, a
    deleted link target for the link check.
    """

    control_root.mkdir(parents=True, exist_ok=True)
    observed: dict[str, Any] = {
        "pytest.base_revision": {
            "control": "run the conformance suite on the unmodified base revision",
            "passed": base_pytest.passed,
            "returncode": base_pytest.detail.get("returncode"),
        }
    }


    half = control_root / "half-renamed"
    if half.exists():
        shutil.rmtree(half, ignore_errors=True)
    shutil.copytree(candidate, half)
    shutil.copy2(repo / "schemas/event.schema.json", half / "schemas/event.schema.json")
    half_report = ignition_checks.schema_check(half)
    observed["schema.half_renamed"] = {
        "control": "revert schemas/event.schema.json to the base revision, keep the renamed CSV",
        "passed": half_report.passed,
        "problems": half_report.detail.get("problems"),
    }

    broken = control_root / "broken-links"
    if broken.exists():
        shutil.rmtree(broken, ignore_errors=True)
    shutil.copytree(candidate, broken)
    (broken / "data/events.csv").unlink()
    broken_report = ignition_checks.link_check(broken)
    observed["link.missing_target"] = {
        "control": "delete data/events.csv, which wiki/Event.md links to",
        "passed": broken_report.passed,
        "problems": broken_report.detail.get("problems"),
    }
    return observed


def measure_anchored_node_roles(repo: Path, *, gate_timeout_s: float) -> dict[str, Any]:
    """What each anchored node DID on the base revision, one node at a time.

    "The suite fails on base" does not say which node moved. A node that already
    passes on the base revision is a regression guard, not discrimination, and
    counting it as discrimination is how a criterion set comes to look stronger
    than it is. Measured here rather than declared: two of the three
    data/knowledge nodes are FAIL_TO_PASS and ``test_wiki_links_resolve`` is a
    guard (the base fixture's links already resolve), and the receipt says so.

    This is NOT a negative control -- a control is an edit that must turn a
    check red, and the receipt refuses one that stays green. These rows are a
    classification of the criterion set, so they live beside the controls.
    """

    roles: dict[str, Any] = {}
    for label, node_ids in (
        ("code-type", ignition_checks.CODE_TYPE_NODE_IDS),
        ("data-knowledge", ignition_checks.DATA_KNOWLEDGE_NODE_IDS),
    ):
        for node in node_ids:
            report = ignition_checks.pytest_check(
                repo, (node,), timeout_s=float(gate_timeout_s), label=f"base-{label}",
            )
            roles[node] = {
                "gate": label,
                "passed_on_base_revision": report.passed,
                "role": "pass_to_pass_guard" if report.passed else "fail_to_pass",
            }
    return roles


#: Replay fields that must hold between two runs of the SAME criterion. The
#: packet digest is deliberately not among them (evidence items bind raw
#: evaluator output, and pytest prints its own duration), and the mission digest
#: is clock-bound, so both are reported without being required.
REPLAY_REQUIRED_STABLE = (
    "mission_id_stable",
    "work_item_ids_stable",
    "base_revision_stable",
    "candidate_revision_stable",
    "graph_delta_stable",
    "check_reports_stable",
)


def criterion_discrimination_blockers(roles: Mapping[str, Any]) -> list[str]:
    """A gate whose anchored nodes all pass on the base revision has no
    criterion of its own.

    THIS IS THE ANSWER TO "THE SEAL AUTHENTICATES A PATH, NOT A PROPOSITION"
    (Codex round 1, 2026-08-23). Every one of the spine's six seal checks --
    path outside the scope, present in the base revision, no writable execution
    path, no in-tree import, named by the gate -- stays green if an operator
    edits the seeded suite until it asserts nothing, because all six measure the
    criterion as a blob. What such an edit cannot survive is the measurement
    beside them: a node that no longer fails on the base revision is recorded as
    a guard, and a gate left with only guards is refused here.

    MEASURED while writing this: replacing the seeded assertions with
    ``assert header is not None`` / ``pass`` turns all three data/knowledge
    nodes into guards, and this function refuses.
    """

    out: list[str] = []
    for gate_label in ("code-type", "data-knowledge"):
        rows = [row for row in roles.values() if row.get("gate") == gate_label]
        if rows and not any(row.get("role") == "fail_to_pass" for row in rows):
            out.append(
                f"the {gate_label} gate has no anchored node that fails on the base "
                "revision; its criterion set guards but does not discriminate"
            )
    return out


def _replay_blockers(replay: Mapping[str, Any]) -> list[str]:
    """Replay instability is a Gate-1 result, not a footnote.

    Plan section 10 requires restart/replay to work, and until now the receipt
    merely REPORTED the comparison: a run whose base revision, candidate
    revision or graph delta moved between two identical invocations still came
    out with an empty ``blockers`` list (Codex round 1, 2026-08-23). It is a
    blocker now -- unless the criterion itself changed since the previous run,
    which moves the base revision by construction and is named as the reason
    rather than silently tolerated.
    """

    if not replay.get("is_replay"):
        return []
    unstable = [name for name in REPLAY_REQUIRED_STABLE if replay.get(name) is False]
    if not unstable:
        return []
    if replay.get("criterion_changed_since_previous"):
        return [
            "replay comparison spans a criterion change ("
            + ", ".join(unstable)
            + " differ); the previous run judged with conformance suite "
            + str(replay.get("previous_conformance_test_sha256"))[:12]
            + ". Run the slice again to compare two runs of the SAME criterion."
        ]
    return [
        "replay is not stable across two runs of the same criterion: "
        + ", ".join(unstable)
    ]


def _packet_attempt_id(attempts: Sequence[Any]) -> str:
    """The Gate-1 packet's attempt id: the two attempts, named as one chain.

    The packet covers a candidate composed from TWO attempts, and
    ``EvidencePacket.attempt_id`` is a single identifier. Rather than pick one
    attempt and imply the other did not happen, the id is derived from both and
    the attempt-binding evidence item carries the pair verbatim.
    """

    digest = canonical_sha([attempt.attempt_id for attempt in attempts])
    return f"gate1-voltage-composed-{digest[:12]}"


def _attempt_chain_digest(contract_sets: Sequence[Any], name: str) -> str:
    """One digest binding both attempts' contracts of a given kind.

    Refuses rather than substitutes: a missing contract means the packet would
    bind a digest of nothing, which is exactly the placeholder this slice
    replaced (``canonical_sha({"attempt": "gate1-voltage"})``).
    """

    digests = []
    for index, contracts in enumerate(contract_sets):
        contract = getattr(contracts, name, None) if contracts is not None else None
        if contract is None:
            raise IgnitionError(
                f"attempt {index} produced no canonical {name} contract; the Gate-1 "
                "packet cannot bind a digest that stands for nothing"
            )
        digests.append(contract.digest)
    return canonical_sha({"schema": f"daedalus-ignition-{name}-chain/1", "digests": digests})


def _attempt_binding(
    mission: MissionContract,
    work_item_ids: Sequence[str],
    attempts: Sequence[Any],
    results: Sequence[Any],
    contract_sets: Sequence[Any],
    reports: Mapping[str, ignition_checks.CheckReport],
) -> dict[str, Any]:
    """What the two attempts actually produced, verbatim, including the weak parts."""

    rows = []
    total_ms = 0
    for work_item_id, attempt, result, contracts in zip(
        work_item_ids, attempts, results, contract_sets
    ):
        gate = result.gates
        gate_ms = int(round((gate.duration_s if gate is not None else 0.0) * 1000))
        total_ms += gate_ms
        evidence = getattr(contracts, "evidence", None)
        rows.append({
            "work_item_id": work_item_id,
            "attempt_id": attempt.attempt_id,
            "mission_id": attempt.mission_id,
            "state": result.state,
            "branch": result.branch,
            "target_paths": list(attempt.task.target_paths),
            "changed_paths": list(result.artifact.changed_paths) if result.artifact else [],
            "patch_sha256": result.artifact.diff_sha256 if result.artifact else None,
            "patch_locator": (result.artifact_locator or {}).get("locator_uri"),
            "worktree_removed": bool(result.worktree_removed),
            "gate_name": gate.name if gate is not None else None,
            # THE COMMAND, because the seal's fourth check is "the gate that ran
            # actually named the criterion" and until now nothing in the receipt
            # let a reader verify it (Codex round 1, 2026-08-23). The declared
            # criterion path sat in the task digest, the argv nowhere.
            "gate_command": (
                [str(part) for part in (getattr(gate, "command", ()) or ())]
                if gate is not None else []
            ),
            # From the ATTEMPT's task, not the result: the spec is what declared
            # the criterion, and the result carries only the gate's outcome.
            "gate_criterion_paths": [
                str(path)
                for path in (getattr(getattr(attempt, "task", None), "gate_criterion_paths", ()) or ())
            ],
            "gate_passed": bool(gate.passed) if gate is not None else False,
            "gate_ms": gate_ms,
            "gate_output_sha256": gate.output_sha256 if gate is not None else None,
            "runtime_manifest_sha256": getattr(getattr(contracts, "runtime", None), "digest", None),
            "policy_decision_sha256": getattr(getattr(contracts, "policy", None), "digest", None),
            "policy_verdict": getattr(getattr(contracts, "policy", None), "verdict", None),
            "attempt_contract_sha256": getattr(getattr(contracts, "attempt", None), "digest", None),
            "evidence_packet_sha256": getattr(evidence, "digest", None),
            "evidence_status": getattr(evidence, "evaluation_status", None),
            "evidence_assurance": sorted(
                {item.assurance for item in getattr(evidence, "items", ())}
            ),
            "attempt_receipt_sha256": getattr(getattr(contracts, "receipt", None), "digest", None),
            "contracts_error": getattr(contracts, "error", None),
        })
    return {
        "schema": "daedalus-ignition-attempt-binding/1",
        "mission_id": mission.mission_id,
        "mission_sha256": mission.digest,
        "attempts": rows,
        "total_gate_ms": total_ms,
        "check_reports": ignition_checks.check_manifest(
            [reports[key] for key in sorted(reports)]
        ),
    }


#: WHAT THIS USED TO BE, AND WHY IT IS ONE SENTENCE NOW. This constant carried
#: a literal diff for the ``gate_criterion_paths`` seal, kept beside the
#: detection so a reader of the receipt could see the proposed fix. The API
#: landed in 93489855 and the seal was HARDENED afterwards -- the shipped
#: version normalises both sides of the comparison, refuses an unarmed write
#: scope, requires the criterion to be a regular file in the base revision tree
#: and requires the gate that ran to have named it. The old text advertised the
#: naive raw-string-set version, which three different spellings of one path
#: walked straight through. A proposal that no longer matches the code is worse
#: than no proposal: it tells a reader to re-introduce the hole. The authority
#: is :func:`daedalus.spine.receipts.evaluator_assurance_detail` and its
#: docstring; this constant only says so.
ATTEMPT_ASSURANCE_HUNK = (
    "superseded: the gate_criterion_paths API landed in 93489855 and the seal "
    "that reads it was hardened afterwards (path normalisation on both sides, "
    "an armed write scope required, base-revision presence measured, and the "
    "gate's own command required to name the criterion). See "
    "daedalus.spine.receipts.evaluator_assurance_detail for the live rule; "
    "there is no pending hunk."
)


def _attempt_assurance_blocker(binding: Mapping[str, Any]) -> dict[str, Any] | None:
    """Name the kernel gap, but only when this run actually hit it.

    MEASURED, NOT ASSERTED. If a future attempt path grants these gates a
    conclusive assurance, this returns ``None`` and the receipt stops carrying a
    blocker nobody has to remove by hand.
    """

    api_present = "gate_criterion_paths" in getattr(TaskSpec, "__dataclass_fields__", {})
    weak = [
        {
            "work_item_id": row["work_item_id"],
            "gate_name": row["gate_name"],
            "evidence_status": row["evidence_status"],
            "evidence_assurance": row["evidence_assurance"],
        }
        for row in binding["attempts"]
        if row["evidence_status"] != "passed" or "unverified" in (row["evidence_assurance"] or [])
    ]
    if not weak:
        return None
    if api_present:
        # The kernel API landed (93489855). What remains inconclusive is not a
        # missing seam but a criterion the candidate itself may write: the
        # data/knowledge gate judges schema-against-CSV, and the rename edits
        # both, so no tree path outside the write scope states it.
        return {
            "missing_api": None,
            "symptom": (
                "an attempt whose gate criterion lives inside its own write "
                "scope reads 'inconclusive'/'unverified' by design"
            ),
            "measured": weak,
            "consequence": (
                "the Gate-1 packet binds that attempt's packet by digest with "
                "its real status and derives the slice-level assurance from "
                "the composed checks; see the gate1-attempt-binding item"
            ),
            "remaining_gap": (
                "a second, spine-authored reading of the schema/CSV relation "
                "(a frozen FAIL_TO_PASS receipt or a target-scope gate) would "
                "make the data/knowledge attempt conclusive"
            ),
            "owner": "daedalus/ignition/gate1.py data_knowledge_gate",
        }
    return {
        "missing_api": (
            "daedalus.spine.attempt.TaskSpec has no way to declare which paths "
            "state its gate's criterion, so daedalus.spine.receipts."
            "evaluator_assurance cannot tell a gate the candidate could have "
            "authored from one it could not. It grants 'deterministic' only for "
            "the spine's own target-scope gate or a frozen FAIL_TO_PASS receipt "
            "under measured containment; every other gate -- including these two, "
            "whose criteria are provably outside the work item's target_paths -- "
            "is 'unverified'. TaskAttempt._canonicalise also never forwards the "
            "'assurance' argument canonicalise_attempt already accepts, so a "
            "caller cannot supply the derivation either."
        ),
        "symptom": (
            "each attempt's own EvidencePacket is evaluation_status "
            "'inconclusive' with an 'unverified' item, although the gate passed "
            "and the patch stayed inside the declared scope"
        ),
        "measured": weak,
        "consequence": (
            "the Gate-1 packet therefore derives its own assurance in "
            "daedalus.ignition.gate1._derive_assurance and BINDS the attempt "
            "packets by digest with their real status, rather than promoting "
            "their verdicts; see the gate1-attempt-binding evidence item"
        ),
        "hunk": ATTEMPT_ASSURANCE_HUNK,
        "owner": "daedalus/spine/attempt.py + daedalus/spine/receipts.py (not this lane)",
    }


def _refused_receipt(
    *,
    mission: MissionContract,
    work_item_ids: Sequence[str],
    base_revision: str,
    candidate_revision: str,
    base_compile: Any,
    binding: Mapping[str, Any],
    base_pytest: ignition_checks.CheckReport,
    fixture_digest: str,
    collected_at: str,
    blockers: Sequence[str],
) -> dict[str, Any]:
    """The receipt for a run that got as far as two attempts and no further.

    Deliberately the SAME schema and the same key names as
    :func:`_build_receipt`, with the candidate-side fields null: a reader must
    not need a second parser to read a failed run, and a receipt whose shape
    changes with the outcome invites exactly the "no receipt means it did not
    run" reading that hides failures.
    """

    return {
        "schema": "daedalus-gate1-ignition-receipt/1",
        "gate": 1,
        "iron_plan": "ALIGNED",
        "collected_at": collected_at,
        "mission_id": mission.mission_id,
        "mission_sha256": mission.digest,
        "mission_objective": mission.objective,
        "mission_source_revision": mission.source_revision,
        "work_item_ids": list(work_item_ids),
        "attempts": [
            {
                key: row[key]
                for key in (
                    "work_item_id", "attempt_id", "state", "target_paths",
                    "changed_paths", "patch_sha256", "patch_locator",
                    "gate_name", "gate_passed", "gate_output_sha256",
                    # the seal's check 4 is "the gate that ran named the
                    # criterion"; both halves of that belong in the receipt
                    "gate_command", "gate_criterion_paths",
                    "attempt_contract_sha256", "policy_decision_sha256",
                    "policy_verdict", "evidence_packet_sha256",
                    "evidence_status", "evidence_assurance",
                    "attempt_receipt_sha256", "contracts_error",
                )
            }
            for row in binding["attempts"]
        ],
        "evidence_packet": {
            "packet_id": "gate1-voltage-evidence",
            "packet_sha256": None,
            "evaluation_status": None,
            "attempt_id": None,
            "source_revision": None,
            "candidate_artifact_sha256": None,
            "error": "the candidate was refused before any evidence could be assembled",
            "items": [],
        },
        "checks": {},
        "check_kinds": [],
        "discrimination": {
            "before_state": {
                "conformance_suite_on_base_revision_passed": base_pytest.passed,
                "conformance_test_sha256": ignition_checks.CONFORMANCE_TEST_SHA256,
            },
            "negative_controls": {},
        },
        "fourfold": {
            "base_source_bundle_sha256": base_compile.source_bundle_sha256,
            "candidate_source_bundle_sha256": None,
            "base_snapshot_sha256": base_compile.snapshot.digest,
            "candidate_snapshot_sha256": None,
            "graph_delta": None,
            "graph_delta_sha256": None,
        },
        "replay": {
            "base_revision": base_revision,
            "candidate_revision": candidate_revision,
            "fixture_tree_sha256": fixture_digest,
            "note": "this run was refused before the candidate compiled",
        },
        "promotion": {
            "status": "nominated, not promoted",
            "auto_merge": False,
            "owner_approval": "not requested",
            "reason": "nothing reached evidence; there is nothing to nominate",
        },
        "blockers": list(blockers),
        "blocker": _attempt_assurance_blocker(binding),
    }


def _build_receipt(
    *,
    mission: MissionContract,
    work_item_ids: Sequence[str],
    base_revision: str,
    candidate_revision: str,
    base_compile: Any,
    candidate_compile: Any,
    packet: EvidencePacket | None,
    packet_error: str | None,
    binding: Mapping[str, Any],
    checks: Sequence[ignition_checks.CheckReport],
    base_pytest: ignition_checks.CheckReport,
    discrimination: Mapping[str, Any],
    anchored_nodes: Mapping[str, Any],
    delta: IgnitionGraphDelta,
    fixture_digest: str,
    collected_at: str,
    blockers: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema": "daedalus-gate1-ignition-receipt/1",
        "gate": 1,
        "iron_plan": "ALIGNED",
        "collected_at": collected_at,
        "mission_id": mission.mission_id,
        "mission_sha256": mission.digest,
        "mission_objective": mission.objective,
        "mission_source_revision": mission.source_revision,
        "work_item_ids": list(work_item_ids),
        "attempts": [
            {
                key: row[key]
                for key in (
                    "work_item_id", "attempt_id", "state", "target_paths",
                    "changed_paths", "patch_sha256", "patch_locator",
                    "gate_name", "gate_passed", "gate_output_sha256",
                    # the seal's check 4 is "the gate that ran named the
                    # criterion"; both halves of that belong in the receipt
                    "gate_command", "gate_criterion_paths",
                    "attempt_contract_sha256", "policy_decision_sha256",
                    "policy_verdict", "evidence_packet_sha256",
                    "evidence_status", "evidence_assurance",
                    "attempt_receipt_sha256", "contracts_error",
                )
            }
            for row in binding["attempts"]
        ],
        "evidence_packet": {
            "packet_id": packet.packet_id if packet else "gate1-voltage-evidence",
            "packet_sha256": packet.digest if packet else None,
            "evaluation_status": packet.evaluation_status if packet else None,
            "attempt_id": packet.attempt_id if packet else None,
            "source_revision": packet.source_revision if packet else None,
            "candidate_artifact_sha256": (
                packet.candidate_artifact_sha256 if packet else None
            ),
            "error": packet_error,
            "items": [
                {
                    "evidence_id": item.evidence_id,
                    "evaluator": item.evaluator,
                    "assurance": item.assurance,
                    "verdict": item.verdict,
                    "output_sha256": item.output_sha256,
                    "evidence_locator": item.evidence_locator,
                }
                for item in (packet.items if packet else ())
            ],
        },
        "checks": {
            report.kind: {
                "evaluator": report.evaluator,
                "passed": report.passed,
                # The raw-output digest, which MOVES between replays: pytest
                # prints its own wall time. The structured verdict digest beside
                # it does not, and it is what the replay comparison uses.
                "output_sha256": report.output_sha256,
                "report_sha256": report.report_sha256,
            }
            for report in checks
        },
        "check_kinds": sorted({report.kind for report in checks}),
        "discrimination": {
            "before_state": {
                "conformance_suite_on_base_revision_passed": base_pytest.passed,
                "conformance_test_sha256": ignition_checks.CONFORMANCE_TEST_SHA256,
            },
            "negative_controls": dict(discrimination),
            "anchored_nodes": dict(anchored_nodes),
            # WHAT THE SEAL DOES NOT COVER, said in the record rather than left
            # for a reader to derive. The data/knowledge verdict is
            # `anchored nodes AND schema AND links`; the spine's seal is granted
            # for the declared criterion PATH and the argv that named it, so it
            # qualifies the GateResult as a whole. The schema and link conjuncts
            # state their criterion in daedalus.ignition.checks, which is not in
            # the judged tree at all -- no candidate can reach it -- but neither
            # is it pinned by the seal, and schema_check compares field SETS, so
            # a schema weakened to `{"properties": {"id": {}, "bias_voltage": {}},
            # "required": []}` would satisfy it. Today's operator is a literal
            # renamer and cannot author that; a more capable one could.
            # (Codex round 1, 2026-08-23.)
            "unsealed_verdict_conjuncts": {
                "ignition-data-knowledge": [
                    {
                        "evaluator": "ignition-schema-check",
                        "criterion_location": "daedalus.ignition.checks.schema_check",
                        "in_judged_tree": False,
                        "sealed_by_gate_criterion_paths": False,
                        "known_weakness": (
                            "compares CSV header and schema property SETS; a schema whose "
                            "properties carry no types and whose required list is empty "
                            "satisfies it, and per-row type checks are then vacuous"
                        ),
                    },
                    {
                        "evaluator": "ignition-link-check",
                        "criterion_location": "daedalus.ignition.checks.link_check",
                        "in_judged_tree": False,
                        "sealed_by_gate_criterion_paths": False,
                        "known_weakness": (
                            "requires each relative link to resolve to an existing file; a "
                            "link retargeted to another existing file still resolves"
                        ),
                    },
                ]
            },
        },
        "fourfold": {
            "base_source_bundle_sha256": base_compile.source_bundle_sha256,
            "candidate_source_bundle_sha256": candidate_compile.source_bundle_sha256,
            "base_snapshot_sha256": base_compile.snapshot.digest,
            "candidate_snapshot_sha256": candidate_compile.snapshot.digest,
            "graph_delta": delta.to_dict(),
            "graph_delta_sha256": delta.digest,
        },
        "replay": {
            "base_revision": base_revision,
            "candidate_revision": candidate_revision,
            "fixture_tree_sha256": fixture_digest,
            "note": (
                "mission_id, work_item_ids, base_revision and candidate_revision are "
                "functions of the fixture tree and the frozen git identity; attempt "
                "ids carry a per-run nonce by construction (the branch name IS the "
                "effect key) and are expected to differ between runs"
            ),
        },
        "promotion": {
            "status": "nominated, not promoted",
            "auto_merge": False,
            "owner_approval": "not requested",
            "reason": (
                "plan Invariant 5: promotion requires an evidence packet, policy "
                "checks and explicit owner approval; this slice produces the packet "
                "and stops"
            ),
        },
        # TWO FIELDS, TWO MEANINGS. ``blockers`` is what stopped THIS run from
        # producing a complete Gate-1 result and is what the exit code reports.
        # ``blocker`` is a kernel API this slice needed and did not find; the
        # run completed without it, so it must not be reported as a failure --
        # but it must not vanish either.
        "blockers": list(blockers),
        "blocker": _attempt_assurance_blocker(binding),
    }


def write_receipt(
    receipt: Mapping[str, Any], receipt_root: str | Path
) -> tuple[Path, dict[str, Any]]:
    """Write the receipt, and record how this run relates to the previous one.

    Returns the written body, not just the path. The replay comparison can only
    be made HERE -- it needs the previous receipt, which this is about to
    overwrite -- so a caller that kept its own pre-write dict would report a
    receipt whose replay block says nothing, while the file on disk said
    otherwise. One body, one truth.
    """

    directory = Path(receipt_root).resolve() / str(receipt["mission_id"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "receipt.json"
    body = dict(receipt)
    replay = dict(body.get("replay") or {})
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - a corrupt previous receipt is not fatal
            previous = {}
        previous_replay = dict(previous.get("replay") or {})

        def _reports(receipt_body: Mapping[str, Any]) -> dict[str, Any]:
            return {
                kind: row.get("report_sha256")
                for kind, row in (receipt_body.get("checks") or {}).items()
            }

        same_clock = previous.get("collected_at") == body.get("collected_at")
        replay.update({
            "is_replay": True,
            "previous_collected_at": previous.get("collected_at"),
            "same_collected_at": same_clock,
            "mission_id_stable": previous.get("mission_id") == body.get("mission_id"),
            "work_item_ids_stable": previous.get("work_item_ids") == body.get("work_item_ids"),
            "base_revision_stable": previous_replay.get("base_revision") == replay.get("base_revision"),
            "candidate_revision_stable": (
                previous_replay.get("candidate_revision") == replay.get("candidate_revision")
            ),
            "previous_mission_sha256": previous.get("mission_sha256"),
            # The mission CONTRACT digest binds provenance.created_at, so it is
            # stable only between runs given the same clock. Reported against
            # that condition rather than asserted unconditionally.
            "mission_sha256_stable": (
                previous.get("mission_sha256") == body.get("mission_sha256")
                if same_clock else None
            ),
            "previous_packet_sha256": (previous.get("evidence_packet") or {}).get("packet_sha256"),
            # MEASURED AND EXPECTED TO BE FALSE. Evidence items bind the digest
            # of the RAW evaluator output, and pytest prints its own duration,
            # so two identical runs produce two packet digests. The claim this
            # slice makes about replay is the one below: identical structured
            # verdicts, identical mission and work item ids, identical base and
            # candidate revisions, identical graph delta.
            "packet_sha256_stable": (
                (previous.get("evidence_packet") or {}).get("packet_sha256")
                == (body.get("evidence_packet") or {}).get("packet_sha256")
            ),
            "check_reports_stable": _reports(previous) == _reports(body),
            # WHAT THE PREVIOUS RUN JUDGED WITH. A criterion change moves the
            # base revision (the suite is seeded into it), so the identity
            # fields legitimately differ between the last run under the old
            # criterion and the first under the new one. Recording the previous
            # digest is what lets a reader -- and _replay_blockers below -- tell
            # that transition from a slice that is simply not deterministic.
            # Codex round 1, 2026-08-23: the receipt committed in d3cdb73b said
            # base_revision_stable false while the commit message claimed the
            # opposite, and nothing in the machinery objected.
            "previous_conformance_test_sha256": (
                (previous.get("discrimination") or {}).get("before_state") or {}
            ).get("conformance_test_sha256"),
            "criterion_changed_since_previous": (
                ((previous.get("discrimination") or {}).get("before_state") or {}).get(
                    "conformance_test_sha256"
                )
                != ignition_checks.CONFORMANCE_TEST_SHA256
            ),
            "previous_graph_delta_sha256": (previous.get("fourfold") or {}).get("graph_delta_sha256"),
            "graph_delta_stable": (
                (previous.get("fourfold") or {}).get("graph_delta_sha256")
                == (body.get("fourfold") or {}).get("graph_delta_sha256")
            ),
        })
    else:
        replay["is_replay"] = False
    body["replay"] = replay
    body["blockers"] = list(body.get("blockers") or []) + _replay_blockers(replay)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, body


__all__ = [
    "DEFAULT_FIXTURE",
    "DEFAULT_RECEIPT_ROOT",
    "IgnitionSliceResult",
    "PlannedWorkItem",
    "code_type_gate",
    "compose_candidate",
    "data_knowledge_gate",
    "ignition_mission",
    "ignition_session",
    "old_symbol_occurrences",
    "plan_work_items",
    "prepare_ignition_repo",
    "rename_operator",
    "run_gate1_ignition",
    "write_receipt",
]
