from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

from daedalus.structcore.cycles import nontrivial_components


ROOT = Path(__file__).resolve().parents[2]
KERNEL_LEASE = "daedalus.kernel.offload_lease"
SPINE_PICKER = "daedalus.spine.picker"
RUNTIME_EGRESS = "daedalus.runtimes.admission.offload_egress"
OLD_CROSS_DOMAIN_COMPONENT = frozenset(
    {
        "daedalus.build",
        "daedalus.build_exec",
        "daedalus.conversation",
        "daedalus.core",
        "daedalus.doctor",
        "daedalus.file_bridge",
        "daedalus.health",
        "daedalus.ikarus_supervisor",
        "daedalus.kairos.gated_writes",
        "daedalus.kairos.scheduler",
        "daedalus.kernel.attempt_execution",
        KERNEL_LEASE,
        "daedalus.kernel.promotion",
        "daedalus.offload",
        "daedalus.progress",
        "daedalus.progress_sources",
        RUNTIME_EGRESS,
        "daedalus.spine.attempt",
        "daedalus.spine.bootstrap",
        SPINE_PICKER,
        "daedalus.status",
    }
)
REMAINING_CROSS_DOMAIN_COMPONENT = OLD_CROSS_DOMAIN_COMPONENT - {
    KERNEL_LEASE,
    RUNTIME_EGRESS,
}
PRE_OFFLOAD_PORT_CROSS_DOMAIN_COMPONENT = REMAINING_CROSS_DOMAIN_COMPONENT - {
    "daedalus.conversation",
}
# G1-SCC-CUT1 cut ``daedalus.kernel.attempt_execution -> daedalus.offload``,
# the repository's single recorded boundary violation: ``offload_runner`` takes
# the workload as an injected port instead of importing it. The whole KERNEL
# and SPINE layer leaves this component as a result -- five modules, and the
# only five that are not flat/kairos modules. What remains is a genuine
# workload-level cycle among the flat root modules and the Kairos write wave.
#
# ``daedalus.offload`` STAYS in the component, and that is not a failure of the
# cut. It was previously held in by the kernel importing it; it is now held in
# by ``daedalus.kairos.gated_writes`` importing it directly, because the write
# wave really does depend on the workload and the workload reaches back through
# ``build_exec -> kairos.scheduler``. The kernel's debt was HIDING that cycle,
# not preventing it. Making it visible is the honest outcome; dissolving it is
# a different packet, and one that has to touch the Git-blob-pinned retained
# source the wave executes.
CURRENT_CROSS_DOMAIN_COMPONENT = PRE_OFFLOAD_PORT_CROSS_DOMAIN_COMPONENT - {
    "daedalus.kernel.attempt_execution",
    "daedalus.kernel.promotion",
    "daedalus.spine.attempt",
    "daedalus.spine.bootstrap",
    SPINE_PICKER,
}
# G1-FLAT-04 moved ``ikarus_supervisor`` into ``daedalus.orchestration``.
# It did NOT leave the cycle and this line does not claim it did: the member
# is RENAMED, one in for one out, so the component's size is unchanged at 13.
# Relocating a module cannot dissolve a cycle it is in -- only cutting an edge
# can, which is what G1-SCC-CUT1 did and what the note above describes.
CURRENT_CROSS_DOMAIN_COMPONENT = (
    CURRENT_CROSS_DOMAIN_COMPONENT - {"daedalus.ikarus_supervisor"}
) | {"daedalus.orchestration.ikarus_supervisor"}
CURRENT_COMPONENTS_SHA256 = (
    # Moved in G1-PKG-01: the 14-module component IS the provider family, so
    # renaming its members renames them inside the component. Count and
    # maximum are unchanged at 12 and 14, and the membership is asserted
    # below rather than left to the digest.
    # Moved again in G1-PKG-02: the 7-module gates component IS the
    # repository_write_* family, so renaming its members renames them inside
    # the component. Count 12 and maximum 14 are unchanged.
    "119512b93c2617c2d375cbbd4b5b0f75ad1ec8912d9b7895b3a755258e63aac2"
)
# Moving census, not an architecture invariant: any packet that legitimately
# splits or adds a leaf module changes these two totals without touching the
# cycle structure. Re-measure and update them in the packet that moves them;
# the SCC claims below (count, maximum size, component digest, membership) are
# the assertions that must not weaken.
# EVERY NUMBER BELOW IS A LOWER BOUND, and the gap is measured, not feared.
# `daedalus/kairos/gated_writes.py` executes a 65,009-byte git-blob-pinned
# source file with `exec(compile(_retained_source_bytes, ...))`. No AST walk
# sees the imports inside it -- including this one, which is why the graph
# this file pins is smaller than the graph the interpreter builds.
#
# Measured 2026-09-02 by parsing the retained blob and adding its edges:
#
#     AST census (what this file asserts)   largest SCC = 18
#     with the exec'd source's imports      largest SCC = 21
#
# Seven edges are reachable only through the blob (config, core,
# kairos.scheduler, kairos.worktree, orchestration.execution, spine.attempt,
# spine.killswitch), and three modules sit in the real cycle solely because of
# them: eval.correctness, orchestration.execution, orchestration.execution
# .attempts. A cut plan derived from the numbers here alone will therefore
# over-promise -- the same cut that reads 18 -> 7 on this graph reads 18 -> 16
# on the corrected one.
#
# Whether the census SHOULD follow an exec is an owner decision about what
# this instrument measures, not a defect to patch quietly. Recorded here
# because this file is where the claim lives.
# 434 -> 437 in G1-FLAT-01, the first flat-module relocation of the hierarchy
# programme. Three implementations moved into ``daedalus.orchestration`` and
# three compatibility facades kept the flat dotted paths, so the count rises by
# the three NEW owner modules only -- the flat paths were already counted and
# still exist as files.
# 437 -> 430 in G1-FLAT-02, the first packet in this series to DELETE modules:
# the three G1-FLAT-01 facades (gui_catalogue, ikarus_runtime_events,
# langgraph_adapter) and the four zero-caller Ikarus->Kairos rename shims
# (decompose, drafts, ikarus, mission_control) are gone. Their owners were
# already counted and are unchanged.
# 430 -> 432 in G1-FLAT-04, and both are package roots this packet created:
# ``daedalus.foundation`` for the leaf utilities and ``daedalus.interfaces.cli``
# for the console entrypoints. No implementation module was added or deleted;
# the eleven relocations are renames.
# 432 -> 431 in G1-FLAT-06, the only DELETION in this series since
# G1-FLAT-02: ``daedalus/token_policy.py`` is gone, its registry row with it.
# The console entrypoint was relocated and renamed, not added, so it costs
# nothing here. dctx was moved into daedalus.twin and moved back inside this
# same packet -- see the message -- so it is where it started.
# 431 -> 432 in G1-PKG-01, and the +1 is the ``daedalus.runtimes.provider``
# package root. Twenty-five modules moved INTO it and were renamed at the
# same time -- the shared ``provider_`` prefix is dropped because the package
# now carries it -- but a rename adds no node. Edges are unchanged at 1642:
# every one of the 25 kept exactly the targets it had, and no caller gained
# or lost a package edge, because nothing imported them as
# ``from daedalus.runtimes import provider_x``.
# 432 -> 433 in G1-PKG-02, the ``daedalus.gates.repository`` package root.
# Sixteen modules moved into it and lost the ``repository_`` prefix the
# package now carries; seven of the sixteen are one strongly connected
# component, which is why the family was a package spelled with underscores.
# Edges unchanged at 1642, for the same reason as G1-PKG-01: every module
# kept its targets and no caller reached them through the parent package.
CENSUS_MODULES = 433
# 1603 -> 1618 in G1-HIER-10, which added no module and deleted none: eighteen
# kernel modules stopped importing the ``daedalus.schemas`` facade and now name
# the owning ``daedalus.kernel.contracts`` module for each symbol, so a file
# that needs contracts from n owners spends n edges where it used to spend one.
# The +15 is exactly the sum of (owners named - 1) over those eighteen files.
#
# 1618 -> 1618 in G1-HIER-11, which did the same kind of repoint for four
# ``daedalus.twin`` modules and moved neither total. That is not a sign the
# re-measurement was skipped: all nine symbols those files took from the facade
# have one owner, ``daedalus.kernel.contracts.base``, so each file trades its
# single ``daedalus.schemas`` edge for a single new one. A repoint changes this
# number only when a file ends up naming more owners than it named before, so
# "unchanged" is a legitimate measured outcome here and the twin edges did
# move -- ``daedalus.twin.contracts`` now points at the kernel contract owner
# rather than the facade.
#
# 1618 -> 1624 in G1-HIER-12, which also added no module and deleted none. The
# +6 decomposes exactly, and the two repointed files behave differently for the
# reason G1-HIER-11's note gives -- a repoint moves this number only when a file
# ends up naming more owners than it named before:
#
#   daedalus/spine/receipts.py  -1 (daedalus.schemas)  +7 owners  = +6
#       .contracts.{attempts,base,evidence,missions,policy,resources,runtime}
#   daedalus/spine/picker.py    -1 (daedalus.schemas)  +1 owner   =  0
#       .contracts.resources, its single owner for ResourceBudget. The file
#       already named .contracts.evaluation, and this graph holds a set of
#       targets per module, so nothing is double-counted.
#
# This graph counts an edge wherever the import appears, module scope or
# function scope, because it walks the whole AST. Hoisting picker's
# ResourceBudget import out of ``_default_attempt`` to module level therefore
# moves no edge by itself: the edge already existed, it merely fired later in
# time. That is also why this census was NOT an instrument that could have
# caught the deferred facade import G1-HIER-12 removed -- it saw the edge all
# along and had no opinion about when it ran.
#
# 1624 -> 1630 in G1-HIER-14, the same repoint for all 33 ``daedalus/runtimes``
# modules that imported the facade. It added no module and deleted none, and
# every one of the 33 had exactly ONE module-scope ``from daedalus.schemas``
# statement, so each spends its single facade edge and buys one edge per owner
# it now names. The +6 is the sum of (owners named - 1) and decomposes as five
# files; the other 28 name exactly one owner and are worth 0 each:
#
#   profiles.py                       -1 facade  +3 owners  = +2
#       .contracts.{base,resources,runtime}
#   live_probe_drivers.py             -1 facade  +2 owners  = +1
#   trust.py                          -1 facade  +2 owners  = +1
#       both .contracts.{base,runtime}
#   ..._retention_admission.py        -1 facade  +2 owners  = +1
#   ..._retention_effect_terminal_evidence.py    +2 owners  = +1
#       both .contracts.{base,policy}
#
# Twenty-eight of the 33 take only ``daedalus.kernel.contracts.base``, which is
# why a 33-file change moves this total by 6 rather than by 33: ``base`` owns
# the shared validators (``_sha256``, ``_identifier``, ``_revision``, ...) that
# most of these modules were reaching through the facade to get.
#
# The five decomposed files were checked against the RESOLVED graph, not just
# their import text, before the edit: none of them already named the owner it
# was about to gain, so no line of the +6 is double-counted.
#
# 1630 -> 1636 and 433 -> 434 MODULES in G1-PORT-01, the first packet in this
# series to ADD a module rather than repoint imports: daedalus/journal_io.py
# came across from wip/g1-freeze-2026-08-31 with the atomic-append fix. The +6
# decomposes exactly and needs no owner-counting argument:
#
#   daedalus.journal_io -> daedalus.atomic                            +1
#   memory, metrics, progress, kairos.archive, council.canary
#       -> daedalus.journal_io                          5 importers   +5
#
# The SCC structure and CURRENT_COMPONENTS_SHA256 are UNCHANGED, which is the
# claim worth making about a new node: journal_io sits on foundation and is
# imported by five leaves, so it joins no cycle and moves no component.
#
# 1636 -> 1637 in G1-SEC-02: daedalus/ikarus_os.py imports cmd_shim_refusal
# from daedalus.providers.codex_cli rather than re-implementing it, so the
# Windows .cmd-relay refusal has one owner across all four CLI sinks. One new
# edge, one file, no module added. Structure and digest unchanged.
#
# 1637 -> 1638 in G1-SCC-CUT1, which added no module and deleted none. Unlike
# every repoint above, this one MOVES THE STRUCTURE: the maximum non-trivial
# SCC drops 18 -> 14 and the cross-domain component drops 18 -> 13. The +1 is a
# net of three, hand-computed from the edit list BEFORE re-measuring, and the
# measurement agreed exactly:
#
#   kernel.attempt_execution  -> offload   -1  the recorded boundary violation
#   orchestration.execution.attempts -> offload  +1  offload_port(), for the
#       picker and bootstrap doors, threaded through daedalus.cli
#   kairos.gated_writes       -> offload   +1  the write wave, which composes
#       the port itself because the retained Git-blob-pinned source it exec()s
#       calls offload_runner through a frozen _recording_runner
#
# ``daedalus.cli`` is NOT in that list: it already imported daedalus.offload
# for the ``offload`` subcommand, so threading the port through it spends no
# edge. Both new sites import ``OffloadCapability`` with
# ``from daedalus.offload import ...`` rather than ``from daedalus import
# offload`` on purpose -- the latter resolves to TWO targets here (the package
# root and the module) and would have made this +1 a +3.
#
# The two spine doors spend nothing either: ``OffloadPort`` joins an EXISTING
# ``from ..kernel.attempt_execution import (...)`` in both picker and
# bootstrap, and this graph holds a set of targets per module.
#
# 1638 -> 1641 in G1-FLAT-01. Hand-computed BEFORE re-measuring, from the edit
# list, and it matched: the three flat modules spent 8 out-edges between them
# (gui_catalogue 6, langgraph_adapter 2, ikarus_runtime_events 0 -- MEASURED at
# e80407e0). Those 8 move WITH the implementation to the owner modules and cost
# nothing net, because this graph holds a set of targets per module and the
# relative-import depth fix (``.context_plan`` -> ``..context_plan``) resolves
# to the identical target. The whole +3 is the three facade -> owner edges, one
# each. It is +3 and not +6 for the same reason G1-SCC-CUT1's note gives: each
# facade imports its owner with ``from .orchestration.<name> import (...)``, a
# single ImportFrom whose base and every alias collapse onto one target.
#
# The facades are deliberately plain module-scope re-exports rather than a
# ``sys.modules`` swap or a ``ModuleType.__getattr__`` forwarder. An opaque
# facade would cost this census its view of all three edges -- the +3 would
# read as +0 and the instrument would go quiet, which is the G1-HIER-13 defect.
#
# 1641 -> 1635 in G1-FLAT-02. Hand-computed BEFORE re-measuring, from the
# edit list: the seven deleted facades spent one owner edge each (-7). Two
# in-package callers were repointed. ``daedalus.runbook`` swaps
# ``daedalus.langgraph_adapter`` for ``daedalus.orchestration.langgraph_adapter``
# (-1, +1). ``daedalus.interfaces.http.read`` swaps ``from ... import
# gui_catalogue`` for ``from ...orchestration import gui_catalogue``, which
# drops ``daedalus.gui_catalogue`` (-1), keeps the ``daedalus`` root edge its
# module-scope imports already spend, and gains BOTH ``daedalus.orchestration``
# and ``daedalus.orchestration.gui_catalogue`` (+2), because ``from <package>
# import <module>`` resolves to two targets here. Net -6. Structure and digest
# unchanged: none of the seven was in a cycle, and removing a leaf's only
# out-edge opens no path.
#
# 1635 -> 1642 in G1-FLAT-03, which moved nineteen flat modules into
# ``daedalus.orchestration`` and deleted none. MODULES is unchanged at 430:
# a relocation renames a node, it does not add one. The +7 is a net of
# thirteen, and every one of them is the same construct -- ``from <package>
# import <module>``, which resolves to TWO targets in this graph, the package
# and the module:
#
#   +10  callers that named the package gained ``-> daedalus.orchestration``:
#        cli, desktop_runtime, file_bridge, health, ikarus_os, web_api,
#        interfaces.http.effects, interfaces.http.sse, kairos.scheduler, and
#        two moved modules importing a sibling that moved with them
#    -3  cli, file_bridge and kairos.scheduler lost ``-> daedalus``: the root
#        package was only ever named to reach a module that left
#
# Verified by diffing the resolved edge sets of HEAD and the working tree with
# the rename table applied to HEAD, which left exactly those thirteen.
# Structure and digest are UNCHANGED -- 12 components, max 14, same
# CURRENT_COMPONENTS_SHA256 -- because none of the nineteen was in a cycle.
#
# 1642 -> 1644 in G1-FLAT-04. The +2 is a net of four, and every one is the
# same ``from <package> import <module>`` two-target construct as last time:
#
#   +3  interfaces.http.read, web_api and tools.inventory gained
#       ``-> daedalus.foundation``
#    -1  tools.inventory lost ``-> daedalus``: it named the root package only
#        to reach ``skills``, which left
#
# The eleven new package edges the moved modules THEMSELVES spend are already
# counted -- each was importing the same owners before, from one level up.
# The digest below DID move this time, and only because
# ``ikarus_supervisor`` is a member of the 13-module cross-domain component:
# renaming a member renames it inside the component too. Count and maximum
# are unchanged at 12 and 14, and the membership assertion is restated
# explicitly above rather than left to the digest.
#
# 1644 -> 1643 in G1-FLAT-05, which moved eleven REGISTERED effect doors.
# MODULES is unchanged at 432; no package root was needed, both destinations
# already existed. The -1 is a net of five, and once again every one of them
# is the ``from <package> import <module>`` two-target construct:
#
#   +2  hooks.events and interfaces.cli.shift_ticker gained
#       ``-> daedalus.interfaces.cli``, having followed ``shift`` there
#   -3  the same two, plus orchestration.conversation_requests, lost
#       ``-> daedalus``: each named the root package only to reach a module
#       that left, and none of them names it for anything else
#
# Structure and digest are unchanged: loop and ikarus_os are large and
# heavily imported but sit in no cycle, so renaming them moves no component.
#
# 1643 -> 1642 in G1-FLAT-06. The -1 is a net of five and is entirely the
# token_policy deletion: the facade's own edge to its owner disappears with
# the file (-1), and its two production callers -- kairos.orchestrate and
# providers.claude_cli -- swap one target for another (-2, +2). The
# entrypoint relocation spends nothing: every caller named it by a path that
# resolves to exactly one target before and after.
#
# Those two callers are the reason this packet added
# tests/contracts/test_no_dangling_daedalus_imports.py. They imported the
# facade as ``from ..token_policy import ...``, which the regex audit before
# the delete could not match, and which THIS census cannot report either:
# _tracked_module_graph drops targets it cannot resolve, so a dangling import
# produces no edge and no movement. The new contract resolves instead of
# matching.
CENSUS_EDGES = 1642


def _module_name(path: str) -> str:
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _tracked_module_graph() -> dict[str, set[str]]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "daedalus"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=30,
    )
    paths = tuple(
        sorted(
            raw.decode("utf-8")
            for raw in completed.stdout.split(b"\0")
            if raw.endswith(b".py")
        )
    )
    modules = {path: _module_name(path) for path in paths}
    known_modules = frozenset(modules.values())
    ordered_modules = tuple(sorted(known_modules, key=len, reverse=True))
    graph = {module: set() for module in known_modules}

    for path, source_module in modules.items():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
        package = (
            source_module
            if path.endswith("/__init__.py")
            else source_module.rpartition(".")[0]
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative = "." * node.level + (node.module or "")
                    base = importlib.util.resolve_name(relative, package)
                else:
                    base = node.module or ""
                candidates = [base]
                candidates.extend(
                    f"{base}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
            else:
                continue
            for candidate in candidates:
                target = next(
                    (
                        module
                        for module in ordered_modules
                        if candidate == module or candidate.startswith(module + ".")
                    ),
                    None,
                )
                if target is not None:
                    graph[source_module].add(target)
    return graph


def test_intent_ledger_port_breaks_the_selected_cross_domain_scc() -> None:
    graph = _tracked_module_graph()
    components = nontrivial_components(graph)
    component_sets = tuple(frozenset(component) for component in components)

    assert OLD_CROSS_DOMAIN_COMPONENT not in component_sets

    cyclic_modules = frozenset().union(*component_sets)
    assert KERNEL_LEASE not in cyclic_modules
    assert RUNTIME_EGRESS not in cyclic_modules


def test_observation_contract_breaks_the_next_cross_domain_scc() -> None:
    graph = _tracked_module_graph()
    components = nontrivial_components(graph)
    component_sets = tuple(frozenset(component) for component in components)

    assert len(graph) == CENSUS_MODULES
    assert sum(len(targets) for targets in graph.values()) == CENSUS_EDGES
    assert len(components) == 12
    assert max(map(len, components)) == 14
    component_bytes = json.dumps(
        components,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(component_bytes).hexdigest() == CURRENT_COMPONENTS_SHA256
    assert REMAINING_CROSS_DOMAIN_COMPONENT not in component_sets
    assert PRE_OFFLOAD_PORT_CROSS_DOMAIN_COMPONENT not in component_sets
    assert CURRENT_CROSS_DOMAIN_COMPONENT in component_sets
    # The claim of G1-SCC-CUT1, stated as membership rather than as a count: a
    # count of 13 would also be satisfied by dropping five unrelated modules.
    # The kernel and the spine are the layers that left, and the kernel no
    # longer names the workload at all.
    assert "daedalus.offload" not in graph["daedalus.kernel.attempt_execution"]
    cyclic = frozenset().union(*component_sets)
    for departed in (
        "daedalus.kernel.attempt_execution",
        "daedalus.kernel.promotion",
        "daedalus.spine.attempt",
        "daedalus.spine.bootstrap",
        SPINE_PICKER,
    ):
        assert departed not in cyclic
    # G1-FLAT-03 moved the module to ``daedalus.orchestration.conversation``.
    # The three live assertions follow it; the historical component sets above
    # keep the flat name, because that is what was in the cycle when they were
    # measured. Renaming a node there would rewrite a past measurement.
    assert "daedalus.orchestration.conversation" not in frozenset().union(
        *component_sets
    )
    assert "daedalus.health" not in graph["daedalus.orchestration.conversation"]
    assert "daedalus.kernel.contracts.observations" in graph[
        "daedalus.orchestration.conversation"
    ]


def test_kernel_lease_has_no_spine_picker_import_or_dynamic_escape() -> None:
    graph = _tracked_module_graph()
    source = (ROOT / "daedalus" / "kernel" / "offload_lease.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    assert SPINE_PICKER not in graph[KERNEL_LEASE]
    assert "resolve_spine_db_path" not in source
    assert "importlib" not in {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "__import__" not in {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
