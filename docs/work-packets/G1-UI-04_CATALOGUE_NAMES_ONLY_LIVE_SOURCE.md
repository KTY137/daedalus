# G1-UI-04 - The GUI catalogue names only source that is there

## Frozen packet metadata

- Packet ID: G1-UI-04
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 1b577a702c7b70bd0866570d1bf96014104096db
- Dependencies: G1-UI-02 integrated at e133e09b85534ff3350fce982ee1aa2ad57ebb9e; G1-UI-03 hierarchy shim register integrated at 81bc5670f67d1482ab9523a9498a9bdd90467194; G1-PKG-01 packaged-resource byte identity present in the base
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Every first-party entry in the shipped GUI catalogue names a source path that
exists in this repository at this revision, and the packaged copy under
`daedalus/resources/` is byte-identical to it.

Twelve entries did not, and had not since `e133e09b`. Each carried a licence, a
licence URL, a provenance origin and a retrieval date for a component whose
source had been deleted, and because `daedalus/resources/catalogue/gui/glass.json`
is a byte-identical packaged copy, the wheel shipped those claims too. Provenance
that names a path which is not there is a claim, not a receipt; this Packet
removes the claims and records what they cost.

## Scope

In scope: `catalogue/gui/glass.json` and its packaged copy, the four tests that
asserted the removed names, `docs/GUI_CATALOGUE.md`, one `ALLOWED` entry in
`tools/docs_reference_check.py`, this Packet, and the regenerated Work Packet
index with its pinned counts.

Out of scope and untouched: every entry in `catalogue/gui/external.json`,
including the three licence traps `ext/react-bits`, `ext/aceternity-ui` and
`ext/21st-dev` pinned as `reference_only` by
`tests/test_gui_catalogue.py::test_the_three_licence_traps_are_reference_only`;
`daedalus/gui_catalogue.py`; any TypeScript, CSS or component under `apps/web`;
navigation and visual behavior; the shim files themselves; the Effect Registry;
the Master Plan and its amendment chain.

### The (a)/(b)/(c) split, measured at 1b577a70

`e133e09b` ("refactor(web): retire Classic app in G1-UI-02") deleted twelve
files under `apps/web/src/components/glass/` (692 deletions). Before assuming
the commit message, each component was checked three ways: its exported symbol
and prop interface at `e133e09b^`; every reference to it by name in the current
tree; and whether an exported, reusable successor with a comparable prop API
exists anywhere under `apps/web/src/shared/ui`, `apps/web/src/features` or
`apps/web/src/app`.

Result: **twelve (a), zero (b), zero (c).** `git grep -c '\b<Name>\b' -- apps/web`
returns 0 for all twelve. No file named after any of them exists anywhere in the
tracked tree — they were deleted, not moved. No exported successor exists:
`apps/web/src/shared/ui/glass/GlassSurface.tsx` is an unrelated SVG-displacement
effect from a different lineage (`44675ff3`) with a disjoint prop API, and it is
not itself catalogued.

| Entry | Symbol and props at `e133e09b^` | Refs now | Successor | Verdict |
| --- | --- | ---: | --- | --- |
| `glass/GlassPanel` | `GlassPanel({ reveal?, revealDistance?, ...div })` | 0 | none; no `.glass` class survives | (a) |
| `glass/GlassCard` | `GlassCard({ hoverable?, reveal?, ...div })` | 0 | none; `cap-card`/`system-card` are unrelated one-off divs | (a) |
| `glass/GlassButton` | `GlassButton({ primary?, ...button })` | 0 | none; shape hand-retyped inline at `features/mission/Decision.tsx:208` and `features/conversation/Conversation.tsx:1787` | (a), role duplicated inline |
| `glass/GlassSheet` | `GlassSheet({ open, title, subtitle?, onClose, children })` | 0 | none; scrim+dialog hand-rolled at `app/Cockpit.tsx:660-679` using the same surviving `scrimVariants`/`surfaceVariants` | (a), role duplicated inline |
| `glass/SegmentedControl` | `SegmentedControl({ options, value?, onChange, className? })` | 0 | none; its CSS survives unreachable at `shared/ui/motion/motion.css:90-108` | (a), dead CSS |
| `glass/Dock` | `Dock({ children, className? })` -> `<nav class="dock glass">` | 0 | none; `ViewSwitch` in `app/Cockpit.tsx:830-902` is a private, non-exported, differently shaped nav | (a) |
| `glass/DockItem` | `DockItem({ icon, label, active?, badge?, onClick?, className? })` | 0 | none; dead CSS at `shared/ui/motion/motion.css:64-88` | (a), dead CSS |
| `glass/LiveRail` | `LiveRail({ children, className? })` -> `<aside class="rail">` | 0 | none; the live-monitoring column has no successor at all | (a) |
| `glass/RailCard` | `RailCard({ title, icon?, badge?, children?, className? })` | 0 | none; role survives only as private `.focuscard` / `HotList` in `app/Cockpit.tsx` | (a) |
| `glass/LiveDot` | `LiveDot({ status?: 'good'\|'warn'\|'bad', className? })` | 0 | none; a superset `.dot` vocabulary in `app/styles/instruments.css:164-186` is hand-written in three files (`StatusLine`, `Decision`, `Settings`); dead CSS at `motion.css:144-179` | (a), role duplicated in 3 files |
| `glass/ChatBubble` | `ChatBubble({ role: 'ik'\|'me', avatar?, children })` | 0 | none; bubbles are inline `motion.article` at `features/conversation/Conversation.tsx:1687-1708`; only `MarkdownMessage` is delegated | (a) |
| `glass/Composer` | `Composer({ value, onChange, onSend, chips?, onChip?, busy?, placeholder?, extra? })` | 0 | none; the form is inline at `features/conversation/Conversation.tsx:1853-1899`; Enter/Shift+Enter at :1870-1875, auto-grow at :820-825, chips at :1679-1683 | (a) |

Nothing was classified (b): a role that survives as hand-written inline JSX
inside a feature component is not a successor a catalogue may point at, because
the entry's `props`, `usage` and `dependencies` would all become false. Nothing
was classified (c) at the level of an individual deletion: G1-UI-02 proved the
closure unreachable from the production esbuild graph before removing it, and
the measurements above confirm no live caller was orphaned.

### The finding that is a (c) at programme level

G1-UI-02's closure audit was scoped to the TypeScript import graph. Its
acceptance matrix has no row for a non-TypeScript consumer, and the GUI
catalogue is one — with a test that pins the binding and a packaged copy that
ships it. The audit's own instrument could not see the artifact it broke.

One packet later, G1-UI-03 knew: it kept `apps/web/src/motion/tokens.ts` and
`apps/web/src/motion/useMotion.ts` alive as re-export shims specifically because
"the GUI catalogue ... address these source paths"
(`apps/web/src/app/hierarchy-shims.json`, group `shared-ui-source-facades`). That
knowledge was applied forward and never applied backward to the twelve entries
G1-UI-02 had already invalidated. The gap is not a rule that was broken; it is a
class of consumer that no packet's closure checklist names.

## Contracts and behavior

### The catalogue

`catalogue/gui/glass.json` drops the twelve component entries and keeps
`motion/tokens` and `motion/useReducedMotionPref`. Entry count falls 29 -> 17;
first-party count falls 14 -> 2. No `retired` flag was introduced: the loader
has no such concept, `_ALLOWED_KEYS` would refuse the key, and adding one to
keep a red test green would make the schema express a permission the catalogue
does not grant. The file's `$comment` states the removal, cites `e133e09b`,
names all twelve, and states the consequence — Daedalus has no first-party GUI
component to offer a build — rather than leaving the reader to infer it.

Both motion entries were repointed from the `apps/web/src/motion/` re-export
shims to their definition sites under `apps/web/src/shared/ui/motion/`. Every
documented value was re-read there on 2026-09-01 before `retrieved` was moved:
`DURATION_MS`, `EASE.glass`, `EASE`'s three keys, `SPRING`'s two, `DISTANCE`,
`SCALE`, `STAGGER`, `staggerFor`, `COMPOSITED_PROPS`, `LAYOUT_TRIGGERING_PROPS`
and `useReducedMotionPref(): boolean` all match the entry text unchanged. This
discharges the catalogue-locator half of the `shared-ui-source-facades` removal
criteria, which name exactly this migration. **The shim files are not deleted**:
the component/test-import half and the downstream package audit belong to
G1-UI-03's own retirement packet.

`catalogue/gui/external.json` is unchanged, byte for byte.

### Packaging

`daedalus/resources/catalogue/gui/glass.json` is overwritten from the canonical
file and verified byte-identical with `cmp`. `external.json` is untouched and
still identical.

### The four tests that named the removed entries

| Test | Was | Is |
| --- | --- | --- |
| `test_gui_catalogue.py::test_every_first_party_entry_points_at_a_file_that_exists` | red | unchanged, green |
| `test_gui_catalogue.py::test_the_glass_set_is_present_and_ours` | `expected <= names` over twelve `glass/*` | renamed `test_the_first_party_set_is_exactly_what_this_repo_still_has`; asserts the EXACT first-party set, plus licence, origin and vendorability over it |
| `test_gui_catalogue.py::test_shipped_catalogue_loads_clean` | `len(entries) >= 25` | `>= 17`, with the packet and reason in a comment |
| `test_gui_catalogue.py::test_shipped_catalogue_answers_a_real_build_question` | top-4 contains `glass/ChatBubble` and `glass/Composer` | same query; asserts ranking is not insertion order, that the winner is now `ext/origin-ui`, that its `use_mode` is `reciprocal` and `vendorable` is False, and that `use_mode: reciprocal` and `MUST NOT` appear in the rendered prompt |
| `test_web_api_catalogue.py::test_q_ranks_entries_and_reports_that_latent_was_not_used` | `hits[0].name.startswith("glass/")` | asserts `hits[0]` is not the first entry in response order and is `ext/magic-ui` |

The superset assertion (`expected <= set(names)`) is what let twelve dead
entries sit unremarked for ten commits, so the replacement is an exact set. No
coverage was dropped: each rewritten test still pins the property it was written
for — licence and vendorability of our own entries, a non-trivial catalogue,
real ranking, and terms travelling with the answer into the prompt.

### Documentation

`docs/GUI_CATALOGUE.md` section 5 is rewritten: 17 entries, the two that remain,
a named record of the twelve that went and where they are recoverable, and the
consequence stated plainly. Section 3's MEASURED search table is re-run; two of
its six queries (`'chat message transcript'`, `'status indicator dot'`) now
return **no hit at all**, and that is printed rather than replaced with a loose
external match. Section 2's schema example still quotes the retired
`glass/GlassSheet` entry — it exercises every field at once — but is now labelled
as history and explicitly not a live locator. Section 6's red counts are
historical evidence and were not rewritten.

`tools/docs_reference_check.py` gains one `ALLOWED` entry for
`("docs/GUI_CATALOGUE.md", "apps/web/src/components/glass/")`, the mechanism that
file documents for a path named *because* it is gone, with the same reasoning as
the existing `docs/STATUS.md` entries. Current-page dead references fall 5 -> 4.

## Acceptance matrix

| Claim/refusal | Evidence | Required result |
| --- | --- | --- |
| Every first-party `source_path` exists | `pytest tests/test_gui_catalogue.py` | 48 passed, 0 failed |
| Canonical and packaged copies match | `cmp` on both `glass.json` and `external.json` | silent, exit 0 |
| Licence traps untouched | `test_the_three_licence_traps_are_reference_only`; `git diff --stat` on `external.json` | passes; zero `external.json` changes |
| Catalogue still loads clean | `load_catalogue` on the shipped directory | 17 entries, 0 rejected, 0 unresolved dependencies |
| No `retired` field invented | `gc._ALLOWED_KEYS`; the file itself | no such key present or accepted |
| Coupled API test still honest | `pytest tests/test_web_api_catalogue.py tests/test_packaged_resources.py tests/test_generated_inventory.py` | 75 passed, matching the pre-change baseline |
| Gate profile does not drop | `tools/run_gate_checks.py g1` | 122 passed, 1 skipped, 28 subtests, matching baseline |
| Work Packet registry consistent | `tools/index_work_packets.py --check`; `pytest tests/contracts/test_work_packet_index.py` | clean; pinned counts re-measured, not guessed |
| Effect boundary unchanged | frozen semantic Registry digest | `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec` |
| No `apps/web` source change | `git diff --stat` | zero paths under `apps/web` |

Builder evidence on 2026-09-01, exit codes read without a pipe:

- baseline `pytest tests/test_gui_catalogue.py -q`: **1 failed, 47 passed**
  (`glass/ChatBubble: apps/web/src/components/glass/ChatBubble.tsx missing`);
  after: **48 passed**;
- baseline `pytest tests/test_web_api_catalogue.py tests/test_packaged_resources.py
  tests/test_generated_inventory.py -q`: **75 passed, 4 subtests passed**;
  after: **75 passed, 4 subtests passed**;
- baseline `tools/run_gate_checks.py g1`: **122 passed, 1 skipped, 28 subtests
  passed**; after: same;
- `cmp catalogue/gui/glass.json daedalus/resources/catalogue/gui/glass.json`:
  silent, exit 0; same for `external.json`;
- `tools/docs_reference_check.py`: **5 -> 4** dead references in current pages.

## Migration and rollback

There is no data, route, JSON-wire, SSE, storage or package migration. The
`/api/catalogue` response shape is unchanged; only its contents shrink, and
`entry_count` is computed from the entries it carries. No consumer reads a
`glass/*` name by literal: the only two that did were tests, and both are
updated here.

Rollback is `git revert` of this commit. It restores twelve entries whose
`source_path` does not resolve and turns
`test_every_first_party_entry_points_at_a_file_that_exists` red again; it does
not restore the components. Restoring the components is a different decision and
a different packet: their sources are at `e133e09b^`, and re-landing them would
have to satisfy G1-UI-03's rule that no TypeScript implementation lives outside
`app`/`features`/`shared`.

## Evidence expected failures and review

`tests/test_docs_reference_check.py` **remains red at HEAD and is not fixed by
this Packet.** Its three failures are driven by four surviving dead references —
`apps/web/src/App.tsx` named by `docs/MISSION_CONTROL.md`,
`docs/architecture-narrative.md` and `vscode-agent-env/DESIGN.md`, plus
`vscode-agent-env/dist/daedalus-vscode.vsix` in `packaging/openvscode/README.md`.
The first three are the same class of defect as this one, from the same commit
`e133e09b`, in a different artifact family; they were not assigned here and were
not touched. This Packet reduced that page's contribution from five findings to
four and no further.

No test was deleted. No assertion was weakened without stating what moved and
why: the one loosened bound is the entry-count floor, from 25 to 17, and it is
still an exact-current-count floor that refuses a further silent shrink.

Deliberately not done, and left as named findings rather than silently swept:

- **Dead CSS.** `apps/web/src/shared/ui/motion/motion.css` still styles
  `.dockbtn[data-motion]` (64-88), `.segmented[data-motion]` (90-108) and
  `.live-dot[data-motion]` (144-179) — selectors no element in the tree renders.
  Inert, not broken. Sweeping it is an `apps/web` change and out of this Packet's
  scope.
- **Duplicated roles.** The status dot is hand-written in three files; the
  scrim+dialog shape is hand-written in `Cockpit.tsx` and differently in
  `ProjectDialog.tsx`. That is a componentisation decision for a UI packet, not
  a catalogue repair.
- **`GlassSurface` is first-party and uncatalogued.**
  `apps/web/src/shared/ui/glass/GlassSurface.tsx` exists, is ours, is Apache-2.0
  and has a documented prop interface, and no catalogue entry names it. That is
  an omission, not a false claim, so it is reported rather than fixed here —
  adding an entry means reading its props at the definition site and is additive
  work with its own acceptance.
- **The shim files stay.** Repointing the catalogue discharges one of the two
  removal criteria for `shared-ui-source-facades`; deleting the shims requires
  the downstream package audit that criterion also names.

Independent review must confirm: that no entry under `external.json` changed;
that the three licence traps still resolve `reference_only` and non-vendorable;
that the packaged copy is byte-identical rather than regenerated with different
formatting; that the rewritten tests pin a real property and are not merely
re-fitted to whatever the code now does; that the entry-count floor change is
stated rather than buried; and that the twelve removals are recoverable from the
commit this document cites.

No automatic merge, promotion, release, or Gate transition is authorized by a
green builder result.
