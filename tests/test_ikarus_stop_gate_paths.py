from __future__ import annotations

from fnmatch import fnmatchcase
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
    "tests/test_ikarus_http_cancellation.py",
    "tests/test_ikarus_stop_gate_paths.py",
)


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _quoted_list_values(text: str) -> tuple[str, ...]:
    """Return quoted YAML list scalars without pretending to parse all YAML."""
    values: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not (stripped.startswith('- "') and stripped.endswith('"')):
            continue
        values.append(stripped[3:-1])
    return tuple(values)


def test_stop_seam_paths_trigger_gate_one() -> None:
    # Path filters are glob patterns.  Requiring every protected file to appear
    # as an exact literal made the guard reject the stronger, lower-drift
    # `apps/web/src/cockpit/**` coverage.  Test the semantics GitHub applies:
    # every protected seam must be matched by at least one configured pattern.
    patterns = _quoted_list_values(_workflow_text())
    missing = [
        path
        for path in STOP_SEAM_PATHS
        if not any(fnmatchcase(path, pattern) for pattern in patterns)
    ]
    assert not missing, f"Gate 1 path filter misses JARVIS Stop seam(s): {missing}"


def test_backend_stream_surface_is_compiled_in_focused_jobs() -> None:
    text = _workflow_text()
    compile_start = text.index("python -m py_compile")
    compile_end = text.index("- run: python -m json.tool", compile_start)
    compile_block = text[compile_start:compile_end]
    for path in (
        "daedalus/web_api.py",
        "daedalus/ikarus_cancellation.py",
        "tests/test_ikarus_cancellation.py",
        "tests/test_ikarus_http_cancellation.py",
        "tests/test_ikarus_stop_gate_paths.py",
    ):
        assert path in compile_block


def test_stop_contract_tests_run_in_focused_matrix() -> None:
    text = _workflow_text()
    pytest_start = text.index("python -m pytest -q -p no:cacheprovider")
    pytest_block = text[pytest_start:]
    for path in (
        "tests/test_ikarus_cancellation.py",
        "tests/test_ikarus_stream.py",
        "tests/test_ikarus_http_cancellation.py",
        "tests/test_ikarus_stop_gate_paths.py",
    ):
        assert path in pytest_block
