# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest


_PREPROVISIONED_ATTEMPT_ROOT_TESTS = frozenset(
    {
        "test_isolated_attempt_lifecycle.py",
        "test_isolated_attempt_time_and_preflight.py",
        "test_isolated_attempt_time_tampering.py",
    }
)


@pytest.fixture(autouse=True)
def _preprovision_attempt_workspace_root(request: pytest.FixtureRequest) -> None:
    """Model the deployment-owned external workspace root in legacy fixtures.

    Gate-0 Attempt admission no longer creates caller-selected workspace roots.
    These existing lifecycle suites intentionally use ``tmp_path/workspaces``;
    provision that operator-owned boundary before each affected test without
    changing production behavior or masking tests that exercise absent roots.
    """
    path = Path(str(request.node.path))
    if path.name not in _PREPROVISIONED_ATTEMPT_ROOT_TESTS:
        return
    temporary = request.getfixturevalue("tmp_path")
    (temporary / "workspaces").mkdir(exist_ok=True)
