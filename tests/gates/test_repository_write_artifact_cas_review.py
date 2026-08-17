from __future__ import annotations

import ast

from daedalus.spine.ledger import ROOT


TARGET = ROOT / "daedalus" / "gates" / "repository_write_artifact_cas.py"
SOURCE = TARGET.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(TARGET))


def _function(name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _called_name(node: ast.Call) -> str:
    parts: list[str] = []
    current: ast.AST = node.func
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def test_module_has_no_publication_process_network_or_promotion_authority() -> None:
    forbidden_import_roots = {
        "subprocess",
        "socket",
        "urllib",
        "http",
        "requests",
        "shutil",
    }
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            assert not forbidden_import_roots.intersection(
                alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[0] not in forbidden_import_roots
            assert "promotion" not in module
            assert "effects" not in module

    forbidden_calls = {
        "open",
        "os.replace",
        "os.rename",
        "os.unlink",
        "os.remove",
        "os.mkdir",
        "os.makedirs",
        "Path.write_bytes",
        "Path.write_text",
        "Path.mkdir",
        "Path.unlink",
        "Path.rename",
        "Path.replace",
        "subprocess.run",
        "subprocess.Popen",
    }
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call):
            assert _called_name(node) not in forbidden_calls


def test_only_os_open_is_explicitly_read_only() -> None:
    calls = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call) and _called_name(node) == "os.open"
    ]
    assert len(calls) == 1
    call = calls[0]
    assert len(call.args) >= 2

    # The flag word is assembled in a local before the call, so when the
    # argument is just that local's name, review the whole reader function.
    argument = ast.unparse(call.args[1])
    flags = (
        ast.unparse(_function("_read_exact_file"))
        if argument.isidentifier()
        else argument
    )
    assert "os.O_RDONLY" in flags
    assert "O_WRONLY" not in flags
    assert "O_RDWR" not in flags
    assert "O_CREAT" not in flags
    assert "O_TRUNC" not in flags
    assert "O_APPEND" not in flags


def test_locator_derivation_is_closed_and_digest_only() -> None:
    function = _function("artifact_relative_path")
    source = ast.get_source_segment(SOURCE, function) or ""
    assert "_artifact_locator(locator" in source
    assert "_locator_sha256" in source
    assert 'f"sha256/{digest[:2]}/{digest[2:]}"' in source
    assert "Path" not in source
    assert "resolve" not in source


def test_exact_file_resolution_rechecks_isolation_and_identity() -> None:
    function = _function("_exact_artifact_file")
    source = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "type(root) is not RepositoryWriteArtifactCASRoot",
        "type(artifact) is not RepositoryWriteArtifactEvidence",
        "artifact.source_revision != root.source_revision",
        "_roots_overlap(cas_root, primary_root)",
        "_is_within(candidate, primary_root)",
        "resolved_parent = parent.resolve(strict=True)",
        "candidate.is_symlink()",
        "candidate.resolve(strict=True)",
        "stat.S_ISREG(before.st_mode)",
        "before.st_nlink != 1",
        "before.st_size > _MAX_ARTIFACT_BYTES",
    )
    for marker in required:
        assert marker in source


def test_bounded_read_binds_descriptor_before_and_after() -> None:
    function = _function("_read_exact_file")
    source = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "os.O_RDONLY",
        "os.O_NOFOLLOW",
        "opened = os.fstat(descriptor)",
        "opened.st_nlink != 1",
        "opened.st_dev, opened.st_ino",
        "remaining = _MAX_ARTIFACT_BYTES + 1",
        "after = os.fstat(descriptor)",
        "_file_identity(after) != _file_identity(before)",
    )
    for marker in required:
        assert marker in source
    assert "os.write" not in source


def test_post_read_revalidation_refuses_path_redirection() -> None:
    function = _function("_revalidate_exact_path")
    source = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "os.path.lexists(path)",
        "path.is_symlink()",
        "path.parent.resolve(strict=True)",
        "path.resolve(strict=True)",
        "_normal(path.parent) != _normal(resolved_parent)",
        "_normal(path) != _normal(resolved)",
        "stat.S_ISREG(after.st_mode)",
        "after.st_nlink != 1",
        "identity_after != identity_before",
    )
    for marker in required:
        assert marker in source


def test_public_resolver_hashes_bytes_and_rechecks_path_identity() -> None:
    function = _function("resolve_repository_write_artifact")
    source = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "_exact_artifact_file(root, artifact)",
        "_read_exact_file(path, before)",
        "hashlib.sha256(content).hexdigest()",
        "content_sha256 != artifact.artifact_content_sha256",
        "after = _revalidate_exact_path(path, before)",
        "ContractProvenance(",
        "artifact.digest",
        "root.digest",
        "RepositoryWriteArtifactResolutionReceipt(",
    )
    for marker in required:
        assert marker in source


def test_receipt_rebinds_locator_path_size_and_provenance() -> None:
    class_node = next(
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RepositoryWriteArtifactResolutionReceipt"
    )
    source = ast.get_source_segment(SOURCE, class_node) or ""
    required = (
        "_locator_sha256(self.locator) != self.artifact_content_sha256",
        "self.relative_path != artifact_relative_path(self.locator)",
        "not 1 <= self.file_size <= _MAX_ARTIFACT_BYTES",
        "type(self.provenance) is not ContractProvenance",
        "self.provenance.source_revision != self.source_revision",
        "self.provenance.created_at != self.resolved_at",
        "_require_provenance_inputs",
    )
    for marker in required:
        assert marker in source


def test_module_does_not_claim_release_gate_or_trust_completion() -> None:
    lowered = SOURCE.lower()
    assert "closed=true" not in lowered
    assert '"trusted"' not in lowered
    assert "ownerapproval" not in lowered
    assert "promotionreceipt" not in lowered
    assert "merge_pull_request" not in lowered
