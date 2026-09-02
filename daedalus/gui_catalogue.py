"""Compatibility facade for :mod:`daedalus.orchestration.gui_catalogue`.

G1-FLAT-01 moved the implementation into ``daedalus.orchestration``. This
module preserves the flat dotted path with exact object identity and holds no
second implementation.

The re-export is a plain module-scope ``from`` import on purpose; see the note
in :mod:`daedalus.ikarus_runtime_events` for why an opaque forwarder was
rejected.

``__file__`` deliberately still points at THIS file. ``load_catalogue`` resolves
the packaged catalogue relative to the owner module's own ``__file__``, so the
packaged-resource path is unaffected -- but a test that fakes ``__file__`` or
reads module source must import the owner
(``daedalus.orchestration.gui_catalogue``), because faking it here would change
nothing the implementation reads.
"""

from .orchestration.gui_catalogue import (
    CATALOGUE_DIR,
    CATALOGUE_SCHEMA,
    Catalogue,
    CatalogueEntry,
    CatalogueError,
    DERIVED_FIELDS,
    ENTRY_KINDS,
    LICENCE_USE_MODE,
    PropSpec,
    Provenance,
    RejectedEntry,
    SearchHit,
    SearchResult,
    USE_MODES,
    load_catalogue,
    parse_entry,
    render_for_prompt,
    search,
    use_mode_for_licence,
)

__all__ = [
    "CATALOGUE_SCHEMA",
    "CATALOGUE_DIR",
    "ENTRY_KINDS",
    "USE_MODES",
    "LICENCE_USE_MODE",
    "DERIVED_FIELDS",
    "PropSpec",
    "Provenance",
    "CatalogueEntry",
    "RejectedEntry",
    "Catalogue",
    "CatalogueError",
    "SearchHit",
    "SearchResult",
    "use_mode_for_licence",
    "load_catalogue",
    "parse_entry",
    "search",
    "render_for_prompt",
]
