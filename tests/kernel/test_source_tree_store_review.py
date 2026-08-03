from __future__ import annotations

import ast
import inspect

import daedalus.kernel.source_trees as source_trees


def _function(tree: ast.AST, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"missing {class_name}.{method_name}")


def test_module_extends_existing_artifact_identity_instead_of_redefining_it() -> None:
    source = inspect.getsource(source_trees)
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    artifact_imports = [node for node in imports if node.module == "daedalus.kernel.artifacts"]
    assert len(artifact_imports) == 1
    imported = {alias.name for alias in artifact_imports[0].names}
    assert imported == {"ArtifactRef", "artifact_locator"}
    assert "def artifact_locator(" not in source
    assert "def locator_sha256(" not in source
    assert source_trees.artifact_locator.__module__ == "daedalus.kernel.artifacts"


def test_capture_fences_external_store_before_traversal_and_publication() -> None:
    tree = ast.parse(inspect.getsource(source_trees))
    method = _function(tree, "SourceTreeStore", "capture_tree")
    source = ast.unparse(method)
    external_at = source.index("self.root == root or self.root.is_relative_to(root)")
    walk_at = source.index("os.walk")
    manifest_at = source.index("SourceTreeManifest")
    publish_at = source.index("self.put_bytes(manifest.to_json()")
    assert external_at < walk_at < manifest_at < publish_at
    assert "followlinks=False" in source
    assert "source contains symlink" in source
    assert "source directory changed during capture" in source


def test_manifest_mandatory_exclusions_and_unique_blob_provenance_are_structural() -> None:
    source = inspect.getsource(source_trees.SourceTreeManifest.__post_init__)
    assert "MANDATORY_IGNORED_ROOTS" in source
    assert "mandatory exclusions" in source
    assert "case-insensitively unique" in source
    assert "file/child path conflict" in source
    assert "sorted({entry.blob_sha256" in source
    assert "_require_provenance_inputs" in source


def test_materialization_is_staged_and_cannot_replace_existing_destination() -> None:
    source = inspect.getsource(source_trees.SourceTreeStore.materialize_tree)
    assert source.index("target.exists() or target.is_symlink()") < source.index(
        "tempfile.mkdtemp"
    )
    assert "output.open(\"xb\")" in source
    assert "os.replace(staging, target)" in source
    assert "shutil.rmtree(staging" in source
    assert "git" not in source.lower()
    assert "subprocess" not in source


def test_source_tree_module_has_no_execution_or_promotion_authority() -> None:
    source = inspect.getsource(source_trees)
    forbidden = (
        "subprocess",
        "Popen",
        "run_in_docker_sandbox",
        "EffectLease",
        "OwnerApproval",
        "promote_candidates",
        "merge_pull_request",
        "provider.invoke",
        "requests.",
        "urllib.request",
    )
    for token in forbidden:
        assert token not in source


def test_every_cas_read_recomputes_address_after_stability_checks() -> None:
    source = inspect.getsource(source_trees.SourceTreeStore.read_bytes)
    assert source.index("os.stat(target, follow_symlinks=False)") < source.index(
        "os.open(target, self._open_flags())"
    )
    assert source.index("after = os.fstat(descriptor)") < source.index(
        "sha256(payload).hexdigest()"
    )
    assert "CAS object changed during read" in source
    assert "CAS object does not match its address" in source
