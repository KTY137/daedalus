# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Capturing the candidate's patch must not run the candidate's code.

THE VECTOR, found by an adversarial sweep and measured on this box before any
of it was fixed. `TaskAttempt._capture_patch` runs `git add -A` in the
candidate's worktree, AFTER the runner and BEFORE the gate, in the parent
process. `<worktree>/.gitattributes` is plain candidate content, it selects a
`filter.<name>.clean` program, and git runs that program.

It was worse than a launch. All three commands in `_capture_patch` returned 0,
the diff came back ~1.6 kB of plausible-looking output, the attempt reached
STATE_CLEAN, and the AttemptResult carried no error. Nothing anywhere would
have said a candidate-chosen program had executed.

Three separate properties close it and this file measures each one against its
own control:

  1. the admin directory is named on the command line, so rewriting
     `<worktree>/.git` to point at a candidate-authored gitdir does nothing;
  2. the system and user git config are removed from the lookup, so a filter
     defined THERE cannot be selected from inside the worktree;
  3. `--no-textconv`, which `--no-ext-diff` does not imply.

EVERY TEST HAS A CONTROL THAT SHOWS THE ATTACK WORKING. A refusal test with no
control proves only that something failed, and "the marker file is absent"
looks identical whether the guard worked or the probe was broken. In this repo
that is not a hypothetical concern: a whole evening's worth of guard tests were
green while the guard was disabled, because each was measuring itself.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.spine.attempt import _git, _git_env, _read_gitdir_pointer

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git is not on PATH")


def _run(args, cwd, env=None):
    return subprocess.run([str(a) for a in args], cwd=str(cwd),
                          capture_output=True, text=True, env=env)


@pytest.fixture
def arena(tmp_path):
    """A real repo with a real linked worktree, and a marker the attack writes.

    Nothing here is faked: `git worktree add` produces the same `.git` pointer
    file the product's worktree manager produces, which is the thing the attack
    rewrites.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-qm", "seed"], repo)

    wt = tmp_path / "wt"
    _run(["git", "worktree", "add", "-q", "-b", "cand", str(wt)], repo)
    assert (wt / ".git").is_file(), "expected a linked worktree pointer file"

    marker = tmp_path / "MARKER"
    payload = tmp_path / "payload.py"
    payload.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path(r'{marker}').write_text('EXECUTED', encoding='utf-8')\n"
        "sys.stdout.write(sys.stdin.read())\n",   # behave like a real clean filter
        encoding="utf-8")
    return {"repo": repo, "wt": wt, "marker": marker, "payload": payload,
            "tmp": tmp_path}


def _plant_candidate_gitdir(arena) -> None:
    """Everything a patch could carry: no prior code execution required.

    Measured during the sweep: a from-scratch static gitdir is enough. The
    candidate does not need to read or copy the real `.git`, and it does not
    need to clear the hidden attribute -- `open(p, "w")` fails on it, but
    `open(p, "r+")` succeeds.
    """
    wt, tmp = arena["wt"], arena["tmp"]
    mygit = wt / "mygit"
    (mygit / "objects" / "info").mkdir(parents=True, exist_ok=True)
    (mygit / "objects" / "pack").mkdir(parents=True, exist_ok=True)
    (mygit / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (mygit / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (mygit / "config").write_text(
        "[core]\n"
        f"\tworktree = {wt.as_posix()}\n"
        "[filter \"evil\"]\n"
        f"\tclean = \"{Path(sys.executable).as_posix()}\" "
        f"\"{arena['payload'].as_posix()}\"\n",
        encoding="utf-8")
    (wt / ".gitattributes").write_text("victim.txt filter=evil\n", encoding="utf-8")
    (wt / "victim.txt").write_text("content\n", encoding="utf-8")
    with open(wt / ".git", "r+", encoding="utf-8") as fh:   # NOT "w"
        fh.write(f"gitdir: {mygit.as_posix()}\n")
        fh.truncate()


# --------------------------------------------------------------------------- #
# 1. the rewritten gitdir pointer                                              #
# --------------------------------------------------------------------------- #
def test_CONTROL_the_attack_works_against_an_unpinned_git(arena):
    """Without this the refusal below proves nothing.

    This is the pre-fix call shape exactly: bare `git add -A` with cwd set to
    the worktree and no --git-dir.
    """
    _plant_candidate_gitdir(arena)
    proc = _run(["git", "add", "-A"], arena["wt"])
    assert arena["marker"].exists(), (
        "the attack did not fire, so this box cannot demonstrate the vector; "
        f"git said rc={proc.returncode} {proc.stderr[:200]!r}")
    assert proc.returncode == 0, "and it was silent, which is the dangerous part"


def test_naming_the_admin_directory_defeats_the_rewritten_pointer(arena):
    admin = _read_gitdir_pointer(arena["wt"])       # read BEFORE the attack
    assert admin is not None and admin.exists()
    _plant_candidate_gitdir(arena)                  # candidate rewrites .git
    _git(["add", "-A"], cwd=arena["wt"], repo_root=arena["repo"],
         git_dir=admin, work_tree=arena["wt"], check=False)
    assert not arena["marker"].exists(), (
        "a candidate-authored gitdir still supplied the filter git executed")


def test_the_pointer_is_read_before_the_candidate_can_move_it(arena):
    """Capture-then-use, not check-then-use.

    The value is taken while no candidate code has run. Re-resolving it later
    -- however carefully -- would be a window; taking it early removes one.
    """
    before = _read_gitdir_pointer(arena["wt"])
    _plant_candidate_gitdir(arena)
    after = _read_gitdir_pointer(arena["wt"])
    assert before != after, "the probe failed to move the pointer at all"
    assert "mygit" not in str(before)


# --------------------------------------------------------------------------- #
# 2. config the candidate did not have to write                                #
# --------------------------------------------------------------------------- #
def test_CONTROL_a_filter_in_the_USER_config_fires_from_gitattributes(
        arena, monkeypatch):
    """The variant needing no `.git` rewrite at all.

    On this machine `git config --list --show-origin` shows filter.lfs.* in
    both the system and the user config, so `* filter=lfs` in a candidate's
    .gitattributes is already enough to make `git add` spawn a program. This
    reproduces that shape with a filter under our own control rather than
    depending on git-lfs being installed.
    """
    cfg = arena["tmp"] / "evil.gitconfig"
    cfg.write_text(
        "[filter \"evil\"]\n"
        f"\tclean = \"{Path(sys.executable).as_posix()}\" "
        f"\"{arena['payload'].as_posix()}\"\n", encoding="utf-8")
    (arena["wt"] / ".gitattributes").write_text("victim.txt filter=evil\n",
                                                encoding="utf-8")
    (arena["wt"] / "victim.txt").write_text("content\n", encoding="utf-8")
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = str(cfg)
    _run(["git", "add", "-A"], arena["wt"], env=env)
    assert arena["marker"].exists(), (
        "the user-config variant did not fire; the guard test below would be "
        "measuring nothing")


def test_the_user_and_system_config_are_removed_from_the_lookup(arena, monkeypatch):
    cfg = arena["tmp"] / "evil.gitconfig"
    cfg.write_text(
        "[filter \"evil\"]\n"
        f"\tclean = \"{Path(sys.executable).as_posix()}\" "
        f"\"{arena['payload'].as_posix()}\"\n", encoding="utf-8")
    (arena["wt"] / ".gitattributes").write_text("victim.txt filter=evil\n",
                                                encoding="utf-8")
    (arena["wt"] / "victim.txt").write_text("content\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    admin = _read_gitdir_pointer(arena["wt"])
    _git(["add", "-A"], cwd=arena["wt"], repo_root=arena["repo"],
         git_dir=admin, work_tree=arena["wt"], check=False)
    assert not arena["marker"].exists(), (
        "a filter defined in the user config still fired")


def test_the_env_drops_variables_whose_empty_value_is_a_valid_command():
    """`GIT_EXTERNAL_DIFF=""` is not "no external diff" everywhere; absence is.

    Emptying is the intuitive move and it is the wrong one for this family, so
    the distinction is asserted rather than left to a reviewer's memory.
    """
    env = _git_env()
    for name in ("GIT_EXTERNAL_DIFF", "GIT_DIR", "GIT_WORK_TREE",
                 "GIT_INDEX_FILE", "GIT_SSH_COMMAND", "GIT_ASKPASS"):
        assert name not in env, f"{name} is present (value {env.get(name)!r})"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_ATTR_NOSYSTEM"] == "1"


def test_the_env_is_actually_passed_to_the_process(arena):
    """A hardened env built and then not used is the classic dead guard."""
    admin = _read_gitdir_pointer(arena["wt"])
    proc = _git(["config", "--show-origin", "--get-regexp", "filter\\..*"],
                cwd=arena["wt"], repo_root=arena["repo"], git_dir=admin,
                work_tree=arena["wt"], check=False)
    text = proc.stdout.decode("utf-8", "replace")
    assert ".gitconfig" not in text, (
        f"user config reached the process: {text[:300]}")


# --------------------------------------------------------------------------- #
# 3. textconv, which --no-ext-diff does not cover                              #
# --------------------------------------------------------------------------- #
def _plant_textconv(arena) -> Path:
    wt = arena["wt"]
    admin = _read_gitdir_pointer(wt)
    _run(["git", "config", "diff.evil.textconv",
          f'"{Path(sys.executable).as_posix()}" "{arena["payload"].as_posix()}"'],
         wt)
    (wt / ".gitattributes").write_text("victim.txt diff=evil\n", encoding="utf-8")
    (wt / "victim.txt").write_text("content\n", encoding="utf-8")
    _run(["git", "add", "-A"], wt)
    (wt / "victim.txt").write_text("changed\n", encoding="utf-8")
    return admin


def test_CONTROL_no_ext_diff_alone_still_spawns_a_textconv(arena):
    admin = _plant_textconv(arena)
    arena["marker"].unlink(missing_ok=True)
    _run(["git", "diff", "--cached", "--no-color", "--no-ext-diff",
          "--no-renames"], arena["wt"])
    assert arena["marker"].exists(), (
        "textconv did not fire under --no-ext-diff on this git build, so the "
        "guard test below would be vacuous")


def test_no_textconv_suppresses_it(arena):
    admin = _plant_textconv(arena)
    arena["marker"].unlink(missing_ok=True)
    _git(["diff", "--cached", "--no-color", "--no-ext-diff", "--no-textconv",
          "--no-renames"], cwd=arena["wt"], repo_root=arena["repo"],
         git_dir=admin, work_tree=arena["wt"], check=False)
    assert not arena["marker"].exists(), "a textconv program still ran"


def test_the_product_pins_no_textconv_in_the_option_list():
    """Belt and braces: the measurement above proves the flag works, this
    proves the product actually passes it."""
    import inspect

    from daedalus.spine.attempt import TaskAttempt

    src = inspect.getsource(TaskAttempt._capture_patch)
    body = src.split('"""')[-1]          # past the docstring
    assert '"--no-textconv"' in body


# --------------------------------------------------------------------------- #
# 4. config the candidate writes into the ADMIN directory                      #
# --------------------------------------------------------------------------- #
def _plant_admin_attributes(arena) -> Path:
    """The variant that survives removing the user and system config.

    Written into the SHARED repo config, not the per-worktree admin directory:
    a linked worktree's own `config` file is ignored unless
    `extensions.worktreeConfig` is enabled, which this repo does not set. That
    was measured while writing this test -- the first version planted the
    attack in the admin directory and it silently did nothing, which would have
    made the guard test below pass for entirely the wrong reason.

    `<repo>/.git/config` is inside the primary checkout, so an OS-contained
    candidate cannot reach it. Containment is not wired yet, and this vector
    runs in the parent process before any gate, so today nothing stops it.
    """
    admin = _read_gitdir_pointer(arena["wt"])
    attrs = arena["tmp"] / "sneaky.attributes"
    attrs.write_text("victim.txt filter=evil\n", encoding="utf-8")
    with open(arena["repo"] / ".git" / "config", "a", encoding="utf-8") as fh:
        fh.write(
            f"[core]\n\tattributesFile = {attrs.as_posix()}\n"
            "[filter \"evil\"]\n"
            f"\tclean = \"{Path(sys.executable).as_posix()}\" "
            f"\"{arena['payload'].as_posix()}\"\n")
    (arena["wt"] / "victim.txt").write_text("content\n", encoding="utf-8")
    return admin


def test_CONTROL_an_attributesFile_in_the_admin_config_fires(arena):
    admin = _plant_admin_attributes(arena)
    _run(["git", "--git-dir", str(admin), "--work-tree", str(arena["wt"]),
          "add", "-A"], arena["wt"], env=_git_env())
    assert arena["marker"].exists(), (
        "the admin-config variant did not fire even with the hardened env, so "
        "the -c pinning below would be measuring nothing")


def test_the_exec_config_keys_are_pinned_empty_on_the_command_line(arena):
    """`-c` beats every config file, which is the point: the admin config is
    reachable by a candidate today, and a config file cannot override -c."""
    admin = _plant_admin_attributes(arena)
    _git(["add", "-A"], cwd=arena["wt"], repo_root=arena["repo"],
         git_dir=admin, work_tree=arena["wt"], check=False)
    assert not arena["marker"].exists(), (
        "core.attributesFile from the admin config still selected a filter")


# --------------------------------------------------------------------------- #
# 5. the WIRING -- the guard reached through the product, not called directly  #
# --------------------------------------------------------------------------- #
def test_a_real_attempt_does_not_execute_the_candidates_filter(tmp_path):
    """End to end through TaskAttempt.run, with the runner AS the attacker.

    Every test above calls _git directly, which measures the guard and not the
    wiring. That distinction is not academic here: setting `self._admin_dir =
    None` left all of them green, because none of them went through run(). A
    guard that is built and not connected is the single most common defect this
    repo keeps finding in itself, and it would have shipped again.
    """
    from daedalus.spine.attempt import TaskAttempt
    from daedalus.spine.attempt import TaskSpec

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-qm", "seed"], repo)

    marker = tmp_path / "MARKER"
    payload = tmp_path / "payload.py"
    payload.write_text(
        f"import pathlib, sys\n"
        f"pathlib.Path(r'{marker}').write_text('EXECUTED', encoding='utf-8')\n"
        "sys.stdout.write(sys.stdin.read())\n", encoding="utf-8")

    def attacking_runner(ctx):
        """A runner that does what a hostile candidate would do."""
        wt = Path(ctx.worktree)
        mygit = wt / "mygit"
        (mygit / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (mygit / "objects" / "pack").mkdir(parents=True, exist_ok=True)
        (mygit / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        (mygit / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
        (mygit / "config").write_text(
            f"[core]\n\tworktree = {wt.as_posix()}\n"
            "[filter \"evil\"]\n"
            f"\tclean = \"{Path(sys.executable).as_posix()}\" "
            f"\"{payload.as_posix()}\"\n", encoding="utf-8")
        (wt / ".gitattributes").write_text("victim.txt filter=evil\n",
                                           encoding="utf-8")
        (wt / "victim.txt").write_text("content\n", encoding="utf-8")
        with open(wt / ".git", "r+", encoding="utf-8") as fh:
            fh.write(f"gitdir: {mygit.as_posix()}\n")
            fh.truncate()
        return {"note": "planted"}

    att = TaskAttempt(
        TaskSpec(task_id="t-attack", instruction="i"),
        runner=attacking_runner, repo_root=str(repo),
        gate=lambda ctx: True)
    res = att.run()

    assert not marker.exists(), (
        f"a real attempt executed the candidate's filter (state={res.state})")
    # And the attempt still WORKED -- otherwise this would pass for the wrong
    # reason, e.g. because the run died before reaching _capture_patch.
    assert res.artifact is not None, f"no patch captured (state={res.state})"
    assert res.artifact.changed_paths, "the patch was empty"


# --------------------------------------------------------------------------- #
# the allow side                                                               #
# --------------------------------------------------------------------------- #
def test_an_ordinary_patch_is_still_captured_correctly(arena):
    """A hardening that broke patch capture would pass every test above."""
    admin = _read_gitdir_pointer(arena["wt"])
    (arena["wt"] / "new.py").write_text("x = 1\n", encoding="utf-8")
    (arena["wt"] / "seed.txt").write_text("seed\nmore\n", encoding="utf-8")
    _git(["add", "-A"], cwd=arena["wt"], repo_root=arena["repo"],
         git_dir=admin, work_tree=arena["wt"])
    out = _git(["diff", "--cached", "--no-color", "--no-ext-diff",
                "--no-textconv", "--no-renames", "--name-only", "-z"],
               cwd=arena["wt"], repo_root=arena["repo"],
               git_dir=admin, work_tree=arena["wt"]).stdout
    names = {p.decode() for p in out.split(b"\0") if p}
    assert names == {"new.py", "seed.txt"}, names
