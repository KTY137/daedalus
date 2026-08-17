"""daedalus.dotenv -- fills gaps in os.environ from a .env file, and refuses
to load one git tracks.

The git-tracked-file case uses a REAL git repo (skipped if git is not on
PATH), matching this repo's own convention in
test_git_is_a_process_launcher.py: mocking `git ls-files` would only prove
the mock says what we told it to say, not that the refusal actually fires
against real git output.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from daedalus.dotenv import DotEnvRefused, describe, load, parse


def _run(args, cwd):
    return subprocess.run([str(a) for a in args], cwd=str(cwd),
                          capture_output=True, text=True)


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


@pytest.fixture
def repo(tmp_path):
    """A real git repo -- so `_is_git_tracked` runs real `git ls-files`."""
    if not _git_available():
        pytest.skip("git is not on PATH")
    r = tmp_path / "repo"
    r.mkdir()
    _run(["git", "init", "-q"], r)
    _run(["git", "config", "user.email", "test@example.com"], r)
    _run(["git", "config", "user.name", "test"], r)
    return r


# ===========================================================================
# rule 1 -- a real export always wins; the file only fills gaps
# ===========================================================================

def test_a_real_export_is_never_overridden_by_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_DOTENV_T_EXPORT", "from-the-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("DAEDALUS_DOTENV_T_EXPORT=from-the-file\n", encoding="utf-8")
    names = load(env_file)
    assert "DAEDALUS_DOTENV_T_EXPORT" not in names
    assert os.environ["DAEDALUS_DOTENV_T_EXPORT"] == "from-the-shell"


def test_the_file_fills_a_gap_the_shell_left_open(tmp_path, monkeypatch):
    monkeypatch.delenv("DAEDALUS_DOTENV_T_GAP", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DAEDALUS_DOTENV_T_GAP=from-the-file\n", encoding="utf-8")
    names = load(env_file)
    assert names == ["DAEDALUS_DOTENV_T_GAP"]
    assert os.environ["DAEDALUS_DOTENV_T_GAP"] == "from-the-file"


def test_load_is_idempotent_and_safe_to_call_more_than_once(tmp_path, monkeypatch):
    """A real export always winning is what makes calling `load` twice safe:
    the second call sees its own first-call result as 'already exported'."""
    monkeypatch.delenv("DAEDALUS_DOTENV_T_IDEMPOTENT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DAEDALUS_DOTENV_T_IDEMPOTENT=first\n", encoding="utf-8")
    assert load(env_file) == ["DAEDALUS_DOTENV_T_IDEMPOTENT"]
    env_file.write_text("DAEDALUS_DOTENV_T_IDEMPOTENT=second\n", encoding="utf-8")
    assert load(env_file) == []           # already set; file no longer wins
    assert os.environ["DAEDALUS_DOTENV_T_IDEMPOTENT"] == "first"


def test_override_flag_exists_only_for_tests(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_DOTENV_T_OVERRIDE", "from-the-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("DAEDALUS_DOTENV_T_OVERRIDE=from-the-file\n", encoding="utf-8")
    names = load(env_file, override=True)
    assert names == ["DAEDALUS_DOTENV_T_OVERRIDE"]
    assert os.environ["DAEDALUS_DOTENV_T_OVERRIDE"] == "from-the-file"


# ===========================================================================
# rule 2 -- a git-tracked .env is refused, loudly
# ===========================================================================

def test_a_git_tracked_env_file_is_refused(repo):
    env_file = repo / ".env"
    env_file.write_text("SOME_KEY=value\n", encoding="utf-8")
    _run(["git", "add", "-f", ".env"], repo)
    with pytest.raises(DotEnvRefused):
        load(env_file)


def test_the_refusal_names_the_remedy(repo):
    env_file = repo / ".env"
    env_file.write_text("SOME_KEY=value\n", encoding="utf-8")
    _run(["git", "add", "-f", ".env"], repo)
    with pytest.raises(DotEnvRefused) as ei:
        load(env_file)
    msg = str(ei.value)
    assert "git rm --cached" in msg
    assert ".env" in msg


def test_an_untracked_env_file_in_the_same_repo_loads_fine(repo, monkeypatch):
    """The control for the two tests above: proves the refusal is about
    TRACKED-ness, not merely about the file living inside a git repo."""
    monkeypatch.delenv("DAEDALUS_DOTENV_T_UNTRACKED", raising=False)
    env_file = repo / ".env"
    env_file.write_text("DAEDALUS_DOTENV_T_UNTRACKED=ok\n", encoding="utf-8")
    # deliberately NOT `git add`-ed
    names = load(env_file)
    assert names == ["DAEDALUS_DOTENV_T_UNTRACKED"]
    assert os.environ["DAEDALUS_DOTENV_T_UNTRACKED"] == "ok"


def test_describe_reports_tracked_and_unsafe_without_raising(repo):
    """`describe` is the doctor/status path: it must be able to REPORT that a
    file is unsafe without itself raising DotEnvRefused."""
    env_file = repo / ".env"
    env_file.write_text("SOME_KEY=value\n", encoding="utf-8")
    _run(["git", "add", "-f", ".env"], repo)
    info = describe(env_file)
    assert info["present"] is True
    assert info["tracked"] is True
    assert info["safe"] is False
    assert info["keys"] == ["SOME_KEY"]


def test_describe_reports_untracked_as_safe(repo):
    env_file = repo / ".env"
    env_file.write_text("SOME_KEY=value\n", encoding="utf-8")
    info = describe(env_file)
    assert info["tracked"] is False
    assert info["safe"] is True


# ===========================================================================
# malformed lines are skipped, never fatal
# ===========================================================================

def test_malformed_lines_are_skipped_not_fatal():
    text = (
        "GOOD_KEY=value\n"
        "no equals sign here\n"
        "=starts with equals\n"
        "9BAD=starts with a digit\n"
        "BAD-KEY=has a dash\n"
        "# a comment\n"
        "\n"
        "   \n"
        "export EXPORTED_KEY=exported_value\n"
        'QUOTED="quoted value"\n'
    )
    assert parse(text) == {
        "GOOD_KEY": "value",
        "EXPORTED_KEY": "exported_value",
        "QUOTED": "quoted value",
    }


def test_load_survives_a_file_full_of_malformed_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("DAEDALUS_DOTENV_T_SURVIVOR", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "not a valid line at all\n"
        "=====\n"
        "DAEDALUS_DOTENV_T_SURVIVOR=made-it\n",
        encoding="utf-8",
    )
    names = load(env_file)
    assert names == ["DAEDALUS_DOTENV_T_SURVIVOR"]
    assert os.environ["DAEDALUS_DOTENV_T_SURVIVOR"] == "made-it"


# ===========================================================================
# describe() carries key NAMES and never values
# ===========================================================================

def test_describe_never_carries_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=super-secret-value-12345\n", encoding="utf-8")
    info = describe(env_file)
    assert info["keys"] == ["SECRET_KEY"]
    assert "super-secret-value-12345" not in repr(info)
    assert "super-secret-value-12345" not in str(info)


def test_describe_keys_are_sorted_names_only(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ZKEY=z-value\nAKEY=a-value\n", encoding="utf-8")
    info = describe(env_file)
    assert info["keys"] == ["AKEY", "ZKEY"]


# ===========================================================================
# a missing file is the normal case
# ===========================================================================

def test_missing_file_load_returns_empty_list(tmp_path):
    missing = tmp_path / "nested" / ".env"
    assert not missing.exists()
    assert load(missing) == []


def test_missing_file_describe_is_present_false_and_safe_true(tmp_path):
    missing = tmp_path / ".env"
    info = describe(missing)
    assert info == {"path": str(missing), "present": False, "tracked": False,
                    "keys": [], "safe": True}


# ===========================================================================
# every key .env can inject is pinned in the suite's conftest
# ===========================================================================

def test_every_example_key_is_cleared_by_the_suite_conftest(pytestconfig):
    """``cli.main`` loads ``.env`` into ``os.environ`` for real, in-process --
    deliberately, because the spend guard's own config lives there. The suite
    survives that only because ``tests/conftest.py`` re-clears every key the
    file can inject before every test. MEASURED 2026-07-29: with only the two
    fence declarations cleared, the operator's ``OLLAMA_MODEL`` and
    ``DEEPSEEK_API_KEY`` leaked out of the first CLI-invoking test file and
    turned twelve later tests red in the full suite while each stayed green
    alone. This test makes the pin self-maintaining: a key added to
    ``.env.example`` without a matching conftest entry fails HERE, with the
    reason, instead of as an order-dependent mystery three directories away.
    """
    import re
    from pathlib import Path

    # NOT `import conftest`. Both conftests in this tree are module-named
    # `conftest`, so the second one imported EVICTS the first from
    # `sys.modules`. That worked while tests/conftest.py was the only one;
    # tests/kernel/conftest.py now exists, and MEASURED 2026-08-17 the bare
    # import bound to the kernel one and raised AttributeError on
    # `_OPERATOR_DECLARATIONS` the moment tests/kernel was collected in the
    # same run -- green alone, red in the suite, which is precisely the
    # order-dependent failure mode this test exists to abolish.
    #
    # pytest's own plugin manager keeps EVERY conftest it loaded, keyed by full
    # path, so ask it. That also makes this check the honest one: it inspects
    # the conftest actually in effect for this run, not a re-import of the file.
    suite_conftest_path = Path(__file__).resolve().parent / "conftest.py"
    conftest = next(
        (plugin for _name, plugin in pytestconfig.pluginmanager.list_name_plugin()
         if getattr(plugin, "__file__", None)
         and Path(plugin.__file__).resolve() == suite_conftest_path),
        None)
    assert conftest is not None, (
        f"pytest did not load {suite_conftest_path} as a conftest plugin; the "
        "suite conftest is what clears the operator declarations, and a run "
        "without it leaks the developer's .env into every test")

    example = Path(__file__).resolve().parents[1] / ".env.example"
    keys = re.findall(r"^([A-Z][A-Z0-9_]*)=", example.read_text(encoding="utf-8"),
                      re.M)
    assert keys, ".env.example lost its keys; this test needs updating"
    pinned = set(conftest._OPERATOR_DECLARATIONS)
    missing = [k for k in keys if k not in pinned]
    assert missing == [], (
        f".env.example can inject {missing} but tests/conftest.py does not "
        f"clear them -- the first in-process cli.main call will leak the "
        f"operator's values into every later test. Add them to "
        f"_OPERATOR_DECLARATIONS.")
