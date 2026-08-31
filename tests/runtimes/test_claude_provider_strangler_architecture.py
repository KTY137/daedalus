from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import pickle
import subprocess
from pathlib import Path

import daedalus.claude_bridge as bridge
import daedalus.providers.claude_cli as legacy_provider
from daedalus.runtimes.contracts import claude as claude_contracts
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    Effect,
    Wiring,
    registry_sha256,
)
from tools import index_work_packets


ROOT = Path(__file__).resolve().parents[2]
PACKET_PATH = (
    "docs/work-packets/"
    "G1-RUNTIME-PROVIDER-01_CLAUDE_CONTRACT_STRANGLER.md"
)
REGISTRY_SHA256 = "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"


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
    graph = {module: set() for module in known_modules}
    ordered_modules = tuple(sorted(known_modules, key=len, reverse=True))

    for path, source_module in modules.items():
        source = (ROOT / path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path)
        package = (
            source_module
            if path.endswith("/__init__.py")
            else source_module.rpartition(".")[0]
        )
        for node in ast.walk(tree):
            candidates: list[str]
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


def _reachable(graph: dict[str, set[str]], source: str, target: str) -> bool:
    pending = [source]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for dependency in graph.get(current, set()):
            if dependency == target:
                return True
            pending.append(dependency)
    return False


def test_tracked_import_graph_breaks_the_claude_cross_domain_scc() -> None:
    graph = _tracked_module_graph()
    bridge_module = "daedalus.claude_bridge"
    provider_module = "daedalus.providers.claude_cli"

    assert provider_module in graph[bridge_module]
    assert bridge_module not in graph[provider_module]
    assert _reachable(graph, bridge_module, provider_module) is True
    assert _reachable(graph, provider_module, bridge_module) is False


def test_legacy_provider_reexports_the_exact_canonical_contract_objects() -> None:
    names = (
        "ClaudeInvocationBindingMismatch",
        "ClaudeProviderAuthorizationRequired",
        "ClaudeProviderScopeMismatch",
        "ClaudeProviderWorkspaceMismatch",
        "ClaudeWorkspaceGrant",
    )
    for name in names:
        assert getattr(legacy_provider, name) is getattr(claude_contracts, name)

    assert legacy_provider.ENTRYPOINT_ID == claude_contracts.CLAUDE_ENTRYPOINT_ID
    assert legacy_provider.RUNTIME_ID == claude_contracts.CLAUDE_RUNTIME_ID
    assert claude_contracts.ClaudeWorkspaceGrant.__module__ == (
        "daedalus.runtimes.contracts.claude"
    )


def test_current_and_historical_pickle_locators_resolve_one_contract() -> None:
    grant = claude_contracts.ClaudeWorkspaceGrant(
        attempt_id="attempt-1",
        source_revision="a" * 40,
        request_sha256="b" * 64,
        execution_sha256="c" * 64,
        worktree="C:/isolated/worktree",
    )
    current_payload = pickle.dumps(grant, protocol=0)
    historical_payload = current_payload.replace(
        b"cdaedalus.runtimes.contracts.claude\nClaudeWorkspaceGrant\n",
        b"cdaedalus.providers.claude_cli\nClaudeWorkspaceGrant\n",
    )
    assert historical_payload != current_payload

    historical = pickle.loads(historical_payload)
    assert type(historical) is claude_contracts.ClaudeWorkspaceGrant
    assert historical == grant

    restored = pickle.loads(current_payload)
    assert type(restored) is claude_contracts.ClaudeWorkspaceGrant
    assert restored == grant


def test_registered_effect_door_and_digest_are_exactly_unchanged() -> None:
    row = REGISTRY_BY_ID["provider.claude"]

    assert registry_sha256() == REGISTRY_SHA256
    assert row.target == "daedalus.providers.claude_cli:ClaudeCLIProvider.run"
    assert row.runtime_id == "claude_code_cli"
    assert row.wiring is Wiring.INVENTORY_ONLY
    assert tuple(effect.value for effect in row.effects) == (
        Effect.PROCESS_SPAWN.value,
        Effect.NETWORK_EGRESS.value,
        Effect.FILESYSTEM_WRITE.value,
        Effect.SPEND.value,
    )
    assert tuple((anchor.target, anchor.call) for anchor in row.anchors) == (
        (
            "daedalus.providers.claude_cli:ClaudeCLIProvider.run",
            "run_runtime_provider",
        ),
    )


def test_authenticated_executable_object_source_locators_do_not_move() -> None:
    invoke = bridge._invoke_claude_payload
    output_digests = legacy_provider._output_digests

    assert f"{invoke.__module__}:{invoke.__qualname__}" == (
        "daedalus.claude_bridge:_invoke_claude_payload"
    )
    assert f"{output_digests.__module__}:{output_digests.__qualname__}" == (
        "daedalus.providers.claude_cli:_output_digests"
    )
    assert Path(inspect.getsourcefile(invoke) or "").resolve() == (
        ROOT / "daedalus" / "claude_bridge.py"
    ).resolve()
    assert Path(inspect.getsourcefile(output_digests) or "").resolve() == (
        ROOT / "daedalus" / "providers" / "claude_cli.py"
    ).resolve()
    assert legacy_provider.ClaudeCLIProvider.__module__ == (
        "daedalus.providers.claude_cli"
    )
    assert legacy_provider.ClaudeCLIProvider.run.__module__ == (
        "daedalus.providers.claude_cli"
    )


def test_runtime_profile_keeps_the_legacy_adapter_locator() -> None:
    payload = json.loads(
        (ROOT / "configs/runtimes/gate0-runtime-profiles-v1.json").read_text(
            encoding="utf-8"
        )
    )
    claude = next(
        row for row in payload["profiles"] if row["runtime_id"] == "claude_code_cli"
    )

    assert claude["adapter_module"] == "daedalus.providers.claude_cli"


def test_provider_has_no_bridge_import_or_dynamic_locator() -> None:
    path = ROOT / "daedalus/providers/claude_cli.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bridge_imports = []
    dynamic_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "claude_bridge" in node.module:
                bridge_imports.append(node.lineno)
        if isinstance(node, ast.Import):
            if any(alias.name == "daedalus.claude_bridge" for alias in node.names):
                bridge_imports.append(node.lineno)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"__import__", "import_module"}:
                dynamic_calls.append(node.lineno)

    assert bridge_imports == []
    assert dynamic_calls == []
    assert not hasattr(legacy_provider, "_invoke_claude_payload")


def test_shim_registry_records_the_partial_registered_door() -> None:
    payload = json.loads(
        (ROOT / "docs/architecture/shim-registry.json").read_text(encoding="utf-8")
    )
    entry = next(
        item
        for item in payload["entries"]
        if item["import_path"] == "daedalus.providers.claude_cli"
    )

    assert entry["owner"] == "runtimes-providers"
    assert entry["targets"] == ["daedalus.runtimes.contracts.claude"]
    assert entry["kind"] == "registered_effect_door_with_contract_reexports"
    assert "Effect Registry digest" in entry["removal_criteria"]
    assert "pickle" in entry["removal_criteria"]


def test_work_packet_satisfies_the_post_index_contract() -> None:
    artifact = index_work_packets._artifact(ROOT, PACKET_PATH, set())
    assert artifact["declared_packet_id"] == "G1-RUNTIME-PROVIDER-01"
    assert artifact["artifact_role"] == "primary"
    assert artifact["metadata"] == {
        "active_gate": 1,
        "classification": "ALIGNED",
        "owner": "repository owner",
        "base_revision": "bacd9e6e69d58de6aebde4847e6afd6101b2ca72",
        "dependencies": (
            "G1-HIER-01 at 72f7e326c70e4404504e9dd04075f0dd0c150cc3; "
            "G1-RUNTIME-02 at d30136e8e351e311fb9b72db7b3d1a3222b1c6e5; "
            "G1-WP-INDEX-01 at b2e74d601ab1af274cf670c58be53645c1001114"
        ),
    }
    assert artifact["sections"] == list(index_work_packets.REQUIRED_SECTIONS)
