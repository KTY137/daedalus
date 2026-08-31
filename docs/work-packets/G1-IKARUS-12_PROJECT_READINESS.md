# G1-IKARUS-12 — Honest project readiness

Status: builder-verified; companion registration blocker repaired and
independently reviewed in `G1-IDE-11`; held for owner review

## Frozen packet metadata

- Packet ID: `G1-IKARUS-12`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `52b4baa5`
- Master-plan authority/digest: Revision 10 / `5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`
- Primary claim: the cockpit distinguishes a registered project from a checkout
  that exists on this machine, defaults to an existing checkout, and keeps
  browser registration honest without copying or uploading repository data.

Baseline: every existing registry row on this host points to a missing
`C:\Users\nukei\...` directory, and the cockpit chooses the first row without
testing it. The current `C:\Users\Administrator\daedalus` checkout is absent
from the registry. The browser also presented a Tauri-only picker as if it were
available, producing the user-provided failure dialog.

In scope: additive `reachable` projection on `GET /api/projects`, compatible
project selection/rendering in the cockpit, the browser/desktop picker
distinction, current-checkout registration, and focused tests/build.

Acceptance: existing path → `reachable=true`; missing path → `false`; old
servers that omit the field remain compatible; an explicit newly registered
row wins; otherwise the first reachable row wins over stale rows; browser path
entry works without a native-picker button; no project row is deleted or
rewritten.

Forbidden: no repository upload/copy/move/delete, no second registry, no policy
or lane widening, no automatic provider selection, no credential/database
copy, no Master Plan/amendment/evaluator edit.

Rollback removes the additive field/selection preference and the local
`daedalus` registry row. Existing registry files are otherwise byte-untouched.

## Builder verification

- Focused Python registration/API/packaging checks: `74 passed, 10 skipped,
  2 subtests passed`. The skips are the retained Windows symlink-privilege
  limitation (`WinError 1314`) and its macOS-bundle fault variants.
- Deterministic browser selection/picker matrix: `12/12 passed`.
- Full GUI check: `53/54` checks passed with no failure. The remaining check
  was honestly skipped because this host has only one reachable registered
  checkout, so a live two-project switch cannot be measured here.
- Production web build passed. Independent changed-path selections reported
  `539 passed, 1 skipped, 96 subtests passed`.
- The machine-specific `projects/daedalus.json` is local runtime state and is
  excluded from any distributable change.

## Retained negative evidence

- The first full GUI run timed out after selecting a stale registered row.
  That rejected behavior led to reachability-aware selection and a stable
  browser test seam.
- Concurrent registration of one canonical root under different names can
  publish two rows because the identity scan and publication are not one
  transaction. The deterministic red baseline published `alpha.json` and
  `beta.json` with two successful `created=true` results. The baseline is
  retained; its independently reviewed repair is isolated in `G1-IDE-11`.
- The unrelated Forest-v2 external-corpora experiment currently has two stale
  kernel-pin failures and observes only three corpora. It remains separate
  negative evidence and is not folded into this product-readiness packet.
