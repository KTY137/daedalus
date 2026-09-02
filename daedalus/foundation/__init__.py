"""Leaf utilities the rest of the tree is allowed to depend on.

WHAT BELONGS HERE. A module qualifies when it is a leaf: no ``daedalus.*``
import at all, or one that points further down into this package. That is a
measurable admission test, not a feeling about the name, and it is the reason
this package can be imported from any layer without inverting anything.

WHAT IS DELIBERATELY NOT HERE. Seven flat modules -- ``atomic``, ``budget``,
``config``, ``limit_policy``, ``primary_tree``, ``sensitivity``, ``storage`` --
are foundation by the same test but stay at the top level, because
``docs/architecture/import-boundaries.json`` names each of them by dotted path
in the ``allowed_target_prefixes`` of the kernel, spine and twin rules. Moving
them is a boundary-contract migration with its own review, not a rename. Until
that packet exists the split is real and this docstring is where it is written
down, so nobody has to rediscover it from the contract.

This package holds no policy, opens no store, and spawns nothing.
"""
