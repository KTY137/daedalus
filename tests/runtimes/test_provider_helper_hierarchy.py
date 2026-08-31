"""Directed-owner contracts for provider report, budget, and token helpers."""

from __future__ import annotations

import ast
from pathlib import Path

import daedalus.token_policy as legacy_tokens
from daedalus.providers import _report as legacy_report
from daedalus.runtimes.providers import budget_admission, execution_policy, reporting
from daedalus.runtimes.providers import token_policy
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
LEGACY_REPORT = ROOT / "daedalus" / "providers" / "_report.py"
LEGACY_TOKENS = ROOT / "daedalus" / "token_policy.py"
OWNERS = (
    ROOT / "daedalus" / "runtimes" / "providers" / "budget_admission.py",
    ROOT / "daedalus" / "runtimes" / "providers" / "execution_policy.py",
    ROOT / "daedalus" / "runtimes" / "providers" / "reporting.py",
    ROOT / "daedalus" / "runtimes" / "providers" / "token_policy.py",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _definitions(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    return imports


def test_legacy_report_helpers_are_exact_runtime_objects() -> None:
    owners = {
        "admit_execution_limit_policy": execution_policy,
        "attempt_numbers": execution_policy,
        "blocked_report": reporting,
        "bounded_execution_limit_policy": execution_policy,
        "budget_refusal_report": budget_admission,
        "build_prompt": reporting,
        "coerce_report": reporting,
        "extract_json": reporting,
        "provider_http_timeout": execution_policy,
        "report_instructions": reporting,
        "reserve_or_report": budget_admission,
    }
    for name, owner in owners.items():
        assert getattr(legacy_report, name) is getattr(owner, name)


def test_legacy_token_policy_is_an_exact_reexport_facade() -> None:
    for name in (
        "ExecutionLimitPolicy",
        "load_limit_policy",
        "trim_paths",
        "trim_text",
    ):
        assert getattr(legacy_tokens, name) is getattr(token_policy, name)
    for name in (
        "CHEAP_MODEL",
        "DEFAULT_MODEL",
        "HIGH_RISK_MODEL",
        "MAX_PATHS_PER_REQUEST",
        "MAX_SUMMARY_CHARS",
        "MAX_TODO_CHARS",
        "STATIC_PROMPT_PREFIX",
    ):
        assert getattr(legacy_tokens, name) == getattr(token_policy, name)
    assert _definitions(LEGACY_TOKENS) == set()


def test_legacy_report_module_retains_only_context_implementation() -> None:
    assert _definitions(LEGACY_REPORT) == {
        "read_provider_context",
        "render_provider_brief",
    }
    assert len(LEGACY_REPORT.read_text(encoding="utf-8").splitlines()) < 130


def test_runtime_helper_owners_do_not_import_outer_layers() -> None:
    forbidden = (
        "daedalus.orchestration",
        "daedalus.interfaces",
        "daedalus.gates",
        "daedalus.providers",
        "daedalus.chip_design",
        "daedalus.kairos",
        "daedalus.lanes",
    )
    for owner in OWNERS:
        assert not any(name.startswith(forbidden) for name in _imports(owner))


def test_structure_packet_keeps_effect_registry_exact() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
