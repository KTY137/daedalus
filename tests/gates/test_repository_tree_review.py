from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/repository_tree.py"
)


def _tree() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def test_module_has_read_only_filesystem_authority() -> None:
    tree = _tree()
    source = TARGET.read_text(encoding="utf-8")
    forbidden_imports = {
        "subprocess",
        "sqlite3",
        "socket",
        "docker",
        "git",
        "shutil",
        "tempfile",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(forbidden_imports)
    assert "Callable" not in source
    assert "Protocol" not in source
    assert "**kwargs" not in source

    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "os.open" in calls
    assert "os.read" in calls
    assert "os.fstat" in calls
    for forbidden in (
        "os.write",
        "os.remove",
        "os.rename",
        "os.replace",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "touch",
        "subprocess.run",
        "subprocess.Popen",
    ):
        assert forbidden not in calls
    assert "os.O_RDONLY" in source
    assert "os.O_WRONLY" not in source
    assert "os.O_RDWR" not in source


def test_path_open_read_and_identity_fences_are_present() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "(?![A-Za-z]:/)",
        "(?!.*(?:^|/)\\.\\.?(?:/|$))",
        "stat.S_ISLNK(component.st_mode)",
        "resolved.relative_to(root)",
        "os.O_NOFOLLOW",
        "before.st_dev",
        "before.st_ino",
        "after.st_dev",
        "after.st_ino",
        "final_path.st_dev",
        "final_path.st_ino",
        "root_before.st_dev",
        "root_before.st_ino",
        "_MAX_SOURCE_BYTES",
        'b"\\x00" in source',
        'source.decode("utf-8", errors="strict")',
    }
    for fragment in required:
        assert fragment in source


def test_descriptor_is_closed_unconditionally() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "read_repository_source"
    )
    source = ast.get_source_segment(
        TARGET.read_text(encoding="utf-8"),
        function,
    )
    assert source is not None
    assert "finally:" in source
    assert "os.close(descriptor)" in source
    assert source.index("finally:") < source.index("os.close(descriptor)")


def test_snapshot_binds_exact_bytes_digest_and_size() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for fragment in (
        "self.size != len(self.source)",
        "hashlib.sha256(self.source).hexdigest()",
        "self.source_sha256 != expected",
        "source_sha256=hashlib.sha256(source).hexdigest()",
        "size=len(source)",
    ):
        assert fragment in source


def test_module_has_no_gate_or_effect_claims() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "closed",
        "GateReport",
        "OwnerApproval",
        "PromotionReceipt",
        "EffectLease",
        "begin_effect",
        "repository_write_classification",
    ):
        assert forbidden not in source
