"""
Tracer for recording argument and return-value shapes of function calls.

Uses ``sys.settrace`` to intercept calls and returns.  When active, overhead is
high (10-100× slower for call-heavy workloads) because every Python function
call and return fires a trace event handled in pure Python.

If another tracer (``sys.gettrace()`` or ``sys.getprofile()``) is already
installed, this tracer becomes a **no-op** – the program runs normally and no
shapes are recorded.  This prevents it from fighting other profiling/tracing
tooling.
"""

import sys
from typing import Any, Dict, Set, Tuple

from .shape import Shape


class Tracer:
    """Context manager that records call shapes.

    A *record* is a (function‑name, tuple‑of‑argument‑shapes, return‑shape)
    triple.  Only distinct records are stored; a hard cap (``max_records``)
    limits the total number of distinct records.  When the cap is reached,
    further shape recording stops but the program continues to execute normally
    (tracing is disabled to avoid useless overhead).

    Guarantee
    ---------
    1. If a tracer (or profiler) is already active, ``__enter__`` does nothing
       and the context manager becomes a stub.  This avoids interfering with
       an existing measurement tool.
    2. While recording, the tracer only *reads* frame data; it never modifies
       program state or raises exceptions (shape‑computation errors are
       silently swallowed with a fallback sentinel).
    3. The stored records are accessible after the context exits via
       ``self.records`` (dict mapping function‑qualified‑name to a set of
       ``(arg_shapes, ret_shape)`` tuples).  The data is never written to
       external storage.
    """

    _sentinel = object()   # fallback when shape computation fails

    def __init__(self, max_records: int = 1000):
        """
        Parameters
        ----------
        max_records : int
            Hard limit on the number of distinct ``(arg_shapes, ret_shape)``
            combinations that will be stored (sum across all functions).
            Once exceeded, recording stops.
        """
        self._max_records = max_records
        self._records: Dict[str, Set[Tuple[Tuple[Any, ...], Any]]] = {}
        self._record_count = 0
        self._installed = False          # did we install our own trace?
        self._pending: Dict[int, Tuple[str, Tuple[Any, ...]]] = {}
        # Mutable flag – set to False once max_records is reached so that we
        # stop recording *and* remove our tracer to avoid pointless overhead.
        self._active = True

    # -- public API ----------------------------------------------------------
    @property
    def records(self):
        """Return the recorded shapes.

        Returns
        -------
        dict mapping ``str`` → ``set`` of ``(tuple of arg shapes, ret shape)``
        """
        return self._records

    def __enter__(self):
        # Degrade honestly when another tracer / profiler is already present.
        if sys.gettrace() is not None or sys.getprofile() is not None:
            self._installed = False
            return self

        self._installed = True
        sys.settrace(self._trace)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._installed:
            sys.settrace(None)            # restore to no tracer
            self._pending.clear()         # free memory
        return False                      # don’t suppress exceptions

    # -- internal trace callback --------------------------------------------
    def _trace(self, frame, event, arg):
        # If we have stopped recording (capacity reached), stop tracing
        # altogether so that the program runs at full speed again.
        if not self._active:
            return None

        if event == 'call':
            # 'call' event fired when a function is entered.
            # Extract argument names from the code object and their current
            # values from the frame locals.
            code = frame.f_code
            # co_varnames includes arguments first, then local variables.
            arg_count = code.co_argcount
            arg_names = code.co_varnames[:arg_count]
            # Build a tuple of shapes, falling back to a sentinel on error.
            try:
                arg_shapes = tuple(Shape(frame.f_locals[name])
                                   for name in arg_names)
            except Exception:
                # shape computation failed – don’t alter execution.
                arg_shapes = tuple(self._sentinel for _ in arg_names)

            # Remember the argument shapes for this frame so we can correlate
            # with the return value when the corresponding 'return' event fires.
            # We key by frame identity; CPython creates a new frame object per
            # call so id(frame) is unique for the lifetime of the call.
            func_name = code.co_qualname
            self._pending[id(frame)] = (func_name, arg_shapes)
            return self._trace          # continue intercepting inside this call

        elif event == 'return':
            # 'return' event – the frame is about to be destroyed.
            try:
                ret_shape = Shape(arg)
            except Exception:
                ret_shape = self._sentinel
            frame_entry = self._pending.pop(id(frame), None)
            if frame_entry is not None:
                func_name, arg_shapes = frame_entry
                self._store(func_name, arg_shapes, ret_shape)
            return None

        elif event == 'exception':
            # An exception was raised inside this frame – we won't get a
            # matching 'return' event, so clean up the pending entry.
            self._pending.pop(id(frame), None)
            return None

        # 'line', 'c_call', etc. – we don't need these events.
        return None

    # -- helper -------------------------------------------------------------
    def _store(self, func_name: str, arg_shapes: Tuple[Any, ...],
               ret_shape: Any) -> None:
        """Record a new combination, respecting the capacity cap."""
        if not self._active:
            return
        rec_set = self._records.setdefault(func_name, set())
        entry = (arg_shapes, ret_shape)
        if entry not in rec_set:
            if self._record_count >= self._max_records:
                # Capacity reached – stop recording and tear down tracing
                # so that we don’t impose further overhead.
                self._active = False
                self._pending.clear()
                return
            rec_set.add(entry)
            self._record_count += 1


# ----------------------------- Failing test -------------------------------
# This test demonstrates a defect: Tracer.__exit__ unconditionally sets
# sys.settrace(None) and thereby clobbers any tracing function that may
# have been installed **inside** the with-statement.  This contradicts the
# promise "does not change program behaviour".

def test_tracer_clobbers_external_trace():
    """
    The tracer claims it does not interfere with other tracing tools, but
    it fails to restore the previous trace function on exit.  If some
    cooperating code installs its own trace function while the Tracer is
    active, the context manager will wipe it out on exit, altering the
    program's behaviour.
    """
    import sys as _sys

    def dummy_trace(frame, event, arg):
        return None

    with Tracer(max_records=5):
        _sys.settrace(dummy_trace)

    # After the with-block, the trace function should still be the one we
    # installed, not None.
    assert _sys.gettrace() is dummy_trace, (
        "Tracer clobbered external trace function!\n"
        f"Expected: {dummy_trace}\nGot: {_sys.gettrace()}"
    )
