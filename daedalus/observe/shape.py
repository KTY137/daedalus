# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""shape.py — what a debug console shows, recorded as data instead of printed.

THE THING THIS CAPTURES
-----------------------
A declaration says ``def load(p: str) -> Run``. A checker can sometimes prove a
little more. Neither can tell you what you see the moment you stop in a debugger:

    ndarray  float64  (1000, 3)  C-contiguous  24.0 KiB
    DataFrame  4821 x 6  [run, voltage, current, temp, mask, weight]
    dict  7 keys  [modules, import_edges, duplication, fan_in, …]

That is the **shape of a live object**, and for this repo it dissolves a named
blindness: ``structcore``'s own index travels as a bare ``dict``, so the most
important data structure in the tree is invisible to any declaration-level pass.
One observed instance names its real keys.

THE RULE THAT MAKES THIS SAFE: SHAPE, NEVER VALUE
-------------------------------------------------
Nothing here reads an element, a cell, a row or a scalar payload. It records
metadata — concrete class, dtype, shape, strides, contiguity, byte size, and
KEY or COLUMN NAMES. Three independent reasons, all of which have bitten
somebody:

* a value can be gigabytes, and an observer that copies data is a memory bug;
* a value can be a secret, and this repo's whole egress posture is built on not
  moving those;
* the graph does not want the value. It wants the shape.

Even names are not automatically safe — a column called ``patient_id`` is a
disclosure. So ``describe`` takes a ``redact`` hook, and the caller that ships an
observation anywhere near a model is expected to pass one. This module owns no
policy about what is sensitive; ``daedalus.sensitivity`` does, and the two are
kept apart on purpose.

WHY THIS IS NOT IN ``structcore``
---------------------------------
Because getting a live object means the program RAN. ``structcore`` is a static
pass by construction and ``daedalus/tools/vet.py`` states the rule outright: you
run untrusted code to decide anything about it. So observation is a separate,
opt-in lane that *feeds* the graph with edges stamped ``provenance=observed`` —
it is never part of an index build, and it runs only on trees the operator owns.

AND AN OBSERVATION IS A SAMPLE, NOT A PROOF
-------------------------------------------
``(1000, 3)`` is the shape this input produced. It is not the shape the function
requires. A field never seen is not a field that cannot appear. Every record
carries ``provenance="observed"`` and the run it came from, and any consumer that
reports it as a fact is wrong — the same discipline ``eval/ceiling.py`` applies
when it separates its clean arm from its leaky one.

Duck-typed throughout: numpy, pandas, h5py and uproot are probed by attribute,
never imported. A tree without them degrades to the generic families and says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SHAPE_VERSION = "1"

#: Bounds. A dict with 40 000 keys is described by its first ``MAX_NAMES`` and a
#: count, never by all of them: an unbounded descriptor is how an observer
#: becomes the memory problem it was meant to diagnose.
MAX_NAMES = 64
MAX_NAME_CHARS = 80
MAX_DEPTH = 3

#: Families, coarse on purpose. The point is a stable vocabulary the graph can
#: join on, not a taxonomy of every library in the world.
ARRAY = "array"          # ndarray, torch tensor, anything with dtype+shape
TABLE = "table"          # DataFrame, Arrow table, recarray
RECORD = "record"        # dict, dataclass instance, namespace
SEQUENCE = "sequence"    # list, tuple, set
TREE = "tree"            # ROOT TTree / uproot / HDF5 group
SCALAR = "scalar"
TEXT = "text"
BINARY = "binary"
OPAQUE = "opaque"        # we could not characterise it, and we say so


def _attr(obj, name, default):
    """Attribute or default, WITHOUT using truthiness.

    ``getattr(obj, "columns", ()) or ()`` looks harmless and raises on a pandas
    Index, whose ``__bool__`` refuses to answer. Any observer that touches
    array-likes has to fetch attributes without asking whether they are truthy.
    """
    v = getattr(obj, name, None)
    return default if v is None else v


def _clip(name) -> str:
    s = str(name)
    return s if len(s) <= MAX_NAME_CHARS else s[: MAX_NAME_CHARS - 1] + "…"


def _qualname(obj) -> str:
    t = type(obj)
    mod = getattr(t, "__module__", "") or ""
    name = getattr(t, "__qualname__", None) or getattr(t, "__name__", "?")
    return f"{mod}.{name}" if mod and mod != "builtins" else str(name)


def _human_bytes(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n / 1:.1f} {unit}"
        n /= 1024.0
    return ""


@dataclass(frozen=True)
class Shape:
    """One observation of one live object. Metadata only."""
    family: str
    type_name: str                     # the CONCRETE class, e.g. numpy.ndarray
    dtype: str = ""
    dims: tuple[int, ...] = ()
    names: tuple[str, ...] = ()        # keys / columns, bounded
    n_names: int = 0                   # the true count, even when names are clipped
    nbytes: int = 0
    layout: str = ""                   # C-contiguous / F-contiguous / strided
    length: int = -1                   # -1 when the object has no length
    element: "Shape | None" = None     # one probe of a homogeneous container
    truncated: bool = False
    note: str = ""
    provenance: str = "observed"

    def to_dict(self) -> dict:
        d = {"family": self.family, "type": self.type_name, "provenance": self.provenance}
        if self.dtype:
            d["dtype"] = self.dtype
        if self.dims:
            d["dims"] = list(self.dims)
        if self.names:
            d["names"] = list(self.names)
        if self.n_names:
            d["n_names"] = self.n_names
        if self.nbytes:
            d["nbytes"] = self.nbytes
        if self.layout:
            d["layout"] = self.layout
        if self.length >= 0:
            d["length"] = self.length
        if self.element is not None:
            d["element"] = self.element.to_dict()
        if self.truncated:
            d["truncated"] = True
        if self.note:
            d["note"] = self.note
        return d

    def signature(self) -> str:
        """A stable one-line form, for comparing two observations or joining an
        observation against a declared type. Deterministic: names are already in
        a fixed order and nothing here consults a hash seed."""
        bits = [self.family, self.type_name]
        if self.dtype:
            bits.append(self.dtype)
        if self.dims:
            bits.append("x".join(str(d) for d in self.dims))
        if self.names:
            bits.append("[" + ",".join(self.names) + ("…]" if self.truncated else "]"))
        elif self.length >= 0:
            bits.append(f"len={self.length}")
        return " ".join(bits)

    def render(self) -> str:
        """The debug-console line this record stands in for."""
        out = [self.type_name]
        if self.dtype:
            out.append(self.dtype)
        if self.dims:
            out.append("(" + ", ".join(str(d) for d in self.dims) + ")")
        elif self.length >= 0:
            out.append(f"len {self.length}")
        if self.layout:
            out.append(self.layout)
        if self.nbytes:
            out.append(_human_bytes(self.nbytes))
        if self.names:
            shown = ", ".join(self.names)
            out.append(f"[{shown}{', …' if self.truncated else ''}]")
        return "  ".join(out)


def _names_of(seq) -> tuple[tuple[str, ...], int, bool]:
    """Bounded, order-preserving name extraction with the TRUE count kept."""
    try:
        items = list(seq)
    except Exception:
        return (), 0, False
    total = len(items)
    shown = tuple(_clip(x) for x in items[:MAX_NAMES])
    return shown, total, total > MAX_NAMES


def _layout_of(obj) -> str:
    flags = getattr(obj, "flags", None)
    if flags is None:
        return ""
    try:
        if getattr(flags, "c_contiguous", False):
            return "C-contiguous"
        if getattr(flags, "f_contiguous", False):
            return "F-contiguous"
        return "strided"
    except Exception:
        return ""


def describe(obj, *, depth: int = 0, redact=None) -> Shape:
    """Describe one live object's SHAPE. Never reads a value.

    ``redact`` is called on every key/column name before it is stored and may
    return a replacement. Pass one whenever the observation could reach a model
    or leave the machine — a column name is data too.
    """
    red = redact or (lambda s: s)
    tname = _qualname(obj)

    # ── array-likes: dtype + shape + layout, the debugger's core line ────────
    if hasattr(obj, "dtype") and hasattr(obj, "shape") and not hasattr(obj, "columns"):
        try:
            dims = tuple(int(d) for d in tuple(obj.shape))
        except Exception:
            dims = ()
        dt = getattr(obj, "dtype", "")
        # A structured dtype IS a schema — surface its fields like columns.
        fields = getattr(dt, "names", None)
        names, n_names, trunc = ((), 0, False)
        if fields:
            names, n_names, trunc = _names_of(red(f) for f in fields)
        return Shape(ARRAY, tname, dtype=str(dt), dims=dims, names=names,
                     n_names=n_names, nbytes=int(_attr(obj, "nbytes", 0)),
                     layout=_layout_of(obj), truncated=trunc,
                     note="structured dtype" if fields else "")

    # ── tables: columns are the schema ───────────────────────────────────────
    if hasattr(obj, "columns"):
        names, n_names, trunc = _names_of(red(c) for c in _attr(obj, "columns", ()))
        dims: tuple[int, ...] = ()
        try:
            dims = tuple(int(d) for d in tuple(_attr(obj, "shape", ())))
        except Exception:
            pass
        dtypes = getattr(obj, "dtypes", None)
        dt = ""
        if dtypes is not None:
            try:
                uniq = sorted({str(v) for v in list(dtypes)})
                dt = ", ".join(uniq[:6]) + ("…" if len(uniq) > 6 else "")
            except Exception:
                dt = ""
        nb = 0
        try:                                    # pandas: cheap, metadata-level
            nb = int(obj.memory_usage(deep=False).sum())
        except Exception:
            nb = int(_attr(obj, "nbytes", 0))
        return Shape(TABLE, tname, dtype=dt, dims=dims, names=names,
                     n_names=n_names, nbytes=nb, truncated=trunc)

    # ── ROOT / HDF5 trees and groups ─────────────────────────────────────────
    for attr in ("keys",):
        if hasattr(obj, attr) and (hasattr(obj, "num_entries") or hasattr(obj, "GetEntries")
                                   or type(obj).__module__.split(".")[0] in ("h5py", "uproot")):
            try:
                names, n_names, trunc = _names_of(red(k) for k in list(obj.keys()))
            except Exception:
                names, n_names, trunc = (), 0, False
            n = getattr(obj, "num_entries", None)
            if n is None and hasattr(obj, "GetEntries"):
                try:
                    n = obj.GetEntries()
                except Exception:
                    n = None
            return Shape(TREE, tname, names=names, n_names=n_names,
                         length=int(n) if isinstance(n, int) else -1, truncated=trunc,
                         note="entry count is metadata; no entry was read")

    # ── mappings: the keys ARE the discovery ─────────────────────────────────
    if isinstance(obj, dict):
        names, n_names, trunc = _names_of(red(k) for k in list(obj.keys()))
        el = None
        if depth < MAX_DEPTH and obj:
            first = next(iter(obj.values()))
            el = describe(first, depth=depth + 1, redact=redact)
        return Shape(RECORD, tname, names=names, n_names=n_names,
                     length=len(obj), element=el, truncated=trunc,
                     note="keys only; no value was recorded")

    # ── dataclasses and simple namespaces ────────────────────────────────────
    df = getattr(type(obj), "__dataclass_fields__", None)
    if df is not None:
        names, n_names, trunc = _names_of(red(k) for k in df)
        return Shape(RECORD, tname, names=names, n_names=n_names, truncated=trunc,
                     note="dataclass fields")
    slots = getattr(type(obj), "__slots__", None)
    if slots:
        names, n_names, trunc = _names_of(red(s) for s in slots)
        return Shape(RECORD, tname, names=names, n_names=n_names, truncated=trunc,
                     note="__slots__")

    # ── sequences: length plus ONE element probe ─────────────────────────────
    if isinstance(obj, (list, tuple, set, frozenset)):
        el = None
        if depth < MAX_DEPTH and len(obj):
            el = describe(next(iter(obj)), depth=depth + 1, redact=redact)
        return Shape(SEQUENCE, tname, length=len(obj), element=el,
                     note="one element probed; the container may be heterogeneous")

    if isinstance(obj, (str, bytes, bytearray)):
        fam = TEXT if isinstance(obj, str) else BINARY
        return Shape(fam, tname, length=len(obj),
                     note="length only; no content recorded")

    if isinstance(obj, (bool, int, float, complex)) or obj is None:
        return Shape(SCALAR, tname)

    # ── give up honestly ─────────────────────────────────────────────────────
    return Shape(OPAQUE, tname, note="no shape could be characterised for this type")


# --------------------------------------------------------------------------- #
# Joining an observation to a declaration                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ShapeConflict:
    """Where a declared shape and an observed one disagree.

    ``missing_in_observation`` is the softest signal — these inputs did not
    exercise that field. ``undeclared_in_observation`` is the sharp one: the
    object carries something the code never declared, so the declaration is
    incomplete or the payload has undocumented shape.
    """
    subject: str
    declared_from: str
    observed_signature: str
    matched: tuple[str, ...] = ()
    missing_in_observation: tuple[str, ...] = ()
    undeclared_in_observation: tuple[str, ...] = ()
    comparable: bool = True
    reason: str = ""
    notes: tuple[str, ...] = ()

    @property
    def agrees(self) -> bool:
        return self.comparable and not self.undeclared_in_observation

    def to_dict(self) -> dict:
        return {"subject": self.subject, "declared_from": self.declared_from,
                "observed": self.observed_signature, "comparable": self.comparable,
                "agrees": self.agrees, "reason": self.reason,
                "matched": list(self.matched),
                "missing_in_observation": list(self.missing_in_observation),
                "undeclared_in_observation": list(self.undeclared_in_observation),
                "notes": list(self.notes)}


def compare_declared(shape: Shape, declared_names, *, subject: str = "",
                     declared_from: str = "") -> ShapeConflict:
    """Compare an observation against declared field names.

    Refuses to compare rather than manufacturing findings: an observation with no
    names (a scalar, an unstructured array, an opaque object) is
    ``comparable=False`` with a reason. Reporting every declared field as
    "missing" because the observation carries no names at all would turn "we
    learned nothing here" into a wall of false positives.
    """
    declared = tuple(sorted({str(n) for n in (declared_names or ())}))
    if not declared:
        return ShapeConflict(subject, declared_from, shape.signature(),
                             comparable=False, reason="nothing was declared")
    if not shape.names:
        return ShapeConflict(subject, declared_from, shape.signature(),
                             comparable=False,
                             reason=f"the observation carries no field names "
                                    f"({shape.family}: {shape.note or 'no names'})")
    notes: list[str] = []
    if shape.truncated:
        notes.append(f"observation listed {len(shape.names)} of {shape.n_names} names; "
                     "'missing' below cannot be trusted while the list is clipped")
    have = set(shape.names)
    missing = tuple(n for n in declared if n not in have)
    return ShapeConflict(
        subject=subject, declared_from=declared_from,
        observed_signature=shape.signature(),
        matched=tuple(n for n in declared if n in have),
        missing_in_observation=() if shape.truncated else missing,
        undeclared_in_observation=tuple(sorted(have - set(declared))),
        notes=tuple(notes),
    )
