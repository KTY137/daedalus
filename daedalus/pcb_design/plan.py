"""Effect-free description of the *later* effectful PCB packet.

Nothing in this module runs. It answers one question honestly: if Daedalus were
allowed to produce PCB evidence, what exactly would it invoke, what would it
need, and what is missing here and now?

The argv shapes are **data**. They are never handed to a process starter in
this package, and the package registers no effect entrypoint, acquires no
EffectLease, and declares no write root -- which is why every plan is
inadmissible by construction, not merely by accident of a missing binary. A
future packet that wants to run these steps must add the lease, the write root,
the sandbox policy and the evidence contract, and must do so under an adopted
amendment. Until then the honest answer is ``admissible: false``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .inspection import canonical_json, payload_digest
from .toolchains import tool_status

__all__ = [
    "GOVERNANCE_PREREQUISITES",
    "PLANNED_STEPS",
    "PlannedStep",
    "build_plan",
]


@dataclass(frozen=True)
class PlannedStep:
    id: str
    label: str
    tool_id: str
    argv_shape: tuple[str, ...]
    produces: str
    evidence_kind: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "tool_id": self.tool_id,
            "argv_shape": list(self.argv_shape),
            "produces": self.produces,
            "evidence_kind": self.evidence_kind,
            "notes": self.notes,
        }


# Placeholders in angle brackets are never substituted here. Substituting them
# would produce a runnable command line, and this package has no admitted path
# on which to run one.
PLANNED_STEPS: tuple[PlannedStep, ...] = (
    PlannedStep(
        id="erc",
        label="Electrical rule check",
        tool_id="kicad-cli",
        argv_shape=(
            "kicad-cli", "sch", "erc",
            "--format", "json",
            "--severity-all",
            "--exit-code-violations",
            "-o", "<workspace>/erc.json",
            "<schematic.kicad_sch>",
        ),
        produces="<workspace>/erc.json",
        evidence_kind="deterministic_evaluator",
        notes=(
            "Exit 5 means violations were found and is not a crash; exit 1/2/3/4 "
            "are argument, unknown, invalid-input and output-conflict errors and "
            "must stay distinct. Warnings are findings, not passes."
        ),
    ),
    PlannedStep(
        id="drc",
        label="Design rule check with schematic parity",
        tool_id="kicad-cli",
        argv_shape=(
            "kicad-cli", "pcb", "drc",
            "--format", "json",
            "--schematic-parity",
            "--severity-all",
            "--exit-code-violations",
            "-o", "<workspace>/drc.json",
            "<board.kicad_pcb>",
        ),
        produces="<workspace>/drc.json",
        evidence_kind="deterministic_evaluator",
        notes=(
            "A pass requires zero violations, zero unconnected_items and zero "
            "schematic_parity entries at every retained severity."
        ),
    ),
    PlannedStep(
        id="netlist",
        label="Netlist export (independent of the inspector)",
        tool_id="kicad-cli",
        argv_shape=(
            "kicad-cli", "sch", "export", "netlist",
            "--format", "kicadsexpr",
            "-o", "<workspace>/netlist.net",
            "<schematic.kicad_sch>",
        ),
        produces="<workspace>/netlist.net",
        evidence_kind="independent_comparison",
        notes=(
            "This is what makes the inspector falsifiable: the parser's authored "
            "geometry can be compared against KiCad's own connectivity result."
        ),
    ),
    PlannedStep(
        id="bom",
        label="Bill of materials export",
        tool_id="kicad-cli",
        argv_shape=(
            "kicad-cli", "sch", "export", "bom",
            "-o", "<workspace>/bom.csv",
            "<schematic.kicad_sch>",
        ),
        produces="<workspace>/bom.csv",
        evidence_kind="independent_comparison",
        notes="Compared against the inspector's symbol table, never trusted over it.",
    ),
    PlannedStep(
        id="gerbers",
        label="Gerber export",
        tool_id="kicad-cli",
        argv_shape=(
            "kicad-cli", "pcb", "export", "gerbers",
            "-o", "<workspace>/fab/",
            "<board.kicad_pcb>",
        ),
        produces="<workspace>/fab/*.gbr",
        evidence_kind="artifact",
        notes=(
            "Fabrication output is an artifact, not a verdict. Export success "
            "says nothing about manufacturability."
        ),
    ),
    PlannedStep(
        id="drill",
        label="Drill file export",
        tool_id="kicad-cli",
        argv_shape=(
            "kicad-cli", "pcb", "export", "drill",
            "-o", "<workspace>/fab/",
            "<board.kicad_pcb>",
        ),
        produces="<workspace>/fab/*.drl",
        evidence_kind="artifact",
        notes="Paired with the Gerber step; both belong to one fabrication set.",
    ),
    PlannedStep(
        id="gerber_render",
        label="Independent Gerber render",
        tool_id="gerbv",
        argv_shape=(
            "gerbv", "--export=png", "--dpi=600",
            "-o", "<workspace>/fab/render.png",
            "<workspace>/fab/<layer>.gbr",
        ),
        produces="<workspace>/fab/render.png",
        evidence_kind="observation",
        notes=(
            "A render is an observation, never acceptance. Visual similarity is "
            "explicitly insufficient UI/artefact acceptance (plan section 13)."
        ),
    ),
    PlannedStep(
        id="spice",
        label="SPICE transient/DC simulation",
        tool_id="ngspice",
        argv_shape=(
            "ngspice", "-b", "-o", "<workspace>/spice.log", "<workspace>/netlist.cir",
        ),
        produces="<workspace>/spice.log",
        evidence_kind="deterministic_evaluator",
        notes=(
            "Requires a SPICE netlist and models the schematic does not have to "
            "carry; unavailable models are reported, never substituted."
        ),
    ),
)


# Prerequisites that are not tools. These are the ones that actually block, and
# they stay unmet for as long as this package is an isolated experiment.
GOVERNANCE_PREREQUISITES: tuple[dict[str, object], ...] = (
    {
        "id": "amendment_013_adopted",
        "met": False,
        "detail": (
            "docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md is "
            "a proposal awaiting the owner; the adopted plan is Revision 12 and "
            "does not include a PCB product strand"
        ),
    },
    {
        "id": "effect_lease",
        "met": False,
        "detail": (
            "daedalus.pcb_design declares no EffectLease port and no effect "
            "registry row; it cannot start a process even if one were installed"
        ),
    },
    {
        "id": "bounded_write_root",
        "met": False,
        "detail": "no workspace write root is declared; every step above writes output",
    },
    {
        "id": "owner_approval",
        "met": False,
        "detail": (
            "no one-use OwnerApproval binds a candidate, EvidencePacket and target; "
            "promotion and publication remain forbidden regardless"
        ),
    },
)


def build_plan(*, step_ids: tuple[str, ...] = ()) -> dict[str, Any]:
    """Describe the effectful packet without performing any part of it."""

    selected = (
        PLANNED_STEPS
        if not step_ids
        else tuple(step for step in PLANNED_STEPS if step.id in set(step_ids))
    )
    unknown = sorted(set(step_ids) - {step.id for step in PLANNED_STEPS})

    tool_ids = sorted({step.tool_id for step in selected})
    prerequisites = [tool_status(tool_id) for tool_id in tool_ids]
    available = {row["id"] for row in prerequisites if row["available"]}
    missing = sorted(tool_id for tool_id in tool_ids if tool_id not in available)

    steps: list[dict[str, Any]] = []
    for step in selected:
        tool_absent = step.tool_id not in available
        blocked_by = [f"{step.tool_id}:absent"] if tool_absent else []
        blocked_by.extend(
            f"governance:{row['id']}" for row in GOVERNANCE_PREREQUISITES if not row["met"]
        )
        steps.append(
            {
                **step.to_dict(),
                # Governance blocks unconditionally; a missing binary is the
                # weaker, host-local reason and is named separately so it is
                # never mistaken for the real blocker.
                "status": "blocked_external" if tool_absent else "blocked_governance",
                "blocked_by": blocked_by,
                "executed": False,
            }
        )

    inadmissible: list[str] = [
        f"governance:{row['id']}" for row in GOVERNANCE_PREREQUISITES if not row["met"]
    ]
    inadmissible.extend(f"tool_absent:{tool_id}" for tool_id in missing)
    if unknown:
        inadmissible.extend(f"unknown_step:{name}" for name in unknown)

    body = {
        "schema": "daedalus.pcb_design/plan/1",
        "packet_id": "G1-HW-01",
        "classification": "EXPERIMENT",
        "active_gate": 1,
        "effects_performed": [],
        "steps": steps,
        "step_count": len(steps),
        "unknown_step_ids": unknown,
        "tool_prerequisites": prerequisites,
        "missing_tools": missing,
        "governance_prerequisites": [dict(row) for row in GOVERNANCE_PREREQUISITES],
        "unmet_governance_prerequisites": [
            str(row["id"]) for row in GOVERNANCE_PREREQUISITES if not row["met"]
        ],
        "admissible": False,
        "inadmissible_reasons": inadmissible,
        "note": (
            "admissible is false by construction: this package has no effect "
            "path. Installing every tool would not make it true."
        ),
    }
    # The digest covers only the host-independent shape of the plan. Tool rows,
    # missing_tools and per-step blocked_by are measurements of *this* host and
    # would make the digest unpinnable; they stay in the report, out of the pin.
    body["plan_shape_sha256"] = payload_digest(
        {
            "schema": body["schema"],
            "packet_id": body["packet_id"],
            "classification": body["classification"],
            "active_gate": body["active_gate"],
            "steps": [step.to_dict() for step in selected],
            "governance_prerequisites": body["governance_prerequisites"],
            "admissible": body["admissible"],
        }
    )
    return body
