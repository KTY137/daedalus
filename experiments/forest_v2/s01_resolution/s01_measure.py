"""EXPERIMENT (forest_v2 / slice s01): the measurement harness.

Read-only.  Pure stdlib.  Prints exactly one JSON object; no writes, no
network, no subprocess, no model calls.

It answers four questions with raw counts on the same denominator:

1. **What did the pre-study probe attribute?**  The baseline is not re-typed
   here -- ``probe_cross_module_resolution.probe`` is imported and run, and its
   own helper functions drive a per-call-site replica.  The replica's totals are
   asserted equal to the probe's (``parity_ok``); without that assertion a
   "gain" could just be a changed denominator.
2. **What does the s01 resolver verify?**  A site counts as *verified* only when
   the resolver names a definition inside the analysed tree (module, symbol,
   file, line).  ``external`` is reported separately and never folded into the
   headline: a stdlib name is a claim, not a proof.
3. **Where does the baseline over-claim?**  The probe's same-module rule matches
   the last dotted segment against every function *and method* name in the file,
   so ``path.read_text()`` is claimed by a local ``read_text`` method.  The
   cross-tab counts how often s01 contradicts such a claim with a definition in
   a different module, or with an external target.  That is a lower bound on the
   baseline's false attributions, retained as negative evidence.
4. **Why do the remaining sites fail?**  Every unresolved site carries a named
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


def _local_functions(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(child.name)
    return names


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
        local_functions = _local_functions(module.tree)
        bindings = probe._bindings(module.tree, module.name)
        file_counter: Counter = Counter()

        for node in ast.walk(module.tree):
            if not isinstance(node, ast.Call):
                continue
            res = by_id.get(id(node))
            if res is None:
                replica["MISSED_BY_S01"] += 1
                continue
            base_bucket = _baseline_site(
                probe._call_name(node.func), local_functions, bindings, module_symbols
            )
            replica[base_bucket] += 1
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

    calls = sum(replica[b] for b in BASELINE_BUCKETS) or 1
    probe_totals = baseline_probe["totals"]
    parity_ok = all(
        replica[bucket] == probe_totals[bucket] for bucket in BASELINE_BUCKETS
    ) and calls == probe_totals["call_sites"]

    baseline_attributed = (
        replica["same_module_resolvable"]
        + replica["cross_module_repo"]
        + replica["cross_module_external"]
    )
    baseline_repo = replica["same_module_resolvable"] + replica["cross_module_repo"]
    verified = s01_status["verified"]
    external = s01_status["external"]

    def pct(value: int) -> float:
        return round(100.0 * value / calls, 2)

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
        "baseline": {
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
            "verified_vs_baseline_repo_claim": verified - baseline_repo,
            "verified_pct_points": round(pct(verified) - pct(baseline_repo), 2),
            "attributed_pct_points": round(
                pct(verified + external) - pct(baseline_attributed), 2
            ),
            "newly_verified_from_baseline_unattributed": cross_tab[
                "baseline_unattributed/s01_verified"
            ],
            "newly_verified_by_kind": dict(gain_kinds.most_common()),
        },
        "baseline_overclaim": {
            "confirmed_false_same_module": cross_tab["baseline_same_module/s01_other_module"]
            + cross_tab["baseline_same_module/s01_external"],
            "agrees_same_module": cross_tab["baseline_same_module/s01_same_module"],
            "undecided": cross_tab["baseline_same_module/s01_unresolved"],
            "examples": overclaim_examples,
        },
        "ablations": ablations,
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
    print(
        json.dumps(
            measure(root, samples=samples, controls=controls), indent=2, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
