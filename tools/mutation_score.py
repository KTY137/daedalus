"""mutation_score.py -- can this suite detect a defect it claims to cover?

A green suite is a claim. A suite that KILLS a seeded defect is a control. This
repo has built that control by hand twice already, on two different subjects:

  * ``runs/ab/oracle_check.py`` -- seeds one defect into an A/B arm's TypeScript
    and requires the specific conformance test that covers that rule to go red.
  * ``tools/self_test.py`` -- seeds one defect into a disposable clone of this
    repository and requires the named acceptance check to report FAIL.

This module is the third instance generalised, not a third shape. It keeps
every invariant those two paid for, and adds nothing that would weaken them:

  1. NOTHING TOUCHES THE WORKING REPOSITORY. Every mutant is written into a
     disposable copy (``Sandbox``), taken as ONE snapshot at the start of the
     run -- so a concurrent editor cannot change the subject mid-measurement.
  2. BASELINE FIRST, AND IT MUST BE GREEN. ``self_test.py`` learned this the
     expensive way: a check that was already FAIL before the defect was seeded
     proves nothing when it comes back red. A red baseline makes the whole run
     ``INCONCLUSIVE`` -- never a score.
  3. A MUTATION THAT DOES NOT APPLY PROVES NOTHING. ``self_test.py``'s first
     run scored five "SURVIVED" results that were every one of them a defect in
     the MUTATION (a no-op edit, a patch to dead code, a patch to the wrong
     class). Here: a mutation whose anchor is absent, that changes no bytes, or
     that produces source which does not compile is ``NOT_APPLICABLE`` -- it is
     never counted as a survivor, and it is never hidden either.
  4. THE DELTA IS WHAT COUNTS. ``oracle_check.py``'s rule: a mutant is CAUGHT
     when a test goes red that was NOT red at baseline. Optionally (see
     ``Mutation.expect_test``) a NAMED test must be the one that goes red --
     "something failed" is weaker evidence than "the test that claims to
     cover this rule failed".
  5. A SURVIVOR IS THE HEADLINE, NOT A FOOTNOTE. A rule nobody can falsify is
     worse than a missing one, because it reads as covered. Survivors are
     named, and the process exits non-zero.

WHAT THIS CANNOT SEE -- stated, not implied (see docs/FITNESS_SIGNAL.md):

  * EQUIVALENT MUTANTS. A survivor may be a mutant that does not change
    behaviour at all (``if x > 0`` -> ``if x >= 0`` on a value that is never
    zero). This tool CANNOT tell an equivalent mutant from a real hole. Every
    survivor is a QUESTION for a human, never a verdict.
  * ANYTHING OUTSIDE THE OPERATOR SET. The generated mutants are five
    single-token edits (see ``OPERATORS``). A missing feature, an absent guard,
    a wrong algorithm, a race, a resource leak, a deletion of the whole
    function -- none of those are in the mutant population, so a 100% score
    says nothing about them.
  * WHAT THE SELECTED TESTS DO NOT RUN. The score is relative to the
    ``--tests`` selection. Scoring a module against a suite that never imports
    it yields a truthful 0% and an equally truthful "this measures nothing".
  * PYTHON ONLY. The generator parses Python with ``ast``. ``oracle_check.py``
    remains the instance for TypeScript; its explicit find/replace shape is
    expressible here (``Mutation.patch``) but its runner is not.
  * TIMEOUTS ARE NOT KILLS. Standard mutation-testing practice counts a hung
    mutant as killed. Here it is ``INCONCLUSIVE``, excluded from the score in
    the conservative direction, and reported.

USAGE

    python tools/mutation_score.py --module daedalus/sensitivity.py \
        --tests tests/test_hardening.py tests/test_fence_anchoring.py

    python tools/mutation_score.py --module daedalus/token_monitor.py \
        --tests tests/test_agent_env.py --sample 12 --json out.json

    # falsification control for the SCORER ITSELF: drop a covering test and
    # require the score to drop.
    python tools/mutation_score.py --module M --tests T --drop-test test_foo

Exit code: 0 only when the baseline was green and no mutant survived.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# statuses                                                                     #
# --------------------------------------------------------------------------- #
CAUGHT = "CAUGHT"                  # baseline green, a test that was green went red
SURVIVED = "SURVIVED"              # baseline green, nothing went red -- a HOLE or an equivalent mutant
NOT_APPLICABLE = "NOT_APPLICABLE"  # the mutation did not apply / changed nothing / did not compile
INCONCLUSIVE = "INCONCLUSIVE"      # the measurement itself failed (red baseline, timeout, runner error)

# Directory names never copied into a sandbox. Two reasons, both measured on
# this repo: correctness (a stale ``__pycache__`` would shadow a mutant) and
# cost (``.captures`` alone is 1.2 GB, ``target``/``node_modules`` similar).
# Excluding ``.git`` is deliberate and SAFE-BY-CONSTRUCTION: if the selected
# tests need git, the baseline goes red and the whole run reports INCONCLUSIVE
# rather than silently scoring against a crippled sandbox.
DEFAULT_IGNORE = (
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "dist", "build", "target", "out", "coverage",
    ".captures", ".edge-capture", ".idea", ".vs", ".vscode",
    "*.pyc", "*.pyo", "*.so", "*.pyd",
)


# --------------------------------------------------------------------------- #
# the mutation                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Mutation:
    """One seeded defect, and the rule it is meant to falsify.

    Two anchoring modes, so this subsumes BOTH hand-rolled instances:

      * SPAN (``start >= 0``) -- what ``generate_mutations`` emits: an exact
        character range, guarded by ``before``. If the file changed underneath
        (another agent editing the tree while a run is in flight), the guard
        fails and the mutation is NOT_APPLICABLE rather than landing somewhere
        unintended -- the exact failure mode ``self_test.py`` paid a round for
        ("a mutation that lands somewhere real but irrelevant looks exactly
        like a check that cannot detect anything").
      * FIND/REPLACE (``start < 0``, see ``Mutation.patch``) -- the shape
        ``oracle_check.py`` and ``self_test.py`` both use by hand: replace the
        FIRST occurrence of ``before``, and refuse if it is absent.

    ``expect_test`` is ``oracle_check.py``'s stronger contract: naming the test
    that MUST go red. Without it, any newly-red test counts as a kill, which is
    weaker evidence -- an unrelated test tripping over the mutant is detection
    by accident, not coverage.
    """

    id: str
    operator: str
    rel_path: str
    line: int
    col: int
    before: str
    after: str
    rule: str = ""
    expect_test: str | None = None
    start: int = -1
    end: int = -1

    @classmethod
    def patch(cls, rel_path: str, find: str, replace: str, *, rule: str = "",
              expect_test: str | None = None, id: str | None = None) -> "Mutation":
        """A hand-written find/replace mutation -- the ``oracle_check.py`` /
        ``self_test.py`` table shape, expressed in this module's vocabulary."""
        return cls(
            id=id or f"patch:{rel_path}:{abs(hash((find, replace))) % 10**8:08d}",
            operator="patch", rel_path=rel_path, line=0, col=0,
            before=find, after=replace, rule=rule, expect_test=expect_test,
        )

    def apply(self, source: str) -> str | None:
        """The mutated source, or ``None`` if this mutation does not apply --
        anchor absent, or the edit changes nothing. A ``None`` here becomes
        NOT_APPLICABLE, never a survivor."""
        if self.start >= 0:
            if source[self.start:self.end] != self.before:
                return None
            mutated = source[:self.start] + self.after + source[self.end:]
        else:
            if self.before not in source:
                return None
            mutated = source.replace(self.before, self.after, 1)
        return None if mutated == source else mutated

    def describe(self) -> str:
        where = f"{self.rel_path}:{self.line}" if self.line else self.rel_path
        return f"{where}  {self.before.strip()!r} -> {self.after.strip()!r}"


# --------------------------------------------------------------------------- #
# the generator -- five single-token operators over Python source              #
# --------------------------------------------------------------------------- #
# Chosen because each corresponds to a defect class this repo has actually
# shipped, not because they are cheap to implement:
#   comparison  -- an off-by-one/inverted boundary in a fence
#   boolop      -- a guard that should have been AND'd, OR'd (7 gate bypasses)
#   bool_const  -- a flag flipped to the permissive value
#   drop_not    -- an inverted predicate (the classic "allow" for "deny")
#   guard_never_fires -- the guard is deleted outright. THIS is the operator
#       behind the finding that motivated this file: of 61 mutants in
#       worktree.py, 18 guards survived their own deletion.
OPERATORS = ("comparison", "boolop", "bool_const", "drop_not", "guard_never_fires")

_CMP_FLIP = {
    "==": "!=", "!=": "==",
    "<": ">=", "<=": ">", ">": "<=", ">=": "<",
    "is": "is not", "is not": "is",
    "in": "not in", "not in": "in",
}
_BOOLOP_FLIP = {"and": "or", "or": "and"}
_TERMINATORS = (ast.Raise, ast.Return, ast.Continue, ast.Break, ast.Pass)


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _index(source: str, starts: list[int], line: int, col: int) -> int:
    """(1-based line, ast col_offset) -> character index.

    ``ast`` reports ``col_offset`` in UTF-8 BYTES, not characters. A module with
    one non-ASCII identifier or docstring above the mutation site would
    otherwise place every subsequent edit off by the byte/char difference --
    silently producing garbage mutants that read as "the suite cannot detect
    this"."""
    if line < 1 or line > len(starts):
        raise IndexError(f"line {line} out of range")
    ls = starts[line - 1]
    nl = source.find("\n", ls)
    line_text = source[ls: nl if nl != -1 else len(source)]
    prefix = line_text.encode("utf-8")[:col].decode("utf-8", errors="ignore")
    return ls + len(prefix)


def _gap(source: str, starts: list[int], left: ast.AST, right: ast.AST) -> tuple[int, int] | None:
    """Character span of the operator token BETWEEN two adjacent nodes.

    ``ast`` gives no location for an operator token itself, so it is recovered
    as "everything between the end of the left operand and the start of the
    right one". Returns ``None`` when either endpoint is missing (a synthesised
    node)."""
    if (getattr(left, "end_lineno", None) is None
            or getattr(right, "lineno", None) is None):
        return None
    a = _index(source, starts, left.end_lineno, left.end_col_offset)
    b = _index(source, starts, right.lineno, right.col_offset)
    return (a, b) if b > a else None


def _pad(seg: str, replacement: str) -> str:
    """Keep the original whitespace around an operator, but never weld a WORD
    operator onto an identifier (``a==b`` -> ``anot inb`` would merely fail to
    compile, i.e. waste a mutant)."""
    lead = seg[: len(seg) - len(seg.lstrip())]
    trail = seg[len(seg.rstrip()):]
    if replacement[0].isalpha() or replacement[-1].isalpha():
        return (lead or " ") + replacement + (trail or " ")
    return lead + replacement + trail


def _mk(source: str, rel_path: str, operator: str, start: int, end: int,
        after: str, node: ast.AST, rule: str) -> Mutation | None:
    """Build a Mutation and REJECT it here if it cannot possibly be evidence:
    it changes nothing, or the result does not parse. Rejecting at generation
    time (rather than after a test run) is what keeps NOT_APPLICABLE cheap and
    keeps the survivor list honest."""
    before = source[start:end]
    if before == after:
        return None
    mutated = source[:start] + after + source[end:]
    try:
        compile(mutated, rel_path, "exec")
    except SyntaxError:
        return None
    return Mutation(
        id=f"{operator}:{rel_path}:{node.lineno}:{node.col_offset}",
        operator=operator, rel_path=rel_path,
        line=node.lineno, col=node.col_offset,
        before=before, after=after, rule=rule, start=start, end=end,
    )


def generate_mutations(source: str, rel_path: str,
                       operators: tuple[str, ...] = OPERATORS) -> list[Mutation]:
    """Every applicable single-token mutant of ``source``, deterministically
    ordered by (line, col, operator, id).

    Deterministic order is load-bearing, not cosmetic: ``--sample`` slices this
    list, so two runs of the same command must select the same mutants or the
    numbers are not comparable across a change.

    A file that does not parse yields ``[]`` -- there is nothing to mutate and
    nothing to claim."""
    try:
        tree = ast.parse(source, rel_path)
    except SyntaxError:
        return []
    starts = _line_starts(source)
    out: list[Mutation] = []

    def add(m: Mutation | None) -> None:
        if m is not None:
            out.append(m)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and "comparison" in operators:
            # Single-op compares only: a chained ``a < b < c`` has ambiguous
            # token spans and is rare enough not to be worth a wrong mutant.
            if len(node.ops) == 1 and len(node.comparators) == 1:
                span = _gap(source, starts, node.left, node.comparators[0])
                if span:
                    seg = source[span[0]:span[1]]
                    tok = " ".join(seg.split())
                    if tok in _CMP_FLIP:
                        add(_mk(source, rel_path, "comparison", span[0], span[1],
                                _pad(seg, _CMP_FLIP[tok]), node,
                                f"boundary/identity test {tok!r} is load-bearing"))

        elif isinstance(node, ast.BoolOp) and "boolop" in operators:
            span = _gap(source, starts, node.values[0], node.values[1])
            if span:
                seg = source[span[0]:span[1]]
                tok = " ".join(seg.split())
                if tok in _BOOLOP_FLIP:
                    add(_mk(source, rel_path, "boolop", span[0], span[1],
                            _pad(seg, _BOOLOP_FLIP[tok]), node,
                            f"the {tok!r} joining these conditions is load-bearing"))

        elif isinstance(node, ast.Constant) and "bool_const" in operators:
            if node.value is True or node.value is False:
                if getattr(node, "end_lineno", None) is None:
                    continue
                a = _index(source, starts, node.lineno, node.col_offset)
                b = _index(source, starts, node.end_lineno, node.end_col_offset)
                lit = source[a:b]
                if lit in ("True", "False"):
                    add(_mk(source, rel_path, "bool_const", a, b,
                            "False" if lit == "True" else "True", node,
                            f"this {lit} is load-bearing"))

        elif isinstance(node, ast.UnaryOp) and "drop_not" in operators:
            if isinstance(node.op, ast.Not) and getattr(node.operand, "lineno", None):
                a = _index(source, starts, node.lineno, node.col_offset)
                b = _index(source, starts, node.operand.lineno, node.operand.col_offset)
                seg = source[a:b]
                # Only the bare ``not x`` form. ``not (a and b)`` would need the
                # paren kept, and a broken mutant is a wasted one.
                if b > a and seg.strip() == "not" and "(" not in seg:
                    add(_mk(source, rel_path, "drop_not", a, b, "", node,
                            "this predicate is inverted on purpose"))

        elif isinstance(node, ast.If) and "guard_never_fires" in operators:
            # A GUARD: an ``if`` whose body only leaves (raise/return/break/
            # continue/pass) and which has no else. Neutralising its test is
            # "delete the guard" -- the operator that found 18 undetectable
            # guards in worktree.py.
            if node.orelse or not node.body:
                continue
            if not all(isinstance(s, _TERMINATORS) for s in node.body):
                continue
            t = node.test
            if getattr(t, "end_lineno", None) is None:
                continue
            a = _index(source, starts, t.lineno, t.col_offset)
            b = _index(source, starts, t.end_lineno, t.end_col_offset)
            add(_mk(source, rel_path, "guard_never_fires", a, b, "False", node,
                    "this guard fires on some real input"))

    out.sort(key=lambda m: (m.line, m.col, m.operator, m.id))
    # Two operators can land on the same span (a bare ``if flag:`` guard where
    # the test is itself a boolean literal). Same span + same replacement is
    # the same experiment; keep the first, deterministically.
    seen: set[tuple[int, int, str]] = set()
    unique: list[Mutation] = []
    for m in out:
        key = (m.start, m.end, m.after)
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)
    return unique


def sample(mutations: list[Mutation], n: int | None) -> list[Mutation]:
    """An evenly SPREAD subset of ``n`` mutants, not the first ``n``.

    Taking a prefix would bias every partial run to the top of the file (the
    imports and the module-level constants), which is exactly where the guards
    are not. Deterministic -- no RNG, so a re-run selects the same mutants."""
    if n is None or n >= len(mutations) or n <= 0:
        return list(mutations)
    step = len(mutations) / n
    return [mutations[int(i * step)] for i in range(n)]


# --------------------------------------------------------------------------- #
# the sandbox -- nothing here touches the working repository                    #
# --------------------------------------------------------------------------- #
class Sandbox:
    """A disposable copy of the repository, taken ONCE.

    One snapshot per run, not one per mutant: mutants are written and reverted
    inside it. That is both cheaper and STRICTLY MORE HONEST than re-copying,
    because it freezes the subject -- fifteen agents editing this tree cannot
    change what is being measured halfway through a run.
    """

    def __init__(self, repo: str | Path, ignore: tuple[str, ...] = DEFAULT_IGNORE):
        self.repo = Path(repo).resolve()
        self.ignore = ignore
        self.root: Path | None = None
        self.error: str | None = None

    def build(self) -> bool:
        try:
            tmp = Path(tempfile.mkdtemp(prefix="mutscore-"))
            dst = tmp / self.repo.name
            shutil.copytree(self.repo, dst, ignore=shutil.ignore_patterns(*self.ignore),
                            symlinks=True, ignore_dangling_symlinks=True)
            self.root = dst
            return True
        except OSError as exc:
            self.error = str(exc)
            return False

    def read(self, rel: str) -> str:
        assert self.root is not None
        return (self.root / rel).read_text(encoding="utf-8")

    def write(self, rel: str, text: str) -> None:
        assert self.root is not None
        (self.root / rel).write_text(text, encoding="utf-8", newline="")

    def destroy(self) -> None:
        if self.root is not None:
            shutil.rmtree(self.root.parent, ignore_errors=True)
            self.root = None


# --------------------------------------------------------------------------- #
# the runner                                                                   #
# --------------------------------------------------------------------------- #
@dataclass
class RunResult:
    returncode: int
    failing: set[str] = field(default_factory=set)
    output: str = ""
    seconds: float = 0.0
    timed_out: bool = False

    @property
    def green(self) -> bool:
        return self.returncode == 0 and not self.failing and not self.timed_out


_FAIL_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)")

# A COLOURED "FAILED" IS STILL A FAILURE. pytest emits its summary as
# ``\x1b[31mFAILED\x1b[0m t/test_x.py::\x1b[1mtest_y\x1b[0m`` whenever colour is
# on, and this agent environment exports FORCE_COLOR=3 unconditionally. Against
# that, ``_FAIL_RE``'s ``^`` anchor never matched: every KILLED mutant came back
# as "returncode != 0 but no test was named", i.e. INCONCLUSIVE, so `scored` was
# 0 and ``mutation_score`` stayed None -- the scorer reported "nothing
# scoreable" for a suite that was killing every mutant. MEASURED 2026-07-31.
#
# Belt AND braces, because the failure is silent and reads as a clean result:
# ``--color=no`` on the command line (which outranks ini `addopts` and
# PYTEST_ADDOPTS) stops it at the source, and the strip stops any plugin,
# wrapper, or future env var that re-colours the stream from breaking the parse
# again. This is the same defect class as the coloured PASS that was read as
# "never ran" in `daedalus/eval` (commit 22ffbf9).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def pytest_runner(root: Path, test_paths: list[str], timeout: float) -> RunResult:
    """Run a pytest selection inside ``root`` and return WHICH tests failed.

    ``--tb=no -q`` because only the identity of the failures matters here,
    ``-p no:cacheprovider`` so a run never writes a ``.pytest_cache`` that a
    later run could read, and ``--color=no`` so the summary this function parses
    is plain text (see ``_ANSI_RE``)."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no", "--color=no",
           "-p", "no:cacheprovider", *test_paths]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return RunResult(returncode=-1, failing=set(), output="TIMEOUT",
                         seconds=time.time() - t0, timed_out=True)
    out = _strip_ansi((proc.stdout or "") + (proc.stderr or ""))
    failing = {m.group(1) for line in out.splitlines()
               if (m := _FAIL_RE.match(line.strip()))}
    return RunResult(returncode=proc.returncode, failing=failing, output=out,
                     seconds=time.time() - t0)


def drop_test(source: str, name: str) -> str:
    """Remove every test function whose name CONTAINS ``name`` from ``source``.

    Not a feature -- a CONTROL. It weakens the oracle on purpose so the scorer
    itself can be falsified: if removing the test that kills mutant M does not
    flip M to SURVIVED, this tool is not measuring what it claims to measure.
    Raises ``ValueError`` when nothing matched (a control that silently did
    nothing would read as "the score did not move", i.e. as evidence against
    the tool, which would be exactly backwards)."""
    tree = ast.parse(source)
    victims: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name in node.name:
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            victims.append((first, node.end_lineno))
    if not victims:
        raise ValueError(f"no test function matching {name!r}")
    lines = source.splitlines(keepends=True)
    for first, last in victims:
        for i in range(first - 1, last):
            # Blank the WHOLE line, never splice mid-line: the surrounding
            # class body keeps its indentation and still parses.
            lines[i] = "\n"
    out = "".join(lines)
    ast.parse(out)  # a control that produces an unparseable suite must fail loudly
    return out


# --------------------------------------------------------------------------- #
# the score                                                                    #
# --------------------------------------------------------------------------- #
def score(repo: str | Path, module_rel: str, test_paths: list[str], *,
          mutations: list[Mutation] | None = None,
          n_sample: int | None = None,
          operators: tuple[str, ...] = OPERATORS,
          timeout: float = 900.0,
          drop_tests: tuple[str, ...] = (),
          runner=pytest_runner,
          progress=None) -> dict:
    """Seed defects into ``module_rel`` one at a time and report which SURVIVE.

    Returns a report dict (see ``render``). Never raises for a mutant-level
    problem: a mutation that will not apply, a runner that times out, and a red
    baseline are all reported outcomes, because a mutation run that dies
    halfway is a measurement that quietly did not happen.
    """
    repo = Path(repo).resolve()
    module_rel = module_rel.replace("\\", "/")
    test_paths = [t.replace("\\", "/") for t in test_paths]
    original = (repo / module_rel).read_text(encoding="utf-8")

    if mutations is None:
        mutations = generate_mutations(original, module_rel, operators)
    mutations = sample(mutations, n_sample)

    report: dict = {
        "schema": 1,
        "repo": str(repo),
        "module": module_rel,
        "tests": list(test_paths),
        "dropped_tests": list(drop_tests),
        "operators": list(operators),
        "n_generated": len(mutations),
        "results": [],
        "baseline_green": False,
        "baseline_failures": [],
        "baseline_seconds": 0.0,
        "mutation_score": None,
        "verdict": INCONCLUSIVE,
    }

    sb = Sandbox(repo)
    if not sb.build():
        report["error"] = f"could not build a sandbox: {sb.error}"
        return report
    try:
        # A test SELECTION may name a directory or a ``file::node`` id; the
        # control only ever rewrites real .py files under it.
        test_files: list[str] = []
        for t in test_paths:
            base = t.split("::", 1)[0]
            p = sb.root / base
            if p.is_dir():
                test_files += [str(q.relative_to(sb.root)).replace("\\", "/")
                               for q in sorted(p.rglob("test_*.py"))]
            elif p.suffix == ".py":
                test_files.append(base)
        for name in drop_tests:
            for t in test_files:
                try:
                    sb.write(t, drop_test(sb.read(t), name))
                except (ValueError, SyntaxError, OSError):
                    continue  # this test file simply has no such function

        base = runner(sb.root, test_paths, timeout)
        report["baseline_green"] = base.green
        report["baseline_failures"] = sorted(base.failing)
        report["baseline_seconds"] = round(base.seconds, 1)
        if base.timed_out:
            report["error"] = "the baseline run timed out; nothing below is evidence"
            return report
        if base.returncode != 0 and not base.failing:
            # Collection error, import error, missing dependency -- pytest
            # failed without naming a test. Scoring against this would compare
            # a broken run to a broken run.
            report["error"] = ("the baseline run failed without naming a test "
                               "(collection/import error) -- see baseline_output")
            report["baseline_output"] = base.output[-2000:]
            return report

        for i, m in enumerate(mutations, 1):
            if progress:
                progress(i, len(mutations), m)
            mutated = m.apply(sb.read(module_rel))
            if mutated is None:
                report["results"].append({
                    "id": m.id, "operator": m.operator, "line": m.line,
                    "status": NOT_APPLICABLE, "rule": m.rule,
                    "detail": "anchor absent, or the edit changes nothing",
                    "before": m.before, "after": m.after,
                })
                continue
            sb.write(module_rel, mutated)
            try:
                res = runner(sb.root, test_paths, timeout)
            finally:
                sb.write(module_rel, original)  # always revert, even on a crash

            newly = sorted(res.failing - base.failing)
            if res.timed_out:
                status, detail = INCONCLUSIVE, f"the run timed out after {timeout:.0f}s"
            elif m.expect_test is not None:
                caught = any(m.expect_test in t for t in newly)
                status = CAUGHT if caught else SURVIVED
                detail = ("" if caught else
                          f"the test that claims this rule ({m.expect_test}) stayed green")
            elif newly:
                status, detail = CAUGHT, ""
            elif res.returncode != 0 and not res.failing:
                status, detail = INCONCLUSIVE, "the run failed without naming a test"
            else:
                status, detail = SURVIVED, "no test went red"
            report["results"].append({
                "id": m.id, "operator": m.operator, "line": m.line,
                "status": status, "rule": m.rule, "detail": detail,
                "before": m.before, "after": m.after,
                "newly_failing": newly, "seconds": round(res.seconds, 1),
            })
    finally:
        sb.destroy()

    caught = [r for r in report["results"] if r["status"] == CAUGHT]
    survived = [r for r in report["results"] if r["status"] == SURVIVED]
    scored = len(caught) + len(survived)
    report["n_caught"] = len(caught)
    report["n_survived"] = len(survived)
    report["n_not_applicable"] = sum(1 for r in report["results"]
                                     if r["status"] == NOT_APPLICABLE)
    report["n_inconclusive"] = sum(1 for r in report["results"]
                                   if r["status"] == INCONCLUSIVE)
    if report["baseline_green"] and scored:
        report["mutation_score"] = len(caught) / scored
        report["verdict"] = "SURVIVORS" if survived else "NO_SURVIVORS"
    return report


def render(report: dict) -> str:
    """The ``oracle_check.py`` output shape: one line per mutant, survivors
    spelled out, and the limits printed with the number rather than beneath
    it."""
    L: list[str] = []
    L.append(f"module : {report['module']}")
    L.append(f"tests  : {' '.join(report['tests'])}")
    if report["dropped_tests"]:
        L.append(f"dropped: {' '.join(report['dropped_tests'])}  "
                 f"(FALSIFICATION CONTROL -- the suite was weakened on purpose)")
    if report.get("error"):
        L.append(f"\nINCONCLUSIVE: {report['error']}")
        if report.get("baseline_output"):
            L.append(report["baseline_output"])
        return "\n".join(L)
    L.append(f"baseline: {'GREEN' if report['baseline_green'] else 'RED'} "
             f"in {report['baseline_seconds']}s"
             + (f" -- {len(report['baseline_failures'])} already failing: "
                f"{report['baseline_failures'][:5]}"
                if report["baseline_failures"] else ""))
    if not report["baseline_green"]:
        L.append("  a mutant is only evidence where the baseline was green; "
                 "everything below is INCONCLUSIVE.")
    L.append("")
    mark = {CAUGHT: "ok  ", SURVIVED: "MISS", NOT_APPLICABLE: "n/a ", INCONCLUSIVE: "??  "}
    for r in report["results"]:
        L.append(f"  [{mark[r['status']]}] {r['operator']:18s} line {r['line']:<5d} "
                 f"{r['before'].strip()!r} -> {r['after'].strip()!r}")
        if r["status"] == SURVIVED:
            L.append(f"           SURVIVED -- nothing went red. The claim "
                     f"\"{r['rule'] or 'this line matters'}\" is UNFALSIFIABLE "
                     f"by these tests, and reads as covered.")
        elif r["status"] == INCONCLUSIVE and r.get("detail"):
            L.append(f"           {r['detail']}")
    ms = report.get("mutation_score")
    L.append("")
    L.append(f"{report.get('n_caught', 0)} caught, {report.get('n_survived', 0)} SURVIVED, "
             f"{report.get('n_not_applicable', 0)} not applicable, "
             f"{report.get('n_inconclusive', 0)} inconclusive "
             f"(of {report['n_generated']} seeded)")
    L.append(f"mutation score: {ms:.1%}" if ms is not None
             else "mutation score: NONE (nothing scoreable)")
    L.append("this score covers ONLY these operators against ONLY these tests. "
             "A survivor may be an equivalent mutant; a 100% score says nothing "
             "about defect classes not in the operator set.")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--module", required=True, help="module to mutate, repo-relative")
    ap.add_argument("--tests", nargs="+", default=[], help="pytest selection to run")
    ap.add_argument("--sample", type=int, default=None,
                    help="score an evenly-spread N of the mutants (deterministic)")
    ap.add_argument("--only", default=None,
                    help="score only mutants whose id contains this -- how a "
                         "single survivor is re-run against a weakened suite")
    ap.add_argument("--operators", nargs="+", default=list(OPERATORS), choices=list(OPERATORS))
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--drop-test", action="append", default=[],
                    help="CONTROL: remove tests whose name contains this, then score")
    ap.add_argument("--json", default=None, help="write the full report here")
    ap.add_argument("--list", action="store_true", help="print the mutants and exit")
    args = ap.parse_args(argv)

    if not args.list:
        # --list prints the mutant table and stays fail-open; scoring spawns
        # pytest against mutated trees and starts at the central boundary.
        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

        begin_effect(
            "tools.mutation_score",
            REGISTRY_BY_ID["tools.mutation_score"].effects,
            (process_guard_boundary_decision(),),
        )
    repo = Path(args.repo).resolve()
    source = (repo / args.module).read_text(encoding="utf-8")
    muts = generate_mutations(source, args.module.replace("\\", "/"),
                              tuple(args.operators))
    if args.only:
        muts = [m for m in muts if args.only in m.id]
    muts = sample(muts, args.sample)
    if args.list:
        for m in muts:
            print(f"  {m.operator:18s} {m.describe()}")
        print(f"\n{len(muts)} mutant(s)")
        return 0
    if not args.tests:
        print("--tests is required (a mutation score with no tests is not a number)")
        return 2

    def progress(i: int, n: int, m: Mutation) -> None:
        print(f"  [{i}/{n}] {m.operator} line {m.line} ...", flush=True)

    rep = score(repo, args.module, args.tests, mutations=muts,
                timeout=args.timeout, drop_tests=tuple(args.drop_test),
                operators=tuple(args.operators), progress=progress)
    print()
    print(render(rep))
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2, sort_keys=True),
                                   encoding="utf-8")
        print(f"\nwrote {args.json}")
    if rep.get("error") or not rep["baseline_green"]:
        return 2
    return 1 if rep.get("n_survived") else 0


if __name__ == "__main__":
    raise SystemExit(main())
