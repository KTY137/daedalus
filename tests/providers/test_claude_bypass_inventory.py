from __future__ import annotations

import ast
from pathlib import Path

import daedalus
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Wiring


_ALLOWED_SUBPROCESS_OWNER = (Path("claude_bridge.py"), "_invoke_claude_payload")


def _package_root() -> Path:
    return Path(daedalus.__file__).resolve().parent


def test_private_claude_subprocess_helper_has_no_cross_domain_importer() -> None:
    imports: list[Path] = []
    calls: list[Path] = []
    for path in sorted(_package_root().rglob("*.py")):
        relative = path.relative_to(_package_root())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "_invoke_claude_payload" for alias in node.names):
                    imports.append(relative)
            elif isinstance(node, ast.Call):
                direct = (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "_invoke_claude_payload"
                )
                sealed = (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_invoke_claude_payload"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "claude_cli"
                )
                if direct or sealed:
                    calls.append(relative)
    assert imports == []
    assert calls == []


def test_claude_subprocess_run_is_owned_only_by_private_helper() -> None:
    owners: list[tuple[Path, str]] = []
    for path in sorted(_package_root().rglob("*.py")):
        relative = path.relative_to(_package_root())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            for child in ast.walk(function):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id in {"subprocess", "local_subprocess"}
                    and child.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
                ):
                    owners.append((relative, function.name))
    claude_owners = [
        owner
        for owner in owners
        if owner[0] in {Path("claude_bridge.py"), Path("providers/claude_cli.py")}
    ]
    assert claude_owners == [_ALLOWED_SUBPROCESS_OWNER]


def test_canonical_registry_activation_remains_an_explicit_blocker() -> None:
    # This packet removes the public bypass first.  Default lease issuance must
    # remain impossible until caller injection and exact-head verification are
    # complete in the next activation packet.
    assert REGISTRY_BY_ID["provider.claude"].wiring is Wiring.INVENTORY_ONLY
