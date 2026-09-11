"""Console entrypoints: the commands a person types.

A module belongs here when its reader is a human at a terminal -- it owns an
``argparse`` parser and a ``main()``, and the product reaches it through a
console script or ``python -m``, not through an import. Zero importers is the
EXPECTED shape here, so the usual island signal does not apply; what is checked
instead is that a documented invocation exists.

Siblings under ``daedalus.interfaces``: ``bridge`` (file-bridge transport),
``desktop`` (the desktop runtime surface) and ``http`` (the local web API).
"""
