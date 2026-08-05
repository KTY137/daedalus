from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKET_PATH = (
    REPOSITORY_ROOT
    / "docs/work-packets/G0-RTC-07I_REPOSITORY_HEAD_RECEIPT_INTEGRATION.json"
)
PORTED_BLOBS = {
    "configs/schemas/repository-head-revision-receipt.schema.json": "ef7eb06c0f64442449d7999c7f43fb3a50b7d7fc",
    "daedalus/gates/repository_head_revision.py": "bbdb28084799ad7a1babbb9ea4ce8563f46f3f3c",
    "scripts/run_repository_head_revision_mutations.py": "8637be139e686e4b69e4e181b9c6243bda1c0ca2",
    "tests/gates/test_repository_head_revision.py": "91522b3cee7c3beb191f15a704b70e98f97c5c0d",
    "tests/gates/test_repository_head_revision_review.py": "a6a274a99a3b889cb3ac9ed2f395c8c2b50e5c94",
    "tests/gates/test_repository_head_revision_schema.py": "9171bd5ba5378f74e33cd17874040a7a82086d9c",
    "tests/gates/test_repository_head_revision_wire.py": "88767051f85f6c7c07359c45dad92f744a7cbab2",
}


def _git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git object identity


def test_integration_ports_exact_reviewed_blobs() -> None:
    observed = {
        path: _git_blob_sha1((REPOSITORY_ROOT / path).read_bytes())
        for path in PORTED_BLOBS
    }
    assert observed == PORTED_BLOBS


def test_packet_records_transfer_as_provenance_not_execution_evidence() -> None:
    packet = json.loads(PACKET_PATH.read_text(encoding="utf-8"))
    assert packet["source_transfer"]["ported_blobs"] == PORTED_BLOBS
    assert packet["verification"]["hard_evidence_claimed"] is False
    assert packet["verification"]["source_inspection_is_hard_evidence"] is False
    assert packet["verification"]["llm_statement_is_hard_evidence"] is False
    assert packet["scope"]["retention_entrypoint_wired"] is False
    assert packet["scope"]["effect_lease_consumed"] is False
    assert packet["scope"]["provider_execution_authorized"] is False
    assert packet["scope"]["owner_approval_issued"] is False
    assert packet["scope"]["promotion_receipt_issued"] is False


def test_ported_verifier_has_no_direct_process_network_or_write_surface() -> None:
    source_path = REPOSITORY_ROOT / "daedalus/gates/repository_head_revision.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    imported_roots: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert imported_roots.isdisjoint(
        {"subprocess", "socket", "requests", "urllib", "sqlite3"}
    )
    assert called_names.isdisjoint(
        {
            "Popen",
            "run",
            "call",
            "check_call",
            "check_output",
            "system",
            "write_bytes",
            "write_text",
            "unlink",
            "replace",
            "rename",
            "mkdir",
            "rmdir",
        }
    )
