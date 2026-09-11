# G1-GENESIS-01 — Owner-directed Genesis v1

## Frozen packet metadata

- Packet ID: `G1-GENESIS-01`
- Artifact role: primary
- Classification: `ALIGNED`
- Active gate: Gate 1 — Renovation and owner-directed Genesis
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Design authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Revision 11,
  SHA-256 `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Promotion: forbidden; nomination and preview do not confer release authority
- Dependencies: canonical Mission, Attempt, EffectLease, source-tree CAS,
  EvidencePacket, kill-switch, and containment paths already present in Daedalus

## Primary acceptance claim

Genesis v1 turns one explicitly started, fully admitted local-collection request
into an isolated, content-addressed Web/PWA or CLI source candidate, evaluates the
exact captured candidate, retains typed evidence, and makes a loopback preview
available. It never edits the primary checkout and has no publish, merge,
deployment, approval, secret, spend, or network-egress authority.

This is a deliberately finite release claim. It is not a general natural-language
application compiler. The admitted grammar covers a single-user local/offline item
collection with title/details, create/edit/delete, completion/reopen, persistence,
and optional search/filter. Any unconsumed requirement blocks before state,
lease, process, or candidate creation. Desktop and mobile selections produce an
installable PWA only; an explicit native/package/store requirement blocks.

The round-trip evaluator proves build/package/runtime observations, exact approved
template identity where used, structural ProductSpec conformance, containment, and
the retained four-plane reference. Per-candidate browser behavior remains named
separately; it is not inferred from source markers.

## Scope

Included:

- strict request normalization, stable idempotency identity, visible defaults,
  and refusal of unsupported targets, stacks, dependencies, product shapes, or
  unconsumed requested features;
- canonical Genesis contracts and registry exports;
- deterministic local Web/PWA and Python-stdlib CLI materialization;
- explicit empty base-repository identity and checkout-external Attempt workspace;
- candidate capture in the canonical source-tree CAS before evaluation;
- fresh materialization of that exact CAS candidate for each contained command;
- independent kernel-owned conformance observations and a typed RoundTripReport;
- terminal-result replay for the same request key and exact request material;
- loopback-only HTTP start and CAS preview routes plus the Agent OS Genesis UI;
- one shared Genesis/Ariadne execution slot on Windows to close their measured MIC
  sibling-workspace crosstalk;
- native-Linux rootless Podman containment with a pinned local image digest,
  read-only root, no network, one workspace bind, bounded resources, and no host
  fallback.

Excluded:

- arbitrary products, arbitrary prose requirements, React/Rust/Electron or other
  unimplemented required stacks;
- authentication, payments, cloud sync, collaboration, reminders, scheduling,
  tags, attachments, export, maps, AI features, or remote services;
- native Windows/macOS/Linux, Android/iOS packages, signing, stores, deployment,
  or public hosting;
- conversational follow-up revisions and general repair search;
- crash reconciliation of a STARTED Attempt; replay currently covers retained
  terminal results, while an unresolved start is reported honestly as pending;
- automatic merge, promotion, or approval.

`DeploymentPlan` and `DeploymentReceipt` stay canonical and parseable because
they are part of the approved end-to-end Genesis contract chain, but this v1
slice has no production constructor for either. The exact contract-producer
census names both as deliberately producer-less until an owner-approved release
adapter exists; creating placeholder deployment artifacts here would invent
publication authority that this packet explicitly excludes.

## Contracts and behavior

The production path is:

`prompt -> deterministic admission -> ProductSpec/TargetFourfoldSpec -> Mission -> EffectLease -> Attempt -> source CAS -> contained evaluations -> EvidencePacket -> RoundTripReport -> loopback preview`

The HTTP facade enters its existing mutation boundary before Genesis dispatch.
Genesis then crosses the registered `python.genesis_switch` control seam and the
`python.genesis` EffectLease. The switch may be initialized by an explicit owner
start but never force-rearmed past an operator's sticky stop.

Generated source is first captured as the authoritative immutable candidate.
Build, test, runtime, and packaging commands receive fresh materializations of
that same digest, so candidate-owned tests cannot mutate the source later served
or attach an observation to bytes they did not receive. Evidence records the
evaluated candidate digest. A candidate failure remains retained and cannot become
a preview.

The preview resolver accepts one canonical Genesis run id and a safe POSIX-relative
path, resolves only a green retained CAS tree, applies bounded reads and known MIME
types, and is served with `nosniff`, no-store, no-referrer, restrictive CSP, and an
opaque sandboxed iframe. The POST route accepts only bounded JSON from the local
application origin or a non-browser client; foreign browser origins and simple
`text/plain` CSRF requests are refused before `run_genesis`.

Windows MIC is write containment, not confidentiality, network isolation, or a
per-workspace ACL. The shared slot covers Genesis and Ariadne; legacy candidate
lanes are not silently claimed by it. Linux uses a separate rootless OCI boundary
and does not require serialization for filesystem isolation.

## Acceptance matrix

| Claim | Acceptance evidence |
|---|---|
| Unsupported intent has zero effects | adversarial admission tests assert no state root, lease, child, or candidate |
| Stable request replay | exact terminal replay returns the retained report; changed material under the same key conflicts |
| Canonical lifecycle | Mission/Attempt/EffectLease/CAS/Evidence/RoundTrip contract and producer tests |
| Immutable evaluation subject | mutation tests prove a gate cannot alter the retained candidate or poison a later gate |
| Honest feature evidence | unsupported-clause and no-op CRUD mutants turn red; source-only and browser claims remain distinct |
| Primary checkout unchanged | before/after identity checks and checkout-external workspaces |
| Preview boundary | traversal, MIME, CSP, loopback, Origin, media-type, and request-size tests |
| Windows containment | live MIC/Job tests plus shared Genesis/Ariadne lock contention tests |
| Debian/RHEL containment | deterministic OCI policy/inspect mutants; live host receipt still required below |
| No release authority | source/AST checks and result schema expose no merge, approval, promotion, or publish action |
| Exact contract producers | the closed 24-type parser registry is the census subject; all 12 Genesis types are visible and deployment plan/receipt have explicit producer-less reasons |
| User surface | CLI, HTTP, TypeScript contract, UI unit, production build, and browser end-to-end checks |

The surface may ship only with the supported-slice matrix green. A blocked request
is a successful refusal, not degraded generation. A missing platform runner is
`blocked`, never an implicit host fallback.

## Migration and rollback

The implementation extends the existing canonical kernel and HTTP/CLI facades; it
does not add a second event store, artifact identity, graph authority, evaluator
authority, or promotion path. Mutable run workspaces and effect evidence remain
under the checkout-external per-repository control root. Candidate identity remains
the source-tree CAS manifest.

Rollback is additive and non-destructive: remove the Genesis UI/routes/package,
its three registered effect rows, and Linux dispatch, then restore the frozen
registry and HTTP source anchors. Retain this packet, all CAS candidates, failed
observations, containment negatives, and terminal ledger records. Never rewrite
them to resemble a later implementation.

## Evidence, expected failures, and review

Retained negative evidence that shaped this packet:

- before Windows MIC, a candidate could write outside its workspace;
- two simultaneous Low-integrity candidates could write into each other's
  Low-labelled workspaces, requiring serialization for the Genesis/Ariadne lanes;
- the earlier host gate had no Linux containment backend and correctly refused;
- SQLite read-only inspection originally created sidecars until immutable/read-only
  lookup paths were added;
- an archetype keyword once allowed Stripe/login/timer and unrelated piggyback
  products to collapse silently into CRUD;
- candidate-owned tests once mutated `app.js` before final CAS capture;
- a no-op `createItem` once passed marker-only checks;
- a foreign Origin using `text/plain` once triggered the loopback POST;
- live Debian and RHEL Podman receipts are absent on the Windows development host.

Required release measurements are the focused Python contract/service/HTTP/CLI/
containment suites, frontend unit/type/build checks, a real loopback API/browser
CRUD-search-preview story, an Ariadne non-mutating campaign smoke, and a clean
Linux Podman integration receipt on each advertised Linux family. Unit-mocked OCI
policy tests may ship the backend as opt-in, but do not by themselves justify a
claim that Debian or RHEL was exercised live.

No Gate-2–5 scientific result is claimed. This owner-directed Gate-1 product slice
does not close the Renovation obligation or waive later baselines, ablations,
held-out tasks, or public-claim requirements.
