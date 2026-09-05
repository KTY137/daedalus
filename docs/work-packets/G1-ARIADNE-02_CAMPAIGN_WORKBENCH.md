# G1-ARIADNE-02 — Campaign Workbench

Packet ID: G1-ARIADNE-02

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1 — owner-directed, controlled evolution

Owner: repository owner

Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`

Dependencies: `G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL`,
`G1-IFACE-HTTP-01_HTTP_STRANGLER_FACADE`,
`G1-UI-02_COCKPIT_SINGLE_IMPLEMENTATION`

## Primary acceptance claim

The existing finite Ariadne controlled-repair campaign is usable from the
packaged, same-origin cockpit without giving the browser a new evaluator,
runtime, repository, or promotion authority. The server resolves one
registered project, re-verifies the exact Git HEAD in the canonical campaign,
and returns the existing `CampaignReceipt` unchanged.

## Scope

This packet adds an operator workbench over `G1-ARIADNE-01`; it does not add a
model operator, apply a candidate, merge a branch, approve a result, or promote
anything. The terminal ceiling remains nomination followed by an independent
owner decision.

## Contracts and behavior

`POST /api/ariadne` accepts exactly:

- `project`
- `source_revision`
- `campaign_id`
- `target_path`
- `before`
- `after`

The browser cannot supply `repo_root`, model/provider selection, evaluator,
command, timeout, budget, policy, approval, merge, or promotion inputs. The
registered project row is the only source of the repository root. The route
uses the existing outer `web.mutations` admission and the existing inner
`python.ariadne_campaign` lease; it creates no registry row or alternate
orchestration state.

Browser requests are loopback, exact-same-origin JSON with one positive bounded
`Content-Length`, no transfer encoding, and a strict body ceiling. Authority,
framing, media-type, and size refusal decisions happen before the body is
parsed; malformed JSON is refused after one bounded body read. After an early
refusal, the live HTTP handler may discard one unambiguous fixed-length body up
to the same 64 KiB ceiling solely to prevent Windows from replacing the JSON
response with a TCP reset. Ambiguous or oversized framing remains unread and
forces connection close. Every refusal still precedes the outer mutation
start. Non-browser callers remain subject to the same exact JSON and size
contract.

## User-visible behavior

- The cockpit keeps one campaign id for the same six inputs across navigation,
  an ambiguous transport timeout, and an explicit retry.
- A changed repair subject gets a new id instead of reusing incompatible
  campaign state.
- Baseline, deliberate negative control, and repair are shown separately in
  their frozen order.
- Retained negative outcomes and blockers are visible beside the arm that
  produced them.
- Candidate, selected evidence, and nomination digests and locators are shown
  without shortening.
- The surface states that nomination is not application, merge, approval, or
  promotion and exposes no control for any of those actions.

## Exact implementation surface

Backend:

- `daedalus/interfaces/http/effects.py`
- `daedalus/interfaces/http/web_api.py`
- `daedalus/interfaces/desktop/projection.py`
- `tests/interfaces/test_http_ariadne.py`

Frontend:

- `apps/web/src/features/ariadne/`
- `apps/web/src/shared/api/index.ts`
- `apps/web/src/app/Cockpit.tsx`
- `apps/web/src/app/run-spec.mjs`
- `apps/web/src/app/styles/cockpit.css`
- `apps/web/src/features/settings/Settings.tsx`
- the corresponding app-contract and browser tests

Forbidden:

- a second campaign store, source identity, evaluator, effect row, or project
  resolver;
- browser-controlled execution or evaluation settings;
- candidate writes to the primary checkout;
- automatic retry under a new id after an ambiguous result;
- apply, merge, approval, deployment, publication, or promotion.

## Acceptance matrix

1. Foreign origins, duplicate origins, cross-site fetch metadata, transfer
   encoding, wrong media types, duplicate/missing/invalid lengths, truncated
   bodies, and oversized bodies are rejected before `web.mutations` begins.
2. Missing, extra, incorrectly typed, or explicitly forbidden fields execute
   no Ariadne campaign.
3. Project resolution uses the registered row and an unknown or unavailable
   project fails closed.
4. The canonical campaign independently verifies `source_revision` against the
   repository HEAD and retains its existing equal-budget three-arm evidence.
5. A completed identical campaign id replays the retained receipt without
   executing another trial; changed material under that id conflicts.
6. The HTTP result contains the canonical receipt rather than a UI-authored
   summary or inferred success claim.
7. The packaged desktop projection advertises `ariadne_campaign_live` only
   while this production route is wired.
8. Unit, contract, type, production-build, packaged-resource, and real browser
   checks cover the complete operator story.

## Migration and rollback

Release staging must explicitly include this new packet and every new Ariadne
source/test file, then regenerate `docs/work-packets/index.json` from the final
Git index. Until that happens, `git commit -am` is known to omit this packet and
the new implementation files.

Rollback removes only this HTTP/UI projection and retains all campaign receipts,
CAS candidates, failed trials, and negative evidence. The CLI and canonical
`G1-ARIADNE-01` campaign remain available.

## Evidence, expected failures and review

Retain rejected-request, stale-HEAD, replay, equal-budget campaign, packaged
resource and browser receipts. Any cross-project response, incomplete canonical
receipt, hidden retry, browser-owned evaluator input, or promotion action is a
release-blocking failure.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
