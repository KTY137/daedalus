from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/g1-ikarus-unified-runtime-admission.yml")

# The JARVIS-style Stop path crosses UI ownership, the SSE transport boundary,
# Ikarus routing, canonical cancellation ownership, and both stream transports.
# A PR that edits any one of these must not be able to skip the canonical Gate 1
# workflow just because the path filter forgot that layer.
STOP_SEAM_PATHS = (
    "apps/web/src/api.ts",
    "apps/web/src/cockpit/Conversation.tsx",
    "apps/web/tests/cockpit-stream.spec.ts",
    "daedalus/web_api.py",
    "daedalus/ikarus_cancellation.py",
    "daedalus/ikarus_os.py",
    "daedalus/providers/_openai_compat.py",
    "daedalus/providers/_ollama_native.py",
    "tests/test_ikarus_cancellation.py",
    "tests/test_ikarus_stream.py",
    "tests/test_ikarus_stop_gate_paths.py",
)


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_stop_seam_paths_trigger_gate_one() -> None:
    text = _workflow_text()
    missing = [path for path in STOP_SEAM_PATHS if f'- "{path}"' not in text]
    assert not missing, f"Gate 1 path filter misses JARVIS Stop seam(s): {missing}"


def test_backend_stream_surface_is_compiled_in_focused_jobs() -> None:
    text = _workflow_text()
    compile_start = text.index("python -m py_compile")
    compile_end = text.index("- run: python -m json.tool", compile_start)
    compile_block = text[compile_start:compile_end]
    assert "daedalus/web_api.py" in compile_block
    assert "daedalus/ikarus_cancellation.py" in compile_block
    assert "tests/test_ikarus_cancellation.py" in compile_block
    assert "tests/test_ikarus_stop_gate_paths.py" in compile_block


def test_gate_path_contract_test_runs_in_focused_matrix() -> None:
    text = _workflow_text()
    pytest_start = text.index("python -m pytest -q -p no:cacheprovider")
    pytest_block = text[pytest_start:]
    assert "tests/test_ikarus_cancellation.py" in pytest_block
    assert "tests/test_ikarus_stop_gate_paths.py" in pytest_block
