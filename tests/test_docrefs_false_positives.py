from pathlib import Path

from daedalus.spine.docrefs import Reference, resolve_reference


ROOT = Path(__file__).resolve().parents[1]


def _resolve(raw: str):
    return resolve_reference(
        Reference(doc_path="docs/example.md", line=1, raw=raw),
        ROOT,
    )


def test_git_core_autocrlf_is_not_reinterpreted_as_core_py():
    result = _resolve("core.autocrlf")
    assert result.state == "skipped"
    assert "known non-module dotted name" in result.why


def test_operation_status_code_is_not_reinterpreted_as_status_py():
    result = _resolve("status.code")
    assert result.state == "skipped"
    assert "known non-module dotted name" in result.why


def test_the_actual_stale_vendor_constant_remains_actionable():
    result = _resolve("vendors._LOCAL_HOSTS")
    assert result.state == "broken"
    assert result.module_path == "daedalus/council/vendors.py"
