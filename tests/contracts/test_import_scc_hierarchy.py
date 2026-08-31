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

    assert len(graph) == 420
    assert sum(len(targets) for targets in graph.values()) == 1575
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
