"""Contracts for the runtime-owned provider catalogue and health projection."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

import daedalus.providers as legacy
from daedalus.runtimes.providers import catalogue
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "daedalus/runtimes/providers/catalogue.py"
FACADE = ROOT / "daedalus/providers/__init__.py"


class _Available:
    def __init__(self, value: bool = True) -> None:
        self.value = value

    def available(self) -> bool:
        return self.value


def test_legacy_metadata_and_listing_are_exact_runtime_objects() -> None:
    assert legacy.ProviderMetadata is catalogue.ProviderMetadata
    assert legacy._PROVIDERS is catalogue.PROVIDER_CATALOGUE
    assert legacy.list_providers is catalogue.list_providers
    assert legacy._configured is catalogue.configured
    rows = legacy.list_providers()
    assert [row["name"] for row in rows] == [
        "ollama",
        "claude_cli",
        "deepseek",
        "openai_api",
        "anthropic_api",
        "codex_cli",
    ]
    assert next(row for row in rows if row["name"] == "codex_cli")[
        "trusted_with_ip"
    ] is False


def test_runtime_projection_receives_probe_and_environment_ports() -> None:
    probed: list[str] = []

    def probe(name: str) -> tuple[bool, str]:
        probed.append(name)
        return True, ""

    rows = catalogue.provider_health(probe, environ={})
    assert probed == list(catalogue.PROVIDER_CATALOGUE)
    deepseek = next(row for row in rows if row["name"] == "deepseek")
    assert deepseek["configured"] is False
    assert deepseek["available"] is False
    ollama = next(row for row in rows if row["name"] == "ollama")
    assert ollama["configured"] is True
    assert ollama["available"] is True
    assert set(catalogue.available_from_health(rows)) == {
        "ollama",
        "claude_cli",
        "deepseek",
        "codex_cli",
    }


def test_placeholder_probe_never_constructs_unimplemented_provider() -> None:
    def refuse_factory(name: str) -> _Available:
        raise AssertionError(f"factory called for {name}")

    assert catalogue.probe_provider("openai_api", refuse_factory) == (
        False,
        "provider placeholder; implementation pending",
    )


def test_probe_failure_is_health_data() -> None:
    def broken_factory(name: str) -> _Available:
        raise OSError(f"{name} offline")

    assert catalogue.probe_provider("ollama", broken_factory) == (
        False,
        "ollama offline",
    )


def test_legacy_health_resolves_the_live_factory_monkeypatch() -> None:
    with patch("daedalus.providers.get_provider", return_value=_Available()) as factory:
        rows = legacy.provider_health()
        available = legacy.available_providers()
    assert factory.call_count == 8
    assert all(
        row["available"]
        for row in rows
        if row["implemented"] and not row["requires_key"]
    )
    assert set(available) == {
        "ollama",
        "claude_cli",
        "deepseek",
        "codex_cli",
    }


def test_unknown_provider_factory_refusal_is_unchanged() -> None:
    with pytest.raises(ValueError, match="unknown provider 'missing'"):
        legacy.get_provider("missing")


def test_runtime_owner_has_no_outer_layer_import() -> None:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden = (
        "daedalus.providers",
        "daedalus.gates",
        "daedalus.kairos",
        "daedalus.orchestration",
        "daedalus.interfaces",
        "daedalus.chip_design",
    )
    assert not any(
        module == prefix or module.startswith(prefix + ".")
        for module in imports
        for prefix in forbidden
    )


def test_legacy_package_defines_no_metadata_or_health_algorithm() -> None:
    tree = ast.parse(FACADE.read_text(encoding="utf-8"), filename=str(FACADE))
    assert not any(isinstance(node, ast.ClassDef) for node in tree.body)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(functions) == {
        "get_provider",
        "_availability_probe",
        "provider_health",
        "available_providers",
    }
    for name in ("_availability_probe", "provider_health", "available_providers"):
        assert not any(
            isinstance(node, (ast.For, ast.While, ast.Try))
            for node in ast.walk(functions[name])
        )


def test_structure_packet_keeps_effect_registry_exact() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
