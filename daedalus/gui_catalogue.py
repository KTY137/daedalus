"""gui_catalogue -- AVAILABLE PARTS as a StructCore-shaped node kind.

WHAT THIS IS, IN ONE LINE
------------------------
``structcore/`` distils *this repo* into a searchable index.  This module
distils *the parts a GUI can be built from* into the same shape: a catalogue is
a corpus of components, searchable by what you are trying to build.  It is
DATA.  It brings no runtime, no npm package, no vendored source, and no second
ranking engine.

WHY IT IS DATA AND NOT A DEPENDENCY
-----------------------------------
``docs/ABSORPTION.md`` states the rule this module obeys verbatim: **absorb
formats and ideas, do not absorb runtimes.**  ADR-002 rejected a subsystem for
being a second scheduler beside the one that existed; ADR-017 rejected an
entire upstream for being "a second scheduler, a second ledger, a second safety
predicate, a second transcript store."  A catalogue entry is a JSON object.  It
cannot be any of those things.

The FORMAT absorbed is shadcn/ui's ``registry-item.json`` (MIT; see
``docs/GUI_CATALOGUE.md`` for the FETCHED evidence).  Its field vocabulary --
``name``/``type``/``title``/``description``/``dependencies``/
``registryDependencies``/``categories``/``docs`` -- is the closest thing the
React ecosystem has to a published schema for exactly this problem, so this
module speaks a superset of it rather than inventing a third dialect.  Two
fields are ADDED because a model cannot choose well without them and shadcn's
schema provably lacks both (MEASURED 2026-07-29 by fetching
``https://ui.shadcn.com/schema/registry-item.json``: no ``props``, no ``api``,
no licence and no provenance field exists anywhere in it):

  * ``props``     -- structured prop names and types.  shadcn carries at most a
                    ``meta.links.*.api`` URL to somebody's prose docs.
  * ``licence`` + ``provenance`` -- MANDATORY, and the reason this module has
                    a refusal path at all.

WHAT THIS MODULE REFUSES TO DO
------------------------------
* **It never decides that source may be copied.**  ``use_mode`` is DERIVED from
  the licence identifier by :data:`LICENCE_USE_MODE`, a table in *code*.  It is
  never read from an entry.  An entry that tries to declare its own
  ``use_mode`` is REFUSED -- a third party does not get to grant itself
  permission by writing a key into a JSON file this repo reads.
* **It never assumes a licence.**  An unrecognised, missing or empty licence
  identifier is ``reference_only`` at best and usually a refusal.  Default-deny,
  the same posture ``sensitivity.slice_egress_rule`` takes on egress.
  MEASURED, and this is why the rule is not theoretical: React Bits
  (reactbits.dev) ships **"MIT + Commons Clause License Condition v1.0"**, which
  GitHub's own detector reports as ``NOASSERTION``.  A reader who pattern-matched
  the string "MIT" would have copied source that its licence forbids
  redistributing.
* **It vendors nothing.**  No entry in ``catalogue/gui/`` carries a third
  party's component source.  External entries carry a name, a URL, a licence and
  a description -- the things you need to CHOOSE, not the things you need to
  ship.  ``files``/``content`` (shadcn's "main payload") is deliberately absent
  from this schema.
* **It executes nothing and imports nothing new.**  Standard library only, plus
  three in-repo modules it deliberately does not duplicate (see below).

SEARCH IS BORROWED, NOT REBUILT
-------------------------------
There is no ranking arithmetic in this file.  A sixth scoring predicate beside
BM25, DSS diffusion, cosine, ``bm25()`` and the fusion weights would be the
exact defect ADR-002 names.  So:

  * **lexical** is :func:`daedalus.context_plan.lexical_seed_scores` -- the
    repo's Okapi BM25 (k1=1.2, b=0.75), called on a *projection* of the
    catalogue into the ``{"modules": {...}}`` shape that function already
    accepts.  The projection is built by :func:`_search_key`, and what it does
    is stated plainly: an entry's searchable identity is rendered as
    path-shaped segments (name / kind / tags / purpose / prop names) so the
    ``x2`` path weighting that function already applies falls uniformly on
    every entry.  Nothing about the ranking is re-implemented or re-tuned.
  * **latent** is :class:`daedalus.memory.embeddings.EventVectorStore` --
    ``nomic-embed-text``, 768-dim, the same index machinery, the same identity
    anchor, the same drift refusal.  It is OPT-IN and defaults OFF, exactly as
    ``context_plan.plan_context(use_latent=False)`` defaults, and it degrades
    through the same :func:`~daedalus.context_plan.latent_not_requested`
    sentinel so "nobody asked" stays distinguishable from "asked and found
    nothing".
  * **fusion** is :func:`daedalus.context_plan.fuse_seed_scores` -- unchanged,
    including its ``effective_latent_weight`` honesty about a configured weight
    that carried no mass.

A CATALOGUE ENTRY IS UNTRUSTED TEXT
-----------------------------------
An entry describing a third party's component was written by that third party.
If it can reach a model prompt it is prompt injection with a filename.  This
module therefore renders prompt text through exactly one path,
:func:`render_for_prompt`, which reuses
``daedalus.council.vendors.PROMPT_DATA_NOTICE`` -- the repo's ONE such notice,
imported rather than copied, because
``docs/archive/2026-07/HANDOFF.md``'s recorded lesson is
that "a fix that lives in one of two implementations is not a closed class."
Untrusted bytes are fenced, never interpolated into an instruction position,
and each fence is labelled with the entry's origin so a reader can see whose
text it is.

The real mitigation is the same one ``council/session.py`` states: not a better
delimiter, but that (a) nothing here can act, and (b) this module has no
network, no subprocess, and no writer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .context_plan import (
    LatentSeedResult,
    LexicalSeedResult,
    fuse_seed_scores,
    latent_not_requested,
    lexical_seed_scores,
)
# Private, and imported deliberately. Max-normalisation is part of how the seed
# halves are made comparable before fusion; a second copy here would be a second
# answer to "what does a score of 1.0 mean", which is the whole objection.
from .context_plan import _normalise_max
# The repo's ONE untrusted-data notice. Imported, never re-typed: a second copy
# is a second thing to forget to fix.
from .council.vendors import PROMPT_DATA_NOTICE

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


#: Bump when the MEANING of an entry changes. Mirrors
#: ``structcore.markdown.DOCUMENT_PARSE_VERSION``'s role.
CATALOGUE_SCHEMA = "daedalus-gui-catalogue/1"

#: Where seeded catalogue files live, relative to the repo root.
CATALOGUE_DIR = "catalogue/gui"

#: What an entry IS. CLOSED -- a file may not invent a twelfth. Deliberately
#: parallel to shadcn's ``type`` enum (registry:ui / registry:component /
#: registry:hook / registry:lib / registry:block / registry:page / registry:theme
#: / registry:style / registry:file / registry:font / registry:base /
#: registry:item), reduced to the distinctions that change how a builder USES a
#: thing rather than how a CLI installs it.
ENTRY_KINDS: tuple[str, ...] = (
    "component",     # a rendered thing with props        (shadcn registry:ui)
    "layout",        # a container that arranges children (shadcn registry:block)
    "primitive",     # unstyled behaviour/accessibility   (Radix, Base UI)
    "hook",          # behaviour, renders nothing         (shadcn registry:hook)
    "token",         # a design vocabulary: durations, easings, distances
    "style",         # a stylesheet or theme layer        (shadcn registry:theme)
    # A SOURCE of parts rather than a part: an upstream library or registry.
    # The external half of this catalogue is deliberately at LIBRARY
    # granularity. Per-component external entries would mean copying a third
    # party's descriptions at scale and re-verifying them as they change --
    # which is vendoring their catalogue, one field at a time. A library entry
    # answers "where would I look, and may I copy from it", which is the
    # question a builder actually has.
    "library",
)

#: What this repo is permitted to DO with an entry's source. CLOSED, and
#: DERIVED -- see :data:`DERIVED_FIELDS`.
USE_MODES: tuple[str, ...] = (
    "copy_in",         # permissive OSI: source may be copied, attribution kept
    "reciprocal",      # copyleft: copying triggers obligations. A HUMAN decides.
    "reference_only",  # restricted / non-OSI / field-limited: NEVER copy source
)

#: Licence identifier -> what may be done with the source. THE TABLE IS THE
#: POLICY, and it lives in code so an entry cannot edit it.
#:
#: Identifiers are SPDX where an SPDX identifier honestly applies. Where a
#: project ships a modified or custom licence, the key is a NON-SPDX string
#: chosen to make that visible at a glance -- because the failure mode this
#: guards against is a reader seeing "MIT" inside a longer string and stopping
#: reading. Every mapping below was verified on 2026-07-29; the evidence and
#: the URLs are in ``docs/GUI_CATALOGUE.md``.
LICENCE_USE_MODE: Mapping[str, str] = {
    # -- permissive: copy, keep the notice ---------------------------------
    "MIT": "copy_in",
    "Apache-2.0": "copy_in",
    "BSD-2-Clause": "copy_in",
    "BSD-3-Clause": "copy_in",
    "ISC": "copy_in",
    "Unlicense": "copy_in",
    "CC0-1.0": "copy_in",
    # -- reciprocal: a human decides, per obligation -----------------------
    "MPL-2.0": "reciprocal",
    "LGPL-2.1-or-later": "reciprocal",
    "LGPL-3.0-or-later": "reciprocal",
    "GPL-2.0-or-later": "reciprocal",
    "GPL-3.0-or-later": "reciprocal",
    "AGPL-3.0": "reciprocal",
    "AGPL-3.0-or-later": "reciprocal",
    # -- restricted: name it, link it, never copy it -----------------------
    # NOT SPDX. React Bits ships "MIT + Commons Clause License Condition v1.0";
    # GitHub's own detector reports NOASSERTION. The Commons Clause forbids
    # selling/sublicensing/redistributing the components themselves, which is
    # precisely what copying them into a repo that may be redistributed does.
    "MIT-with-Commons-Clause": "reference_only",
    # NOT SPDX. Aceternity UI's own licence page: build and sell end products,
    # but no re-distribution of the Item or source files.
    "Aceternity-License": "reference_only",
    "Proprietary": "reference_only",
    # An explicit "we looked and could not establish it". Distinct from a
    # MISSING licence, which is a refusal, because "unknown" is a finding.
    "NOASSERTION": "reference_only",
}

#: Keys a catalogue FILE may not contain, because this module derives them.
#: An entry carrying one is refused rather than ignored: silently dropping a
#: field named ``use_mode`` from a file that clearly meant it to matter would
#: let a third party believe it had granted itself a permission.
DERIVED_FIELDS: frozenset[str] = frozenset({"use_mode", "usable", "vendorable"})

#: Fields every entry must carry, non-empty, or it is not loadable at all.
REQUIRED_FIELDS: tuple[str, ...] = ("name", "kind", "title", "purpose", "licence", "provenance")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,127}$")
# ISO-8601 date, the form every provenance record in this repo already uses.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CatalogueError(ValueError):
    """An entry could not be admitted to the catalogue."""


def use_mode_for_licence(licence: str) -> str:
    """What may be done with source under ``licence``.

    DEFAULT-DENY. An identifier absent from :data:`LICENCE_USE_MODE` raises --
    it does not fall back to ``reference_only``, because an unrecognised
    identifier means nobody checked, and "nobody checked" must be visible as a
    refusal rather than absorbed as a conservative-looking default.
    """
    key = (licence or "").strip()
    if not key:
        raise CatalogueError(
            "licence is required: an entry whose licence is unknown is unusable"
        )
    try:
        return LICENCE_USE_MODE[key]
    except KeyError:
        raise CatalogueError(
            f"unrecognised licence identifier {key!r}: add it to "
            "LICENCE_USE_MODE with evidence, or record it as 'NOASSERTION'. "
            "A licence this module has not been taught is never assumed to be "
            "permissive."
        ) from None


# --------------------------------------------------------------------------- #
# Data                                                                          #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PropSpec:
    """One prop. The field shadcn's registry-item schema does not have.

    ``type`` is the TypeScript type as written at the definition site, carried
    as a string rather than parsed: a model choosing a component needs to read
    ``'ik' | 'me'``, not a normalised type graph, and a parser for TypeScript
    types would be a second thing to keep correct.
    """

    name: str
    type: str
    required: bool = False
    default: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise CatalogueError("prop name must not be empty")
        if not str(self.type).strip():
            raise CatalogueError(f"prop {self.name!r} must declare a type")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "description": self.description,
        }

    def signature(self) -> str:
        mark = "" if self.required else "?"
        tail = f" = {self.default}" if self.default else ""
        return f"{self.name}{mark}: {self.type}{tail}"


@dataclass(frozen=True)
class Provenance:
    """WHERE an entry came from. Mandatory, and checked, not decorative.

    ``origin`` is the project or repository the description was taken from.
    ``url`` is where a human can go and check it.  ``retrieved`` is the date the
    facts were read, because upstream facts age -- the same discipline
    ``docs/ABSORPTION.md`` applies to every FETCHED version string.
    ``source_path`` is set only for entries whose source lives in THIS repo.
    """

    origin: str
    url: str
    retrieved: str
    source_path: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not str(self.origin).strip():
            raise CatalogueError("provenance.origin is required")
        if not str(self.url).strip():
            raise CatalogueError("provenance.url is required")
        if not _DATE_RE.match(str(self.retrieved).strip()):
            raise CatalogueError(
                "provenance.retrieved must be an ISO-8601 date (YYYY-MM-DD); "
                f"got {self.retrieved!r}"
            )

    @property
    def in_repo(self) -> bool:
        """True when the component's source is part of this repository."""
        return bool(self.source_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "url": self.url,
            "retrieved": self.retrieved,
            "source_path": self.source_path,
            "note": self.note,
        }


@dataclass(frozen=True)
class CatalogueEntry:
    """One available part.

    Construction is the first of three places an entry without a licence or
    without a provenance is refused (the others are :func:`parse_entry`, which
    never reaches the constructor for a malformed record, and
    :class:`Catalogue`, which quarantines rather than serves).  Three layers is
    not belt-and-braces: the constructor protects code that builds an entry
    directly, the parser protects the file path, and the quarantine protects a
    caller who loads a directory and iterates it.
    """

    name: str
    kind: str
    title: str
    purpose: str
    licence: str
    provenance: Provenance
    props: tuple[PropSpec, ...] = ()
    dependencies: tuple[str, ...] = ()          # npm runtime packages
    catalogue_dependencies: tuple[str, ...] = ()  # sibling entries, by name
    tags: tuple[str, ...] = ()
    usage: str = ""
    licence_url: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not _NAME_RE.match(str(self.name or "")):
            raise CatalogueError(
                f"entry name {self.name!r} must match {_NAME_RE.pattern}"
            )
        if self.kind not in ENTRY_KINDS:
            raise CatalogueError(
                f"entry {self.name!r}: kind must be one of {ENTRY_KINDS!r}, "
                f"got {self.kind!r}"
            )
        if not str(self.title).strip():
            raise CatalogueError(f"entry {self.name!r}: title is required")
        if not str(self.purpose).strip():
            raise CatalogueError(
                f"entry {self.name!r}: purpose is required -- an entry a model "
                "cannot match against a task is not a catalogue entry"
            )
        if not isinstance(self.provenance, Provenance):
            raise CatalogueError(
                f"entry {self.name!r}: provenance is required and must be a "
                "Provenance; an entry whose origin is unknown is unusable"
            )
        # Raises for a missing or unrecognised licence. This is the check that
        # makes "no licence -> unusable" true rather than promised.
        use_mode_for_licence(self.licence)

    # -- derived, never declared -------------------------------------------
    @property
    def use_mode(self) -> str:
        """What may be done with this entry's SOURCE. Derived from the licence.

        Never read from the entry file. See :data:`DERIVED_FIELDS`.
        """
        return use_mode_for_licence(self.licence)

    @property
    def vendorable(self) -> bool:
        """True only when the licence permits copying source into this repo.

        ``reciprocal`` is deliberately False: a copyleft licence does not
        forbid copying, it attaches obligations, and deciding to accept an
        obligation is a human's call and not a table lookup's.
        """
        return self.use_mode == "copy_in"

    @property
    def is_first_party(self) -> bool:
        """True when this component's source lives in this repository.

        NOT ``is_local``. In this repo "local" is a question about a HOST, and
        ``sensitivity.lane_for_host`` is its one answer; a property here wearing
        that name reads like a sixth copy of a safety predicate at a glance, and
        ``tests/test_host_predicate.py`` flags the shape on purpose.
        """
        return self.provenance.in_repo

    def signature(self) -> str:
        """The prop list as a reader would write it."""
        return ", ".join(prop.signature() for prop in self.props)

    def search_text(self) -> str:
        """Everything a lexical query should be able to match."""
        parts = [
            self.name,
            self.kind,
            self.title,
            self.purpose,
            " ".join(self.tags),
            " ".join(prop.name for prop in self.props),
        ]
        return " ".join(part for part in parts if part)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "title": self.title,
            "purpose": self.purpose,
            "licence": self.licence,
            "licence_url": self.licence_url,
            "provenance": self.provenance.to_dict(),
            "props": [prop.to_dict() for prop in self.props],
            "dependencies": list(self.dependencies),
            "catalogue_dependencies": list(self.catalogue_dependencies),
            "tags": list(self.tags),
            "usage": self.usage,
            "notes": self.notes,
            # Derived. Emitted so a consumer sees the answer, marked so nobody
            # mistakes the output for something a file may declare.
            "use_mode": self.use_mode,
            "vendorable": self.vendorable,
        }


@dataclass(frozen=True)
class RejectedEntry:
    """An entry that could not be admitted, and why.

    Rejections are RETAINED rather than dropped. A catalogue that silently
    serves nine of ten entries is indistinguishable from one that has nine, and
    the missing entry is exactly the one somebody needs to fix.
    """

    source: str
    raw_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "name": self.raw_name, "reason": self.reason}


@dataclass(frozen=True)
class Catalogue:
    """The loaded catalogue: what was admitted, and what was refused."""

    entries: tuple[CatalogueEntry, ...] = ()
    rejected: tuple[RejectedEntry, ...] = ()
    sources: tuple[str, ...] = ()
    schema: str = CATALOGUE_SCHEMA

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def by_name(self, name: str) -> CatalogueEntry | None:
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.entries)

    def first_party(self) -> tuple[CatalogueEntry, ...]:
        """Entries whose source is in this repo -- what a build should reach for."""
        return tuple(entry for entry in self.entries if entry.is_first_party)

    def vendorable(self) -> tuple[CatalogueEntry, ...]:
        return tuple(entry for entry in self.entries if entry.vendorable)

    def unresolved_dependencies(self) -> tuple[tuple[str, str], ...]:
        """(entry, missing sibling) pairs.

        Same rule ``structcore/markdown.py`` applies to links: an unresolved
        reference is reported, never guessed onto a near-match.
        """
        known = set(self.names)
        out: list[tuple[str, str]] = []
        for entry in self.entries:
            for dependency in entry.catalogue_dependencies:
                if dependency not in known:
                    out.append((entry.name, dependency))
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sources": list(self.sources),
            "entry_count": len(self.entries),
            "rejected_count": len(self.rejected),
            "entries": [entry.to_dict() for entry in self.entries],
            "rejected": [row.to_dict() for row in self.rejected],
        }


# --------------------------------------------------------------------------- #
# Parsing                                                                       #
# --------------------------------------------------------------------------- #
def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise CatalogueError(f"{label} must be a list of strings")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CatalogueError(f"{label} must contain only non-empty strings")
        out.append(item.strip())
    return tuple(out)


def _parse_props(value: Any, name: str) -> tuple[PropSpec, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CatalogueError(f"entry {name!r}: props must be a list")
    out = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise CatalogueError(f"entry {name!r}: each prop must be an object")
        unknown = set(raw) - {"name", "type", "required", "default", "description"}
        if unknown:
            raise CatalogueError(
                f"entry {name!r}: unknown prop key(s) {sorted(unknown)!r}"
            )
        out.append(PropSpec(
            name=str(raw.get("name", "")),
            type=str(raw.get("type", "")),
            required=bool(raw.get("required", False)),
            default=(str(raw["default"]) if raw.get("default") is not None else None),
            description=str(raw.get("description", "") or ""),
        ))
    return tuple(out)


def _parse_provenance(value: Any, name: str) -> Provenance:
    if not isinstance(value, Mapping):
        raise CatalogueError(
            f"entry {name!r}: provenance is required and must be an object with "
            "origin, url and retrieved"
        )
    unknown = set(value) - {"origin", "url", "retrieved", "source_path", "note"}
    if unknown:
        raise CatalogueError(
            f"entry {name!r}: unknown provenance key(s) {sorted(unknown)!r}"
        )
    source_path = value.get("source_path")
    return Provenance(
        origin=str(value.get("origin", "") or ""),
        url=str(value.get("url", "") or ""),
        retrieved=str(value.get("retrieved", "") or ""),
        source_path=(str(source_path) if source_path else None),
        note=str(value.get("note", "") or ""),
    )


_ALLOWED_KEYS = frozenset({
    "name", "kind", "title", "purpose", "licence", "licence_url", "provenance",
    "props", "dependencies", "catalogue_dependencies", "tags", "usage", "notes",
})


def parse_entry(raw: Mapping[str, Any]) -> CatalogueEntry:
    """Build one entry from a JSON object, refusing anything malformed.

    Refuses, specifically: a missing required field, an unknown key, a
    :data:`DERIVED_FIELDS` key (a file trying to grant itself a permission), a
    bad kind, a bad prop, a bad provenance, and a missing or unrecognised
    licence.
    """
    if not isinstance(raw, Mapping):
        raise CatalogueError("a catalogue entry must be a JSON object")
    name = str(raw.get("name", "") or "<unnamed>")

    declared_derived = DERIVED_FIELDS & set(raw)
    if declared_derived:
        raise CatalogueError(
            f"entry {name!r} declares derived field(s) {sorted(declared_derived)!r}. "
            "use_mode/vendorable/usable are computed from the licence by this "
            "module; an entry does not get to grant itself a permission."
        )
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise CatalogueError(f"entry {name!r}: unknown key(s) {sorted(unknown)!r}")
    for required in REQUIRED_FIELDS:
        if not raw.get(required):
            raise CatalogueError(
                f"entry {name!r}: {required!r} is required and must be non-empty"
            )

    return CatalogueEntry(
        name=str(raw["name"]).strip(),
        kind=str(raw["kind"]).strip(),
        title=str(raw["title"]).strip(),
        purpose=str(raw["purpose"]).strip(),
        licence=str(raw["licence"]).strip(),
        licence_url=str(raw.get("licence_url", "") or "").strip(),
        provenance=_parse_provenance(raw.get("provenance"), name),
        props=_parse_props(raw.get("props"), name),
        dependencies=_string_tuple(raw.get("dependencies"), f"entry {name!r}: dependencies"),
        catalogue_dependencies=_string_tuple(
            raw.get("catalogue_dependencies"), f"entry {name!r}: catalogue_dependencies"
        ),
        tags=_string_tuple(raw.get("tags"), f"entry {name!r}: tags"),
        usage=str(raw.get("usage", "") or ""),
        notes=str(raw.get("notes", "") or ""),
    )


def load_catalogue(path: str | Path | None = None) -> Catalogue:
    """Load every ``*.json`` under ``path`` (default ``catalogue/gui``).

    A file that will not parse, and an entry that will not validate, become
    :class:`RejectedEntry` rows.  They are NEVER returned as entries and are
    never searchable.  A duplicate name is a rejection too: two entries under
    one name means a caller resolving that name gets whichever loaded first,
    which is a coin flip wearing a lookup's clothes.
    """
    root = Path(path) if path is not None else Path(__file__).resolve().parent.parent / CATALOGUE_DIR
    entries: list[CatalogueEntry] = []
    rejected: list[RejectedEntry] = []
    sources: list[str] = []
    seen: dict[str, str] = {}

    if not root.exists():
        return Catalogue((), (), ())

    for file in sorted(root.glob("*.json")):
        label = file.name
        sources.append(label)
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            rejected.append(RejectedEntry(label, "<file>", f"unreadable: {exc}"))
            continue
        if isinstance(payload, Mapping):
            records = payload.get("entries")
        else:
            records = payload
        if not isinstance(records, list):
            rejected.append(RejectedEntry(
                label, "<file>",
                "expected a JSON list of entries, or an object with an 'entries' list",
            ))
            continue
        for record in records:
            raw_name = ""
            if isinstance(record, Mapping):
                raw_name = str(record.get("name", "") or "")
            try:
                entry = parse_entry(record)
            except CatalogueError as exc:
                rejected.append(RejectedEntry(label, raw_name or "<unnamed>", str(exc)))
                continue
            if entry.name in seen:
                rejected.append(RejectedEntry(
                    label, entry.name,
                    f"duplicate name; already defined in {seen[entry.name]}",
                ))
                continue
            seen[entry.name] = label
            entries.append(entry)

    entries.sort(key=lambda item: item.name)
    return Catalogue(tuple(entries), tuple(rejected), tuple(sources))


# --------------------------------------------------------------------------- #
# Search -- borrowed whole, tuned nowhere                                       #
# --------------------------------------------------------------------------- #
def _search_key(entry: CatalogueEntry) -> str:
    """Project one entry into the path-shaped document key BM25 already accepts.

    ``lexical_seed_scores`` builds its document from the module key's terms
    (weighted x2) plus symbol names from a StructCore resolver.  A catalogue has
    no resolver, so the entry's whole searchable text is carried in the key.
    The ``/`` separators are cosmetic -- ``context_plan._terms`` splits on every
    non-alphanumeric anyway -- and the x2 weighting therefore falls uniformly on
    every entry, which leaves the RELATIVE ranking exactly as that function
    computes it.  Nothing here re-implements or re-tunes the ranking.
    """
    return "/".join(part for part in entry.search_text().split() if part)


def _lexical(catalogue: Catalogue, objective: str, limit: int) -> tuple[LexicalSeedResult, dict[str, str]]:
    """BM25 over the projected catalogue, via the repo's one implementation."""
    key_to_name: dict[str, str] = {}
    modules: dict[str, dict[str, Any]] = {}
    for entry in catalogue.entries:
        key = _search_key(entry)
        # A collision would silently merge two entries into one document.
        while key in key_to_name:
            key = key + "/~"
        key_to_name[key] = entry.name
        modules[key] = {"language": entry.kind}
    index = {"modules": modules, "root": "", "scope_key": None}
    return lexical_seed_scores(index, objective, limit=max(1, limit)), key_to_name


def _latent(
    catalogue: Catalogue,
    objective: str,
    *,
    limit: int,
    db_path: Any,
    host: str,
    model: str,
    backend: Any,
) -> LatentSeedResult:
    """Optional semantic half, on the repo's one embedding index.

    Mirrors ``context_plan.latent_memory_seed_scores`` in shape and in failure
    behaviour: a corrupt, absent or drifted index must not take down the search
    the caller asked for, but it must be NAMED in the result rather than read as
    "found nothing".
    """
    # Imported lazily: the lexical path must stay usable on a box with no
    # vector database and no embedder, and importing the store eagerly would
    # make an optional half a hard requirement of the module.
    from .memory import VECTOR_DB_PATH
    from .memory.embeddings import EMBED_MODEL, EventVectorStore

    resolved_db = VECTOR_DB_PATH if db_path is None else db_path
    resolved_model = EMBED_MODEL if model is None else model
    path = Path(resolved_db) if str(resolved_db) != ":memory:" else None
    if backend is None and path is not None and not path.exists():
        return LatentSeedResult(
            "not_configured",
            f"vector index does not exist: {path}",
            {}, (), requested=True, consulted=False,
        )

    by_name = {entry.name: entry for entry in catalogue.entries}
    consulted = False
    try:
        store = EventVectorStore(resolved_db, backend=backend)
        try:
            if not store.list_indexes():
                return LatentSeedResult(
                    "index_unavailable",
                    "no versioned projections are available for the catalogue",
                    {}, (), requested=True, consulted=False,
                )
            consulted = True
            report = store.search_report(
                objective, limit=max(1, limit), host=host, model=resolved_model,
            )
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        return LatentSeedResult(
            "error",
            f"latent catalogue lookup failed: {type(exc).__name__}: {exc}",
            {}, (), requested=True, consulted=consulted,
        )

    if not report.status.available:
        return LatentSeedResult(
            report.status.code, report.status.message, {}, (),
            report.status.index_id, requested=True, consulted=True,
        )

    scores: dict[str, float] = {}
    mapped: list[Mapping[str, Any]] = []
    for event, raw_score in report.matches:
        # Clamped, not computed: the store did the scoring. Clamping only keeps
        # a float error at the boundary from leaving [0, 1].
        score = max(0.0, min(1.0, float(raw_score)))
        if score <= 0:
            continue
        # Same discipline as the latent seed mapper: a hit counts only when it
        # names a catalogue entry EXPLICITLY. No fuzzy mapping back.
        name = str((event.metadata or {}).get("catalogue_entry") or "")
        if name not in by_name:
            continue
        scores[name] = max(scores.get(name, 0.0), score)
        mapped.append({"event_id": event.event_id, "score": score, "entry": name})

    return LatentSeedResult(
        "ready",
        f"mapped {len(mapped)} of {len(report.matches)} projection hits to catalogue entries",
        _normalise_max(scores), tuple(mapped), report.status.index_id,
        requested=True, consulted=True, candidates=len(report.matches),
    )


@dataclass(frozen=True)
class SearchHit:
    entry: CatalogueEntry
    score: float


@dataclass(frozen=True)
class SearchResult:
    """Ranked entries plus the receipt for how they were ranked."""

    objective: str
    hits: tuple[SearchHit, ...]
    lexical: LexicalSeedResult
    latent: LatentSeedResult
    latent_weight: float
    latent_applied: bool
    schema: str = CATALOGUE_SCHEMA

    @property
    def entries(self) -> tuple[CatalogueEntry, ...]:
        return tuple(hit.entry for hit in self.hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "objective": self.objective,
            "hits": [
                {"name": hit.entry.name, "score": round(hit.score, 6),
                 "use_mode": hit.entry.use_mode, "licence": hit.entry.licence}
                for hit in self.hits
            ],
            "seeds": {
                "lexical": self.lexical.to_dict(),
                "latent": self.latent.to_dict(),
                "latent_weight": self.latent_weight,
                "latent_applied": self.latent_applied,
            },
        }


def search(
    catalogue: Catalogue,
    objective: str,
    *,
    limit: int = 8,
    kinds: Sequence[str] | None = None,
    first_party_only: bool = False,
    use_latent: bool = False,
    vector_db: Any = None,
    embedding_host: str | None = None,
    embedding_model: str | None = None,
    embedding_backend: Any = None,
) -> SearchResult:
    """Rank catalogue entries against a plain-language objective.

    Lexical BM25 always; latent embeddings only when ``use_latent`` is True, and
    fused by ``context_plan.fuse_seed_scores``.  No ranking arithmetic lives in
    this module.

    Quarantined entries are unreachable here by construction: this function only
    ever sees ``catalogue.entries``, and :func:`load_catalogue` never puts an
    entry that failed validation into that tuple.
    """
    objective = (objective or "").strip()
    if not objective:
        raise ValueError("objective must not be empty")
    if limit < 1:
        raise ValueError("limit must be positive")

    selected = catalogue.entries
    if kinds is not None:
        allowed = set(kinds)
        unknown = allowed - set(ENTRY_KINDS)
        if unknown:
            raise ValueError(f"unknown kind(s) {sorted(unknown)!r}")
        selected = tuple(entry for entry in selected if entry.kind in allowed)
    if first_party_only:
        selected = tuple(entry for entry in selected if entry.is_first_party)
    scoped = Catalogue(selected, catalogue.rejected, catalogue.sources)

    lexical, key_to_name = _lexical(scoped, objective, limit=max(limit * 4, 32))
    if use_latent:
        from .providers.ollama import DEFAULT_HOST
        latent = _latent(
            scoped, objective, limit=max(limit * 4, 32), db_path=vector_db,
            host=embedding_host or DEFAULT_HOST, model=embedding_model,
            backend=embedding_backend,
        )
    else:
        latent = latent_not_requested()

    # Re-key the lexical scores onto entry names BEFORE fusing, so both halves
    # of the fusion speak the same identifier.
    renamed = LexicalSeedResult(
        scores={key_to_name[key]: value for key, value in lexical.scores.items()},
        query_terms=lexical.query_terms,
        matched_terms={
            key_to_name[key]: value for key, value in lexical.matched_terms.items()
        },
        projector_version=lexical.projector_version,
    )
    fused = fuse_seed_scores(renamed, latent)

    by_name = {entry.name: entry for entry in scoped.entries}
    ranked = sorted(fused.scores.items(), key=lambda item: (-item[1], item[0]))
    hits = tuple(
        SearchHit(by_name[name], score)
        for name, score in ranked[:limit]
        if name in by_name
    )
    return SearchResult(
        objective=objective, hits=hits, lexical=renamed, latent=latent,
        latent_weight=fused.latent_weight, latent_applied=fused.latent_applied,
    )


# --------------------------------------------------------------------------- #
# The only path to a model prompt                                               #
# --------------------------------------------------------------------------- #
#: Opens a fence around one entry's untrusted bytes. The origin is in the
#: opening line so a reader can see WHOSE text follows.
_FENCE_OPEN = "<<<CATALOGUE_ENTRY name={name} origin={origin} licence={licence}"
_FENCE_CLOSE = ">>>END_CATALOGUE_ENTRY"


def render_for_prompt(entries: Iterable[CatalogueEntry], *, header: str = "") -> str:
    """Render entries as DATA for a model prompt.

    THE ONLY path from a catalogue to a prompt, so the notice cannot be skipped
    by a caller who forgot.  Shape and reasoning are ``council/session.py``'s,
    not a new idiom:

      1. session-authored instruction text first (the ``header`` and the
         notice), so the untrusted bytes never occupy an instruction position;
      2. ``PROMPT_DATA_NOTICE`` -- imported from ``council/vendors.py``, the
         repo's one such notice -- next;
      3. only then untrusted bytes, each inside a fence labelled with the
         entry's origin and licence.

    As ``council/vendors.py`` says in place: the mitigation is not a better
    delimiter.  It is that an injection attempt becomes a FINDING, and that
    nothing reachable from here can act.
    """
    lines: list[str] = []
    if header.strip():
        lines.append(header.strip())
    lines.append(PROMPT_DATA_NOTICE)
    lines.append(
        "Each entry below is a THIRD-PARTY DESCRIPTION of an available UI part. "
        "Its origin and licence are on the fence line. An entry whose use_mode "
        "is 'reference_only' or 'reciprocal' MUST NOT have its source copied: "
        "name it and link it."
    )
    for entry in entries:
        lines.append(_FENCE_OPEN.format(
            name=entry.name, origin=entry.provenance.origin, licence=entry.licence,
        ))
        lines.append(f"title: {entry.title}")
        lines.append(f"kind: {entry.kind}    use_mode: {entry.use_mode}")
        lines.append(f"purpose: {entry.purpose}")
        if entry.props:
            lines.append(f"props: {entry.signature()}")
        if entry.dependencies:
            lines.append(f"npm dependencies: {', '.join(entry.dependencies)}")
        if entry.provenance.source_path:
            lines.append(f"source in this repo: {entry.provenance.source_path}")
        lines.append(f"source of record: {entry.provenance.url}")
        if entry.usage:
            lines.append("usage:")
            lines.append(entry.usage)
        if entry.notes:
            lines.append(f"notes: {entry.notes}")
        lines.append(_FENCE_CLOSE)
    return "\n".join(lines)
