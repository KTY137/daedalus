from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _compat_prepare_original_primary_fingerprint_fixture(request, tmp_path) -> None:
    """Temporary test-only bridge until the superseded fixture file is removed.

    The first draft of the fingerprint test passed ``tmp_path / 'unstable'`` to
    a helper that expected its parent to exist. Restrict this compatibility
    setup to that exact historical test module; the reviewed v2 fixture creates
    its own parents and does not depend on this bridge.
    """
    if request.node.path.name == "test_primary_checkout_fingerprint.py":
        (tmp_path / "unstable").mkdir(exist_ok=True)
