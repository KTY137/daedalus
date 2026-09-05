"""Effect-free KiCad/PCB inspection.

**Isolated EXPERIMENT, packet `G1-HW-01`.** The plan revision in force is 12,
which has no PCB product strand;
`docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md` is a
proposal awaiting the repository owner. This package is therefore frozen,
bounded and isolated in the sense of master plan section 1: it reads, it
reports, and it is wired into nothing.

Concretely, and testably:

* no process is started -- there is no ``subprocess`` import in this package;
* nothing is written -- there is no ``open(..., "w")``, no ``Path.write_*``;
* no network is touched;
* no product surface is registered: no effect-registry row, no HTTP route, no
  desktop projection, no ``daedalus-chip`` subcommand;
* models and embeddings are absent by construction; a parser proposes nothing.

It also produces no evidence about a design. Inspecting a board cleanly says
the bytes parsed, not that the board is correct. ERC and DRC verdicts come only
from ``kicad-cli`` under an admitted effect path, which :mod:`.plan` describes
and deliberately cannot perform.
"""

from .inspection import (
    BOARD_VERSIONS,
    SCHEMATIC_VERSIONS,
    build_board_report,
    build_schematic_report,
    canonical_json,
    inspect_artifact,
    payload_digest,
)
from .plan import GOVERNANCE_PREREQUISITES, PLANNED_STEPS, PlannedStep, build_plan
from .sexpr import (
    ABSOLUTE_MAX_BYTES,
    Atom,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_NODES,
    PcbRefusal,
    REFUSAL_REASONS,
    ReadArtifact,
    parse,
    parse_bytes,
    read_artifact,
)
from .sources import (
    ArtifactSpec,
    ProjectSpec,
    classify_artifact,
    discover_artifacts,
    discover_projects,
    is_authoritative,
)
from .toolchains import (
    TOOLS,
    PcbToolSpec,
    all_tool_status,
    find_tool_path,
    get_tool,
    interpret_version_probe,
    tool_status,
)

__all__ = [
    "ABSOLUTE_MAX_BYTES",
    "BOARD_VERSIONS",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "GOVERNANCE_PREREQUISITES",
    "PLANNED_STEPS",
    "REFUSAL_REASONS",
    "SCHEMATIC_VERSIONS",
    "TOOLS",
    "ArtifactSpec",
    "Atom",
    "PcbRefusal",
    "PcbToolSpec",
    "PlannedStep",
    "ProjectSpec",
    "ReadArtifact",
    "all_tool_status",
    "build_board_report",
    "build_plan",
    "build_schematic_report",
    "canonical_json",
    "classify_artifact",
    "discover_artifacts",
    "discover_projects",
    "find_tool_path",
    "get_tool",
    "inspect_artifact",
    "interpret_version_probe",
    "is_authoritative",
    "parse",
    "parse_bytes",
    "payload_digest",
    "read_artifact",
    "tool_status",
]
