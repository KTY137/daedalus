"""Tests for ``daedalus.wiki.verify`` -- the half of wiki generation that a
model does not get a vote in.

The module went from 4046 findings to 0 on ``project_tct`` in one afternoon
(2026-08-25). Almost all of that drop was correct: four classes of false
positive were removed. But "the number went to zero" is also the shape of a
result produced by an instrument that stopped looking, and here it was both:
the widened vocabulary was built by reading *every* file under the root --
including the wiki pages themselves, and including the verifier's own report
from the previous run under ``runs/``. A page therefore supplied the evidence
that cleared its own claims, and ``unknown_symbol`` could only fire when a page
happened to be named after the symbol it invented.

That hole was found from these tests, confirmed independently, and closed the
same day: ``exclusions()`` is computed once in ``verify`` and passed to all
three evidence sources, so the checked set may not vouch for itself. The tests
below pin both directions of the result:

* **six positives** -- every finding kind the verifier can emit is fired once,
  so no future narrowing can silently retire a check;
* **four regressions** -- the false-positive classes measured on 2026-08-25
  (builtins, imported foreign names, backticked filenames, ``self``
  attributes), each with a positive control in the same fixture, so that
  "nothing was flagged" cannot come from a fixture that could not have flagged
  anything;
* **three placements of the NAME** -- an invented name is caught wherever it is
  written down;
* **twelve placements of the EVIDENCE** -- eight that must not vouch, four that
  must, because a rule enforced in one of three sources is a hole with a
  docstring;
* **the SYMBOL_SHAPE boundary**, **the verdict rule**, and **truncation per
  kind** -- the instrument has to say how much it did not show.

WHAT THIS CHECK COSTS IN THE FIELD, MEASURED
--------------------------------------------
On ``project_tct`` after the fix: 4 ``unknown_symbol`` findings over 37 pages
and 1413 concepts, and all four are false positives of one shape --
``E_puls``, ``Q_ref_i``, ``R_term``, ``_um``, formula symbols and a suffix
convention written in German prose inside backticks. ``SYMBOL_SHAPE`` admits
them through its underscore branch. The most instructive is ``R_term``: the
page introduces it as the prose name for the real config key
``termination_ohm``, so reporting it penalises good documentation rather than
catching a false claim. A predicted flood of the ``NaN``/``IDs``/``kHz`` shape
did NOT materialise -- that prediction was an extrapolation from a three-word
fixture, and the field refuted it. Whether the residual four earn a declared
stoplist is follow-up work, deliberately not decided by these tests.

Nothing here assumes the vocabulary contains only Python names --
``tree_vocabulary`` is deliberately wider and takes QML and JS names too. The
fixtures assert on findings, never on the size or membership of the
vocabulary.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from daedalus.wiki import verify as wiki_verify


# --------------------------------------------------------------------------
# fixture helpers -- everything lives under tmp_path, LF, nothing else touched
# --------------------------------------------------------------------------

def _write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _repo(tmp_path: pathlib.Path, files: dict, name: str = "repo") -> pathlib.Path:
    """A synthetic repository. ``files`` maps posix-ish relpaths to content."""
    root = (tmp_path / name).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        _write(root, rel, text)
    (root / "docs" / "wiki").mkdir(parents=True, exist_ok=True)
    return root


def _verify(root: pathlib.Path) -> dict:
    return wiki_verify.verify(root, root / "docs" / "wiki")


def _details(report: dict, kind: str) -> set:
    return {f["detail"] for f in report["findings"].get(kind, [])}


# The invented name. Defined nowhere in any fixture below, so it is the
# positive control that proves a fixture could have produced a finding.
INVENTED = "# SurveyPlan\n\n`SurveyPlan` ist erfunden.\n"


# --------------------------------------------------------------------------
# 1. every finding kind, fired once, on one tree
# --------------------------------------------------------------------------

def test_every_finding_kind_fires_once_on_one_small_tree(tmp_path: pathlib.Path) -> None:
    """All six kinds from one page over a two-module tree.

    One fixture on purpose: it is also the check that the kinds do not
    interfere -- a backticked filename must not consume the symbol check, a
    covered module must not suppress the uncovered one.
    """
    root = _repo(tmp_path, {
        "pkg/core.py": "class Engine:\n    def __init__(self):\n        self.io_lock = None\n",
        "pkg/linked.py": "VERSION = 1\n",
        "docs/wiki/SurveyPlan.md": (
            "# SurveyPlan\n\n"
            "`SurveyPlan` ist das Planobjekt, `Engine` fuehrt es aus.\n\n"
            "Die Geraete stehen in `devices.yaml`.\n\n"
            "Siehe [linked](../../pkg/linked.py) und [weg](./fehlt.md).\n\n"
            "> **Extern:** IEEE 802.3 verlangt eine Praeambel.\n"
        ),
    })

    report = _verify(root)
    kinds = report["findings_by_kind"]

    assert set(kinds) == {
        "unknown_symbol", "broken_link", "missing_file_reference",
        "unsourced_claim", "uncovered_module", "thin_concept",
    }, f"not every kind fired on this tree: {kinds}"

    assert _details(report, "unknown_symbol") == {"SurveyPlan"}
    assert _details(report, "broken_link") == {"./fehlt.md"}
    assert _details(report, "missing_file_reference") == {"devices.yaml"}
    assert _details(report, "uncovered_module") == {"pkg/core.py"}, (
        "pkg/linked.py is linked from the page and must not be reported; "
        "pkg/core.py is not and must be"
    )
    assert _details(report, "thin_concept") == {"SurveyPlan", "Engine"}
    assert next(iter(_details(report, "unsourced_claim"))).startswith(
        ":** IEEE 802.3"), "the unsourced block is not the one that was flagged"

    assert report["pages"] == 1
    assert report["source_modules"] == 2
    assert report["modules_linked_from_wiki"] == 1
    assert report["module_coverage"] == 0.5
    assert report["relative_links"] == 2
    assert report["distinct_concepts"] == 2, (
        "a backticked filename is a file reference and must not also be "
        "counted as a concept"
    )
    assert report["verdict"] == "FAIL"


def test_a_link_that_leaves_the_tree_is_broken_too(tmp_path: pathlib.Path) -> None:
    """The second ``broken_link`` branch: the target exists but is not ours.

    A wiki that documents this repository by pointing at a file next to it
    documents nothing reproducible, so an existing target outside the root is
    still a broken link -- and says so in the detail.
    """
    root = _repo(tmp_path, {
        "pkg/core.py": "VERSION = 1\n",
        "docs/wiki/core.md": (
            "# Core\n\n"
            "[weg](./fehlt.md) und [draussen](../../../outside.md)\n"
        ),
    })
    (tmp_path / "outside.md").write_text("# outside\n", encoding="utf-8", newline="\n")

    report = _verify(root)
    assert _details(report, "broken_link") == {
        "./fehlt.md", "../../../outside.md (outside the tree)"}
    assert report["relative_links"] == 2
    assert report["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# 2. the four false-positive classes measured on 2026-08-25
#    Each fixture carries `SurveyPlan` as a positive control.
# --------------------------------------------------------------------------

def test_python_builtins_are_not_unknown_symbols(tmp_path: pathlib.Path) -> None:
    """(a) ``False`` and ``ValueError`` in backticks are not defects.

    Since the wiki no longer feeds the vocabulary, nothing but
    ``BUILTIN_NAMES`` and ``SYMBOL_SHAPE`` stands between these two names and a
    finding -- the fixture needs no trick to isolate them any more.
    """
    root = _repo(tmp_path, {
        "pkg/core.py": "VERSION = 1\n",
        "docs/wiki/errors.md": "# Fehler\n\n`ValueError` wird geworfen, `False` schaltet ab.\n",
        "docs/wiki/SurveyPlan.md": INVENTED,
    })

    report = _verify(root)
    assert _details(report, "unknown_symbol") == {"SurveyPlan"}, (
        "a builtin was reported as an unknown symbol -- false-positive class "
        "(a) is back"
    )

    # Which guard did the work, measured rather than assumed: the two names
    # fail out at different points, and only one of them reaches BUILTIN_NAMES.
    assert wiki_verify.SYMBOL_SHAPE.match("ValueError"), (
        "ValueError has symbol shape, so BUILTIN_NAMES is what must save it")
    assert "ValueError" in wiki_verify.BUILTIN_NAMES
    assert not wiki_verify.SYMBOL_SHAPE.match("False"), (
        "False is shape-filtered before the name lookup ever happens")


def test_imported_foreign_names_are_indexed_as_definitions(tmp_path: pathlib.Path) -> None:
    """(b) mechanism: an import binds the name into the tree's symbol index."""
    root = _repo(tmp_path, {
        "pkg/ui.py": (
            "from PySide6.QtCore import QObject, Signal as Emitted\n"
            "import numpy as np\n\n"
            "class Panel(QObject):\n"
            "    pass\n"
        ),
    })

    names, modules = wiki_verify.index_symbols(root, [])
    assert modules == {"pkg/ui.py"}
    assert "QObject" in names, "`from x import QObject` must define QObject"
    assert "Emitted" in names, "an `as` alias is the name the code actually uses"
    assert {"np", "numpy"} <= names, "plain imports bind both alias and tail"
    assert "Panel" in names


def test_an_imported_foreign_name_is_not_reported_unknown(tmp_path: pathlib.Path) -> None:
    """(b) outcome: ``QObject`` documented next to its import is not a defect.

    This assertion isolates the import handling now that the wiki is out of the
    vocabulary: the only thing in this tree that knows the name ``QObject`` is
    the import statement in ``pkg/ui.py``.
    """
    root = _repo(tmp_path, {
        "pkg/ui.py": "from PySide6.QtCore import QObject\n\n\nclass Panel(QObject):\n    pass\n",
        "docs/wiki/ui.md": "# UI\n\n`QObject` ist die Basis von `Panel`.\n",
        "docs/wiki/SurveyPlan.md": INVENTED,
    })

    report = _verify(root)
    assert _details(report, "unknown_symbol") == {"SurveyPlan"}, (
        "an imported third-party name was reported -- false-positive class "
        "(b) is back"
    )


def test_a_backticked_filename_is_a_file_reference_never_a_symbol(
    tmp_path: pathlib.Path,
) -> None:
    """(c) ``devices.yaml`` is a file claim, and a different finding.

    Both states in one test: absent, it is a ``missing_file_reference``;
    present anywhere in the tree, it is nothing at all. In neither state may it
    become an ``unknown_symbol``, and in neither state may it be counted as a
    concept.
    """
    root = _repo(tmp_path, {
        "pkg/core.py": "VERSION = 1\n",
        "docs/wiki/devices.md": (
            "# Devices\n\nSiehe `devices.yaml` und `plan_v2.json`.\n"
        ),
        "docs/wiki/SurveyPlan.md": INVENTED,
    })

    missing = _verify(root)
    assert _details(missing, "missing_file_reference") == {"devices.yaml", "plan_v2.json"}
    assert _details(missing, "unknown_symbol") == {"SurveyPlan"}, (
        "a filename in backticks was reported as a symbol -- false-positive "
        "class (c) is back"
    )
    assert _details(missing, "thin_concept") == {"SurveyPlan"}, (
        "a file reference must not enter the concept census")

    # The lookup is by basename, anywhere in the tree -- not by path. Note
    # `tree_files` is deliberately NOT subject to the exclusions: it answers
    # "does this file exist", not "is this name real".
    _write(root, "config/nested/devices.yaml", "device: 1\n")
    _write(root, "config/plan_v2.json", '{"steps": []}\n')
    present = _verify(root)
    assert "missing_file_reference" not in present["findings_by_kind"]
    assert _details(present, "unknown_symbol") == {"SurveyPlan"}


def test_self_attributes_are_indexed_as_definitions(tmp_path: pathlib.Path) -> None:
    """(d) mechanism: ``self.io_lock = ...`` defines ``io_lock``.

    ``ast.Assign`` only handles plain-name targets, so an attribute assignment
    is picked up by the ``ast.Attribute`` walk. Both names below carry an
    underscore, i.e. they have symbol shape and would reach the name lookup --
    an index that missed them would produce a finding.
    """
    root = _repo(tmp_path, {
        "pkg/core.py": (
            "class Engine:\n"
            "    def __init__(self):\n"
            "        self.io_lock = None\n"
            "        self.retry_count = 0\n"
        ),
    })

    names, _ = wiki_verify.index_symbols(root, [])
    assert {"io_lock", "retry_count"} <= names
    assert wiki_verify.SYMBOL_SHAPE.match("io_lock")


def test_a_self_attribute_is_not_reported_unknown(tmp_path: pathlib.Path) -> None:
    """(d) outcome: the attribute assignment is the only evidence in the tree."""
    root = _repo(tmp_path, {
        "pkg/core.py": (
            "class Engine:\n"
            "    def __init__(self):\n"
            "        self.io_lock = None\n"
        ),
        "docs/wiki/core.md": "# Core\n\n`io_lock` schuetzt den Zugriff.\n",
        "docs/wiki/SurveyPlan.md": INVENTED,
    })

    report = _verify(root)
    assert _details(report, "unknown_symbol") == {"SurveyPlan"}, (
        "a self attribute was reported -- false-positive class (d) is back")


# --------------------------------------------------------------------------
# 3. the SYMBOL_SHAPE boundary
# --------------------------------------------------------------------------

def test_prose_in_backticks_is_not_a_symbol_claim(tmp_path: pathlib.Path) -> None:
    """``und`` and ``positive`` fire nothing. ``NaN`` is the boundary itself.

    Two mechanisms, and the difference is the whole point. ``und`` and
    ``positive`` have no symbol shape and never reach the name lookup. ``NaN``
    *does* have symbol shape -- ``.*[a-z].*[A-Z].*`` matches the ``a`` before
    the second ``N`` -- so it is judged like any other claim: it fires when the
    tree does not know the name, and is silent when the tree does.

    Before the vocabulary fix, ``NaN`` was spared by the page that mentioned
    it, which is why this test used to assert silence unconditionally. That was
    the hole, not a rule. The field consequence of the honest behaviour is
    measured and small -- 4 findings of exactly this shape on project_tct, all
    of them notation rather than defects (see the module docstring).
    """
    files = {
        "pkg/core.py": "VERSION = 1\n",
        "docs/wiki/prose.md": (
            "# Prosa\n\n"
            "`und` verbindet, `positive` Werte, `NaN` als Luecke.\n"
        ),
        "docs/wiki/SurveyPlan.md": INVENTED,
    }
    homeless = _verify(_repo(tmp_path, files, name="homeless"))
    assert _details(homeless, "unknown_symbol") == {"NaN", "SurveyPlan"}, (
        "a shaped token the tree never mentions must be reported like any "
        "other claim"
    )

    with_home = dict(files)
    with_home["pkg/values.py"] = "NaN = float('nan')\n"
    homed = _verify(_repo(tmp_path, with_home, name="homed"))
    assert _details(homed, "unknown_symbol") == {"SurveyPlan"}, (
        "one definition outside the wiki is enough to clear the same token")

    assert not wiki_verify.SYMBOL_SHAPE.match("und")
    assert not wiki_verify.SYMBOL_SHAPE.match("positive")
    assert wiki_verify.SYMBOL_SHAPE.match("SurveyPlan")
    assert wiki_verify.SYMBOL_SHAPE.match("NaN"), (
        "NaN is not shape-filtered; the pair of runs above is what decides it")

    # All four become concepts: the census is taken before the shape filter,
    # so prose in backticks inflates `distinct_concepts` and can produce
    # `thin_concept`.
    assert homeless["distinct_concepts"] == 4
    assert _details(homeless, "thin_concept") == {"und", "positive", "NaN", "SurveyPlan"}


# --------------------------------------------------------------------------
# 4. the verdict rule
# --------------------------------------------------------------------------

_PASSING = {
    "pkg/core.py": "class Engine:\n    def __init__(self):\n        self.io_lock = None\n",
    "docs/wiki/core.md": "# Core\n\n`io_lock` schuetzt den Zugriff.\n",
}


def test_uncovered_modules_and_thin_concepts_alone_still_pass(
    tmp_path: pathlib.Path,
) -> None:
    """Coverage and thinness inform; they do not block.

    They are properties of how much of the tree the wiki reached, not claims
    the wiki got wrong, so a wiki that is true but incomplete passes.
    """
    root = _repo(tmp_path, dict(_PASSING))
    report = _verify(root)

    assert set(report["findings_by_kind"]) == {"uncovered_module", "thin_concept"}
    assert _details(report, "uncovered_module") == {"pkg/core.py"}
    assert _details(report, "thin_concept") == {"io_lock"}
    assert report["verdict"] == "PASS"


@pytest.mark.parametrize("kind, extra", [
    ("broken_link",
     {"docs/wiki/core.md": "# Core\n\n`io_lock` -- [weg](./fehlt.md)\n"}),
    ("unknown_symbol",
     {"docs/wiki/SurveyPlan.md": INVENTED}),
    ("unsourced_claim",
     {"docs/wiki/extern.md": "# Extern\n\n> **Extern:** Behauptung ohne Beleg.\n"}),
])
def test_each_wrong_claim_alone_fails(
    tmp_path: pathlib.Path, kind: str, extra: dict,
) -> None:
    """Exactly one blocking kind added to the passing tree flips the verdict."""
    files = dict(_PASSING)
    files.update(extra)
    root = _repo(tmp_path, files)

    report = _verify(root)
    assert report["findings_by_kind"].get(kind, 0) >= 1
    assert report["verdict"] == "FAIL", (
        f"{kind} did not block the verdict: {report['findings_by_kind']}")
    # and the two non-blocking kinds are still present, so it is demonstrably
    # the added kind that flipped it and not their disappearance.
    assert report["findings_by_kind"].get("uncovered_module", 0) >= 1
    assert report["findings_by_kind"].get("thin_concept", 0) >= 1


def test_the_url_is_what_spares_an_external_block(tmp_path: pathlib.Path) -> None:
    """Two extern blocks in one page: the sourced one passes, the bare one does not.

    Both halves in one fixture on purpose. A test that only showed the sourced
    block being accepted would stay green if ``EXTERNAL_MARK`` stopped matching
    altogether -- "nothing found" would then mean "nothing looked".
    """
    files = dict(_PASSING)
    files["docs/wiki/extern.md"] = (
        "# Extern\n\n"
        "> **Extern:** Behauptung mit Beleg.\n"
        "> Quelle: https://example.org/norm-1234\n\n"
        "> **Extern:** Behauptung ohne Beleg.\n"
    )
    root = _repo(tmp_path, files)

    report = _verify(root)
    assert report["findings_by_kind"].get("unsourced_claim", 0) == 1, (
        "exactly one of the two blocks must be reported: "
        f"{report['findings'].get('unsourced_claim')}"
    )
    assert next(iter(_details(report, "unsourced_claim"))).startswith(
        ":** Behauptung ohne Beleg"), "the wrong block was flagged"
    assert report["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# 5. the instrument has to say what it did not show
# --------------------------------------------------------------------------

def test_the_result_json_reports_truncation_per_kind(tmp_path: pathlib.Path) -> None:
    """``findings`` is capped at 80 per kind, and the cap is declared per kind.

    A single global "truncated: true" would let a reader believe the 80
    ``uncovered_module`` entries in front of them are all of them while a
    second kind was the one that got cut. So the assertion is not only that the
    number is right, but that *every reported kind* carries one -- a kind with
    nothing hidden must say 0 rather than say nothing.

    Asserted on ``json.loads(json.dumps(report))`` because the artefact that
    reaches a reader is ``runs/wiki_verify.json``, not the dict.
    """
    files = {f"pkg/mod_{i:03d}.py": "VALUE = 1\n" for i in range(95)}
    files["docs/wiki/core.md"] = "# Core\n\n`VALUE` steht in `mod_001`.\n"
    root = _repo(tmp_path, files)

    payload = json.loads(json.dumps(_verify(root)))

    assert payload["findings_by_kind"]["uncovered_module"] == 95
    assert len(payload["findings"]["uncovered_module"]) == 80
    assert payload["findings_per_kind_truncated"]["uncovered_module"] == 15, (
        "95 findings, 80 shown -- the report must declare the 15 it dropped")

    assert payload["findings_by_kind"]["thin_concept"] == 2
    assert len(payload["findings"]["thin_concept"]) == 2
    assert payload["findings_per_kind_truncated"]["thin_concept"] == 0, (
        "a kind that hid nothing must still report 0, not be absent")

    assert set(payload["findings_per_kind_truncated"]) == set(payload["findings_by_kind"]), (
        "every reported kind needs its own truncation count -- otherwise the "
        "reader cannot tell which list is complete"
    )
    assert payload["verdict"] == "PASS"


# --------------------------------------------------------------------------
# 6. three placements of the NAME
# --------------------------------------------------------------------------

@pytest.mark.parametrize("placement, page, extra", [
    ("page named after the symbol", "AppComposition.md", {}),
    ("page named something else", "architecture.md", {}),
    ("only in a previous run's report", "architecture.md",
     {"runs/wiki_verify.json": '{"findings": {"unknown_symbol": '
                               '[{"detail": "AppComposition"}]}}\n'}),
])
def test_an_invented_name_is_caught_wherever_it_is_written(
    tmp_path: pathlib.Path, placement: str, page: str, extra: dict,
) -> None:
    """The same invented name, three placements, one rule: it fires.

    Before 2026-08-25 only the first of these was caught, because the
    vocabulary was read from every file under the root -- so a page vouched for
    its own claims, and the verifier's own report from the previous run vouched
    for the run after it. The third case is the one that hides best: nothing a
    human reads changes, the tree merely accumulated an artefact.
    """
    files = {
        "pkg/core.py": "VERSION = 1\n",
        f"docs/wiki/{page}": "# Seite\n\n`AppComposition` ist erfunden.\n",
    }
    files.update(extra)
    root = _repo(tmp_path, files)

    report = _verify(root)
    assert _details(report, "unknown_symbol") == {"AppComposition"}, (
        f"an invented name was not caught when placed: {placement}")
    assert report["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# 7. twelve placements of the EVIDENCE
# --------------------------------------------------------------------------

_DEF_PY = "def Fabricated_Alpha():\n    pass\n"
_DEF_JSON = '{"Fabricated_Alpha": 1}\n'
_DEF_YAML = "Fabricated_Alpha: 1\n"
_DEF_TOML = "Fabricated_Alpha = 1\n"

# Under the wiki or under runs/, no format and no evidence source may vouch.
_MAY_NOT_VOUCH = [
    ("docs/wiki/evil.py", _DEF_PY),
    ("runs/evil.py", _DEF_PY),
    ("docs/wiki/meta.json", _DEF_JSON),
    ("runs/old_report.json", _DEF_JSON),
    ("docs/wiki/meta.yaml", _DEF_YAML),
    ("runs/old.yaml", _DEF_YAML),
    ("docs/wiki/meta.toml", _DEF_TOML),
    ("runs/old.toml", _DEF_TOML),
]

# Anywhere else it is ordinary project evidence and must be believed --
# including a `.md`, which is how a format specification documents a field
# name that no code declares.
_MUST_VOUCH = [
    ("pkg/real.py", _DEF_PY),
    ("docs/SPEC.md", "Das Feld `Fabricated_Alpha` ist Teil des Formats.\n"),
    ("docs/spec.json", _DEF_JSON),
    ("pkg/conf.yaml", _DEF_YAML),
]


def _claiming_repo(tmp_path: pathlib.Path, rel, text, name: str) -> pathlib.Path:
    files = {
        "pkg/core.py": "VERSION = 1\n",
        "docs/wiki/architecture.md": "# Architektur\n\n`Fabricated_Alpha` behauptet.\n",
    }
    if rel is not None:
        files[rel] = text
    return _repo(tmp_path, files, name=name)


def test_a_name_only_the_wiki_claims_is_a_finding(tmp_path: pathlib.Path) -> None:
    """The control for both tables below: without any evidence, it fires.

    A placement test whose fixture could not have produced a finding in the
    first place measures nothing, so this is the dynamic range for the twelve
    cases that follow.
    """
    report = _verify(_claiming_repo(tmp_path, None, None, "control"))
    assert report["findings_by_kind"].get("unknown_symbol", 0) == 1
    assert report["verdict"] == "FAIL"


@pytest.mark.parametrize("rel, text", _MAY_NOT_VOUCH, ids=[r for r, _ in _MAY_NOT_VOUCH])
def test_the_checked_set_may_not_vouch_for_itself(
    tmp_path: pathlib.Path, rel: str, text: str,
) -> None:
    """Evidence under the wiki or under runs/ does not clear a wiki claim.

    Eight cells, and they are not eight special cases: they are two evidence
    sources that took no exclusions (``index_symbols``, ``_config_keys``) times
    two excluded trees times the config formats. Measured 2026-08-25: all eight
    acquitted the invented name before ``exclusions()`` was threaded through
    every source.
    """
    report = _verify(_claiming_repo(tmp_path, rel, text, "coat"))
    assert report["findings_by_kind"].get("unknown_symbol", 0) == 1, (
        f"a file at {rel} vouched for a name only the wiki claims")
    assert report["verdict"] == "FAIL"


@pytest.mark.parametrize("rel, text", _MUST_VOUCH, ids=[r for r, _ in _MUST_VOUCH])
def test_ordinary_project_evidence_still_clears_a_claim(
    tmp_path: pathlib.Path, rel: str, text: str,
) -> None:
    """The counter-direction: the exclusions must not swallow real evidence.

    ``docs/SPEC.md`` is the load-bearing one. A ``.md`` outside the wiki stays
    evidence on purpose -- a format specification names fields that no code
    declares -- and an exclusion written one directory too wide would silently
    turn every such field into a finding.
    """
    report = _verify(_claiming_repo(tmp_path, rel, text, "evidence"))
    assert "unknown_symbol" not in report["findings_by_kind"], (
        f"evidence at {rel} was ignored: {report['findings'].get('unknown_symbol')}")
    assert report["verdict"] == "PASS"
