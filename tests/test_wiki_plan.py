"""Tests for ``daedalus.wiki.plan`` -- the deterministic half of wiki generation.

Three things are worth testing here, in rising order of value.

**The partition rule.** A directory becomes a topic only with at least
``MIN_BUCKET_FILES`` modules and ``MIN_BUCKET_LOC`` lines, and test code never
becomes a topic. That is cheap to check and cheap to break.

**The two planner defects measured on 2026-08-25.** Both made the planner
invent topics that are not the project:

* a virtual environment was surveyed as source because it was not *named*
  ``venv``. On project_tct the topic list contained ``Scripts`` and ``bin``.
  The fix keys on ``pyvenv.cfg``, so the regression test builds a venv under a
  name nothing recognises (``myenv``) and then removes the marker file to show
  the exclusion is caused by the marker and not by the fixture being too small
  to qualify.
* artefact trees were surveyed as source. On this repository ``runs/`` alone
  produced 602 "topics", one per run directory.

Both tests carry that positive control on purpose: an exclusion test whose
fixture would not have become a topic anyway measures nothing.

**The planner/verifier coupling.** ``plan.PROMPT`` promises an author that four
named requirements are machine-checked, and ``daedalus.wiki.verify`` is what
checks them. Those are two files that can drift apart silently -- rename a
finding kind in the verifier and the planner keeps quoting the old name at
every author it dispatches. The coupling tests below read the requirement names
out of the *verifier's source* and run the extern-block format the *prompt*
prescribes through the *verifier's* implementation, in both directions.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

from daedalus.wiki import plan as wiki_plan
from daedalus.wiki import verify as wiki_verify


# --------------------------------------------------------------------------
# fixture construction
# --------------------------------------------------------------------------

def _write(root: pathlib.Path, rel: str, text: str) -> pathlib.Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _module(symbol: str, body_lines: int = 120) -> str:
    """A syntactically real module with one public top-level symbol.

    ``plan.survey`` counts lines as ``text.count("\\n")`` and reads symbols from
    ``ast.parse(...).body`` only, so the fixture has to be parseable and define
    at top level -- a string of the right length would pass the LOC gate and
    contribute no symbols.
    """
    lines = [f"def {symbol}(value):"]
    lines += [f"    step_{i} = value + {i}" for i in range(body_lines)]
    lines += ["    return value", "", "", "def _private_helper():", "    return None", ""]
    return "\n".join(lines)


def _fat_dir(root: pathlib.Path, directory: str, prefix: str = "a") -> None:
    """Two modules, ~250 lines: exactly what ``survey`` calls a topic."""
    _write(root, f"{directory}/{prefix}_one.py", _module(f"{prefix}_one_entry"))
    _write(root, f"{directory}/{prefix}_two.py", _module(f"{prefix}_two_entry"))


def _names(topics) -> set[str]:
    return {t.name for t in topics}


def _dirs(topics) -> set[str]:
    return {t.directory for t in topics}


# --------------------------------------------------------------------------
# 1. survey: what becomes a topic
# --------------------------------------------------------------------------

def test_survey_topic_thresholds_and_test_exclusion(tmp_path: pathlib.Path) -> None:
    """>=2 modules and >=200 lines make a topic; test code never does."""
    _fat_dir(tmp_path, "core", prefix="core")
    _write(tmp_path, "solo/only.py", _module("solo_entry", body_lines=400))   # 1 file
    _write(tmp_path, "small/a.py", _module("small_a", body_lines=5))          # 2 files,
    _write(tmp_path, "small/b.py", _module("small_b", body_lines=5))          # too few lines
    _write(tmp_path, "core/test_core_one.py", _module("test_helper", body_lines=400))
    _fat_dir(tmp_path, "tests/harness", prefix="harness")

    topics = wiki_plan.survey(tmp_path)

    assert _names(topics) == {"core"}, "only the fat non-test directory is a topic"
    core = topics[0]
    assert core.directory == "core"
    assert core.files == ("core/core_one.py", "core/core_two.py")
    assert core.loc >= wiki_plan.MIN_BUCKET_LOC
    # the test module in the same directory contributes neither file nor lines
    assert not any(f.startswith("core/test_") for f in core.files)
    assert core.loc < 500, "a test_ module inside a topic directory still leaks LOC"


def test_survey_reports_public_symbols_only(tmp_path: pathlib.Path) -> None:
    """The prompt tells authors not to invent symbols; survey supplies real ones."""
    _fat_dir(tmp_path, "core", prefix="core")

    (core,) = wiki_plan.survey(tmp_path)

    assert set(core.symbols) == {"core_one_entry", "core_two_entry"}
    assert not any(s.startswith("_") for s in core.symbols)
    assert list(core.symbols) == sorted(set(core.symbols)), "symbols are sorted and unique"


def test_survey_ranks_topics_by_weight(tmp_path: pathlib.Path) -> None:
    _fat_dir(tmp_path, "light", prefix="light")
    _write(tmp_path, "heavy/a.py", _module("heavy_a", body_lines=400))
    _write(tmp_path, "heavy/b.py", _module("heavy_b", body_lines=400))

    topics = wiki_plan.survey(tmp_path)

    assert [t.name for t in topics] == ["heavy", "light"]
    assert topics[0].loc > topics[1].loc


# --------------------------------------------------------------------------
# 2a. REGRESSION: a venv is excluded by its marker file, not by its name
# --------------------------------------------------------------------------

def test_venv_is_excluded_by_pyvenv_cfg_whatever_it_is_called(tmp_path: pathlib.Path) -> None:
    """Measured 2026-08-25 on project_tct: ``Scripts`` and ``bin`` were topics.

    The environment was not called ``venv``, so the name-based ``SKIP_DIRS``
    never saw it. The fixture reproduces that shape under the name ``myenv``.
    """
    _fat_dir(tmp_path, "core", prefix="core")
    _write(tmp_path, "myenv/pyvenv.cfg", "home = C:\\Python313\nversion = 3.13.0\n")
    _fat_dir(tmp_path, "myenv/Scripts", prefix="script")
    _fat_dir(tmp_path, "myenv/Lib/vendored", prefix="vendor")

    topics = wiki_plan.survey(tmp_path)

    assert _names(topics) == {"core"}, f"the venv leaked into the topics: {_dirs(topics)}"
    assert not any(t.directory.startswith("myenv") for t in topics)
    assert "Scripts" not in _names(topics)
    assert all(not f.startswith("myenv/") for t in topics for f in t.files)

    # DYNAMIC RANGE. Remove only the marker file: the very same directories now
    # qualify. Without this the test above would also pass if the fixture were
    # simply too small to be a topic.
    (tmp_path / "myenv" / "pyvenv.cfg").unlink()
    unguarded = wiki_plan.survey(tmp_path)
    assert "Scripts" in _names(unguarded), (
        "fixture does not exercise the guard: these directories are not "
        "topic-worthy even without a venv marker"
    )
    assert "vendored" in _names(unguarded)


def test_venv_marker_below_the_root_still_excludes_its_own_subtree(
    tmp_path: pathlib.Path,
) -> None:
    """A nested environment (``tools/env/``) is found by ``rglob``, not only one at the root."""
    _fat_dir(tmp_path, "core", prefix="core")
    _write(tmp_path, "tools/env/pyvenv.cfg", "home = /usr\n")
    _fat_dir(tmp_path, "tools/env/Scripts", prefix="nested")

    topics = wiki_plan.survey(tmp_path)
    assert _names(topics) == {"core"}, f"the nested venv leaked in: {_dirs(topics)}"


# --------------------------------------------------------------------------
# 2b. REGRESSION: artefact trees are not topics
# --------------------------------------------------------------------------

@pytest.mark.parametrize("artefact_dir", ["runs", "scratchpad", "artifacts_claude"])
def test_artefact_trees_are_excluded(tmp_path: pathlib.Path, artefact_dir: str) -> None:
    """Measured 2026-08-25 on this repository: ``runs/`` produced 602 phantom topics.

    Every run directory holds a copy of whatever the run executed, so an
    unguarded planner reports the same code once per run and calls each one a
    subject of the project.
    """
    _fat_dir(tmp_path, "core", prefix="core")
    _fat_dir(tmp_path, f"{artefact_dir}/some_run_2026", prefix="art")
    _fat_dir(tmp_path, f"{artefact_dir}/other_run_2026/nested", prefix="art")
    # DYNAMIC RANGE: the identical shape under a name that is not on the list.
    _fat_dir(tmp_path, "myruns/some_run_2026", prefix="art")

    topics = wiki_plan.survey(tmp_path)

    assert not any(t.directory.split("/")[0] == artefact_dir for t in topics), (
        f"{artefact_dir}/ was surveyed as source"
    )
    assert "myruns/some_run_2026" in _dirs(topics), (
        "fixture does not exercise the guard: this shape is not a topic anyway"
    )
    assert "core" in _names(topics)


def test_many_run_directories_do_not_multiply_into_topics(tmp_path: pathlib.Path) -> None:
    """The shape of the 602-topic result: one directory per run, all identical."""
    _fat_dir(tmp_path, "core", prefix="core")
    for i in range(12):
        _fat_dir(tmp_path, f"runs/wiki_run_{i:03d}", prefix="art")

    topics = wiki_plan.survey(tmp_path)

    assert [t.name for t in topics] == ["core"], (
        f"{len(topics)} topics from 1 source directory and 12 run directories"
    )


# --------------------------------------------------------------------------
# 3. assign: balanced partition
# --------------------------------------------------------------------------

def _topic(name: str, loc: int) -> wiki_plan.Topic:
    return wiki_plan.Topic(
        name=name,
        directory=name,
        files=(f"{name}/a.py",),
        symbols=(f"{name}_entry",),
        loc=loc,
    )


def test_assign_does_not_give_one_author_both_heavy_topics() -> None:
    """Weights [100, 90, 10, 10] over 2 authors: 110/100, never 190/20."""
    topics = [_topic("big", 100), _topic("large", 90), _topic("tail_a", 10),
              _topic("tail_b", 10)]

    buckets = wiki_plan.assign(topics, 2)

    assert len(buckets) == 2
    for bucket in buckets:
        heavy = [t for t in bucket if t.loc >= 90]
        assert len(heavy) <= 1, f"one author got both heavy topics: {bucket}"

    loads = sorted(sum(t.loc for t in bucket) for bucket in buckets)
    assert loads == [100, 110], "any optimal assignment yields these loads"


def test_assign_places_every_topic_exactly_once() -> None:
    topics = [_topic(f"t{i}", loc) for i, loc in enumerate([300, 220, 200, 40, 30, 10])]

    for authors in (1, 2, 3, 5):
        buckets = wiki_plan.assign(topics, authors)
        placed = [t for bucket in buckets for t in bucket]
        assert len(placed) == len(topics)
        assert {t.name for t in placed} == {t.name for t in topics}
        loads = [sum(t.loc for t in bucket) for bucket in buckets]
        assert max(loads) - min(loads) <= max(t.loc for t in topics), (
            f"imbalance exceeds the largest indivisible topic: {loads}"
        )


def test_assign_survives_a_degenerate_author_count() -> None:
    """``max(1, authors)`` is load-bearing: a zero here would be a ZeroDivision-shaped crash."""
    topics = [_topic("only", 250)]
    assert [[t.name for t in b] for b in wiki_plan.assign(topics, 0)] == [["only"]]
    assert wiki_plan.assign([], 3) == [[], [], []]


def test_build_plan_reports_only_authors_that_got_work(tmp_path: pathlib.Path) -> None:
    _fat_dir(tmp_path, "core", prefix="core")

    plan = wiki_plan.build_plan(tmp_path, authors=4, wiki_dir="docs/wiki")

    assert plan["authors"] == 1 == len(plan["tasks"])
    assert [t["author"] for t in plan["tasks"]] == [1]


# --------------------------------------------------------------------------
# 4. the planner/verifier contract
# --------------------------------------------------------------------------

# The names the emitted prompt quotes at every author it dispatches.
PROMISED_KINDS = ("unknown_symbol", "broken_link", "thin_concept", "unsourced_claim")


def _verifier_finding_kinds() -> set[str]:
    """Every ``Finding("kind", ...)`` literal in the verifier's own source."""
    source = pathlib.Path(wiki_verify.__file__).read_text(encoding="utf-8")
    kinds: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Finding" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            kinds.add(node.args[0].value)
    return kinds


def _built_prompt(tmp_path: pathlib.Path, wiki_dir: str = "docs/wiki") -> str:
    _fat_dir(tmp_path, "core", prefix="core")
    plan = wiki_plan.build_plan(tmp_path, authors=1, wiki_dir=wiki_dir)
    return plan["tasks"][0]["prompt"]


def test_prompt_names_requirements_the_verifier_can_actually_emit(
    tmp_path: pathlib.Path,
) -> None:
    """The coupling. Rename a finding kind in verify.py and this test fails.

    Without it the planner keeps quoting a requirement name at every author it
    dispatches while the verifier reports something else entirely, and the two
    halves drift apart with nothing red in between.
    """
    prompt = _built_prompt(tmp_path)
    emitted = _verifier_finding_kinds()

    assert emitted, "could not read any Finding kind out of the verifier's source"
    for kind in PROMISED_KINDS:
        assert kind in prompt, f"the prompt stopped naming the requirement {kind!r}"
        assert kind in emitted, (
            f"the prompt promises {kind!r} is machine-checked, but "
            f"daedalus.wiki.verify never emits it; it emits {sorted(emitted)}"
        )


def test_prompt_carries_the_external_block_with_its_url_obligation(
    tmp_path: pathlib.Path,
) -> None:
    prompt = _built_prompt(tmp_path)

    assert "**Extern:**" in prompt, "the prompt no longer shows the external-knowledge block"
    assert "Quelle: https://" in prompt, "the block no longer demands a source URL"
    assert "unsourced_claim" in prompt, "the block no longer names its failure mode"
    # the block, and the obligation, are in the same instruction
    extern_at = prompt.index("**Extern:**")
    distance = prompt.index("unsourced_claim", extern_at) - extern_at
    assert 0 < distance < 600, (
        f"the URL obligation is {distance} characters away from the block it governs"
    )


def _extern_block_from(prompt: str) -> str:
    """The ONE blockquote the prompt shows for external knowledge, verbatim.

    Anchored on the line carrying ``**Extern:**`` and stopped at the first line
    that is no longer part of that blockquote. Collecting every ``>`` line in
    the prompt instead would glue a second, unrelated blockquote onto this one
    -- and because ``verify.EXTERNAL_MARK`` scans 600 characters past the mark,
    a URL sitting in that foreign block would make the unsourced case look
    sourced. The test would then break in the WRONG direction: red, reporting
    format drift where there is none.
    """
    lines = prompt.splitlines()
    start = next((i for i, ln in enumerate(lines) if "**Extern:**" in ln), None)
    assert start is not None, "the prompt no longer shows an external-knowledge block"
    block: list[str] = []
    for line in lines[start:]:
        if not line.strip().startswith(">"):
            break
        block.append(line.strip())
    return "\n".join(block)


def test_the_external_block_the_prompt_prescribes_is_the_one_the_verifier_accepts(
    tmp_path: pathlib.Path,
) -> None:
    """Run the prompt's own example format through the verifier, both directions.

    This is the second half of the coupling: not just that both modules use the
    same *word*, but that a page written exactly as the planner instructs is
    accepted, and the same page with the source line removed is rejected.
    """
    repo = tmp_path / "repo"
    _fat_dir(repo, "core", prefix="core")
    wiki = repo / "docs" / "wiki"

    template = _extern_block_from(_built_prompt(tmp_path / "probe"))
    sourced = (template
               .replace("**Extern:** ...", "**Extern:** Die Norm verlangt eine Prüfsumme.")
               .replace("https://...", "https://example.org/norm-1234"))
    assert re.search(r"https?://\S+\w", sourced), "placeholder URL was not substituted"
    unsourced = "\n".join(ln for ln in sourced.splitlines()
                          if not re.match(r"^\s*>\s*(Quelle|Source|Ref)\s*:", ln))
    assert unsourced != sourced

    page = ("# Core\n\n`core_one_entry` und `core_two_entry` leben in "
            "[core_one.py](../../core/core_one.py) und "
            "[core_two.py](../../core/core_two.py).\n\n{block}\n")

    _write(repo, "docs/wiki/core.md", page.format(block=sourced))
    accepted = wiki_verify.verify(repo, wiki)
    assert accepted["findings_by_kind"].get("unsourced_claim", 0) == 0, (
        "the block format the prompt prescribes is rejected by the verifier: "
        f"{accepted['findings'].get('unsourced_claim')}"
    )

    _write(repo, "docs/wiki/core.md", page.format(block=unsourced))
    rejected = wiki_verify.verify(repo, wiki)
    assert rejected["findings_by_kind"].get("unsourced_claim", 0) == 1, (
        "dropping the source line did not produce unsourced_claim -- the "
        "obligation the prompt states is not the one the verifier enforces"
    )
    assert rejected["verdict"] == "FAIL"


def test_an_invented_symbol_on_a_wiki_page_is_refused(tmp_path: pathlib.Path) -> None:
    """PROMPT requirement 1, end to end: the verifier really refuses invented symbols.

    Measured 2026-08-25, BEFORE the fix, it did not. ``verify.tree_vocabulary``
    read every file under the root -- including the wiki page making the claim
    -- so an invented name sat in its own evidence set and the page passed with
    no ``unknown_symbol`` at all. The planner was promising every author it
    dispatched a machine check that did not run.

    Deliberately agnostic about HOW that is fixed: this goes through the public
    ``verify.verify(root, wiki_dir)`` and states the obligation, not the
    mechanism that meets it.
    """
    repo = tmp_path / "repo"
    _fat_dir(repo, "core", prefix="core")
    wiki = repo / "docs" / "wiki"

    # The page must NOT be named after the invented symbol: a page stem is
    # subtracted from `known` by an older, separate rule (`known -= wiki_own`),
    # so a page called `Nonexistent_Widget.md` would go green through that path
    # without exercising this check at all.
    invented = "Nonexistent_Widget"
    _write(repo, "docs/wiki/core.md", f"""# Core

`core_one_entry` und `{invented}` leben in
[core_one.py](../../core/core_one.py).
""")
    outside_the_wiki = [p for p in repo.rglob("*")
                        if p.is_file() and wiki not in p.parents]
    assert outside_the_wiki and all(
        invented not in p.read_text(encoding="utf-8") for p in outside_the_wiki), (
        "fixture leak: the invented name occurs in the tree it must be absent from"
    )

    report = wiki_verify.verify(repo, wiki)
    kinds = report["findings_by_kind"]

    assert kinds.get("unknown_symbol", 0) >= 1, (
        f"the invented symbol {invented!r} was accepted -- PROMPT requirement 1 "
        f"(`unknown_symbol`) is not enforced. findings: {kinds}"
    )
    assert any(f["detail"] == invented
               for f in report["findings"]["unknown_symbol"]), report["findings"]
    assert report["verdict"] == "FAIL"


def test_prompt_names_the_files_and_output_location_of_its_own_bucket(
    tmp_path: pathlib.Path,
) -> None:
    _fat_dir(tmp_path, "core", prefix="core")

    plan = wiki_plan.build_plan(tmp_path, authors=1, wiki_dir="docs/wiki")
    task = plan["tasks"][0]

    assert "docs/wiki" in task["prompt"]
    assert task["index_page"] in task["prompt"]
    for path in task["files"]:
        assert path in task["prompt"], f"the author is not told to cover {path}"
    for symbol in ("core_one_entry", "core_two_entry"):
        assert symbol in task["prompt"]
    assert "_private_helper" not in task["prompt"]


# --------------------------------------------------------------------------
# 5. determinism
# --------------------------------------------------------------------------

VOLATILE = re.compile(r"(?i)time|stamp|date|generated|uuid|host|pid")


def _strip_volatile(value):
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items() if not VOLATILE.search(k)}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def test_build_plan_is_deterministic(tmp_path: pathlib.Path) -> None:
    """Twice over the same tree is byte-identical, so a re-plan is reviewable as a diff."""
    _fat_dir(tmp_path, "core", prefix="core")
    _fat_dir(tmp_path, "engine", prefix="engine")
    _write(tmp_path, "engine/extra.py", _module("engine_extra", body_lines=300))
    _fat_dir(tmp_path, "runs/run_001", prefix="art")

    first = wiki_plan.build_plan(tmp_path, authors=2, wiki_dir="docs/wiki")
    second = wiki_plan.build_plan(tmp_path, authors=2, wiki_dir="docs/wiki")

    assert json.dumps(_strip_volatile(first), sort_keys=True, ensure_ascii=False) == \
        json.dumps(_strip_volatile(second), sort_keys=True, ensure_ascii=False)
    # and the plan really has no clock in it, so the comparison above is total
    assert _strip_volatile(first) == first, "build_plan grew a volatile field"
    assert first["total_loc"] > 0 and first["topics"]


def test_survey_is_order_independent_of_the_filesystem(tmp_path: pathlib.Path) -> None:
    """Ties are broken by name, not by directory-walk order."""
    for name in ("zulu", "alpha", "mike"):
        _fat_dir(tmp_path, name, prefix=name)

    topics = wiki_plan.survey(tmp_path)

    assert len({t.loc for t in topics}) == 1, "fixture must produce equal weights"
    assert [t.name for t in topics] == sorted(t.name for t in topics)
    assert [t.name for t in wiki_plan.survey(tmp_path)] == [t.name for t in topics]


def test_a_nested_checkout_is_not_half_the_plan(tmp_path: pathlib.Path) -> None:
    """A repository below the root is a copy, not more material.

    MEASURED 2026-08-26 on this repository, with a git worktree checked out at
    `.claude/worktrees/`: the survey returned 983 files across 78 topics, and
    **480 of those files came from the copy**. Nearly half the plan -- topics,
    line weights, author assignment -- was computed over a duplicate of the
    tree it was describing, and the authors would have been sent to write pages
    about it.

    The name-based `SKIP_DIRS` could not have caught it: the directory was
    `.claude/worktrees`, not `.worktrees`, and a name list is always one name
    behind. The rule is structural -- a directory holding a `.git` entry is a
    different repository -- exactly like the `pyvenv.cfg` rule above.
    """
    _fat_dir(tmp_path, "core", prefix="core")
    # A worktree marks itself with a `.git` FILE; a clone with a directory.
    # The fixture uses the shape that actually bit.
    _write(tmp_path, "nested/.git", "gitdir: /elsewhere" + chr(10))
    _fat_dir(tmp_path, "nested/core", prefix="core")
    _fat_dir(tmp_path, "nested/extra", prefix="extra")

    topics = wiki_plan.survey(tmp_path)

    assert _names(topics) == {"core"}, f"the nested checkout leaked: {_dirs(topics)}"
    assert all(not f.startswith("nested/") for t in topics for f in t.files)

    # DYNAMIC RANGE, the same control the venv probe carries: remove ONLY the
    # marker and the identical directories qualify again. Without it this
    # probe would also pass on a fixture that produced no topics at all.
    (tmp_path / "nested" / ".git").unlink()
    after = wiki_plan.survey(tmp_path)
    assert "extra" in _names(after), (
        "the fixture never had enough material to be excluded; this probe "
        f"proves nothing: {_dirs(after)}"
    )
