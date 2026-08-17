"""Marker registration for runtime tests that need a real container runtime."""
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "docker: requires a reachable Docker daemon with a Linux engine; "
        "deselect with -m 'not docker'",
    )
