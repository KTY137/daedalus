# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""observe — the behavioural axis: what the code actually did, not what it declares.

Deliberately OUTSIDE ``structcore``. Getting a live object means the program ran,
and ``structcore`` is a static pass by construction. This package feeds the graph
with edges stamped ``provenance="observed"``; it is never part of an index build
and it runs only on trees the operator owns.
"""
from .shape import (ARRAY, BINARY, OPAQUE, RECORD, SCALAR, SEQUENCE, SHAPE_VERSION,
                    TABLE, TEXT, TREE, Shape, ShapeConflict, compare_declared, describe)

__all__ = ["describe", "Shape", "ShapeConflict", "compare_declared", "SHAPE_VERSION",
           "ARRAY", "TABLE", "RECORD", "SEQUENCE", "TREE", "SCALAR", "TEXT", "BINARY", "OPAQUE"]
