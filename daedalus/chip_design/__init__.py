"""Daedalus chip-design support: RTL discovery, EDA tool registry and Tcl execution."""
from .executor import ExecutionResult, execute_argv
from .sources import SourceSpec, classify_source, discover_sources, is_rtl
from .toolchains import (
    EdaToolSpec,
    TOOLS,
    all_tool_status,
    build_rtl_lint_argv,
    build_tcl_argv,
    get_tool,
    tool_status,
)

__all__ = [
    "EdaToolSpec", "ExecutionResult", "SourceSpec", "TOOLS",
    "all_tool_status", "build_rtl_lint_argv", "build_tcl_argv",
    "classify_source", "discover_sources", "execute_argv", "get_tool",
    "is_rtl", "tool_status",
]
