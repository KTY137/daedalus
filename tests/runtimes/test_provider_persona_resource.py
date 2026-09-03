"""Source/wheel parity contracts for the runtime provider persona catalogue."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus.providers import personas as legacy
from daedalus.resources import ResourceDriftError, read_builtin_text
from daedalus.runtimes.providers import personas
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
LEGACY_MODULE = ROOT / "daedalus" / "providers" / "personas.py"
LEGACY_JSON = ROOT / "daedalus" / "providers" / "personas.json"
PACKAGED_JSON = (
    ROOT
    / "daedalus"
    / "resources"
    / "catalogue"
    / "providers"
    / "personas.json"
)


def test_packaged_and_legacy_persona_resources_are_byte_identical() -> None:
    assert PACKAGED_JSON.read_bytes() == LEGACY_JSON.read_bytes()
    assert read_builtin_text(
        "catalogue/providers/personas.json", legacy=LEGACY_JSON
    ) == LEGACY_JSON.read_text(encoding="utf-8")


def test_legacy_persona_functions_are_exact_runtime_objects() -> None:
    assert legacy.persona_for is personas.persona_for
    assert legacy.culture is personas.culture
    assert legacy.roster is personas.roster
    assert legacy._registry is personas._registry
    assert legacy._REGISTRY_PATH == personas.LEGACY_PERSONAS_PATH


def test_persona_values_and_roster_order_are_unchanged() -> None:
    personas._registry.cache_clear()
    assert personas.persona_for("ollama", "qa-critic") == "Rosa"
    assert personas.persona_for("deepseek", None) == "Wei"
    assert personas.persona_for("unknown", None) == "unknown"
    assert personas.culture("codex_cli") == "American"
    roster = personas.roster("ollama")
    assert roster[:3] == ["Diego", "Sofia", "Lucia"]
    assert roster.count("Mateo") == 1


def test_packaged_default_works_without_checkout_mirror(monkeypatch, tmp_path) -> None:
    personas._registry.cache_clear()
    monkeypatch.setattr(
        personas,
        "LEGACY_PERSONAS_PATH",
        tmp_path / "missing" / "personas.json",
    )
    assert personas.persona_for("ollama", "researcher") == "Marco"
    personas._registry.cache_clear()


def test_divergent_legacy_persona_mirror_refuses(monkeypatch, tmp_path) -> None:
    mirror = tmp_path / "personas.json"
    mirror.write_bytes(LEGACY_JSON.read_bytes() + b"\n")
    personas._registry.cache_clear()
    monkeypatch.setattr(personas, "LEGACY_PERSONAS_PATH", mirror)
    with pytest.raises(ResourceDriftError, match="differs from legacy mirror"):
        personas.roster("ollama")
    personas._registry.cache_clear()


def test_legacy_module_is_only_a_runtime_reexport() -> None:
    tree = ast.parse(
        LEGACY_MODULE.read_text(encoding="utf-8"), filename=str(LEGACY_MODULE)
    )
    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in tree.body
    )
    imports = {
        node.module or ""
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    assert imports == {"runtimes.providers.personas"}


def test_structure_packet_keeps_effect_registry_exact() -> None:
    assert registry_sha256() == (
        "615372b006399f851eb5f707ccc21ccdb347dec2e717e0911c6ac36549164752"
    )
