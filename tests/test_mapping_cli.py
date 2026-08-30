# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""`daedalus map` -- the command that produces the architecture artifact.

What is pinned here is the set of properties that make the artifact trustworthy
rather than merely present:

  * ``--json`` and ``--check`` write NOTHING. A gate with a side effect is a
    gate that quietly re-baselines what it was asked to complain about.
  * ``--check`` exits non-zero on unaccepted drift and zero when clean.
  * The page is self-contained: no external ``src``/``href``, so a strict CSP
    (and an offline machine) render exactly what was generated.
  * Everything agent-authored is escaped. Module docstrings, acceptance prose
    and the narrative file are all written by agents, and a map that executes
    what an agent wrote into a docstring is worse than a stale one.
  * A MISSING narrative renders every hand-written section as explicitly
    ABSENT. A section that silently vanishes is indistinguishable from one
    nobody ever wrote, which is precisely how the hand inventory rotted.
  * The staleness stamp is present and reports the fixture's own revision.

Every fixture is a real (tiny) source tree. Nothing here touches the network, a
model, a vendor CLI, or the developer's own cache or snapshot.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from daedalus.mapping import drift, render

FIXTURE_SHA = "1234abcd5678ef901234abcd5678ef901234abcd"
FIXTURE_BRANCH = "fixture-branch"

BASE = {
    "pyproject.toml": '[project]\nname = "pkg"\n\n[project.scripts]\npkg = "pkg.cli:main"\n',
    "pkg/__init__.py": "from pkg import wired\n",
    "pkg/wired.py": "from pkg import deep\nVALUE = 1\n",
    "pkg/deep.py": "VALUE = 2\n",
    "pkg/cli.py": "from pkg import clionly\n\n\ndef main():\n    return 0\n",
    "pkg/clionly.py": "X = 1\n",
    "tests/test_main.py": "from pkg import wired\n",
    "docs/notes.md": "# notes\n",
}

NARRATIVE = """# narrative

## The state {#state}

> Small, honest, and mostly a fixture.

## How to read it {#reading}

Two halves. One derived, one written.

## The kitchen {#kitchen}

| Rolle | Existiert als |
| --- | --- |
| waiter | `pkg/cli.py` |

## The areas {#areas}

### Surfaces

**Realitat.** The CLI is the surface.

## The reversals {#reversals}

### A claim that did not survive

- **measured** -- it did not.

## Drift {#drift}

- one hand-evidenced entry.

## Blockers {#blockers}

- nothing blocking.

## The invariants {#invariants}

- fail closed where it costs money or bytes.

## A section with no key

Rendered anyway, because dropping what somebody wrote is the one behaviour
this file must not have.
"""


def mk(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def fake_git(root: Path, sha: str = FIXTURE_SHA, branch: str = FIXTURE_BRANCH) -> None:
    """A .git with just enough in it to be read. The revision reader walks
    HEAD/refs/packed-refs directly and never shells out, which is what makes it
    testable without a git binary."""
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    (git / "refs" / "heads" / branch).write_text(sha + "\n", encoding="utf-8")


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    # Point the structcore cache at the sandbox: a test must never write into
    # the developer's real cache, and must never read a warm entry from it.
    monkeypatch.setenv("DAEDALUS_CACHE_DIR", str(tmp_path / "cache"))
    root = mk(tmp_path / "repo", dict(BASE))
    mk(root, {render.NARRATIVE_REL: NARRATIVE})
    fake_git(root)
    return root


def run(root: Path, *args: str) -> int:
    """--no-git skips only the dirty PROBE (which would shell out); the
    revision and branch still come from the fixture's .git."""
    return render.main(["--repo", str(root), "--no-git", *args])


def snapshot(root: Path) -> Path:
    return root / drift.SNAPSHOT_REL


def page(root: Path) -> str:
    return (root / render.MAP_REL).read_text(encoding="utf-8")


def listing(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix()
            for p in root.rglob("*") if p.is_file()}


# ------------------------------------------------------------------ --json

def test_json_is_parseable_and_carries_both_halves(repo, capsys):
    assert run(repo, "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema"] == render.SCHEMA
    assert data["counts"]["modules"] >= 6
    assert data["narrative"]["present"] is True
    assert data["narrative"]["missing"] == []
    assert "text" in data["gate"]


def test_json_writes_nothing(repo, capsys):
    before = listing(repo)
    assert run(repo, "--json") == 0
    capsys.readouterr()
    assert listing(repo) == before
    assert not snapshot(repo).exists()


def test_json_counts_agree_with_the_module_list(repo, capsys):
    """The 136-vs-827 failure mode in miniature: a headline number that no
    longer matches the list beside it."""
    run(repo, "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["modules"] == len(data["reach"]["modules"])
    per_class = {}
    for m in data["reach"]["modules"]:
        per_class[m["classification"]] = per_class.get(m["classification"], 0) + 1
    for cls, n in per_class.items():
        assert data["counts"][cls] == n


# ------------------------------------------------------------------ --check

def test_check_without_a_baseline_fails_and_says_so(repo, capsys):
    """Gate mode writes nothing, so it cannot create the baseline it is
    missing. Reporting OK against nothing is the failure this exists to
    prevent -- ``drift.check`` may call a first run clean because it writes
    one; ``--check`` may not."""
    assert run(repo, "--check") == 1
    out = capsys.readouterr().out
    assert "No baseline" in out
    assert "daedalus map" in out
    assert not snapshot(repo).exists()


def test_check_is_clean_immediately_after_a_write(repo, capsys):
    assert run(repo) == 0
    capsys.readouterr()
    assert run(repo, "--check") == 0
    assert "no drift against the snapshot" in capsys.readouterr().out


def test_check_exits_non_zero_on_unaccepted_new_island(repo, capsys):
    run(repo)
    capsys.readouterr()
    # No test imports it either: the gate's island rule counts a module
    # reached only by its own test as REACHED, deliberately (drift.py), which
    # is a stricter rule than the reachability table's on the same page.
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    assert run(repo, "--check") == 1
    out = capsys.readouterr().out
    assert drift.NEW_ISLAND in out
    assert "pkg/lonely.py" in out


def test_check_writes_nothing_even_when_drift_exists(repo, capsys):
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    before = snapshot(repo).read_text(encoding="utf-8")
    listing_before = listing(repo)
    assert run(repo, "--check") == 1
    capsys.readouterr()
    assert snapshot(repo).read_text(encoding="utf-8") == before
    assert listing(repo) == listing_before


def test_check_passes_once_the_island_is_accepted(repo, capsys):
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    assert run(repo, "--check") == 1
    capsys.readouterr()

    assert run(repo, "--accept", "island:pkg/lonely.py",
               "--why", "wiring lands in the follow-up commit",
               "--who", "kaya") == 0
    capsys.readouterr()
    assert run(repo, "--check") == 0
    assert "Nothing blocking" in capsys.readouterr().out


# ----------------------------------------------------------------- --accept

def test_accept_refuses_a_reason_that_is_not_one(repo, capsys):
    run(repo)
    capsys.readouterr()
    before = snapshot(repo).read_text(encoding="utf-8")
    assert run(repo, "--accept", "island:pkg/lonely.py", "--why", "wip") == 1
    assert "refused" in capsys.readouterr().out
    assert snapshot(repo).read_text(encoding="utf-8") == before


def test_accept_refuses_a_horizon_beyond_the_cap(repo, capsys):
    run(repo)
    capsys.readouterr()
    assert run(repo, "--accept", "island:pkg/lonely.py",
               "--why", "waiting on the era-4 sweep",
               "--until", "2099-01-01") == 1
    assert "cap" in capsys.readouterr().out


def test_accept_does_not_re_baseline_unrelated_drift(repo, capsys):
    """Recording a reason for ONE item must not quietly bank everything else
    that moved since the baseline was taken."""
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n",
              "pkg/other.py": "VALUE = 4\n"})
    assert run(repo, "--accept", "island:pkg/lonely.py",
               "--why", "wiring lands in the follow-up commit") == 0
    capsys.readouterr()
    doc = json.loads(snapshot(repo).read_text(encoding="utf-8"))
    assert "pkg/other.py" not in doc["islands"]
    assert run(repo, "--check") == 1
    assert "pkg/other.py" in capsys.readouterr().out


def test_accept_without_a_snapshot_refuses(repo, capsys):
    assert run(repo, "--accept", "island:pkg/lonely.py",
               "--why", "wiring lands in the follow-up commit") == 1
    assert "no snapshot" in capsys.readouterr().out


# --------------------------------- BYPASS: --accept as a snapshot laundry
#
# CONFIGURATION for this block: ``render.main([...])`` -- the shipped commands,
# nothing else. No Python, no hand-computed hash. That is the whole point: the
# measured attack used three published verbs in order.

def test_accept_refuses_to_inherit_a_snapshot_whose_digest_does_not_verify(repo, capsys):
    """The measured three-step laundry, end to end.

    STEP 1 hand-edit the snapshot: add a real island to ``islands`` and
           ``modules``, bump the counts -> ``--check`` EXIT 1, INVALID SNAPSHOT.
    STEP 2 ``--accept`` any unrelated item. accept() carried the mechanical
           lists over VERBATIM and write_snapshot re-signed them unconditionally.
    STEP 3 ``--check`` -> EXIT 0, "Nothing blocking." The hand-edit is now
           covered by a valid digest and the real island is never reported.

    accept() now verifies the digest it is about to inherit and writes nothing
    on a mismatch, so step 2 fails and step 3 still reports the edit.
    """
    run(repo)
    capsys.readouterr()
    # a genuinely unreached module, plus a decoy for the acceptance to land on
    mk(repo, {"pkg/secret.py": "VALUE = 9\n", "pkg/decoy.py": "VALUE = 8\n"})

    # STEP 1 -- hand-edit, exactly as a text editor would
    doc = json.loads(snapshot(repo).read_text(encoding="utf-8"))
    doc["modules"] = sorted(doc["modules"] + ["pkg/secret.py"])
    doc["islands"] = sorted(doc["islands"] + ["pkg/secret.py"])
    doc["counts"]["modules"] = len(doc["modules"])
    doc["counts"]["islands"] = len(doc["islands"])
    doc["counts"]["unreached"] = doc["counts"]["islands"]
    snapshot(repo).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    assert run(repo, "--check") == 1
    assert drift.INVALID_SNAPSHOT in capsys.readouterr().out
    edited = snapshot(repo).read_text(encoding="utf-8")

    # STEP 2 -- the laundry verb. It must refuse, and write nothing.
    assert run(repo, "--accept", "island:pkg/decoy.py",
               "--why", "decoy is wired in the next commit") == 1
    out = capsys.readouterr().out
    assert "refused" in out
    assert "hand-edited" in out
    assert snapshot(repo).read_text(encoding="utf-8") == edited, (
        "a refused acceptance must not touch the file at all")

    # STEP 3 -- and the finding is still there
    assert run(repo, "--check") == 1
    out = capsys.readouterr().out
    assert drift.INVALID_SNAPSHOT in out
    assert "Nothing blocking." not in out


def test_accept_still_works_on_an_honest_snapshot(repo, capsys):
    """The refusal must not be a blanket one, or the Tier-1 path is gone."""
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    assert run(repo, "--accept", "island:pkg/lonely.py",
               "--why", "wiring lands in the follow-up commit") == 0
    capsys.readouterr()
    doc = json.loads(snapshot(repo).read_text(encoding="utf-8"))
    assert doc[drift.DIGEST_KEY] == drift._digest(doc)
    assert run(repo, "--check") == 0


def test_accept_refuses_a_snapshot_from_another_schema(repo, capsys):
    """Lists written by a different engine must not be carried forward under a
    digest computed by this one -- that is the same laundry with an extra step."""
    run(repo)
    capsys.readouterr()
    doc = json.loads(snapshot(repo).read_text(encoding="utf-8"))
    doc["schema"] = 2
    doc[drift.DIGEST_KEY] = drift._digest(doc)      # signed, and still refused
    snapshot(repo).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    before = snapshot(repo).read_text(encoding="utf-8")
    assert run(repo, "--accept", "island:pkg/lonely.py",
               "--why", "wiring lands in the follow-up commit") == 1
    assert "schema" in capsys.readouterr().out
    assert snapshot(repo).read_text(encoding="utf-8") == before


# -------------------------------------------------------------------- write

def test_default_run_writes_the_page_and_the_snapshot(repo, capsys):
    assert run(repo) == 0
    out = capsys.readouterr().out
    assert (repo / render.MAP_REL).is_file()
    assert snapshot(repo).is_file()
    assert "re-baselined" in out


def test_default_run_prints_the_drift_before_re_baselining_it(repo, capsys):
    """Re-baselining is Tier 2 acceptance. Tier 2 has teeth only if the human
    running the command is shown what moved."""
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    assert run(repo) == 0
    out = capsys.readouterr().out
    assert drift.NEW_ISLAND in out
    assert "pkg/lonely.py" in out
    doc = json.loads(snapshot(repo).read_text(encoding="utf-8"))
    assert "pkg/lonely.py" in doc["islands"]


def test_the_page_never_reads_its_own_output_back(repo, capsys):
    """The generator parses the NARRATIVE file, never the previous HTML, which
    is what makes it impossible for regeneration to eat hand-written prose."""
    run(repo)
    capsys.readouterr()
    first = page(repo)
    assert "A claim that did not survive" in first
    run(repo)
    capsys.readouterr()
    assert "A claim that did not survive" in page(repo)


# --------------------------------------------------------- self-containment

def test_page_has_no_external_src_or_href(repo, capsys):
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert re.findall(r"\ssrc\s*=", html) == []
    hrefs = re.findall(r'\shref\s*=\s*"([^"]*)"', html)
    assert hrefs, "the page should still carry its internal nav"
    assert all(h.startswith("#") for h in hrefs), hrefs
    for forbidden in ("<link", "<iframe", "@import", "url("):
        assert forbidden not in html


def test_page_carries_both_themes_and_lets_the_toggle_win(repo, capsys):
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "@media (prefers-color-scheme:dark)" in html
    assert ':root[data-theme="dark"]' in html
    assert ':root[data-theme="light"]' in html


def test_status_vocabulary_is_on_the_page_with_its_meanings(repo, capsys):
    run(repo)
    capsys.readouterr()
    html = page(repo)
    for slug, label, meaning in render.STATUS_VOCAB:
        assert f'class="chip s-{slug}"' in html
        assert meaning.split(" -- ")[0][:40] in html


# ---------------------------------------------------------------- escaping

def test_agent_authored_html_in_source_is_escaped(repo, capsys):
    mk(repo, {"pkg/nasty.py":
              '"""<script>alert("island")</script> & <img src=x>."""\n'
              "VALUE = 5\n"})
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "<script>alert(" not in html
    assert "<img src=x>" not in html
    assert re.findall(r"\ssrc\s*=", html) == []


def test_agent_authored_html_in_the_narrative_is_escaped(repo, capsys):
    mk(repo, {render.NARRATIVE_REL:
              NARRATIVE + '\n## Injected {#extra1}\n\n'
                          '<script>alert(1)</script> and <a href="http://x">x</a>\n'})
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'href="http://x"' not in html


def test_acceptance_prose_is_escaped(repo, capsys):
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    run(repo, "--accept", "island:pkg/lonely.py",
        "--why", 'pending <script>alert("why")</script>')
    capsys.readouterr()
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert '<script>alert("why")</script>' not in html
    assert "&lt;script&gt;" in html


def test_inline_markup_cannot_smuggle_a_tag(repo, capsys):
    """Escaping happens BEFORE inline markup is applied, so the only tags in
    the output are the ones the renderer put there."""
    out = render._inline("`<b>x</b>` and **<i>y</i>**")
    assert out == "<code>&lt;b&gt;x&lt;/b&gt;</code> and <strong>&lt;i&gt;y&lt;/i&gt;</strong>"


# --------------------------------------------------------------- narrative

def test_missing_narrative_marks_every_section_absent(repo, capsys):
    (repo / render.NARRATIVE_REL).unlink()
    assert run(repo) == 0
    out = capsys.readouterr().out
    html = page(repo)
    assert "narrative: ABSENT" in out
    for key, title in render.NARRATIVE_SECTIONS:
        assert f'id="n-{key}"' in html
    assert html.count("<strong>ABSENT</strong>") == len(render.NARRATIVE_SECTIONS)
    assert "does not exist" in html


def test_a_single_missing_section_is_absent_not_omitted(repo, capsys):
    text = (repo / render.NARRATIVE_REL).read_text(encoding="utf-8")
    mk(repo, {render.NARRATIVE_REL: text.replace("{#invariants}", "{#something-else}")})
    assert run(repo) == 0
    assert "MISSING invariants" in capsys.readouterr().out
    html = page(repo)
    assert 'id="n-invariants"' in html
    assert html.count("<strong>ABSENT</strong>") == 1
    assert "{#invariants}" in html or "n-invariants" in html


def test_a_keyless_section_still_renders(repo, capsys):
    run(repo)
    capsys.readouterr()
    assert "A section with no key" in page(repo)


def test_narrative_sections_are_addressed_by_key_not_by_wording(repo, capsys):
    text = (repo / render.NARRATIVE_REL).read_text(encoding="utf-8")
    mk(repo, {render.NARRATIVE_REL:
              text.replace("## The invariants {#invariants}",
                           "## Voellig andere Ueberschrift {#invariants}")})
    assert run(repo) == 0
    assert "MISSING" not in capsys.readouterr().out
    html = page(repo)
    assert "Voellig andere Ueberschrift" in html
    assert "fail closed where it costs money or bytes" in html


def test_narrative_markdown_subset_renders(repo, capsys):
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "<code>pkg/cli.py</code>" in html          # inline code in a table
    assert "<strong>Realitat.</strong>" in html       # bold
    assert "<th>Rolle</th>" in html                   # table header
    assert "<li>one hand-evidenced entry.</li>" in html


# ------------------------------------------------------------------- stamp

def test_stamp_reflects_the_fixture_revision(repo, capsys):
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert FIXTURE_SHA[:12] in html
    assert FIXTURE_BRANCH in html
    assert "generated" in html


def test_stamp_reads_a_packed_ref(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_CACHE_DIR", str(tmp_path / "cache"))
    root = mk(tmp_path / "repo", dict(BASE))
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/packed\n", encoding="utf-8")
    (git / "packed-refs").write_text(
        f"# pack-refs with: peeled\n{FIXTURE_SHA} refs/heads/packed\n",
        encoding="utf-8")
    stamp = render.git_stamp(root, probe_dirty=False)
    assert stamp.revision == FIXTURE_SHA
    assert stamp.branch == "packed"


def test_stamp_degrades_to_unknown_without_a_repo(tmp_path):
    stamp = render.git_stamp(tmp_path, probe_dirty=False)
    assert stamp.revision == "unknown"
    assert stamp.branch == "unknown"
    assert stamp.dirty == "unknown"
    assert stamp.generated_at


def test_dirty_tree_is_stated_on_the_page(repo, capsys):
    data = render.build(
        repo, narrative_path=repo / render.NARRATIVE_REL,
        snapshot_path=snapshot(repo),
        stamp=render.Stamp(generated_at="2026-07-28 12:00:00Z",
                           revision=FIXTURE_SHA, branch=FIXTURE_BRANCH,
                           dirty="dirty", dirty_paths=43))
    html = render.render_html(data, render.load_narrative(repo / render.NARRATIVE_REL))
    assert "DIRTY" in html
    assert "43 paths" in html


def test_build_writes_nothing(repo):
    before = listing(repo)
    render.build(repo, narrative_path=repo / render.NARRATIVE_REL,
                 snapshot_path=snapshot(repo), probe_dirty=False)
    assert listing(repo) == before


# --------------------------------------------------- ONE ENGINE on the page

def test_the_page_and_the_gate_never_run_two_analyses(repo, capsys, monkeypatch):
    """H5, at the plumbing level. The page ran ``reach.analyse`` and
    ``switches.analyse``; the gate then ran its OWN scanners; the default run
    re-baselined with a third. They disagreed, and the page printed prose
    reconciling the gap. One walk, handed to all three."""
    from daedalus.mapping import reach as reach_mod, switches as switches_mod
    calls = {"reach": 0, "switches": 0}
    real_reach, real_switches = reach_mod.analyse, switches_mod.analyse

    def counted_reach(*a, **k):
        calls["reach"] += 1
        return real_reach(*a, **k)

    def counted_switches(*a, **k):
        calls["switches"] += 1
        return real_switches(*a, **k)

    monkeypatch.setattr(reach_mod, "analyse", counted_reach)
    monkeypatch.setattr(switches_mod, "analyse", counted_switches)
    assert run(repo) == 0            # render + gate + re-baseline, one command
    capsys.readouterr()
    assert calls == {"reach": 1, "switches": 1}, calls


def test_the_reconciliation_is_arithmetic_not_prose(repo, capsys):
    """The block that used to explain the 6-vs-11 island gap predicted the
    gate's number would be SMALLER; it was nearly twice as large. Every number
    in it is now a subtraction over the same walk, so it cannot say something
    the data does not."""
    run(repo, "--json")
    data = json.loads(capsys.readouterr().out)
    counts = data["counts"]
    gate_state = data["gate"]["state"]

    assert counts["gate_islands"] == counts["island"] + counts["orphan"]
    assert counts["gate_islands"] == len(gate_state["islands"])
    assert counts["gate_test_only"] == len(gate_state["test_only"])
    assert counts["gate_test_only"] <= counts["gate_islands"]
    assert counts["gate_dark_switches"] <= counts["dark_env_switches"]

    # the dark subtraction has to name BOTH reasons; lumping them together
    # invites the reader to assume one, and they have different arguments
    from daedalus.mapping.drift import DocIndex
    docs = DocIndex.build(repo)
    dark = [s for s in data["switches"]["env_switches"] if s["dark"]]
    secrets = [s for s in dark if s["kind"] == "secret"]
    documented = [s for s in dark
                  if s["kind"] != "secret" and docs.documents(s["name"])]
    assert (len(dark) - len(secrets) - len(documented)
            == counts["gate_dark_switches"])

    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "the gate against this page" in html
    assert "TWO ISLAND RULES" not in html, "the stale reconciliation prose"
    assert "TWO DARK-SWITCH RULES" not in html
    assert "ONE ENGINE." in html


def test_gate_and_page_agree_on_the_island_set(repo, capsys):
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n"})
    run(repo, "--json")
    data = json.loads(capsys.readouterr().out)
    page_islands = {m["module"] for m in data["reach"]["modules"]
                    if m["classification"] in ("island", "orphan")}
    assert page_islands == set(data["gate"]["state"]["islands"])
    assert "pkg/lonely.py" in page_islands


# ------------------------------ FALSE REACHABLE, ON THE SHIPPED CODE PATH
#
# CONFIGURATION for this block: ``render.main([...])`` with NO ``--index`` of
# any kind, i.e. exactly what a human types. That matters more than it sounds:
# ``render.analyse_once`` reads ``index=None`` as "build one yourself" and
# calls ``structcore.cached_index(refresh=True)``, so a REAL structural index
# is always present. The guard tests for these properties lived in
# tests/test_mapping_reach.py in the one arrangement that never ships --
# ``analyse(root)`` with no index -- and passed while the shipped path printed
# the opposite answer.

def test_daedalus_map_does_not_call_a_dead_branch_import_reachable(repo, capsys):
    """Measured: ``if False: from pkg import secret`` inside the entry module.
    The page said ``classification: reachable / entry: script:pkg / depth 1``
    while, further down the same page, printing "a module whose only importers
    are these is unknown, never reachable"."""
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/cli.py": ("from pkg import clionly\n\nif False:\n"
                             "    from pkg import secret\n\n\ndef main():\n"
                             "    return 0\n")})
    assert run(repo, "--json") == 0
    data = json.loads(capsys.readouterr().out)

    facts = {m["module"]: m for m in data["reach"]["modules"]}["pkg/secret.py"]
    assert facts["classification"] == "unknown", facts
    assert facts["entry"] == ""
    assert facts["path"] == []
    assert "pkg/cli.py" not in facts["imported_by"]
    assert any("pkg/cli.py -> pkg/secret.py" in w
               for w in data["reach"]["weak_edges"])
    # the real structcore index DOES carry this edge -- which is precisely why
    # unioning it was fatal -- and it is reported, not merged
    assert "pkg/cli.py -> pkg/secret.py" in data["reach"]["index_extra_edges"]


def test_daedalus_map_check_blocks_on_a_dead_branch_import(repo, capsys):
    """The same route, at the exit code. It was EXIT 0."""
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/cli.py": ("from pkg import clionly\n\nif False:\n"
                             "    from pkg import secret\n\n\ndef main():\n"
                             "    return 0\n")})
    assert run(repo, "--check") == 1
    out = capsys.readouterr().out
    assert drift.NEW_UNKNOWN in out
    assert "pkg/secret.py" in out


def test_daedalus_map_check_blocks_on_a_new_unreached_shim(repo, capsys):
    """The fourth measured route: a module that only re-exports."""
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/oldname.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n"})
    assert run(repo, "--check") == 1
    out = capsys.readouterr().out
    assert drift.NEW_SHIM in out
    assert "pkg/oldname.py" in out


def test_the_page_does_not_promise_something_the_code_no_longer_does(repo, capsys):
    """The two false guarantees that were PRINTED ON THE ARTIFACT. A reader
    trusts a generated page precisely because it is generated, so a sentence
    on it that the code does not enforce is the worst kind of stale."""
    mk(repo, {"pkg/secret.py": "VALUE = 9\n",
              "pkg/cli.py": ("from pkg import clionly\n\nif False:\n"
                             "    from pkg import secret\n\n\ndef main():\n"
                             "    return 0\n")})
    run(repo)
    capsys.readouterr()
    html = page(repo)

    # guarantee 1: weak edges never make a module reachable -- now qualified
    # with the configuration it holds in, which is the one that ships
    assert "never" in html and "<code>reachable</code>" in html
    assert "which is every run of <code>daedalus map</code>" in html
    # guarantee 2: index-extra edges are not in the walk -- they used to be
    assert "are NOT in this walk" in html
    assert "missing from this walk" not in html
    # and the page agrees with itself about this module
    assert "pkg/secret.py" in html
    row = html.split("pkg/secret.py", 1)[1][:400]
    assert "s-unknown" in row, row


def test_the_page_adds_up_to_the_honest_unreached_total(repo, capsys):
    """The arithmetic. ``islands`` is one of three unreached lists, and the page
    printed only it -- on this fixture it would have said 1 where the truth is
    3."""
    mk(repo, {"pkg/orphan.py": "VALUE = 9\n",
              "pkg/oldname.py": "from pkg.deep import VALUE\n\n__all__ = ['VALUE']\n",
              "pkg/secret.py": "VALUE = 9\n",
              "pkg/wired.py": "from pkg import deep\nNOTE = 'pkg.secret'\n"})
    assert run(repo, "--json") == 0
    data = json.loads(capsys.readouterr().out)
    counts = data["counts"]

    assert counts["gate_unreached"] == 3
    assert counts["gate_unreached"] == (counts["gate_islands"]
                                        + counts["gate_unknown"]
                                        + counts["gate_shims"])
    assert counts["gate_unreached"] == (counts["island"] + counts["orphan"]
                                        + counts["unknown"] + counts["shim"])

    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "unreached (nothing gets here)" in html
    assert "UNREACHED, the honest total" in html
    assert "pkg/oldname.py" in html and "pkg/secret.py" in html


# ------------------------------------------------- reached only by a test

def test_a_test_only_module_gets_its_own_class_on_the_page(repo, capsys):
    """H4. A module reached only by its own test used to be silently green:
    the gate counted the test as wiring and printed nothing at all."""
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n",
              "tests/test_lonely.py": "from pkg import lonely\n"})
    run(repo, "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["gate"]["state"]["test_only"] == ["pkg/lonely.py"]
    assert data["counts"]["gate_test_only"] == 1

    run(repo)
    out = capsys.readouterr().out
    html = page(repo)
    assert "reached only by their own tests" in html
    assert "tests/test_lonely.py" in html
    assert "test-only 1" in out or "test-only 1)" in out


def test_a_test_only_module_does_not_fail_the_gate(repo, capsys):
    run(repo)
    capsys.readouterr()
    mk(repo, {"pkg/lonely.py": "VALUE = 3\n",
              "tests/test_lonely.py": "from pkg import lonely\n"})
    assert run(repo, "--check") == 0, "the rule is KEPT: a test is intent"
    out = capsys.readouterr().out
    # kept, but no longer silent: named kind, named module, counted
    assert drift.TEST_ONLY in out
    assert "pkg/lonely.py" in out
    assert "test_only=1" in out
    assert drift.NEW_ISLAND not in out
    assert "Nothing blocking" in out


# ------------------------------------------------ broken declared entry point

def test_a_dead_console_script_is_named_on_the_page(repo, capsys):
    mk(repo, {"pyproject.toml": BASE["pyproject.toml"]
              + 'ghost = "pkg.clionly:nosuchfunc"\n'})
    run(repo, "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["broken_entries"] == 1
    assert any("nosuchfunc" in b for b in data["reach"]["broken_entries"])

    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "declared entry points that cannot be taken" in html
    assert "nosuchfunc" in html


# ------------------------------------------------------------- the stamp

def test_the_stamp_does_not_claim_a_revision_it_did_not_verify(repo, capsys):
    """M2. The page stamped "rev X / tree clean / gate OK" while rendering a
    module and a switch that were in NEITHER that revision NOR git's view --
    ``git status`` reports what git TRACKS, and the scanner reads the
    filesystem. The fixture has no git binary answer at all, so the stamp must
    say it could not verify rather than implying it did."""
    run(repo)
    capsys.readouterr()
    html = page(repo)
    assert "is not a description of revision" in html
    assert "could not be determined" in html


def test_the_stamp_counts_scanned_files_git_does_not_track(tmp_path, monkeypatch, capsys):
    """The measured hole: a module hidden from git via .git/info/exclude is
    invisible to the dirty probe and fully visible to the scanner."""
    git = shutil.which("git")
    if not git:
        pytest.skip("git binary not available")
    monkeypatch.setenv("DAEDALUS_CACHE_DIR", str(tmp_path / "cache"))
    root = mk(tmp_path / "repo", dict(BASE))
    mk(root, {render.NARRATIVE_REL: NARRATIVE})
    sub = lambda *a: subprocess.run([git, *a], cwd=str(root),
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, check=True)
    sub("init")
    sub("add", "-A")
    stamp = render.git_stamp(root, scanned=sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.py")))
    assert stamp.untracked_scanned == 0

    # now the exact bypass: a module git is told to ignore
    (root / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (root / ".git" / "info" / "exclude").write_text("hidden.py\n", encoding="utf-8")
    mk(root, {"pkg/hidden.py": "VALUE = 1\n"})
    scanned = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py"))
    assert "pkg/hidden.py" in scanned
    stamp = render.git_stamp(root, scanned=scanned)
    assert stamp.untracked_scanned == 1
    assert stamp.untracked_sample == ("pkg/hidden.py",)
    assert stamp.describes_revision is False
    assert "1 scanned modules untracked" in stamp.one_line()


def test_a_clean_verified_tree_may_claim_its_revision(repo):
    stamp = render.Stamp(generated_at="2026-07-28 12:00:00Z", revision=FIXTURE_SHA,
                         branch=FIXTURE_BRANCH, dirty="clean", dirty_paths=0,
                         untracked_scanned=0)
    assert stamp.describes_revision is True
    data = render.build(repo, narrative_path=repo / render.NARRATIVE_REL,
                        snapshot_path=snapshot(repo), stamp=stamp)
    html = render.render_html(data, render.load_narrative(repo / render.NARRATIVE_REL))
    assert "what this page describes is revision" in html
    assert "is not a description of revision" not in html


# ------------------------------------------------------------- determinism

def test_two_runs_over_an_unchanged_tree_agree(repo, capsys):
    kw = dict(narrative_path=repo / render.NARRATIVE_REL,
              snapshot_path=snapshot(repo), probe_dirty=False,
              stamp=render.Stamp(generated_at="2026-07-28 12:00:00Z",
                                 revision=FIXTURE_SHA, branch=FIXTURE_BRANCH,
                                 dirty="clean", dirty_paths=0))
    narrative = render.load_narrative(repo / render.NARRATIVE_REL)
    first = render.render_html(render.build(repo, **kw), narrative)
    second = render.render_html(render.build(repo, **kw), narrative)
    assert first == second
