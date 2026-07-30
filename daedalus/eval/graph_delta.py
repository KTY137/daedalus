"""graph_delta.py — does the MULTI-LAYER GRAPH see a defect the test suite missed?

THE QUESTION
------------
``tools/gate_discrimination.py`` seeds real, incident-modelled defects and records
whether the frozen gate (pytest over the whole suite) CAUGHT or SURVIVED each one.
Its own docstring records the finding that motivates this module: *"An audit
measured the gate's rejection rate against the three known-bad changes of a single
day at 0/3."*

Tests answer one bit, and that day they answered it wrong three times. The claim
under test here is that the layered graph carries a second, independent signal:

    For a candidate patch, does the DELTA IN THE GRAPH carry information about
    the patch that the test suite does not — available before the tests run, at
    negligible cost?

If yes, a code-evolution loop gains a selection signal that Best-of-N does not
have: two candidates that both pass the gate are currently indistinguishable, and
a graph delta can tell them apart AND say what changed.

WHY THIS CORPUS AND NOT THE ATTEMPT LEDGER
------------------------------------------
The obvious corpus is the 91 attempts in ``runs/spine/spine.sqlite3``. It cannot
answer the question: 69 of the 82 completed attempts carry a diff and **all 69
are ``state=clean``**, so the label is very nearly constant, several diffs are
byte-identical repeats of one task, and the diff text was never stored (only
``diff_sha256`` and ``byte_length``). Calibrating a signal on a corpus where every
example wears the same label would measure nothing. The mutation corpus has ground
truth by construction: every mutant is bad, and the label is whether the existing
gate noticed.

PREDICTIONS, STATED BEFORE THE FIRST RUN
----------------------------------------
``Mutation.predicted_survive`` exists in the corpus for exactly this reason, so
this module adopts the same discipline. Written 2026-07-30, before any result:

  * a mutation that DELETES A CALL (``_verify_reachable(...)`` -> ``pass``) should
    be visible — an edge disappears;
  * a mutation that makes a condition vacuous (``if X not in Y:`` -> ``if False:``)
    should be visible — the identifiers ``X`` and ``Y`` leave that function's body;
  * a mutation that only changes a DATA LITERAL (adding ``"claude_cli"`` to a
    tuple) should be INVISIBLE — no edge moves, and I expect this layer to miss it;
  * a mutation that inserts an early ``return`` should be INVISIBLE to a
    name-based view — the following statements are still lexically present, so
    nothing is deleted. Catching it needs control flow, which this repo does not
    build.

So the honest prediction is roughly **three of five detected, two missed**, and the
two misses are the interesting half: they say precisely which defect classes a
graph delta cannot cover, and therefore what a fitness function built on it would
still be blind to.

WHAT THIS IS NOT
----------------
It is not a gate. Nothing here blocks, scores a candidate, or moves a picker
band. It produces a measurement and the evidence behind it, and a signal that
misses two of five defect classes is not a verification story — it is at best one
input among several, and this module says so rather than letting a later reader
assume otherwise.
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..structcore import graph as graph_mod
from ..structcore import parse as parse_mod
from ..structcore.languages import spec_for

DELTA_VERSION = "1"


def load_mutations(repo_root: str | Path):
    """Import the corpus from ``tools/gate_discrimination.py`` rather than copying
    it. One corpus, one definition — a second copy would drift and then the two
    measurements would disagree for a bookkeeping reason."""
    path = Path(repo_root) / "tools" / "gate_discrimination.py"
    spec = importlib.util.spec_from_file_location("_gate_discrimination", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the mutation corpus from {path}")
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: ``@dataclass`` resolves annotations through
    # ``sys.modules[cls.__module__]``, so a module that is not registered yet
    # makes every dataclass in the imported file raise on definition.
    import sys as _sys
    _sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        _sys.modules.pop(spec.name, None)
        raise
    return tuple(mod.MUTATIONS)


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LayerDelta:
    """What moved in one layer. Counts plus the names, so a finding is inspectable."""
    layer: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def moved(self) -> int:
        return len(self.added) + len(self.removed)

    def to_dict(self) -> dict:
        return {"layer": self.layer, "added": list(self.added),
                "removed": list(self.removed), "moved": self.moved}


@dataclass
class DeltaResult:
    mutation_id: str
    defect_class: str
    file: str
    applied: bool
    layers: list[LayerDelta] = field(default_factory=list)
    skipped_reason: str = ""

    #: Layers that may count toward a detection. ``code.refs.leaky`` is
    #: deliberately excluded: it scans raw source, so the corpus's own
    #: "SEEDED DEFECT" comments move it for every single mutation and a
    #: verdict built on it would be a tautology.
    SCORING_LAYERS = ("code.refs.ast", "literals", "structure", "types", "data.literals")

    @property
    def detected(self) -> bool:
        """Detected means a SCORING layer moved. It does NOT mean the defect was
        understood — only that the graph is not blind to it."""
        return self.applied and any(l.moved for l in self.layers
                                    if l.layer in self.SCORING_LAYERS)

    @property
    def detected_leaky(self) -> bool:
        """What the measurement would claim if comments counted. Reported so the
        artefact has a number instead of a footnote."""
        return self.applied and any(l.moved for l in self.layers)

    def to_dict(self) -> dict:
        return {"mutation": self.mutation_id, "defect_class": self.defect_class,
                "file": self.file, "applied": self.applied,
                "detected": self.detected, "detected_leaky": self.detected_leaky,
                "skipped_reason": self.skipped_reason,
                "layers": [l.to_dict() for l in self.layers]}


def _ast_refs(module: str, text: str) -> tuple[set[str], str]:
    """Identifier references from the AST — the CLEAN arm.

    THE ARTEFACT THIS EXISTS TO REMOVE. The first run of this module reported
    10/12 detected, and every single detection contained the tokens ``SEEDED``
    and ``DEFECT`` — the marker words the corpus writes into its own replacement
    comments. ``graph.identifiers`` scans raw source, so comments are tokens, and
    the measurement was detecting the LABEL rather than the defect. That is the
    same self-prediction artefact ``eval/ceiling.py`` separates with its clean
    and leaky arms, and it is why both arms are reported here.

    Comments do not exist in an AST, and docstrings are skipped explicitly, so
    what remains is names the program actually uses.
    """
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return set(), f"unparseable after mutation: {exc.__class__.__name__}"

    # MULTISET, not a set. Set semantics erase the deletion of a call that still
    # occurs elsewhere in the same function -- and "this function now calls
    # _verify_reachable once instead of twice" is exactly the kind of change a
    # seeded defect makes. Counting is independently correct, not a tune to the
    # answer: it was wrong before the result was known.
    from collections import Counter
    counts: "Counter[str]" = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]                      # drop the docstring
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name):
                    counts[f"{node.name}->{sub.id}"] += 1
                elif isinstance(sub, ast.Attribute):
                    counts[f"{node.name}->.{sub.attr}"] += 1
    # Flatten the multiset so the existing set difference sees multiplicity.
    refs = {f"{k}#{i}" for k, n in counts.items() for i in range(n)}
    return refs, ""



def _literals_by_function(module: str, text: str) -> dict:
    """Constant VALUES per function — the layer that closes the data-only blind spot.

    Three of the five mutations the reference layer missed change no name at all:
    ``FREE_LANES`` gains ``"claude_cli"``; a host constant gains ``localhost``; an
    argv list loses ``--no-textconv``. A name-based view is structurally blind to
    every one of them, because the identifiers are identical before and after.

    Constants are a multiset per function, like references, so losing one of two
    identical flags is visible. Values are stored as ``repr`` and CLIPPED: this
    layer must never become a way for a secret in a literal to travel into a
    report.
    """
    import ast
    from collections import Counter

    MAX_REPR = 80
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        c: Counter = Counter()
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Constant) and not isinstance(sub.value, type(...)):
                    r = repr(sub.value)
                    c[r if len(r) <= MAX_REPR else r[:MAX_REPR - 1] + "…"] += 1
        out[node.name] = out.get(node.name, Counter()) + c
    return out


def _module_literals(module: str, text: str) -> set:
    """Constants at MODULE level too — ``FREE_LANES = (...)`` is a module
    assignment, so a function-scoped walk would never see it change."""
    import ast
    from collections import Counter

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    c: Counter = Counter()
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Constant):
                    r = repr(sub.value)
                    c[r if len(r) <= 80 else r[:79] + "…"] += 1
    return {f"{k}#{i}" for k, n in c.items() for i in range(n)}


def _literal_keys(module: str, text: str) -> set:
    """All constants, function-scoped and module-scoped, as comparable keys."""
    keys = set(_module_literals(module, text))
    for fn, counter in _literals_by_function(module, text).items():
        for value, n in counter.items():
            for i in range(n):
                keys.add(f"{fn}:{value}#{i}")
    return keys


def _structure_by_function(module: str, text: str) -> dict:
    """Statement SHAPE per function — the layer for the control-flow blind spot.

    The two mutations that neither references nor literals can see change only the
    shape of the code: one inserts an early ``return``, the other inverts a
    condition. In both, the identifier multiset and the constant multiset are
    byte-identical before and after, because nothing is named or valued
    differently — only the control flow moved.

    So this layer records node TYPES and their nesting depth, deliberately
    discarding every name and every value. That makes it orthogonal to the other
    two by construction rather than by hope: a change that renames a variable
    moves the reference layer and not this one, and a change that wraps a
    statement in ``if not ...`` moves this one and not the others.
    """
    import ast
    from collections import Counter

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        c: Counter = Counter()

        def walk(n, depth):
            if depth > 24:                       # malformed/adversarial guard
                return
            for child in ast.iter_child_nodes(n):
                # Names and constants are the OTHER layers' business. Recording
                # only the node class is what keeps the three signals independent.
                if not isinstance(child, (ast.Name, ast.Constant, ast.Load,
                                          ast.Store, ast.Del)):
                    c[f"{type(child).__name__}@{depth}"] += 1
                walk(child, depth + 1)

        for stmt in body:
            c[f"{type(stmt).__name__}@0"] += 1
            walk(stmt, 1)
        out[node.name] = out.get(node.name, Counter()) + c
    return out


def _structure_keys(module: str, text: str) -> set:
    keys = set()
    for fn, counter in _structure_by_function(module, text).items():
        for shape, n in counter.items():
            for i in range(n):
                keys.add(f"{fn}:{shape}#{i}")
    return keys

def _units_and_refs(module: str, text: str):
    """Per-unit identifier references — the name-based call view, one file wide.

    Whole-repo resolution is deliberately not used: the question is whether the
    graph MOVES, and a single file answers that far more cheaply than two index
    builds. A cross-file consequence would only ADD movement, so measuring one
    file is the conservative direction.
    """
    spec = spec_for(Path(module))
    units = parse_mod.extract_units(module, text, spec)
    refs: set[str] = set()
    for u in units:
        for name in graph_mod.identifiers(u.source):
            refs.add(f"{u.name}->{name}")
    return units, refs


def _type_edge_keys(module: str, text: str) -> set[str]:
    """Type-layer edges for one file, as comparable keys.

    Uses the same extraction the index uses. Degrades to an empty set for a
    language with no type vocabulary — which is reported, never silently
    treated as "nothing changed"."""
    try:
        facts = parse_mod.python_type_facts(module, text)  # type: ignore[attr-defined]
    except AttributeError:
        return set()
    except SyntaxError:
        return set()
    keys: set[str] = set()
    for t in getattr(facts, "types", ()) or ():
        keys.add(f"type:{t.qualname}")
        for f in getattr(t, "fields", ()) or ():
            keys.add(f"has_field:{t.qualname}.{f.name}:{getattr(f, 'annotation', '')}")
    for s in getattr(facts, "signatures", ()) or ():
        for p in getattr(s, "params", ()) or ():
            keys.add(f"consumes:{s.qualname}:{p.name}:{getattr(p, 'annotation', '')}")
        keys.add(f"produces:{s.qualname}:{getattr(s, 'returns', '')}")
    return keys


def measure(mutation, repo_root: str | Path) -> DeltaResult:
    """Apply one mutation IN MEMORY and report what moved. Nothing is written."""
    root = Path(repo_root)
    target = root / mutation.file
    res = DeltaResult(mutation.id, mutation.defect_class, mutation.file, applied=False)

    try:
        before = target.read_text(encoding="utf-8")
    except OSError as exc:
        res.skipped_reason = f"cannot read {mutation.file}: {exc.__class__.__name__}"
        return res
    if mutation.find not in before:
        # The corpus is pinned to a revision; a drifted anchor is a real finding
        # about the corpus, not a licence to fuzzy-match into place.
        res.skipped_reason = ("the mutation's `find` anchor is not present in the "
                              "current file — the corpus has drifted from this revision")
        return res

    after = before.replace(mutation.find, mutation.replace, 1)
    res.applied = True

    # LEAKY arm: raw-source identifiers, comments included. Kept on purpose --
    # the gap between the two arms IS the measured size of the marker artefact.
    _, refs_before = _units_and_refs(mutation.file, before)
    _, refs_after = _units_and_refs(mutation.file, after)
    res.layers.append(LayerDelta(
        "code.refs.leaky",
        added=tuple(sorted(refs_after - refs_before)),
        removed=tuple(sorted(refs_before - refs_after)),
    ))

    # CLEAN arm: AST identifiers. Comments are not tokens here.
    ast_before, err_b = _ast_refs(mutation.file, before)
    ast_after, err_a = _ast_refs(mutation.file, after)
    if err_b or err_a:
        res.skipped_reason = (err_b or err_a) + " (clean arm)"
    res.layers.append(LayerDelta(
        "code.refs.ast",
        added=tuple(sorted(ast_after - ast_before)),
        removed=tuple(sorted(ast_before - ast_after)),
    ))

    lit_before = _literal_keys(mutation.file, before)
    lit_after = _literal_keys(mutation.file, after)
    res.layers.append(LayerDelta(
        "literals",
        added=tuple(sorted(lit_after - lit_before)),
        removed=tuple(sorted(lit_before - lit_after)),
    ))

    st_before = _structure_keys(mutation.file, before)
    st_after = _structure_keys(mutation.file, after)
    res.layers.append(LayerDelta(
        "structure",
        added=tuple(sorted(st_after - st_before)),
        removed=tuple(sorted(st_before - st_after)),
    ))

    ty_before = _type_edge_keys(mutation.file, before)
    ty_after = _type_edge_keys(mutation.file, after)
    res.layers.append(LayerDelta(
        "types",
        added=tuple(sorted(ty_after - ty_before)),
        removed=tuple(sorted(ty_before - ty_after)),
    ))

    try:
        from ..structcore import artifacts as art_mod
        a_before = {f"{l.relation}:{l.raw}" for l in art_mod.extract_literals(mutation.file, before)}
        a_after = {f"{l.relation}:{l.raw}" for l in art_mod.extract_literals(mutation.file, after)}
        res.layers.append(LayerDelta(
            "data.literals",
            added=tuple(sorted(a_after - a_before)),
            removed=tuple(sorted(a_before - a_after)),
        ))
    except ImportError:
        pass

    return res


def run(repo_root: str | Path = ".") -> dict:
    muts = load_mutations(repo_root)
    results = [measure(m, repo_root) for m in muts]
    applied = [r for r in results if r.applied]
    detected = [r for r in applied if r.detected]
    by_class: dict[str, dict] = {}
    for r in applied:
        b = by_class.setdefault(r.defect_class, {"total": 0, "detected": 0, "missed": []})
        b["total"] += 1
        if r.detected:
            b["detected"] += 1
        else:
            b["missed"].append(r.mutation_id)
    return {
        "version": DELTA_VERSION,
        "corpus_size": len(muts),
        "applied": len(applied),
        # Skipped mutants are NOT counted as misses and NOT counted as passes.
        # An anchor that no longer matches means the corpus drifted; folding that
        # into either column would turn a bookkeeping problem into a result.
        "skipped": [{"mutation": r.mutation_id, "reason": r.skipped_reason}
                    for r in results if not r.applied],
        "detected": len(detected),
        "detected_leaky": sum(1 for r in applied if r.detected_leaky),
        "missed": sorted(r.mutation_id for r in applied if not r.detected),
        "by_defect_class": dict(sorted(by_class.items())),
        "results": [r.to_dict() for r in results],
    }


def render(rep: dict) -> str:
    lines = [f"mutation corpus: {rep['corpus_size']}  applied: {rep['applied']}  "
             f"skipped: {len(rep['skipped'])}",
             f"CLEAN arm (AST, comments excluded): {rep['detected']}/{rep['applied']} detected",
             f"LEAKY arm (raw source, comments count): {rep['detected_leaky']}/{rep['applied']}"
             f"  <- the gap is the marker artefact", ""]
    lines.append(f"{'MUTATION':44} {'CLASS':32} {'DELTA':>6}  LAYERS THAT MOVED")
    lines.append("-" * 118)
    for r in rep["results"]:
        if not r["applied"]:
            lines.append(f"{r['mutation']:44} {r['defect_class']:32} {'SKIP':>6}  {r['skipped_reason'][:40]}")
            continue
        moved = [f"{l['layer'].replace('code.refs.','')}(+{len(l['added'])}/-{len(l['removed'])})"
                 for l in r["layers"] if l["moved"] and l["layer"] != "code.refs.leaky"]
        lines.append(f"{r['mutation']:44} {r['defect_class']:32} "
                     f"{'SEEN' if r['detected'] else 'BLIND':>6}  {', '.join(moved) or '—'}")
    if rep["missed"]:
        lines.append("")
        lines.append("BLIND TO: " + ", ".join(rep["missed"]))
    return "\n".join(lines)


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    root = argv[0] if argv and not argv[0].startswith("-") else "."

    # MEASURED 2026-07-30: `specificity`, `commit_shas` and `measure_commit` are
    # defined BELOW the `if __name__` block and this function is defined above
    # them, so no committed command could reach the specificity arm at all. The
    # published false-alarm figures (0.9% refs, 0.7% structure) were produced by
    # a throwaway script during a session and could not be regenerated by anyone
    # afterwards -- a measurement without a command is a measurement without
    # provenance, which this repository treats as no measurement.
    if "--held-out" in argv:
        rep = held_out(root, count=_int_arg(argv, "--count", 300))
        out = Path(root) / "runs" / "eval" / "graph_delta_held_out.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(json.dumps(rep, indent=1))
        print(f"\nevidence: {out}")
        return 0

    if "--specificity" in argv:
        from . import graph_delta as _self          # resolves the late bindings
        rep = _self.specificity(root, limit=_int_arg(argv, "--limit", 80))
        out = Path(root) / "runs" / "eval" / "graph_delta_specificity.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(json.dumps(rep, indent=1))
        print(f"\nevidence: {out}")
        return 0

    rep = run(root)
    out = Path(root) / "runs" / "eval" / "graph_delta.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1) if "--json" in argv else render(rep))
    print(f"\nevidence: {out}")
    return 0


def held_out(repo_root=".", *, count: int = 300, seed: int = 20260730) -> dict:
    """Detection rate over a MECHANICALLY generated corpus, per operator.

    MEASURED 2026-07-30, and the reason this exists as a function rather than as
    a number in a document: the published 75.3% held-out figure had **no
    committed command**. It was produced by a throwaway script inside a session
    and nobody -- including its author -- could regenerate it afterwards. This
    repository treats a measurement without a command as a measurement without
    provenance, which is to say as no measurement at all.

    Held out in the meaningful sense: :mod:`daedalus.eval.mutate` builds the
    corpus from the tree by rule, with no knowledge of what the scoring layers
    look at, so nothing here was tuned against these specific mutants.

    Scored on the CLEAN arm only. The three layers are applied to a function's
    source before and after mutation, and a mutant counts as detected if any of
    them moves. Per-operator breakdown is reported because the aggregate hides
    the interesting failure -- one operator scoring zero while the rest score
    well is a blind spot, and it averages away into a respectable-looking total.
    """
    from .mutate import generate

    mutants = generate(repo_root, count=count, seed=seed)
    per_op: dict[str, dict] = {}
    detected_total = 0
    for m in mutants:
        before, after = m.before, m.after
        moved = []
        for label, fn in (("refs", lambda s: _ast_refs(m.file, s)[0]),
                          ("literals", lambda s: _literal_keys(m.file, s)),
                          ("structure", lambda s: _structure_keys(m.file, s))):
            try:
                if fn(before) != fn(after):
                    moved.append(label)
            except (SyntaxError, ValueError, RecursionError):
                # An unparsable half is not a detection and not a failure of the
                # detector; counting it either way would move the headline for a
                # bookkeeping reason.
                continue
        row = per_op.setdefault(m.operator, {"n": 0, "detected": 0, "layers": {}})
        row["n"] += 1
        if moved:
            row["detected"] += 1
            detected_total += 1
            for label in moved:
                row["layers"][label] = row["layers"].get(label, 0) + 1
    for row in per_op.values():
        row["rate"] = round(row["detected"] / row["n"], 4) if row["n"] else 0.0
    return {
        "corpus": "daedalus.eval.mutate.generate",
        "seed": seed,
        "requested": count,
        "mutants": len(mutants),
        "detected": detected_total,
        "rate": round(detected_total / len(mutants), 4) if mutants else 0.0,
        "per_operator": dict(sorted(per_op.items())),
        "filtered_sites": dict(getattr(generate, "last_filtered", {}) or {}),
        "rejected_mutations": dict(getattr(generate, "last_rejected", {}) or {}),
        "arm": "clean (code.refs.ast + literals + structure); no leaky layer",
    }


def _int_arg(argv: list[str], flag: str, default: int) -> int:
    """``--limit 40``, or the default. Silent fallback is deliberate: a
    malformed limit should not lose the run, and the value is echoed in the
    written report either way."""
    try:
        return int(argv[argv.index(flag) + 1])
    except (ValueError, IndexError):
        return default


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))


# --------------------------------------------------------------------------- #
# The SPECIFICITY arm — the half the first calibration was missing              #
# --------------------------------------------------------------------------- #
# The mutation corpus contains only BAD patches, so it measures sensitivity and
# cannot measure specificity at all. A signal that moves for every change
# discriminates nothing. This arm runs REAL COMMITS through the identical
# pipeline so the two distributions can be compared.
#
# The hypothesis is stated before the run, from the shape of the first result:
# five of the seven detected mutations were PURE DELETIONS (``+0/-N``). Seeded
# defects disable things — they remove a guard, a call, a check — while real
# work usually adds or exchanges. So the candidate discriminator is not "did the
# delta move" but "did it move in the DELETING direction only".
import subprocess


def _git(repo_root, *args, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True,
                         timeout=60)
    if out.returncode != 0:
        return None
    return out.stdout if binary else out.stdout.decode("utf-8", errors="replace")


def commit_shas(repo_root, limit: int = 80, paths: str = "*.py") -> list[str]:
    """Non-merge commits touching Python, newest first. Merges are excluded
    because a merge's diff against its first parent attributes other people's
    work to it, which would pollute the corpus with changes it did not make."""
    out = _git(repo_root, "log", "--no-merges", f"-{limit}", "--format=%H", "--", paths)
    return [l.strip() for l in (out or "").splitlines() if l.strip()]


def measure_commit(sha: str, repo_root, *, max_files: int = 12) -> dict:
    """The same layer delta, for one real commit. Returns per-file and totals."""
    changed = _git(repo_root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha,
                   "--", "*.py")
    files = [f.strip().replace("\\", "/") for f in (changed or "").splitlines() if f.strip()]
    files = [f for f in files if f.endswith(".py")]
    rec = {"sha": sha[:12], "files": len(files), "skipped": "", "added": 0,
           "removed": 0, "type_moved": 0, "per_file": []}
    if not files:
        rec["skipped"] = "no python files"
        return rec
    if len(files) > max_files:
        # A sweeping commit would dominate the distribution for a reason that has
        # nothing to do with defectiveness. Bounded and SAID, never silently cut.
        rec["skipped"] = f"{len(files)} files exceeds the {max_files}-file bound"
        return rec

    for rel in files:
        before = _git(repo_root, "show", f"{sha}^:{rel}")
        after = _git(repo_root, "show", f"{sha}:{rel}")
        if after is None:
            continue                      # deleted in this commit
        if before is None:
            before = ""                   # added in this commit
        rb, eb = _ast_refs(rel, before)
        ra, ea = _ast_refs(rel, after)
        if eb or ea:
            continue                      # unparseable at one end; not a finding
        add, rem = len(ra - rb), len(rb - ra)
        ty = len(_type_edge_keys(rel, after) ^ _type_edge_keys(rel, before))
        rec["added"] += add
        rec["removed"] += rem
        rec["type_moved"] += ty
        rec["per_file"].append({"file": rel, "added": add, "removed": rem, "types": ty})
    rec["pure_deletion"] = rec["added"] == 0 and rec["removed"] > 0
    rec["moved"] = rec["added"] + rec["removed"] > 0
    return rec


def specificity(repo_root=".", limit: int = 80) -> dict:
    shas = commit_shas(repo_root, limit)
    rows = [measure_commit(s, repo_root) for s in shas]
    used = [r for r in rows if not r["skipped"] and r["per_file"]]
    moved = [r for r in used if r["moved"]]
    pure_del = [r for r in used if r.get("pure_deletion")]
    return {
        "commits_considered": len(shas),
        "commits_used": len(used),
        "skipped": [{"sha": r["sha"], "reason": r["skipped"]} for r in rows if r["skipped"]],
        "moved": len(moved),
        "pure_deletion": len(pure_del),
        "pure_deletion_shas": [r["sha"] for r in pure_del],
        "rows": used,
    }


def _refs_by_function(module: str, text: str) -> dict:
    """Per-FUNCTION reference multisets. The granularity a defect actually has.

    Aggregating a delta per commit was wrong and the measurement showed it: this
    repository's history is nearly all growth (median +354 references per commit,
    median -0), so any "removed vs added" rule is trivially never true at commit
    scale, and a guard deleted beside a new 300-line module is invisible. A
    seeded defect edits ONE function; so the comparison has to be one function
    wide or the signal drowns in the rest of the patch.
    """
    import ast
    from collections import Counter

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out: dict[str, Counter] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = list(node.body)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(getattr(body[0], "value", None), ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        c: Counter = Counter()
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name):
                    c[sub.id] += 1
                elif isinstance(sub, ast.Attribute):
                    c["." + sub.attr] += 1
        # Qualify by line so two same-named methods in one file stay distinct.
        out[f"{node.name}"] = out.get(node.name, Counter()) + c
    return out


def function_deltas(before: str, after: str, module: str = "m.py") -> list[dict]:
    """One row per function that exists in BOTH versions and changed.

    Functions added or removed wholesale are excluded: a new function has no
    'before' to lose references against, and counting it as a huge addition
    would swamp the distribution the rule is read from.
    """
    fb, fa = _refs_by_function(module, before), _refs_by_function(module, after)
    rows = []
    for name in sorted(set(fb) & set(fa)):
        b, a = fb[name], fa[name]
        added = sum((a - b).values())
        removed = sum((b - a).values())
        if added or removed:
            rows.append({"function": name, "added": added, "removed": removed})
    return rows
