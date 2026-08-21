"""G-04: the kill-switch registry join must fail CLOSED (invariant 8).

`_ContainedProcess._register` joins the registry that
`cancel.cancel_all_managed` sweeps. Its docstring promises a loud failure,
but the body swallowed every exception — the exact failure it names (a
rename in `cancel`) silently produced the one child the kill switch cannot
reach. The register step must terminate the child and raise instead.

`_unregister` stays silent by design: failing to leave a registry on the way
out strands nothing.
"""
import sys

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("containment registry is a win32 surface", allow_module_level=True)

from daedalus.spine import cancel, containment


def _bare_process():
    proc = object.__new__(containment.ContainedProcess)
    proc.handle = 0
    proc.thread = 0
    proc.pid = -1
    proc._job = None
    proc._returncode = None
    proc._closed = True
    return proc


class _FakeKernel32:
    """Records Terminate/Close calls; never touches real handles."""

    def __init__(self, terminate_rc=1):
        self.terminate_rc = terminate_rc
        self.terminated = []
        self.closed = []

    def TerminateProcess(self, handle, code):
        self.terminated.append(getattr(handle, "value", handle))
        return self.terminate_rc

    def CloseHandle(self, handle):
        self.closed.append(getattr(handle, "value", handle))
        return 1


def test_register_fails_closed_when_registry_unavailable(monkeypatch):
    proc = _bare_process()
    monkeypatch.delattr(cancel, "_LIVE")
    with pytest.raises(RuntimeError):
        proc._register()


def test_register_failure_terminates_child_and_scrubs_handles(monkeypatch):
    # Codex finding: the first version only asserted the raise; nothing
    # proved the child was terminated or the handles retired exactly once.
    proc = _bare_process()
    proc.handle, proc.thread, proc._job = 1111, 2222, 3333
    proc._closed = False
    fake = _FakeKernel32(terminate_rc=1)
    monkeypatch.setattr(containment, "_kernel32", fake)
    monkeypatch.delattr(cancel, "_LIVE")
    with pytest.raises(RuntimeError, match="terminated"):
        proc._register()
    assert fake.terminated == [1111]
    assert sorted(fake.closed) == [1111, 2222, 3333]
    assert (proc.handle, proc.thread, proc._job) == (0, 0, None)
    assert proc._closed is True


def test_register_failure_reports_terminate_failure_and_keeps_handles(monkeypatch):
    # If TerminateProcess itself fails, the child may still be running:
    # the error must say so and the handles must stay open for a retry.
    proc = _bare_process()
    proc.handle, proc.thread, proc._job = 1111, 2222, 3333
    proc._closed = False
    fake = _FakeKernel32(terminate_rc=0)
    monkeypatch.setattr(containment, "_kernel32", fake)
    monkeypatch.delattr(cancel, "_LIVE")
    with pytest.raises(RuntimeError, match="FAILED"):
        proc._register()
    assert fake.closed == []
    assert (proc.handle, proc.thread, proc._job) == (1111, 2222, 3333)
    assert proc._closed is False


def test_register_joins_live_registry_and_unregister_leaves_it():
    proc = _bare_process()
    proc._register()
    try:
        with cancel._LIVE_LOCK:
            assert proc in cancel._LIVE
    finally:
        proc._unregister()
    with cancel._LIVE_LOCK:
        assert proc not in cancel._LIVE
