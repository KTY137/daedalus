"""EXPERIMENT (forest_v2 / slice s01): the measurement harness.

Read-only.  Pure stdlib.  Prints exactly one JSON object; no writes, no
network, no subprocess, no model calls.

It answers four questions with raw counts on the same denominator:

1. **What did the pre-study probe attribute?**  The baseline is not re-typed
   here -- ``probe_cross_module_resolution.probe`` is imported and run, and its
   own helper functions drive a per-call-site replica.  The replica's totals
   must equal the probe's or :class:`ParityError` is raised and no JSON is
   printed; without that enforcement a "gain" could just be a changed
   denominator.  (Until 2026-08-18 ``parity_ok`` was computed, put in the dict
   and asserted by nothing -- see ``README.md``, "Retraction".)
2. **What does the s01 resolver verify?**  A site counts as *verified* only when
   the resolver names a definition inside the analysed tree (module, symbol,
   file, line).  ``external`` is reported separately and never folded into the
   headline: a stdlib name is a claim, not a proof.
3. **Against WHICH baseline?**  Four control arms are computed on one pass, and
   the comparison arm is ``DEFAULT_ARM`` (B1), not the probe's own rule (B0).
   B0 walks ``ClassDef`` for its *methods* and never adds the class name, so
   every same-module constructor call is unattributable to it by construction.
   B1 repairs exactly that hole and strictly dominates B0 on this corpus (more
   coverage, an identical contradiction population), so a lift measured against
   B0 is a lift against a dominated control.
4. **Where does the baseline over-claim?**  The same-module rule matches the
   last dotted segment against a flat name set, so ``path.read_text()`` is
   claimed by a local ``read_text`` method.  The cross-tab counts how often s01
   contradicts such a claim with a definition in a different module, or with an
   external target.  That is a lower bound on the arm's false attributions,
   retained as negative evidence.  It is also the reason a rise in "share of
   sites bound to a named in-tree definition" proves nothing on its own: the
   metric is monotone in guessing, so it may only be compared between arms of
   equal or better contradiction rate.
5. **Why do the remaining sites fail?**  Every unresolved site carries a named
   reason.  The reason histogram is the Gate-2 work list.

Usage::

    python experiments/forest_v2/s01_resolution/s01_measure.py [ROOT] [--samples N]
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _extra in (_HERE, _HERE.parent):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import probe_cross_module_resolution as probe  # noqa: E402  (pre-study baseline)
from s01_index import DEFAULT_PACKAGES, build_index  # noqa: E402
from s01_resolver import (  # noqa: E402
    EXTERNAL_KINDS,
    FULL,
    VERIFIED_KINDS,
    Options,
    resolve_module,
)

# Ablations remove one mechanism at a time so its marginal contribution is
# measured rather than asserted.  The separate randomised control keeps every
# mechanism switched on and only makes the bindings name the wrong module; what
# still verifies under it is name coincidence, not binding following.
ABLATIONS = {
    "full": FULL,
    "no_imports": Options(use_imports=False),
    "no_hierarchy": Options(use_hierarchy=False),
    "no_receiver_types": Options(use_receiver_types=False),
}

ACCEPTANCE_FILES = probe.ACCEPTANCE_FILES


class ParityError(RuntimeError):
    """The per-site replica disagreed with the pre-study probe.

    Fatal on purpose.  A report whose replica does not reproduce the probe is
    comparing two different denominators, and every delta in it is meaningless.
    """


class DeadSwitchError(RuntimeError):
    """An ablation switch changed nothing, so the ablation table proves nothing.

    ``ablated <= full`` is satisfied by a switch that does nothing at all.  This
    check demands the stronger property: each switch must be observably live on
    the measured corpus.  A zero marginal is therefore reported as a broken
    instrument, not as a quiet zero -- if a mechanism genuinely earns nothing on
    a future corpus, that is a finding to write down, not to publish silently.
    """


BASELINE_BUCKETS = (
    "same_module_resolvable",
    "cross_module_repo",
    "cross_module_external",
    "still_unattributed",
    "unresolvable_shape",
)


def _baseline_site(
    name: str,
    local_functions: set[str],
    bindings: dict[str, str],
    module_symbols: dict[str, set[str]],
) -> str:
    """The pre-study probe's decision for one call site, its rules verbatim."""
    if not name:
        return "unresolvable_shape"
    if name.split(".")[-1] in local_functions:
        return "same_module_resolvable"
    head, _, rest = name.partition(".")
    target = bindings.get(head)
    if target is None:
        return "still_unattributed"
    dotted = f"{target}.{rest}" if rest else target
    owner, _, symbol = dotted.rpartition(".")
    if owner in module_symbols and symbol in module_symbols[owner]:
        return "cross_module_repo"
    if dotted in module_symbols:
        return "cross_module_repo"
    return "cross_module_external"


def audit_definition(root: Path, target: str, rel: str, line: int, cache: dict) -> str:
    """Reopen a claimed definition site and check the definition is really there.

    A resolver that reports percentages without this check grades its own
    homework.  Returns ``'def'`` (a ``def``/``class`` for the claimed name),
    ``'assign'`` (a module-level binding of that name), ``'mismatch'`` (the line
    does not mention the name at all) or ``'unreadable'``.
    """
    if not rel or line <= 0:
        return "unreadable"
    lines = cache.get(rel)
    if lines is None:
        try:
            lines = (root / rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            lines = []
        cache[rel] = lines
    if line > len(lines):
        return "unreadable"
    text = lines[line - 1].split("#", 1)[0]
    name = re.escape(target.rsplit(".", 1)[-1])
    if re.match(rf"\s*(?:async\s+def|def|class)\s+{name}\b", text):
        return "def"
    head = text.split("=", 1)[0] if "=" in text else text
    if re.search(rf"\b{name}\b", head):
        return "assign"
    return "mismatch"


def rotation_map(index, rotate: int) -> dict:
    """Repo module -> a different repo module, a deterministic rotation.

    Feeds the randomised control: every repo-internal binding keeps its shape
    and its symbol but names the wrong module.  Whatever still verifies is name
    coincidence rather than binding following.

    RETAINED NEGATIVE RESULT (2026-08-18).  The first two attempts at this
    control both came back null and neither null meant anything.  (a) Rotating
    each module's import *table* onto another module barely moved the number,
    because an ``ImportFrom`` target is stored as an absolute dotted path -- the
    owning module only matters for relative imports.  (b) Rewriting the table on
    the index leaked, because the resolver re-seeds function-level imports
    straight from the AST and overwrote the permuted values.  A control has to
    be applied where the resolver actually reads, which is why the mapping is an
    ``Options`` field rather than a mutation of the index.
    """
    names = sorted(index.modules)
    return {
        name: names[(position + rotate) % len(names)]
        for position, name in enumerate(names)
    }


def verified_count(index, options) -> dict:
    """Verified/external/unresolved totals for one ablation or control run."""
    status = Counter()
    kinds = Counter()
    for module in index.modules.values():
        for _node, res in resolve_module(index, module, options):
            status[res.status] += 1
            if res.status == "verified":
                kinds[res.kind] += 1
    total = sum(status.values()) or 1
    return {
        "verified": status["verified"],
        "verified_pct": round(100.0 * status["verified"] / total, 2),
        "external": status["external"],
        "unresolved": status["unresolved"],
        "verified_kinds": dict(kinds.most_common()),
    }


def arm_b0(tree: ast.Module) -> set[str]:
    """B0 -- the pre-study probe's rule, verbatim.  **A dominated control.**

    It walks each ``ClassDef`` for its methods and never adds ``node.name``, so
    a call to a class defined in the same module can never be attributed to it.
    Retained because the pre-study reported against it, and because parity with
    the probe has to be checked against the probe's actual rule.  It must not be
    the comparison arm; see :data:`DEFAULT_ARM`.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(child.name)
    return names


def arm_b1(tree: ast.Module) -> set[str]:
    """B1 -- B0 plus the module-level class names.  The repaired control.

    One line of repair, and it is not a courtesy: on this corpus B1 strictly
    dominates B0 -- it attributes 3,368 more sites and contradicts s01 on
    exactly as many (109, of which 26 external) as B0 did.
    """
    names = arm_b0(tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
    return names


def arm_b2(tree: ast.Module) -> set[str]:
    """B2 -- every ``def``/``class`` name anywhere in the module, nested included."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def arm_b3(tree: ast.Module) -> set[str]:
    """B3 -- B2 plus module-level assignment targets.  The sloppiest arm.

    Rule as implemented: ``Assign``/``AnnAssign`` targets that are plain
    ``Name`` nodes in ``tree.body``.  A wider reading (every assignment target
    anywhere in the module) yields 30.50 % instead of 29.61 % on this corpus --
    reported in the README, because the exact spelling of "sloppier still" moves
    the number and the reader is owed that.
    """
    names = arm_b2(tree)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


BASELINE_ARMS = {"B0": arm_b0, "B1": arm_b1, "B2": arm_b2, "B3": arm_b3}

#: The arm every headline in this slice is measured against.
DEFAULT_ARM = "B1"
#: The arm the pre-study probe implements; parity is checked against this one.
PARITY_ARM = "B0"

# Historical alias.  ``_local_functions`` was the only name set that existed,
# which is how a dominated control became "the" control.
_local_functions = arm_b0


def measure(
    root: Path,
    packages: tuple[str, ...] = DEFAULT_PACKAGES,
    samples: int = 0,
    controls: bool = True,
) -> dict:
    baseline_probe = probe.probe(root)
    index = build_index(root, packages)

    module_symbols = {
        name: probe._collect_symbols(info.tree) for name, info in index.modules.items()
    }

    replica = Counter()
    arm_buckets = {arm: Counter() for arm in BASELINE_ARMS}
    arm_contradictions = {arm: Counter() for arm in BASELINE_ARMS}
    arm_misses_s01_verifies = Counter()
    s01_kinds = Counter()
    s01_status = Counter()
    unresolved_reasons = Counter()
    var_origins = Counter()
    cross_tab = Counter()
    overclaim_examples: list[dict] = []
    gain_kinds = Counter()
    sample_bank: dict[str, list[dict]] = {}
    per_file: dict[str, Counter] = {}
    audit = Counter()
    audit_by_kind: dict[str, Counter] = {}
    audit_failures: list[dict] = []
    source_cache: dict[str, list[str]] = {}

    for module in index.modules.values():
        results = resolve_module(index, module)
        by_id = {id(node): res for node, res in results}
        arm_names = {arm: build(module.tree) for arm, build in BASELINE_ARMS.items()}
        bindings = probe._bindings(module.tree, module.name)
        file_counter: Counter = Counter()

        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            res = by_id.get(id(node))
            if res is None:
                replica["MISSED_BY_S01"] += 1
                continue
            call_name = probe._call_name(node.func)
            per_arm = {
                arm: _baseline_site(call_name, names, bindings, module_symbols)
                for arm, names in arm_names.items()
            }
            for arm, bucket in per_arm.items():
                arm_buckets[arm][bucket] += 1
                if bucket == "same_module_resolvable":
                    if res.status == "verified" and res.target_module != module.name:
                        arm_contradictions[arm]["s01_other_module"] += 1
                    elif res.status == "external":
                        arm_contradictions[arm]["s01_external"] += 1
                elif res.status == "verified" and bucket != "cross_module_repo":
                    arm_misses_s01_verifies[arm] += 1
            # The replica exists to reproduce the PROBE, so it must use the
            # probe's own (dominated) rule.  The comparison arm is a different
            # question and is DEFAULT_ARM.
            replica[per_arm[PARITY_ARM]] += 1
            base_bucket = per_arm[DEFAULT_ARM]
            s01_kinds[res.kind] += 1
            s01_status[res.status] += 1
            file_counter[res.status] += 1
            if res.status == "unresolved":
                unresolved_reasons[res.kind] += 1
            if res.origin:
                var_origins[res.origin] += 1
            if res.status == "verified":
                verdict = audit_definition(
                    root, res.target, res.target_rel, res.target_line, source_cache
                )
                audit[verdict] += 1
                audit_by_kind.setdefault(res.kind, Counter())[verdict] += 1
                if verdict in {"mismatch", "unreadable"} and len(audit_failures) < 15:
                    audit_failures.append(
                        {
                            "site": f"{module.rel}:{res.site_line}",
                            "claimed": res.target,
                            "at": f"{res.target_rel}:{res.target_line}",
                            "kind": res.kind,
                            "verdict": verdict,
                        }
                    )

            if base_bucket == "same_module_resolvable":
                if res.status == "verified":
                    if res.target_module == module.name:
                        cross_tab["baseline_same_module/s01_same_module"] += 1
                    else:
                        cross_tab["baseline_same_module/s01_other_module"] += 1
                        if len(overclaim_examples) < 12:
                            overclaim_examples.append(
                                {
                                    "site": f"{module.rel}:{res.site_line}",
                                    "s01_target": res.target,
                                    "s01_kind": res.kind,
                                }
                            )
                elif res.status == "external":
                    cross_tab["baseline_same_module/s01_external"] += 1
                    if len(overclaim_examples) < 12:
                        overclaim_examples.append(
                            {
                                "site": f"{module.rel}:{res.site_line}",
                                "s01_target": res.target,
                                "s01_kind": res.kind,
                            }
                        )
                else:
                    cross_tab["baseline_same_module/s01_unresolved"] += 1
            elif base_bucket in {"still_unattributed", "unresolvable_shape"}:
                if res.status == "verified":
                    cross_tab["baseline_unattributed/s01_verified"] += 1
                    gain_kinds[res.kind] += 1
                elif res.status == "external":
                    cross_tab["baseline_unattributed/s01_external"] += 1
                else:
                    cross_tab["baseline_unattributed/s01_unresolved"] += 1
            else:
                cross_tab[f"baseline_{base_bucket}/s01_{res.status}"] += 1

            if samples:
                bank = sample_bank.setdefault(res.kind, [])
                if len(bank) < samples:
                    bank.append(
                        {
                            "site": f"{module.rel}:{res.site_line}",
                            "target": res.target,
                            "status": res.status,
                        }
                    )
        per_file[module.rel] = file_counter

    ablations: dict[str, dict] = {}
    if controls:
        for name, options in ABLATIONS.items():
            ablations[name] = verified_count(index, options)
        ablations["control_permuted_binding_targets"] = verified_count(
            index, Options(module_map=rotation_map(index, rotate=7))
        )

    switch_liveness = {}
    if controls:
        full_verified = ablations["full"]["verified"]
        for name in ABLATIONS:
            if name == "full":
                continue
            marginal = full_verified - ablations[name]["verified"]
            switch_liveness[name] = {"marginal": marginal, "live": marginal > 0}
        control = ablations["control_permuted_binding_targets"]["verified"]
        switch_liveness["control_permuted_binding_targets"] = {
            "marginal": full_verified - control,
            "live": control < full_verified,
        }
        dead = sorted(n for n, s in switch_liveness.items() if not s["live"])
        if dead:
            raise DeadSwitchError(
                "ablation/control switches changed nothing on this corpus, so the "
                f"marginals below them prove nothing: {dead}"
            )

    calls = sum(replica[b] for b in BASELINE_BUCKETS) or 1
    probe_totals = baseline_probe["totals"]
    parity_ok = all(
        replica[bucket] == probe_totals[bucket] for bucket in BASELINE_BUCKETS
    ) and calls == probe_totals["call_sites"]
    if not parity_ok:
        raise ParityError(
            "the per-site replica does not reproduce the pre-study probe, so the "
            "denominator is not shared and no delta in this report is meaningful; "
            f"replica={dict(replica)} probe={probe_totals}"
        )

    verified = s01_status["verified"]
    external = s01_status["external"]

    def pct(value: int) -> float:
        return round(100.0 * value / calls, 2)

    arms_report = {}
    for arm, buckets in arm_buckets.items():
        attributed = (
            buckets["same_module_resolvable"]
            + buckets["cross_module_repo"]
            + buckets["cross_module_external"]
        )
        repo = buckets["same_module_resolvable"] + buckets["cross_module_repo"]
        contradictions = sum(arm_contradictions[arm].values())
        arms_report[arm] = {
            "rule": (BASELINE_ARMS[arm].__doc__ or "").strip().splitlines()[0],
            "buckets": dict(buckets),
            "attributed": attributed,
            "attributed_pct": pct(attributed),
            "repo_claimed": repo,
            "repo_claimed_pct": pct(repo),
            "s01_lift_pp": round(pct(verified) - pct(repo), 2),
            "contradicted_by_s01": dict(arm_contradictions[arm]),
            "contradicted_by_s01_total": contradictions,
            "contradiction_rate_pct": round(
                100.0 * contradictions / (buckets["same_module_resolvable"] or 1), 2
            ),
            "sites_this_arm_misses_that_s01_verifies": arm_misses_s01_verifies[arm],
        }

    default_buckets = arm_buckets[DEFAULT_ARM]
    baseline_attributed = (
        default_buckets["same_module_resolvable"]
        + default_buckets["cross_module_repo"]
        + default_buckets["cross_module_external"]
    )
    baseline_repo = (
        default_buckets["same_module_resolvable"] + default_buckets["cross_module_repo"]
    )
    b0_repo = (
        arm_buckets["B0"]["same_module_resolvable"] + arm_buckets["B0"]["cross_module_repo"]
    )

    acceptance = {}
    for rel in ACCEPTANCE_FILES:
        counter = per_file.get(rel)
        if counter is None:
            continue
        total = sum(counter.values()) or 1
        acceptance[rel] = {
            "call_sites": sum(counter.values()),
            "verified": counter["verified"],
            "verified_pct": round(100.0 * counter["verified"] / total, 1),
            "external": counter["external"],
            "unresolved": counter["unresolved"],
        }

    return {
        "schema": "forest-v2-s01-resolution/1",
        "read_only": True,
        "packages": list(packages),
        "modules_indexed": len(index.modules),
        "unparseable": len(index.unparseable),
        "call_sites": calls,
        "baseline_probe_totals": probe_totals,
        "baseline_replica": dict(replica),
        "parity_ok": parity_ok,
        "parity_enforced": True,
        "baseline_arms": arms_report,
        "default_arm": DEFAULT_ARM,
        "parity_arm": PARITY_ARM,
        "baseline": {
            "arm": DEFAULT_ARM,
            "attributed": baseline_attributed,
            "attributed_pct": pct(baseline_attributed),
            "repo_claimed": baseline_repo,
            "repo_claimed_pct": pct(baseline_repo),
        },
        "s01": {
            "verified": verified,
            "verified_pct": pct(verified),
            "external": external,
            "external_pct": pct(external),
            "attributed": verified + external,
            "attributed_pct": pct(verified + external),
            "unresolved": s01_status["unresolved"],
            "unresolved_pct": pct(s01_status["unresolved"]),
            "by_kind": dict(s01_kinds.most_common()),
            "verified_kinds": {
                k: v for k, v in s01_kinds.most_common() if k in VERIFIED_KINDS
            },
            "external_kinds": {
                k: v for k, v in s01_kinds.most_common() if k in EXTERNAL_KINDS
            },
            "receiver_type_origin": dict(var_origins.most_common()),
        },
        "delta": {
            "measured_against_arm": DEFAULT_ARM,
            "verified_vs_baseline_repo_claim": verified - baseline_repo,
            "verified_pct_points": round(pct(verified) - pct(baseline_repo), 2),
            "attributed_pct_points": round(
                pct(verified + external) - pct(baseline_attributed), 2
            ),
            "retracted_vs_B0_dominated_control": {
                "verified_pct_points": round(pct(verified) - pct(b0_repo), 2),
                "why_retracted": (
                    "B0 cannot attribute a same-module constructor call by "
                    "construction (arm_b0 never adds ClassDef.name); B1 repairs "
                    "that with no extra contradictions, so B0 is dominated and a "
                    "lift over it measures the hole, not the resolver"
                ),
            },
            "newly_verified_from_baseline_unattributed": cross_tab[
                "baseline_unattributed/s01_verified"
            ],
            "newly_verified_by_kind": dict(gain_kinds.most_common()),
        },
        "baseline_overclaim": {
            "arm": DEFAULT_ARM,
            "confirmed_false_same_module": cross_tab["baseline_same_module/s01_other_module"]
            + cross_tab["baseline_same_module/s01_external"],
            "agrees_same_module": cross_tab["baseline_same_module/s01_same_module"],
            "undecided": cross_tab["baseline_same_module/s01_unresolved"],
            "examples": overclaim_examples,
        },
        "ablations": ablations,
        "ablation_switch_liveness": switch_liveness,
        "definition_audit": {
            "checked": sum(audit.values()),
            "confirmed_def": audit["def"],
            "confirmed_assign": audit["assign"],
            "mismatch": audit["mismatch"],
            "unreadable": audit["unreadable"],
            "confirmed_pct": round(
                100.0 * (audit["def"] + audit["assign"]) / (sum(audit.values()) or 1), 2
            ),
            "by_kind": {k: dict(v) for k, v in sorted(audit_by_kind.items())},
            "failures": audit_failures,
        },
        "cross_tab": dict(sorted(cross_tab.items())),
        "unresolved_reasons": dict(unresolved_reasons.most_common()),
        "acceptance_sites": acceptance,
        "samples": sample_bank,
    }


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[3]
    samples = 0
    controls = True
    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item == "--samples":
            samples = int(rest.pop(0)) if rest else 0
        elif item == "--no-controls":
            controls = False
        elif not item.startswith("--"):
            root = Path(item)
    try:
        report = measure(root, samples=samples, controls=controls)
    except (ParityError, DeadSwitchError) as exc:
        # No JSON on stdout: a report whose instrument failed must not be
        # publishable, and a consumer that only reads stdout must get nothing.
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
