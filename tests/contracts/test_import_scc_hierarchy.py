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
CURRENT_CROSS_DOMAIN_COMPONENT = REMAINING_CROSS_DOMAIN_COMPONENT - {
    "daedalus.conversation",
}
CURRENT_COMPONENTS_SHA256 = (
    "36d80ea6d701892c1cbb08057c2715477fbfcad972aa36b9f331d3065f3434a1"
)
# Moving census, not an architecture invariant: any packet that legitimately
# splits or adds a leaf module changes these two totals without touching the
# cycle structure. Re-measure and update them in the packet that moves them;
# the SCC claims below (count, maximum size, component digest, membership) are
# the assertions that must not weaken.
CENSUS_MODULES = 434
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
CENSUS_EDGES = 1637


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
    assert max(map(len, components)) == 18
    component_bytes = json.dumps(
        components,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(component_bytes).hexdigest() == CURRENT_COMPONENTS_SHA256
    assert REMAINING_CROSS_DOMAIN_COMPONENT not in component_sets
    assert CURRENT_CROSS_DOMAIN_COMPONENT in component_sets
    assert "daedalus.conversation" not in frozenset().union(*component_sets)
    assert "daedalus.health" not in graph["daedalus.conversation"]
    assert "daedalus.kernel.contracts.observations" in graph[
        "daedalus.conversation"
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
