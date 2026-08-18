"""dctx.py -- the Certified Context Artifact: a slice, plus a proof about it.

``semantic_slice`` returns a slice and some numbers. Nobody downstream can check,
later or on another machine, that a given blob of context was complete, secret-
free, and derived from a specific commit -- so context is passed around as an
opaque, unfalsifiable blob. A ``.dctx`` receipt is the certificate that makes it
checkable: content-addressed, offline-verifiable, and portable.

THIS MODULE ADDS NO CONTEXT LOGIC. ``compile`` is a thin wrapper over
``structcore.slice.semantic_slice``; every fact in the receipt is either read
back from that result, hashed off disk, or supplied by the caller. If a number
here disagrees with the slicer, the slicer is right and this is a bug.

WHAT IS IN THE RECEIPT SHA, AND WHY EVERYTHING ELSE IS OUT
----------------------------------------------------------
A certificate whose identity moves when the environment moves certifies nothing:
two machines on the same commit would mint two receipts and every cross-machine
comparison would be a false alarm. So the SHA covers STRUCTURAL claims only --
what was included, what was withheld and under which rule, what the source bytes
were, what the labels claimed -- and deliberately excludes:

  * ``slice_tokens`` / ``whole_repo_tokens`` / ``reduction_pct`` and the
    per-unit ``tokens`` -- ``tokens.count_tokens`` is cl100k_base when tiktoken
    is installed and chars/4 otherwise, so these differ by INSTALL, not by code.
  * ``whole_repo_tokens_exact`` -- a degraded-measurement flag about the index
    that was handed in (an older JSON dump / the Rust engine lacks
    ``total_tokens``), i.e. a property of the environment, not of the slice.
  * ``backend`` -- which engine happened to be available.
  * absolute paths and the repo root -- the same checkout at two paths is the
    same checkout; every path in the receipt is repo-relative and /-normalised.
  * timestamps -- there are none, on purpose. A ``generated_at`` field would be
    either in the hash (making the receipt irreproducible) or decorative.

CAVEAT, STATED PLAINLY: with ``max_tokens`` set, WHICH neighbours survive
``_fit_budget`` is decided by the token estimator, so the kept set -- and
therefore the receipt SHA -- is only reproducible under the same tokenizer.
Un-budgeted receipts (``max_tokens=None``, the default) have no such dependency.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .sensitivity import Policy, slice_egress_rule, _compile
# Imported rather than re-implemented on purpose: the digests below and the
# egress re-check must see EXACTLY the bytes the gate scanned. A local copy of
# "utf-8, errors=replace" would drift silently; an import breaks loudly.
from .structcore.slice import _read, semantic_slice

RECEIPT_VERSION = "dctx/1"

# Folded into every unit digest so that changing HOW a unit is identified
# invalidates old digests instead of silently comparing apples to oranges.
DIGEST_VERSION = "dctx-unit/1"

# The shared cross-track vocabulary. "none" is not a placeholder -- it is the
# only honest answer when the caller supplied no labels, and it forces recall to
# be null rather than a vacuous 1.0.
LABEL_PROVENANCE = ("hand_reachable", "independent_diff", "temporal_churn", "none")


# --------------------------------------------------------------------------- #
# provenance of the checkout                                                   #
# --------------------------------------------------------------------------- #
def _commit(root: Path) -> tuple[str | None, str]:
    """``(sha, status)`` for the checkout at ``root``.

    Absence is REPORTED, never omitted: a receipt with no ``commit_sha`` key and
    a receipt for a non-git tree are indistinguishable to a reader, and only one
    of them is trustworthy. So the field is always present and always paired
    with a status naming why it is None.
    """
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None, "git_unavailable"
    sha = p.stdout.strip()
    if p.returncode != 0 or not sha:
        return None, "not_a_git_repo"
    return sha, "ok"


def _unit_digest(rel: str, role: str, mode: str, text: str) -> str:
    """Content hash of one included unit, bound to its identity.

    Follows ``structcore.cache.file_key``: the same bytes at two paths are two
    different facts, so the path is hashed too -- and here the role/mode as well,
    because "``x.py`` as a full callee body" and "``x.py`` as a caller signature"
    are different claims about the same file.

    GRANULARITY, STATED HONESTLY: ``semantic_slice``'s ``included`` manifest
    carries ``file``/``role``/``mode``/``tokens`` and NOT the emitted symbol body,
    so this digest binds the unit's identity to its CONTAINING FILE's bytes. It
    therefore over-detects (an edit elsewhere in the file trips it) and never
    under-detects, which is the correct direction for a tamper check. Tightening
    it to the symbol body requires the slicer to surface that body.
    """
    h = hashlib.sha256()
    for part in (DIGEST_VERSION, rel, role, mode):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    h.update(text.encode("utf-8", "replace"))
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# the receipt                                                                  #
# --------------------------------------------------------------------------- #
def _canonical(receipt: dict) -> dict:
    """The structural projection that the receipt SHA is taken over.

    Everything the module docstring lists as excluded is dropped HERE, in one
    place, so there is exactly one answer to "is this field in the hash?".
    """
    m = receipt["manifest"]
    canon = {
        "receipt_version": receipt["receipt_version"],
        "commit_sha": receipt["commit_sha"],
        "commit_status": receipt["commit_status"],
        "target": receipt["target"],
        "lane": receipt["lane"],
        "max_tokens": receipt["max_tokens"],
        "focus_file": receipt["plan"]["focus_file"],
        "focus_symbol": receipt["plan"]["focus_symbol"],
        "included": [{"file": u["file"], "role": u["role"], "mode": u["mode"],
                      "sha256": u["sha256"]} for u in m["included"]],
        "withheld": m["withheld"],
        "shell_boundary_stops": m["shell_boundary_stops"],
        "trimmed_count": m["trimmed_count"],
        "egress_verdict": receipt["egress_verdict"],
        "recall": receipt["recall"],
        "label_provenance": receipt["label_provenance"],
        "labels": receipt["labels"],
        "labels_found": receipt["labels_found"],
        "slice_text_sha256": receipt["slice_text_sha256"],
    }
    # The egress verdict is only meaningful RELATIVE to the predicate that produced
    # it, so when the receipt was minted under a caller-supplied policy that policy
    # is part of the claim and must be in the hash -- otherwise the recorded
    # allow-list could be swapped for a laxer one without moving receipt_sha. Keyed
    # conditionally: a default-policy receipt (the only wired path) carries no such
    # field and hashes byte-for-byte as it did before this field existed.
    if "egress_policy" in receipt:
        canon["egress_policy"] = receipt["egress_policy"]
    return canon


def _receipt_sha(receipt: dict) -> str:
    canon = _canonical(receipt)
    return hashlib.sha256(json.dumps(
        canon, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def compile(root, target: str, lane: str = "trusted", max_tokens: int | None = None,
            policy=None, *, labels: list[str] | None = None,
            label_provenance: str = "none", idx: dict | None = None) -> dict:
    """Slice ``target`` and mint a verifiable receipt for the result.

    THE LABELS ARE AN INPUT AND ARE NEVER DERIVED HERE. Minting ``must_include``
    labels from the same graph walk that assembled the slice makes recall 1.0 by
    construction: the slicer grades itself on the answers it chose, and the
    certificate proves nothing at all. That circularity is live in this repo --
    ``daedalus/eval/tasks.py`` states its labels were "VERIFIED reachable by
    running semantic_slice", and ``eval/harness.py:_recall`` returns 1.0 for an
    empty label list -- so this wrapper takes the opposite position:

      * labels come from the caller or not at all;
      * ``label_provenance`` records WHERE they came from, in the shared
        vocabulary, and travels with the number forever;
      * no labels -> ``recall`` is None. Never 1.0. A vacuous 1.0 is the lie.

    ``label_provenance="hand_reachable"`` is accepted but is, by definition,
    the circular case; it is recorded, not rejected, so that a consumer can
    segregate it rather than blend it into a headline number.
    """
    if label_provenance not in LABEL_PROVENANCE:
        raise ValueError(f"label_provenance must be one of {LABEL_PROVENANCE!r}, "
                         f"got {label_provenance!r}")
    if labels and label_provenance == "none":
        raise ValueError("labels supplied without a provenance: recall would be "
                         "unattributable. Pass label_provenance explicitly.")
    if not labels and label_provenance != "none":
        raise ValueError(f"label_provenance={label_provenance!r} with no labels: "
                         "there is no recall claim to attribute.")

    root = Path(root).resolve()
    res = semantic_slice(root, target, idx=idx, lane=lane, policy=policy,
                         max_tokens=max_tokens)

    # sorted(): the manifest is a set of claims about what is in the slice, not a
    # rendering of it, and this repo has been bitten by iteration order reaching
    # output. Duplicates (two callee units from one module) are kept, so the
    # count still matches n_included.
    included = sorted(
        ({"file": u["file"], "role": u["role"], "mode": u["mode"],
          "sha256": _unit_digest(u["file"], u["role"], u["mode"], _read(root, u["file"])),
          "tokens": u["tokens"]}
         for u in res["included"]),
        key=lambda u: (u["file"], u["role"], u["mode"], u["sha256"]),
    )

    slice_text = res["slice_text"]
    recall: float | None = None
    found: list[str] = []
    if labels:
        # Same substring test as eval/harness.py:_recall, so the two numbers are
        # comparable; the difference is entirely in where the labels came from.
        found = sorted(m for m in labels if m in slice_text)
        recall = len(found) / len(labels)

    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "commit_sha": None,
        "commit_status": "",
        "target": res["target"],
        "lane": lane,
        "max_tokens": max_tokens,
        "plan": {
            "focus_file": res["focus_file"],
            "focus_symbol": res["focus_symbol"],
            "n_included": res["n_included"],
            "withheld_count": res["withheld_count"],
        },
        "manifest": {
            "included": included,
            "withheld": res["withheld"],
            "shell_boundary_stops": res["shell_boundary_stops"],
            # The fail-closed focus-gate path in slice.py returns a result dict
            # WITHOUT trimmed_count; .get keeps a refused slice certifiable
            # instead of crashing the wrapper on the safety path.
            "trimmed_count": res.get("trimmed_count", 0),
        },
        "egress_verdict": _egress_verdict(root, included, lane, policy),
        "recall": recall,
        "label_provenance": label_provenance,
        "labels": sorted(labels) if labels else [],
        "labels_found": found,
        "tokens": {
            "slice_tokens": res["slice_tokens"],
            "whole_repo_tokens": res["whole_repo_tokens"],
            "whole_repo_tokens_exact": res.get("whole_repo_tokens_exact"),
            "reduction_pct": res["reduction_pct"],
        },
        "backend": res["backend"],
        "slice_text_sha256": hashlib.sha256(slice_text.encode("utf-8")).hexdigest(),
    }
    # A caller-supplied policy IS part of the egress claim: verify() must re-check
    # under the same allow-list / deny-content or an honestly-minted receipt false-
    # alarms offline against the generic default. Recorded only when non-None so a
    # caller that passes no policy gets a byte-identical receipt to before.
    if policy is not None:
        receipt["egress_policy"] = _egress_policy_fingerprint(policy)
    receipt["commit_sha"], receipt["commit_status"] = _commit(root)
    # Derived, not hand-maintained: the list of hashed fields cannot drift out of
    # step with _canonical because it IS _canonical's key set.
    receipt["hashed_fields"] = sorted(_canonical(receipt))
    receipt["receipt_sha"] = _receipt_sha(receipt)
    return receipt


def _egress_verdict(root: Path, included: list[dict], lane: str, policy) -> dict:
    """Re-run the egress gate over everything the slice claims to INCLUDE.

    ``semantic_slice`` already gates at emission, so a clean repo yields
    ``pass: True`` with no violations -- that is the point. This is the
    certificate's independent second opinion: if the slicer ever emits a unit
    whose file trips the floor, the receipt says so instead of blessing it.
    Only the rule NAME is recorded, never matched text -- see verify()'s note.
    """
    violations = []
    for rel in sorted({u["file"] for u in included}):
        rule = slice_egress_rule(rel, _read(root, rel), lane=lane, policy=policy)
        if rule:
            violations.append({"file": rel, "rule": rule})
    return {"lane": lane, "pass": not violations, "violations": violations}


def _egress_policy_fingerprint(policy: Policy) -> dict:
    """The egress-relevant projection of a Policy, as portable plain data.

    ONLY the fields ``slice_egress_rule``'s tier-2 (``classify_data`` /
    ``_path_is_sensitive``) consults are recorded: the change-risk and
    write-block fields do not move the egress verdict this receipt certifies, so
    hashing them would bind the certificate to irrelevant state. Compiled
    ``deny_content`` patterns are stored as their SOURCE strings so ``verify``
    can rebuild the identical predicate offline with no pickled objects.

    ``sorted()`` throughout: the egress decision is order-independent (``any()``
    over the substring sets, and ``classify_data`` only reports whether ANY
    deny_content pattern matched), and this projection reaches the receipt SHA,
    which must not move with set/dict iteration order.
    """
    return {
        "deny_substrings": sorted(policy.deny_substrings),
        "allow_substrings": sorted(policy.allow_substrings),
        "allow_exceptions": sorted(policy.allow_exceptions),
        "deny_content": sorted(p.pattern for p in policy.deny_content),
        "default_deny": bool(policy.default_deny),
    }


def _policy_from_fingerprint(fp: dict) -> Policy:
    """Rebuild the egress predicate a receipt was minted under, from its
    fingerprint. Fail-closed on a malformed/absent field: ``default_deny``
    defaults to True (withhold), never False. The change-risk fields are left at
    their generic defaults -- ``verify`` only ever calls ``slice_egress_rule``,
    which does not read them."""
    return Policy(
        deny_substrings=tuple(fp.get("deny_substrings", ())),
        allow_substrings=tuple(fp.get("allow_substrings", ())),
        allow_exceptions=tuple(fp.get("allow_exceptions", ())),
        deny_content=_compile(fp.get("deny_content", ())),
        default_deny=bool(fp.get("default_deny", True)),
    )


# --------------------------------------------------------------------------- #
# verification -- offline, no model                                            #
# --------------------------------------------------------------------------- #
def _recall_claim_failures(receipt: dict) -> list[str]:
    """The anti-tautology invariants. A receipt may not claim recall it cannot
    attribute, and may not claim 1.0 out of thin air."""
    prov, recall = receipt.get("label_provenance"), receipt.get("recall")
    labels, found = receipt.get("labels") or [], receipt.get("labels_found") or []
    out = []
    if prov not in LABEL_PROVENANCE:
        return [f"label_provenance {prov!r} is not in the shared vocabulary"]
    if prov == "none":
        if recall is not None:
            out.append(f"recall {recall!r} claimed with label_provenance 'none' "
                       "(no labels were supplied; recall must be null)")
        if labels:
            out.append("labels present but label_provenance is 'none'")
        return out
    if not labels:
        out.append(f"label_provenance {prov!r} with an empty label set")
    elif recall is None:
        out.append(f"label_provenance {prov!r} supplied labels but recall is null")
    else:
        if not set(found) <= set(labels):
            out.append("labels_found is not a subset of labels")
        if abs(recall - len(found) / len(labels)) > 1e-9:
            out.append(f"recall {recall!r} disagrees with labels_found "
                       f"({len(found)}/{len(labels)})")
    return out


def verify(receipt: dict, root) -> tuple[bool, list[str]]:
    """Re-check a receipt against a checkout. Offline, no model, no network.

    Returns ``(ok, failures)`` -- always the SPECIFIC failures, never a bare
    False: "this context is stale" is unactionable, "unit digest mismatch:
    pkg/app.py [callee/full]" is a diff to go read.

    WHAT IS AND IS NOT PROVED. The commit, the per-unit source digests, the
    no-secret-egress predicate and the receipt's own integrity are re-derived
    from disk, so tampering with either the checkout or the receipt is caught.
    The recall claim is checked for INTERNAL CONSISTENCY and against the
    anti-tautology invariants -- reproducing the number itself would mean
    re-running the slicer, which is a recompile, not a predicate. To reproduce
    it, recompile and compare ``receipt_sha``.
    """
    root = Path(root).resolve()
    failures: list[str] = []
    if receipt.get("receipt_version") != RECEIPT_VERSION:
        return False, [f"receipt_version {receipt.get('receipt_version')!r} "
                       f"!= {RECEIPT_VERSION!r} (cannot verify)"]
    if _receipt_sha(receipt) != receipt.get("receipt_sha"):
        failures.append("receipt_sha does not match the receipt's own contents "
                        "(tampered or hand-edited)")
    sha, status = _commit(root)
    if sha != receipt.get("commit_sha"):
        failures.append(f"commit mismatch: receipt {receipt.get('commit_sha')} "
                        f"vs checkout {sha} ({status})")
    lane = receipt.get("lane", "trusted")
    # Re-check egress under the SAME predicate that minted the verdict. A receipt
    # minted with a caller-supplied policy carries its egress-relevant projection
    # (folded into receipt_sha above, so a swapped policy is already caught as a
    # sha mismatch); its absence means the default policy, matching a default mint
    # byte-for-byte. The unconditional secret floor (tier 1) runs regardless of
    # this, so a forged laxer policy still cannot ride a real secret through.
    fp = receipt.get("egress_policy")
    policy = _policy_from_fingerprint(fp) if fp is not None else None
    included = receipt["manifest"]["included"]
    for u in included:
        if _unit_digest(u["file"], u["role"], u["mode"],
                        _read(root, u["file"])) != u["sha256"]:
            failures.append(f"unit digest mismatch: {u['file']} "
                            f"[{u['role']}/{u['mode']}] changed on disk")
    # The floor re-runs on the CURRENT bytes: a secret planted into an already-
    # included file after minting must fail the receipt, not ride along on it.
    # Only the rule name is reported -- a certificate that quoted the secret it
    # certifies the absence of would be an own-goal.
    for rel in sorted({u["file"] for u in included}):
        rule = slice_egress_rule(rel, _read(root, rel), lane=lane, policy=policy)
        if rule:
            failures.append(f"egress violation: {rel} ({rule})")
    failures.extend(_recall_claim_failures(receipt))
    return not failures, failures


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="daedalus dctx",
        description="Mint or verify a .dctx certified-context receipt.")
    ap.add_argument("repo", help="repo root")
    ap.add_argument("target", nargs="?", help="path/to/file.ext  or  path/to/file.ext::symbol")
    ap.add_argument("--lane", default="trusted", choices=("trusted", "untrusted"))
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--out", default=None, help="write the receipt JSON here")
    ap.add_argument("--verify", default=None, metavar="RECEIPT.dctx",
                    help="verify an existing receipt against <repo> instead of minting")
    args = ap.parse_args(argv)

    if args.verify:
        receipt = json.loads(Path(args.verify).read_text(encoding="utf-8"))
        ok, failures = verify(receipt, args.repo)
        print("VERIFIED" if ok else "FAILED")
        for f in failures:
            print(f"  - {f}")
        return 0 if ok else 1

    if not args.target:
        ap.error("target is required unless --verify is given")
    # Receipt verification above stays fail-open read-only inspection; the
    # minting path (worktree/git probes plus the optional receipt write)
    # starts at the central boundary.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.dctx",
        REGISTRY_BY_ID["cli.dctx"].effects,
        (process_guard_boundary_decision(),),
    )
    receipt = compile(args.repo, args.target, lane=args.lane, max_tokens=args.max_tokens)
    text = json.dumps(receipt, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"receipt_sha {receipt['receipt_sha']}  ->  {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
