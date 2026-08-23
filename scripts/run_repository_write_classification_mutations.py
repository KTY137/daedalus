#!/usr/bin/env python3
"""Run bounded source mutations against the classification contract tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_classification.py"
TESTS = (
    "tests/gates/test_repository_write_classification.py",
    "tests/gates/test_repository_write_classification_review.py",
    "tests/gates/test_repository_write_evidence_authentication.py",
    "tests/gates/test_repository_write_non_runtime_conformity_admission.py",
    "tests/gates/test_gate_report_v3_raw_input_composition.py",
)
MUTATIONS = {
    "force-closed": ('"closed": False', '"closed": True'),
    # Revision 2 removed the module-wide flag from the payload; this anchor
    # pins its absence.  Putting it back is a claim one report cannot make
    # about many surfaces.
    "restore-module-wide-authentication-flag": (
        '            "classification_ready": self.classification_ready,\n',
        '            "classification_ready": self.classification_ready,\n'
        '            "evidence_authenticated": True,\n',
    ),
    "forge-primary-checkout-proof": (
        '"primary_checkout_target_proven": False',
        '"primary_checkout_target_proven": True',
    ),
    "drop-effect-lease-evidence": (
        "EvidenceKind.EFFECT_LEASE_RECEIPT,\n",
        "# mutated: effect lease evidence omitted\n",
    ),
    "accept-stale-inventory-digest": (
        'if value["inventory_digest"] != inventory.digest:',
        'if False and value["inventory_digest"] != inventory.digest:',
    ),
    "accept-duplicate-surface": (
        "if row.surface in by_surface:",
        "if False and row.surface in by_surface:",
    ),
    "accept-cross-surface-evidence": (
        "item.surface_sha256 != expected_surface_sha256 for item in self.evidence",
        "False for item in self.evidence",
    ),
    "accept-unbound-guard-contract": (
        "if evidenced_contracts != set(self.guard_contracts):\n"
        "                raise ValueError(\"central guard evidence does not match guard contracts\")",
        "if False and evidenced_contracts != set(self.guard_contracts):\n"
        "                raise ValueError(\"central guard evidence does not match guard contracts\")",
    ),
    "allow-unreachable-nonretired": (
        "not self.production_reachable\n"
        "            and self.guard is not GuardDisposition.RETIRED",
        "False",
    ),
    # --- per-surface evidence authentication ---------------------------
    # Every applicable stage must have replied verified, or the surface is
    # not authenticated.
    "weaken-stage-conjunction": (
        "    return all(\n"
        "        verdicts.get(stage) == STAGE_VERDICT_VERIFIED for stage in applicable\n"
        "    )\n",
        "    return True\n",
    ),
    # ``all(())`` is True; this guard is what stops a surface no stage
    # speaks for from authenticating vacuously.
    "vacuous-empty-applicable-set": (
        "    if not applicable:\n",
        "    if False and not applicable:\n",
    ),
    # Applicability is read off the typed row, never declared.
    "applicability-not-derived-from-the-row": (
        "    if row.guard_contracts:\n"
        "        stages.add(AuthenticationStage.GUARD)\n"
        "    if row.production_reachable:\n"
        "        stages.add(AuthenticationStage.LEASE)\n",
        "    pass\n",
    ),
    # The composition takes the exact report object a verifier returns; a
    # mapping parsed from JSON is not one.
    "accept-untyped-stage-report": (
        "        if type(value) is not stage_report_type(stage):\n",
        "        if False and type(value) is not stage_report_type(stage):\n",
    ),
    "accept-foreign-classification-binding": (
        "        if value.classification_digest != report.digest:\n",
        "        if False and value.classification_digest != report.digest:\n",
    ),
    # All six evidence kinds are authenticable; narrowing the set back to
    # the three receipt kinds silently excuses anchors, guards and
    # retirements.
    "narrow-authenticated-kinds": (
        "AUTHENTICATED_EVIDENCE_KINDS = frozenset(EvidenceKind)\n",
        "AUTHENTICATED_EVIDENCE_KINDS = frozenset(\n"
        "    {\n"
        "        EvidenceKind.EFFECT_LEASE_RECEIPT,\n"
        "        EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,\n"
        "        EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,\n"
        "    }\n"
        ")\n",
    ),
    # not_applicable is a collector-signed replay fact, not a caller field.
    "accept-unsigned-not-applicable": (
        "        verify_non_runtime_conformity_binding(binding, collector_secrets=secrets)\n",
        "        pass\n",
    ),
    # The other direction of the fail-closed rule: runtime work wearing a
    # non-runtime label must be refused, not excused.
    "excuse-a-runtime-writer-declared-non-runtime": (
        "        conformity = reports.get(AuthenticationStage.CONFORMITY)\n"
        "        if conformity is not None and _surface_records(\n"
        "            conformity, binding.surface_sha256\n"
        "        ):\n",
        "        conformity = reports.get(AuthenticationStage.CONFORMITY)\n"
        "        if False and conformity is not None and _surface_records(\n"
        "            conformity, binding.surface_sha256\n"
        "        ):\n",
    ),
    # A signature is not a replay: the lease stage re-derived the fact and
    # its record has the last word over the signed claim.
    "ignore-lease-replay-contradiction": (
        "            if (\n"
        "                record.runtime_bound is not False\n"
        "                or record.runtime_id is not None\n"
        "                or record.execution_id != binding.execution_id\n"
        "            ):\n",
        "            if False:\n",
    ),
    # --- the row contract: what may replace a runtime receipt ------------
    # A signature is not a replay.  Dropping the replay leaves a field that
    # says "non_runtime" and nothing that ever checked it.
    "admit-a-binding-without-a-replay": (
        "        replay_non_runtime_effect_subject(\n"
        "            self.subject,\n"
        "            expected_execution_id=self.binding.execution_id,\n"
        "        )\n",
        "        pass\n",
    ),
    # And a replay is not a signature: an unsigned binding must not admit.
    "admit-an-unverified-binding": (
        "        verify_non_runtime_conformity_binding(\n"
        "            self.binding,\n"
        "            collector_secrets=self.collector_secrets,\n"
        "        )\n",
        "        pass\n",
    ),
    # Exactly one evidence kind may be excused.  Emptying the required set
    # excuses the guard contract, the lease receipt and the disjointness
    # receipt along with it.
    "excuse-more-than-the-runtime-receipt": (
        "                required.discard(EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT)\n",
        "                required = set()\n",
    ),
    "admit-a-row-that-also-carries-a-receipt": (
        "                if EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT in kinds:\n",
        "                if False and EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT in kinds:\n",
    ),
    "admit-an-admission-on-a-noncentral-row": (
        "            if self.guard is not GuardDisposition.CENTRAL:\n",
        "            if False and self.guard is not GuardDisposition.CENTRAL:\n",
    ),
    "admit-an-admission-for-another-surface": (
        "            if self.non_runtime_conformity.surface_sha256 != expected_surface_sha256:\n",
        "            if False and self.non_runtime_conformity.surface_sha256 != expected_surface_sha256:\n",
    ),
    "applicability-ignores-the-row-admission": (
        "        row.non_runtime_conformity is None\n"
        "        and surface_binding_sha256(row.source_revision, row.surface)\n",
        "        surface_binding_sha256(row.source_revision, row.surface)\n",
    ),
    # --- Codex point 1: the six verifiers must actually run --------------
    "skip-the-stage-verifiers": (
        "        _run_stage_verifiers(report, inputs) if inputs is not None else {},\n",
        "        {},\n",
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            if original.count(needle) != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found "
                    f"{original.count(needle)}"
                )
            TARGET.write_text(original.replace(needle, replacement), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            if completed.returncode == 0:
                survivors.append(name)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors:
        print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-write classification mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
