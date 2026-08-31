from __future__ import annotations

import ast
from pathlib import Path

from daedalus.providers import base as legacy
from daedalus.providers.claude_cli import ClaudeCLIProvider
from daedalus.providers.codex_cli import CodexCLIProvider
from daedalus.providers.deepseek import DeepSeekProvider
from daedalus.providers.ollama import OllamaProvider
from daedalus.runtimes.providers import contracts
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "providers" / "base.py"
OWNER = ROOT / "daedalus" / "runtimes" / "providers" / "contracts.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    return imports


def test_legacy_provider_contracts_are_exact_owner_objects() -> None:
    assert legacy.Provider is contracts.Provider
    assert legacy.ProviderCapabilities is contracts.ProviderCapabilities


def test_every_builtin_provider_uses_the_runtime_contract_owner() -> None:
    for provider in (
        ClaudeCLIProvider,
        CodexCLIProvider,
        DeepSeekProvider,
        OllamaProvider,
    ):
        assert issubclass(provider, contracts.Provider)


def test_legacy_module_is_only_a_contract_reexport() -> None:
    tree = ast.parse(FACADE.read_text(encoding="utf-8"), filename=str(FACADE))
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions == set()
    assert _imports(FACADE) == {"__future__", "runtimes.providers.contracts"}


def test_runtime_contract_owner_has_no_outer_layer_import() -> None:
    imports = _imports(OWNER)
    assert not any(
        name.startswith(
            (
                "daedalus.providers",
                "daedalus.gates",
                "daedalus.orchestration",
                "daedalus.interfaces",
                "daedalus.chip_design",
            )
        )
        for name in imports
    )


def test_read_only_contract_preserves_advisory_handoff() -> None:
    class FixtureProvider(contracts.Provider):
        def available(self) -> bool:
            return True

        def run(self, **_kwargs: object) -> dict[str, object]:
            return {}

    provider = FixtureProvider()
    provider.caps = contracts.ProviderCapabilities(
        name="fixture",
        can_write=False,
        local=True,
        trusted_with_ip=False,
        agentic=False,
    )
    report = {
        "status": "done",
        "files_changed": ["src/example.py"],
        "tests_run": ["pytest"],
        "handoff": {},
    }

    assert provider._enforce_read_only(report) == {
        "status": "needs_review",
        "files_changed": [],
        "tests_run": [],
        "handoff": {"suggested_files": ["src/example.py"]},
    }


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
