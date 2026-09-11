# Ikarus full-checkout integration intake

Classification: ALIGNED. Gate 1 remains active. Owner request: continue the
30-stage delivery plan through working integration, not isolated modules alone.
Frozen base: 7a47de525527e1ecbf7eda84c1909d59702424e3 on the existing canonical
Ikarus line. Main input: 217d5edc2b5e59441051b9cb0df60a5fbca93fe2.

## Primary acceptance claim

Run the delivered regressions and their existing shell/supervisor/runner callers
in a complete installed checkout on Python 3.10 and 3.12. Retain real failures,
not an assertion that prior isolated module results imply integration success.
Separately diagnose the branch/main merge without mutating either remote ref.

Scope: a dedicated read-only GitHub Actions test workflow and this packet.
This workflow uses the checkout/setup-python pins already used by the canonical
runtime workflow. It receives contents:read, persists no credentials, uses no
repository secrets, calls no paid provider, never pushes and never publishes a
product. A Git bundle containing public tracked repository history permits an
exact offline checkout when the local build environment has no GitHub DNS.
No runner environment, Git configuration or untracked runtime data is exported.
The seven-day artifact is a reproducibility input, not a readiness certificate.

Forbidden: policy/constitution/evaluator changes, broadened runtime permissions,
new remote branches, main/archive mutation, forced ref updates, automatic merge,
release and invented provider evidence. The older Ikarus layout is not copied
onto main. Integration and dependent product work stay blocked until the exact
changes and their tests have been examined.

## Measurement status

Pending: the new hosted runs have not executed at authoring time. XML reports,
exact source revisions and non-mutating merge diagnosis are the evidence. A
transport-job success does not imply merge success; the explicit merge exit code
and diagnostics are retained. Failures are not allowed-to-fail test steps.

Rollback: remove this dedicated workflow and packet with a normal revert. No
runtime state or data migration exists. Existing CI remains unchanged.
