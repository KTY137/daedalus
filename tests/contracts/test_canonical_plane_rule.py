"""One canonical answer to "which plane does this artifact belong to?".

`G2_TYPE_PLANE_DECISION_20260909.md` measured four incompatible Type-plane
rules in this repository, disagreeing from 0 % to 100 % coverage of the same
corpus' declared type information, and named
`daedalus/twin/extractors/registry.py::LANGUAGE_SPECS` canonical.

This file is what makes that a decision rather than a document. Plan Invariant 1
and `AGENTS.md` §3 both require one canonical path per responsibility; a second
plane rule appearing in production, or the canonical assignments changing
without the decision being revisited, should fail here.

What it deliberately does NOT do: police the two experiment-local rules
(`PLANE_BY_SUFFIX`, `infer_plane`). Those keep their measurements and their
scope. Rewriting an experiment's plane rule after its results are published
would invalidate them, which the frozen criterion forbade.
"""
from __future__ import annotations

from daedalus.twin.contracts import FOURFOLD_PLANES
from daedalus.twin.extractors.registry import LANGUAGE_SPECS, detect_language

CANONICAL_MODULE = "daedalus.twin.extractors.registry"


def _planes_for(path: str) -> frozenset[str]:
    detection = detect_language(path)
    if detection is None:
        return frozenset()
    for spec in LANGUAGE_SPECS:
        if spec.language_id == detection.language_id:
            return frozenset(spec.semantic_planes)
    return frozenset()


# --------------------------------------------------------------------------
# the rule is a rule about the plan's planes
# --------------------------------------------------------------------------
def test_every_declared_plane_is_a_plan_plane() -> None:
    """No spec may mint a plane the four-plane contract does not define.

    `PLANE_BY_SUFFIX` has a `presentation` plane that plan §5 does not define.
    That is tolerable in an experiment and would not be in the canonical rule.
    """
    known = set(FOURFOLD_PLANES)
    for spec in LANGUAGE_SPECS:
        unknown = set(spec.semantic_planes) - known
        assert not unknown, f"{spec.language_id} declares non-plan planes {unknown}"


def test_the_type_plane_has_members() -> None:
    """Coverage 0 was a pre-registered disqualifier; it must stay non-zero."""
    typed = [s.language_id for s in LANGUAGE_SPECS if "type" in s.semantic_planes]
    assert typed, "the canonical rule must assign at least one language to type"


def test_the_type_plane_is_a_proper_subset() -> None:
    """Discrimination 100 % was the other disqualifier.

    A rule that puts every language in the Type plane partitions nothing, and
    ablating it would ablate the whole corpus.
    """
    typed = [s for s in LANGUAGE_SPECS if "type" in s.semantic_planes]
    assert len(typed) < len(LANGUAGE_SPECS), "the Type plane must exclude something"


# --------------------------------------------------------------------------
# the assignments the decision was measured against
# --------------------------------------------------------------------------
def test_python_is_both_code_and_type() -> None:
    """The multi-plane membership the decision turns on.

    100 % coverage on all three measured subjects follows from exactly this:
    every annotation lives in a code file, and this is the only rule that says
    a code file is also a type file.
    """
    assert _planes_for("pkg/mod.py") == frozenset({"code", "type"})
    assert _planes_for("pkg/mod.pyi") == frozenset({"code", "type"})


def test_a_json_schema_is_data_not_type() -> None:
    """Measured three times independently, against my own earlier refinement.

    `G2-TYPEPLANE-01` proposed `.schema.json -> type` and it was withdrawn: the
    fixture manifest, `PLANE_BY_SUFFIX` and this registry all say `data`.
    """
    assert _planes_for("schemas/event.schema.json") == frozenset({"data"})


def test_markdown_is_knowledge_only() -> None:
    assert _planes_for("docs/readme.md") == frozenset({"knowledge"})


def test_an_unknown_suffix_claims_no_plane() -> None:
    """Silence, not a guess. A rule that assigns a plane to everything cannot
    be wrong, and cannot be useful either."""
    assert _planes_for("build/artifact.bin") == frozenset()
    assert _planes_for("Makefile.unknownsuffix") == frozenset()


# --------------------------------------------------------------------------
# one canonical path
# --------------------------------------------------------------------------
def test_production_has_exactly_one_plane_rule() -> None:
    """A second production plane oracle is the defect this test exists for.

    Searched over `daedalus/` only: the two experiment rules live under
    `experiments/` and keep their scope by design.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "daedalus"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        # A module that both names the planes and maps suffixes to them is a
        # plane rule. The canonical one is allowed to be exactly that.
        if "semantic_planes" in text and path.name != "registry.py":
            if "LanguageSpec(" in text or "PLANE_BY_SUFFIX" in text:
                offenders.append(str(path.relative_to(root)))
    assert not offenders, (
        "a second production plane rule appeared; the canonical one is "
        f"{CANONICAL_MODULE}: {offenders}"
    )
