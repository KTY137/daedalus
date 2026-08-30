# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""No second promotion path.

The Phase-0 reachability receipt recorded that the checkpoint line's verifier
had ZERO production callers -- a trust root nothing calls is documentation. The
opposite failure is worse: two callers of a trust root are two promotion paths
wearing one name, and invariant 1 ("one kernel") is about exactly that.

So this file pins the number at ONE, structurally, by reading the tree rather
than by importing it. A grep-shaped test is the right instrument here: an
import-time check only sees the modules that happened to be imported, while the
claim is about every module in the package.

The live chain these tests pin:

    daedalus/spine/effect_boundary.py   EntrypointSpec("python.promote_candidates")
      -> daedalus/kairos/gated_writes.py   promote_candidates
        -> daedalus/kernel/promotion.py    authorize_persisted_promotion
          -> daedalus/kernel/promotion_trust_root.py   evaluate_promotion_trust
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "daedalus"

ROOT_MODULE = "daedalus.kernel.promotion_trust_root"
ROOT_MODULE_PATH = PACKAGE / "kernel" / "promotion_trust_root.py"

#: The only module allowed to reach the decision function.
CANONICAL_CALLER = PACKAGE / "kernel" / "promotion.py"

#: Symbols that ARE the trust root's authority. Importing one of these outside
#: the canonical caller creates a second promotion path.
AUTHORITY_SYMBOLS = {
    "evaluate_promotion_trust",
    "verify_promotion_approval",
    "claim_approval",
    "evaluate_second_factor",
}

#: Symbols that are safe to import anywhere: they carry no verdict. The
#: environment scrub in particular is deliberately used by the attempt path.
NON_AUTHORITY_SYMBOLS = {
    "scrubbed_child_env",
    "SECRET_ENV_PREFIXES",
    "second_factor_ledger_path",
    "approval_tag_for",
    "voided_by_regeneration",
    "replay_key",
    "TRUST_ROOT_MODE",
    "TRUTH_TABLE",
    "TRUTH_TABLE_RECORD",
    "PREAUTHORIZATION_STAGE",
    "SEALED_STAGE",
    "PromotionTrustDecision",
    "PromotionTrustRootError",
    "SecondFactorOutcome",
    "ApprovalVerdict",
    "_append_record",
    "ALLOWED_SIGNERS_REL",
    "MAX_APPROVAL_AGE",
    "ARTIFACT_BINDING_FIELDS",
    "REPLAY_KEY_SPEC",
    "REPLAY_STATE_RETENTION",
    "REVOCATION_AUTHORITY",
    "APPROVAL_BODY_SCHEMA",
    "TAG_PREFIX",
}


def _python_modules() -> list[Path]:
    return [
        path
        for path in PACKAGE.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _imported_root_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == ROOT_MODULE or module.endswith("promotion_trust_root"):
                names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == ROOT_MODULE:
                    names.add("<module>")
    return names


def test_exactly_one_module_imports_the_root_authority() -> None:
    offenders: dict[str, set[str]] = {}
    for path in _python_modules():
        if path == ROOT_MODULE_PATH:
            continue
        authority = _imported_root_symbols(path) & AUTHORITY_SYMBOLS
        if not authority:
            continue
        if path == CANONICAL_CALLER:
            continue
        offenders[str(path.relative_to(REPO_ROOT))] = authority
    assert offenders == {}, (
        "a second module reaches the D5 trust root's authority; a trust root "
        f"with two callers is two promotion paths: {offenders}"
    )


def test_the_canonical_caller_actually_calls_it() -> None:
    """The opposite failure: a root nothing calls (the checkpoint's state)."""
    imported = _imported_root_symbols(CANONICAL_CALLER)
    assert "evaluate_promotion_trust" in imported
    source = CANONICAL_CALLER.read_text(encoding="utf-8")
    assert source.count("evaluate_promotion_trust(") == 1


def test_non_authority_helpers_stay_off_the_authority_list() -> None:
    """Guard against the list being widened until it means nothing."""
    assert not (AUTHORITY_SYMBOLS & NON_AUTHORITY_SYMBOLS)


def test_the_live_promotion_seam_reaches_the_canonical_caller() -> None:
    seam = (PACKAGE / "kairos" / "gated_writes.py").read_text(encoding="utf-8")
    assert "authorize_persisted_promotion" in seam
    # both the effect-free preflight and the under-lock evaluation
    assert seam.count("authorize_persisted_promotion(") == 1
    assert seam.count("authorize_promotion(") >= 1
    # the root cannot be reached without a repository to read the tag from
    assert seam.count("repo_root=root") == 2
    assert "promotion_stage=PREAUTHORIZATION_STAGE" in seam
    assert "promotion_stage=SEALED_STAGE" in seam


def test_the_registered_entrypoint_still_names_the_live_seam() -> None:
    registry = (PACKAGE / "spine" / "effect_boundary.py").read_text(encoding="utf-8")
    assert 'id="python.promote_candidates"' in registry
    assert 'target="daedalus.kairos.gated_writes:promote_candidates"' in registry
    assert '"promotion.owner_approval"' in registry


def test_no_module_reimplements_the_signed_tag_check() -> None:
    """One verifier, not a convenience copy in a second place."""
    offenders = []
    for path in _python_modules():
        if path == ROOT_MODULE_PATH:
            continue
        text = path.read_text(encoding="utf-8")
        if "verify-tag" in text or "gpg.ssh.allowedSignersFile" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"a second signed-tag verification exists outside the trust root: {offenders}"
    )
