from __future__ import annotations

from typing import Any


def langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True


def build_graph() -> Any:
    """Build the production graph when LangGraph is installed.

    The stdlib harness keeps the state contract small and serializable. This
    adapter is intentionally thin so a future LangGraph graph can reuse the same
    state keys instead of inventing a second orchestration model.
    """
    if not langgraph_available():
        raise RuntimeError(
            "LangGraph is not installed. Install it with `pip install langgraph`, "
            "then wire nodes around RunState."
        )
    raise NotImplementedError("LangGraph node wiring is intentionally deferred.")
