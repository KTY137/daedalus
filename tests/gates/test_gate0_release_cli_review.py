from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.gates.release_cli import main

ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "daedalus" / "gates" / "release_cli.py"
IO_PATH = ROOT / "daedalus" / "gates" / "release_io.py"


def _module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_names(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def test_cli_is_read_only_and_contains_no_release_authority() -> None:
    calls = _call_names(_module(CLI_PATH)) | _call_names(_module(IO_PATH))
    forbidden = {
        "assemble_gate0_release_report",
        "issue_evidence_trust_bundle",
        "issue_owner_approval",
        "promote_candidates",
        "merge_pull_request",
        "update_ref",
        "Popen",
        "run",
        "system",
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
    }
    assert forbidden.isdisjoint(calls)
    assert "gate0_release_verification_blockers" in calls


def test_cli_accepts_only_secret_variable_name_not_secret_value_option() -> None:
    source = CLI_PATH.read_text(encoding="utf-8")
    assert "--collector-secret-env" in source
    assert '"--collector-secret"' not in source
    assert "os.environ.get(args.collector_secret_env)" in source
    assert "collector_secret=" not in source


def test_loader_rejects_duplicate_keys_and_noncanonical_wire() -> None:
    source = IO_PATH.read_text(encoding="utf-8")
    assert "object_pairs_hook=_reject_duplicate_keys" in source
    assert "wire != value.to_dict()" in source
    assert "Gate0ReleaseReport.from_dict" in source


def test_cli_returns_distinct_success_blocker_and_malformed_statuses() -> None:
    source = ast.unparse(_module(CLI_PATH))
    assert "return 0 if not blockers else 1" in source
    assert "return 2" in source
    assert '"trusted": not blockers' in source or "'trusted': not blockers" in source


def test_cli_entrypoint_has_no_ambient_default_repository_or_revision() -> None:
    signature = inspect.signature(main)
    assert tuple(signature.parameters) == ("argv",)
    source = CLI_PATH.read_text(encoding="utf-8")
    for required in (
        "--repo-root",
        "--current-revision",
        "--current-tree-revision",
        "--release",
        "--mechanical-report",
        "--evidence-index",
        "--trust-bundle",
    ):
        assert f'parser.add_argument("{required}", required=True)' in source


def test_counter_review_does_not_claim_human_owner_or_gate_authority() -> None:
    source = Path(__file__).read_text(encoding="utf-8").lower()
    assert "approved by owner" not in source
    assert "human review passed" not in source
    assert "gate 0 closed" not in source
