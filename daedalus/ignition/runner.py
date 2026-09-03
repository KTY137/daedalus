"""Deterministic Gate-1 ignition: ``voltage`` -> ``bias_voltage``.

This is a bounded Renovation slice, not an autonomous agent loop. It executes
two explicit WorkItems inside a copied candidate tree, proves that the source
fixture remains byte-identical, recompiles a real FourfoldSnapshot, measures a
graph delta and behavior, and emits one canonical EvidencePacket. It never
consumes approval and never promotes the candidate.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from daedalus.kernel.fourfold_evidence import assemble_fourfold_evidence_packet
from daedalus.schemas import ContractProvenance, EvidenceItem, EvidencePacket, ResourceUsage
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import compile_reference_project
from daedalus.twin.contracts import FourfoldSnapshot


class IgnitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class IgnitionWorkItem:
    work_item_id: str
    planes: tuple[str, ...]
    paths: tuple[str, ...]


WORK_ITEMS = (
    IgnitionWorkItem(
        "rename-code-type",
        ("code", "type"),
        (
            "src/ignition_app/models.py",
            "src/ignition_app/repository.py",
        ),
    ),
    IgnitionWorkItem(
        "rename-data-knowledge",
        ("data", "knowledge"),
        (
            "data/events.csv",
            "schemas/event.schema.json",
            "wiki/Event.md",
            "fourfold.json",
        ),
    ),
)


@dataclass(frozen=True)
class IgnitionGraphDelta:
    added_nodes: tuple[str, ...]
    removed_nodes: tuple[str, ...]
    added_bindings: tuple[str, ...]
    removed_bindings: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "added_nodes": list(self.added_nodes),
            "removed_nodes": list(self.removed_nodes),
            "added_bindings": list(self.added_bindings),
            "removed_bindings": list(self.removed_bindings),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class IgnitionResult:
    base_source_bundle_sha256: str
    candidate_source_bundle_sha256: str
    base_snapshot: FourfoldSnapshot
    candidate_snapshot: FourfoldSnapshot
    graph_delta: IgnitionGraphDelta
    evidence_packet: EvidencePacket
    behavior_sha256: str
    primary_tree_before_sha256: str
    primary_tree_after_sha256: str
    work_items: tuple[IgnitionWorkItem, ...] = WORK_ITEMS

    @property
    def primary_unchanged(self) -> bool:
        return self.primary_tree_before_sha256 == self.primary_tree_after_sha256


def _tree_digest(root: Path) -> str:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        rows.append({"path": rel, "sha256": canonical_sha({"bytes": path.read_bytes().hex()})})
    return canonical_sha({"schema": "daedalus-tree-digest/1", "files": rows})


def _replace(path: Path, old: str, new: str, *, expected: int | None = None) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 or (expected is not None and count != expected):
        raise IgnitionError(
            f"rename precondition failed for {path.name}: {old!r} count={count}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def materialize_voltage_rename(source_root: str | Path, candidate_root: str | Path) -> Path:
    source = Path(source_root).resolve()
    candidate = Path(candidate_root).resolve()
    if candidate.exists():
        raise IgnitionError("candidate root must not already exist")
    if candidate == source or source in candidate.parents:
        raise IgnitionError("candidate root must be isolated from the source fixture")
    shutil.copytree(source, candidate)

    # WorkItem A: Code + Type.
    _replace(candidate / "src/ignition_app/models.py", "    voltage: float", "    bias_voltage: float", expected=1)
    _replace(candidate / "src/ignition_app/repository.py", 'voltage=float(row["voltage"])', 'bias_voltage=float(row["bias_voltage"])', expected=1)

    # WorkItem B: Data + Knowledge, including the claims that define verified
    # Type->Data identities in the candidate snapshot.
    _replace(candidate / "data/events.csv", "id,voltage", "id,bias_voltage", expected=1)
    _replace(candidate / "schemas/event.schema.json", '"voltage"', '"bias_voltage"')
    _replace(candidate / "wiki/Event.md", "voltage", "bias_voltage")
    _replace(candidate / "fourfold.json", '"voltage"', '"bias_voltage"')
    return candidate


#: The probe body, which runs in a CHILD interpreter. It prints one JSON object
#: and nothing else, so the parent never has to guess where the measurement
#: starts. ``sys.argv[1]`` is the candidate's ``src``: under ``-c`` the argument
#: vector is ``['-c', <first extra arg>]``.
_BEHAVIOR_PROBE = """\
import json, sys
sys.path.insert(0, sys.argv[1])
import ignition_app
event = ignition_app.parse_event({"id": "1", "bias_voltage": "125.0"})
json.dump({
    "type": type(event).__name__,
    "id": event.id,
    "bias_voltage": event.bias_voltage,
    "has_old_voltage_attribute": hasattr(event, "voltage"),
}, sys.stdout)
"""

#: A candidate that has not answered in this long is a refusal. Generous on
#: purpose: the probe is one import and one call, and a bound that trips on a
#: slow box would read as a broken candidate.
BEHAVIOR_PROBE_TIMEOUT_S = 120.0


def _behavior(candidate: Path) -> Mapping[str, object]:
    """Measure the candidate's runtime behavior WITHOUT importing it here.

    THE PROCESS BOUNDARY IS THE POINT. Until 2026-09-03 this function did
    ``sys.path.insert(0, source)`` and ``importlib.import_module`` -- so the
    candidate's module-level code ran inside the interpreter that holds the
    ``python.attempt`` EffectLease, assembles the EvidencePacket, decides
    ``behavior_ok`` and writes the receipt. Master plan invariant 3 says
    candidate execution "cannot modify its evaluator, policy, evidence, budget
    ledger, or promotion mechanism", ``AGENTS.md`` lists "candidate access to
    its evaluator" as a release-blocking defect, and
    ``G1_ACTIVATION_CHECKLIST.md`` §2.3 named this exact line on 2026-08-17.
    ``tests/ignition/test_behavior_probe_isolation.py`` pins the fix by having
    the candidate record ``os.getpid()`` at import: against the old
    implementation that pid IS this process's.

    ``-I`` (isolated) is deliberate and does two things worth naming: it drops
    the script directory and ``PYTHONPATH`` from ``sys.path``, so the candidate
    cannot import the evaluator's own package through an inherited environment,
    and it ignores ``PYTHON*`` variables generally. It does NOT remove
    ``site-packages``; a candidate can still import whatever this interpreter
    has installed. That is a bound, not a sandbox, and it is stated rather
    than implied.

    WHAT THIS IS NOT. ``daedalus.spine.containment.spawn_contained`` is the
    capability-bounded mechanism in this repository, and it is not used here:
    it is win32-only (``platform_supported()`` is ``os.name == "nt"``) and
    never falls back, so it would make this slice refuse on every other
    platform, and with ``log=None`` the contained child has no stdio at all --
    there would be no way to read the measurement back. So the result declares
    ``"isolation": "subprocess"`` and claims process isolation only.

    SECOND HONEST LIMIT: ``subprocess.run(timeout=...)`` kills the direct child
    on expiry, not its descendants. A candidate that spawns a grandchild at
    import would leave it behind. The gate path already solves this with
    :mod:`daedalus.spine.cancel`; wiring it here is deferred work, named in
    ``docs/work-packets/G1-ISO-01_BEHAVIOR_PROBE_OUT_OF_PROCESS.md`` §8, not
    silently assumed away.
    """

    source = str(Path(candidate).resolve() / "src")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _BEHAVIOR_PROBE, source],
            capture_output=True,
            text=True,
            timeout=BEHAVIOR_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise IgnitionError(
            "the candidate behavior probe did not answer within "
            f"{BEHAVIOR_PROBE_TIMEOUT_S:g}s"
        ) from None
    except OSError as exc:
        raise IgnitionError(
            "the candidate behavior probe could not be started "
            f"({type(exc).__name__}: {exc})"
        ) from exc

    if completed.returncode != 0:
        # The child's traceback is the diagnosis -- a candidate that still
        # carries the retired symbol fails here with its own KeyError, which is
        # exactly what a reader of a red receipt needs to see.
        raise IgnitionError(
            f"the candidate behavior probe failed (rc={completed.returncode}): "
            + (completed.stderr or "").strip()[-2000:]
        )
    try:
        observed = json.loads(completed.stdout)
    except ValueError as exc:
        raise IgnitionError(
            f"the candidate behavior probe did not return JSON ({exc}): "
            f"{(completed.stdout or '')[:400]!r}"
        ) from exc
    if not isinstance(observed, dict):
        raise IgnitionError(
            "the candidate behavior probe returned "
            f"{type(observed).__name__}, not an object"
        )

    # NOT a pid, NOT a duration, NOT a path. `gate1` digests this mapping into
    # the `ignition-behavior` evidence item and the receipt compares two runs'
    # check reports, so a field that moved per run would make every Gate-1 run
    # report itself as a failed replay. `run_voltage_ignition` below digests it
    # into `behavior_sha256` for the same reason.
    observed["isolation"] = "subprocess"
    return observed


def _old_symbol_occurrences(root: Path) -> tuple[str, ...]:
    pattern = re.compile(r"(?<![A-Za-z0-9_])voltage(?![A-Za-z0-9_])")
    paths = [path for item in WORK_ITEMS for path in item.paths]
    hits = []
    for rel in sorted(set(paths)):
        text = (root / rel).read_text(encoding="utf-8")
        if pattern.search(text):
            hits.append(rel)
    return tuple(hits)


def _graph_delta(base: FourfoldSnapshot, candidate: FourfoldSnapshot) -> IgnitionGraphDelta:
    base_nodes = {node for plane in base.planes for node in plane.node_ids}
    candidate_nodes = {node for plane in candidate.planes for node in plane.node_ids}
    base_bindings = {canonical_sha(list(binding.semantic_key)) for binding in base.bindings}
    candidate_bindings = {canonical_sha(list(binding.semantic_key)) for binding in candidate.bindings}
    return IgnitionGraphDelta(
        added_nodes=tuple(sorted(candidate_nodes - base_nodes)),
        removed_nodes=tuple(sorted(base_nodes - candidate_nodes)),
        added_bindings=tuple(sorted(candidate_bindings - base_bindings)),
        removed_bindings=tuple(sorted(base_bindings - candidate_bindings)),
    )


def _item(
    *,
    evidence_id: str,
    evaluator: str,
    output_sha256: str,
    source_revision: str,
    collected_at: str,
    details: Mapping[str, object],
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        evaluator=evaluator,
        assurance="deterministic",
        verdict="passed",
        output_sha256=output_sha256,
        evidence_locator=f"artifact-locator:sha256:{output_sha256}",
        collected_at=collected_at,
        provenance=ContractProvenance(
            origin=f"daedalus.ignition.{evaluator}",
            source_revision=source_revision,
            created_at=collected_at,
            input_digests=(output_sha256,),
        ),
        details=dict(details),
    )


def run_voltage_ignition(
    source_root: str | Path,
    candidate_root: str | Path,
    *,
    base_revision: str,
    candidate_revision: str,
    collected_at: str,
) -> IgnitionResult:
    source = Path(source_root).resolve()
    before = _tree_digest(source)
    base = compile_reference_project(
        source,
        source_revision=base_revision,
        created_at=collected_at,
        trace_id="gate1-voltage-base",
    )
    candidate_path = materialize_voltage_rename(source, candidate_root)
    after = _tree_digest(source)
    if before != after:
        raise IgnitionError("source fixture changed while materializing the candidate")

    candidate = compile_reference_project(
        candidate_path,
        source_revision=candidate_revision,
        created_at=collected_at,
        trace_id="gate1-bias-voltage-candidate",
    )
    old_hits = _old_symbol_occurrences(candidate_path)
    if old_hits:
        raise IgnitionError("old trusted symbol remains in: " + ", ".join(old_hits))
    behavior = _behavior(candidate_path)
    if behavior["has_old_voltage_attribute"] or behavior["bias_voltage"] != 125.0:
        raise IgnitionError("candidate behavior does not satisfy the rename contract")
    behavior_sha = canonical_sha(dict(behavior))
    delta = _graph_delta(base.snapshot, candidate.snapshot)
    if not delta.added_nodes or not delta.removed_nodes:
        raise IgnitionError("rename produced no observable Fourfold node delta")

    extra = (
        _item(
            evidence_id="gate1-behavior",
            evaluator="ignition-behavior",
            output_sha256=behavior_sha,
            source_revision=candidate_revision,
            collected_at=collected_at,
            details=behavior,
        ),
        _item(
            evidence_id="gate1-graph-delta",
            evaluator="ignition-graph-delta",
            output_sha256=delta.digest,
            source_revision=candidate_revision,
            collected_at=collected_at,
            details=delta.to_dict(),
        ),
    )
    packet = assemble_fourfold_evidence_packet(
        snapshot=candidate.snapshot,
        candidate_artifact_sha256=candidate.source_bundle_sha256,
        candidate_artifact_locator=f"artifact-locator:sha256:{candidate.source_bundle_sha256}",
        packet_id="gate1-voltage-evidence",
        mission_id="gate1-voltage-rename",
        attempt_id="gate1-voltage-candidate",
        attempt_contract_sha256=canonical_sha({"attempt": "gate1-voltage"}),
        policy_decision_sha256=canonical_sha({"policy": "gate1-no-promotion"}),
        collected_at=collected_at,
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="gate1-voltage-rename",
        extra_items=extra,
    )
    return IgnitionResult(
        base_source_bundle_sha256=base.source_bundle_sha256,
        candidate_source_bundle_sha256=candidate.source_bundle_sha256,
        base_snapshot=base.snapshot,
        candidate_snapshot=candidate.snapshot,
        graph_delta=delta,
        evidence_packet=packet,
        behavior_sha256=behavior_sha,
        primary_tree_before_sha256=before,
        primary_tree_after_sha256=after,
    )


# --------------------------------------------------------------------------- #
# public names for the sibling Gate-1 slice                                    #
# --------------------------------------------------------------------------- #
#: :mod:`daedalus.ignition.gate1` reuses these three measurements verbatim
#: rather than re-deriving them. They were written private because this module
#: was the only caller; a second caller in the same package is a reason to name
#: them, not a reason to copy them -- a second tree digest or a second graph
#: delta would be exactly the drift the Fourfold delta exists to detect.
tree_digest = _tree_digest
candidate_behavior = _behavior
fourfold_graph_delta = _graph_delta

__all__ = [
    "BEHAVIOR_PROBE_TIMEOUT_S",
    "IgnitionError",
    "IgnitionGraphDelta",
    "IgnitionResult",
    "IgnitionWorkItem",
    "WORK_ITEMS",
    "candidate_behavior",
    "fourfold_graph_delta",
    "materialize_voltage_rename",
    "run_voltage_ignition",
    "tree_digest",
]
