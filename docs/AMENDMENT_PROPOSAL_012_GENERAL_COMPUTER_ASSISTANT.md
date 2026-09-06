# Amendment proposal 012: Ikarus general computer assistant

Status: ADOPTED by explicit owner approval on 2026-09-05; runtime delivery is
tracked separately by capability Work Packets.
Owner: repository owner. Date: 2026-09-05.
Classification: AMENDMENT. Active gate: 1.
Request: make Ikarus a general computer assistant like Hermes, covering all
computer tasks and real computer vision with OpenCV.
Base HEAD: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`, with substantial pre-existing
uncommitted work. This proposal does not change that work.
Base plan: revision 11, version 2.2.0, SHA-256
`711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`.

## Decision and reason

Add general computer assistance as a production strand of Ikarus through the
existing Daedalus kernel. Software construction remains available. A general
task need not invent a repository, candidate tree or Project Twin. Actual
software changes still obey Renovation/Genesis contracts. Ariadne remains the
separate controlled evolution workload.

The requested breadth covers files, programs, terminal, browser, documents,
research, integrations, persistent goals, scheduled work, skills, product
memory, and visual interaction with desktop applications. Capability breadth
is not a claim that every application can already be automated.

## Exact proposed plan edits

1. Change metadata to Revision `12`, Version `2.3.0`, Date `2026-09-05`, and
   Active delivery gate `Gate 1 — Renovation, owner-directed Genesis and general computer assistance`.
2. In section 2 replace `Daedalus has two product modes:` with
   `Daedalus supports the following product modes:`. After the Genesis bullet,
   insert:

> - **General computer assistance** — Ikarus executes owner-directed file,
>   application, terminal, browser, document, integration and scheduled tasks
>   through canonical Missions and policy-scoped tools, with persistent goals,
>   product memory, reusable skills and computer vision. Repository and Twin
>   inputs are explicitly inapplicable to non-software tasks; software-producing
>   work retains the Renovation or Genesis requirements.

3. Insert the following section immediately before section 8:

### 7.2 General computer assistance

Ikarus may compile a general computer request into a canonical MissionContract
and typed WorkItems without a ProductSpec or Project Twin when neither is
applicable. Missing and inapplicable inputs are distinct. The canonical kernel
remains the authority for policy, attempts, leases, evidence, cancellation,
budgets and recovery. No separate assistant scheduler, effect authority or
event store is introduced.

Execution follows observe, propose, admit, act and verify. Existing runtime
manifests and policy decisions restrict individual tools, file roots, network
destinations, applications, desktop sessions and secret use. Reversible work
inside an owner-authorized task proceeds without repeated confirmation;
authority widening and irreversible external commitments require explicit
owner authorization. A natural-language classifier does not grant authority.
The existing sealed software release and promotion rules remain unchanged.

Desktop control runs through a trusted, policy-scoped adapter. It is not a
candidate-process sandbox and does not give candidates host control. Desktop
input is serialized per interactive session. Every action binds a current
observation, target and expected postcondition. Stale observations, changed
focus, ambiguous targets, unavailable permissions and unknown outcomes cause
re-observation or a visible blocked result, never a blind repeat of an effect.

Computer vision includes local OpenCV image processing, template and feature
matching and change detection, with independently configured OCR and optional
vision-language inference. DOM and operating-system accessibility data may
provide stronger target grounding. Image similarity and model interpretation
are observations, not proof of task success. Coordinates retain monitor,
window, scale, crop and timestamp provenance. Screen capture, camera access
and remote image transmission are separate scoped capabilities. Credentials
and sensitive images must not enter model context or retained artifacts
without applicable policy authorization.

Long-running and scheduled work resumes through the existing canonical
contracts and scheduler, with explicit reconciliation of interrupted effects.
Skills and product memory are versioned, provenance-bearing inputs; they do
not modify policy or evaluators and remain separate from Ariadne adaptive
memory. External tools and connectors use adapters behind the same admission
boundary. Unavailable dependencies and integrations are reported as unavailable.

### End of insertion

4. Rename the Gate 1 heading to
   `Gate 1 — Renovation, owner-directed Genesis and general computer assistance (active)`.
   Append the following paragraph to Gate 1 before Gate 2:

> Gate 1 also permits the general computer assistance strand of section 7.2.
> Each capability activates only after its bounded Work Packet, independent
> review and acceptance matrix pass. Required evidence includes real adapter
> execution, verified postconditions, policy refusal, stale-target handling,
> cancellation, timeout and crash recovery. General-assistant availability
> neither closes the Renovation gate nor establishes a scientific comparison
> against Hermes or another system.

5. Append a revision-12 decision note before section 13 recording adoption of
   this exact scope by owner approval. Append one accepted amendment record
   with actual approval reference, base/result digests and previous-record
   hash, following section 16. Never fabricate an approval or historical hash.

## Concrete implementation sequence after adoption

Each row becomes a separate bounded Work Packet; dependent implementation
starts only after the preceding interface is reviewed and green.

| Slice | Existing seam and deliverable | Acceptance |
| --- | --- | --- |
| 1. Mission/tool loop | Extend Ikarus shell, supervisor, runtime tool projection and effect bridge; expose general tasks through existing desktop conversation | File task completes in authorized scratch root; model tool calls traverse canonical admission; denial performs zero effects |
| 2. Local vision | Optional pinned OpenCV dependency; screen capture adapter; image observations with provenance; OCR adapter | Real screenshot plus fixture matching; DPI/crop/monitor coordinate tests; ambiguous, missing and stale targets refused; no remote image egress by default |
| 3. Desktop action | Windows accessibility and mouse/keyboard adapters, scoped application launch | Open a test editor, enter and save text in scratch root, independently verify file contents; focus change and kill interrupt prevent the next input |
| 4. Browser | Browser adapter through existing runtime transport and admission | Navigate local fixture, fill form, download into allowed root, verify output; denied destination and prompt injection cannot widen scope |
| 5. Durable work | Reuse canonical scheduler, receipts, product memory and skill inputs | Restart/resume without duplicate submission; expired authority blocks; preferences persist independently of research memory |
| 6. Integrations and breadth | Tool adapters for documents, search and user-configured services; capability/settings UI | Actual configured service works end to end; unavailable services and pending external authorization are visible; no invented success |

Windows is the first host acceptance target. Other platforms remain visibly
unavailable until their adapters pass their own matrix. OCR and vision models
are selected and pinned during their packet; OpenCV alone is not a semantic
screen reader. The first live trials use disposable fixtures and scratch paths,
not personal files, logged-in external submissions or camera capture.

## Baseline and sources

Read-only inspection found existing `tool_scope.py`, `effect_bridge.py` and
`supervisor.py` under `daedalus/orchestration/ikarus/`. These already bind tool
requests to policy/runtime evidence and project work onto canonical attempts.
The current supervisor describes caller-declared WorkItems rather than an LLM
planning loop. Search of Python sources and pyproject found no `cv2`, `opencv`,
`screenshot` or `pyautogui` implementation; Playwright mentions alone are not
evidence of a general browser adapter. This is scoped inspection, not proof
that no relevant external component exists.

Reference functionality, not a parity claim:
Measured baseline on 2026-09-05:
`python -m pytest -q tests/test_ikarus_tool_scope.py tests/test_ikarus_effect_bridge.py tests/test_ikarus_supervisor.py`
completed with **29 passed in 72.34 seconds**. This verifies existing seams,
not desktop control, OpenCV or the proposed extension.

- https://hermes-agent.nousresearch.com/docs/user-guide/features/tools/
- https://hermes-agent.nousresearch.com/docs/user-guide/features/browser/
- https://docs.opencv.org/4.x/de/da9/tutorial_template_matching.html

The old ADR-017 rejects adopting Hermes wholesale but explicitly allows design
inspiration. Reusing its whole runtime would require resolving duplicate state
and authority; this proposal uses adapters and existing kernel ownership.

Observed governance drift: the current plan is revision 11 while the last
amendment-chain record is revision 10. Adoption must reconcile revision 11
using its actual owner-approval evidence before appending revision 12; this
proposal neither silently repairs history nor attributes approval that was
not inspected.

## Alternatives, migration, rollback and review

Alternatives: retain software-only Ikarus (does not meet the request); run
Hermes independently (does not extend Ikarus); adopt its complete runtime
(duplicates kernel responsibilities); implement only screenshot prompting
(does not provide grounded computer control).

Migration is additive and capability-gated. Existing software missions and
their frozen policy remain valid. No new global all-tools grant, parallel
memory authority or replacement GUI is needed. Capabilities remain off until
their real host acceptance succeeds. Existing uncommitted work is preserved.

Rollback disables the affected adapter for new work, cancels its active leases
and retains evidence. Interrupted external effects require reconciliation;
rollback does not claim to undo an already submitted action. Constitutional
rollback is a new amendment. Review must challenge kernel bypass, stale visual
targets, coordinate transforms, sensitive screenshots, duplicate effects after
crash, prompt injection and false success reports.

The owner approved this exact plan extension by replying `ja implmenetierer`
on 2026-09-05. Revision 12 records adoption under master-plan section 16. This
document alone grants no runtime capability.

Adoption investigation retained the governance drift above: revision 11's
bytes are preserved in owner-authored recovery checkpoint
`d9655df2412e9a87762c15ed84b6bcc62f2d9c83`, but no independent approval reference
was found in inspected docs/history. Reconciliation therefore records the
missing historical record explicitly, without claiming it is repaired. The
single new revision-12 record binds the actual revision-11 digest and actual
revision-10 predecessor. See
`docs/work-packets/G1-IKARUS-17_GENERAL_ASSISTANT_AMENDMENT.md` and
`docs/evidence/G1-IKARUS-17_AMENDMENT_VALIDATION.json`.
