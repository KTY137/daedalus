# Ikarus agent surface — design, 2026-09-02

Iron Plan: ALIGNED · Iron Gate: 1 · Packet: `G1-UI-05`

The owner's brief, verbatim: *"verbesser die UI, das soll die beste UI auf
der Welt werden und Ikarus soll wie Hermes und du sein und besser."* This
spec turns that into one bounded build on `apps/web` and one read-only
backend route. It was written under the autonomous mandate of the session
(the owner said *"u can do it"* and is not answering questions mid-task), so
every judgement call below is stated as an assumption rather than asked.

## 1. What "like Hermes and Claude Code, and better" means here

Hermes Agent and Claude Code are agent *harnesses*. What makes them feel
like agents on screen is not the model — it is five things the surface
shows:

| Harness trait | Hermes / Claude Code | Daedalus today | This build |
| --- | --- | --- | --- |
| The agent's hands are visible | tool-call blocks, `todo`, diffs | one dispatch card per turn, no step model | the **Protokoll**: a receipt ledger per answer built from the kernel's own envelope and task frames |
| Sessions | `--resume`, session list, `hermes sessions` | one thread id per project in localStorage, no list | thread list per project, resumable, backed by a read-only spine route |
| Commands | `/model`, `/cost`, `/resume`, skills | none | a `/` command menu in the composer mapped to existing deterministic routes and UI actions |
| Control over cost and depth | effort / model picker, `/cost` | picker exists; `effort` accepted by the API but never sent | effort control wired; cost is **not** invented (the API carries none) |
| Honest state | permission prompts, interrupt | offer + confirm, cancel request | kept, and every state row says *unknown* when it is |

"Better" is the part only Daedalus can do: Claude Code shows what a model
*called*; Ikarus can show what the **kernel receipted** — which runtime was
selected and why, what project context was read and what was withheld, which
policy refused what, whether a dispatch was linked durably, and whether a
handoff was confirmed. None of that is a model claim. That is the signature
of this surface and the one place the design spends its boldness.

## 2. Rulings this build obeys (from the design record)

- German interface; plain, declarative, sentence case, never chirpy.
- Every colour, radius, type size and duration comes from a theme or motion
  token. A literal value in a feature stylesheet is a defect.
- Glass is a material for at most two surfaces. No skeuomorphism.
- No fake affordances; a control reports the state it has, including
  "unknown". No metric strips, no doctrine in chrome, no demo garnish.
- Chat and graph are the joint hero; the map keeps its own page.
- React Bits is never vendored (MIT + Commons Clause). The registry MCP is
  unreachable in this session, so structural components are built on the
  app's own tokens and motion vocabulary.
- The cockpit is a read surface over the canonical kernel. The single
  effectful transition in the conversation stays
  `POST /api/conversations/{id}/turns`; dispatch stays `POST /api/queue`
  behind the existing confirmation/autonomy rule.

## 3. Assumptions (stated, not asked)

1. The conversation page is the deliverable; the map, IDE, Settings and
   Theme Studio are out of scope except where the rail needs a hook.
2. Cost/token figures are not shown because the backend does not record
   them per turn. A number nobody measured is not printed.
3. Tool-call streaming is not shown because no HTTP route emits the runtime
   event projection (`ikarus_runtime_events`); the ledger shows only frames
   and envelope fields that actually arrive.
4. Threads are listed from the canonical spine through a new read-only
   route rather than from a second localStorage registry, because the spine
   is the truth and a cache beside it would be a parallel source.
5. `react-markdown` + `remark-gfm` replace the hand-rolled parser. The
   parser cannot render tables or nested lists, both of which model answers
   contain. Both packages are MIT, render React nodes (never HTML), and the
   component map below disables images so a model answer can never make the
   browser fetch an external URL.
6. Syntax highlighting is deferred: it needs a grammar library, and a
   hand-rolled highlighter is exactly the slop this repo rejects.

## 4. The surface

### 4.1 Layout — Gespräch page at ≥ 1180 px

```
┌ chrome ────────────────────────────────────────────────────────────────────┐
│ [scope ▾] │ Karte  Gespräch  IDE │                  Suchen Neu lesen … Themes │
├ .talk-main ───────────────────────────────────┬ .talk-side ────────────────┤
│ thread bar: Verlauf · 4 Turns · e90e07e2      │ [Verlauf] [Karte]           │
│           antwortet · 12s        Neuer Chat   │ ┌─────────────────────────┐ │
│ (quiet decision line when a draft is pending) │ │ ● Mach den Parser rob…  │ │
│ ┌ transcript, scrolls, fills ───────────────┐ │ │   4 Turns · vor 2 min   │ │
│ │ you   Mach den Parser robuster            │ │ │   status                │ │
│ │ ikarus                                    │ │ │   1 Turn · gestern      │ │
│ │ ┃ Route    Automatisch → Claude Code 0,4s │ │ └─────────────────────────┘ │
│ │ ┃ Kontext  attempt.py +6 · 2 zurückgeh.   │ │ (Karte tab: focus card and  │
│ │ ┃ Antwort  MODELL claude · 12,8 s         │ │  the hot list, unchanged)   │
│ │ ┃ Angebot  in die Schlange · Loslegen     │ │                             │
│ │ ┃ Auftrag  a91f läuft · 40 s · local      │ │                             │
│ │ prose in the voice face …                 │ │                             │
│ └───────────────────────────────────────────┘ │                             │
│ ┌ composer well ────────────────────────────┐ │                             │
│ │ / Nachricht an Ikarus …               [↑] │ │                             │
│ │ Antwortet Automatisch ▾ · Aufwand gering ▾ │ │                             │
│ │ Bühne attempt.py Einfügen · Was würde gel. │ │                             │
│ └───────────────────────────────────────────┘ │                             │
├ status line ───────────────────────────────────┴─────────────────────────────┤
```

The composer is docked at the bottom of `.talk-main`; the transcript is the
only thing that scrolls. The empty page centres the invitation in the
transcript's own space instead of stacking it against the top edge. Below
1180 px the rail collapses; the thread list is reachable from the thread
bar as a sheet.

### 4.2 The Protokoll (signature)

Every Ikarus answer carries a ledger drawn as a hairline spine on its left
with one row per receipt, in the order the kernel produced them. Rows are
derived — never stored — from the turn's SSE frames and final envelope, so a
resumed thread shows the same rows from the stored envelope.

| Row | Source | Datum shown | Tone |
| --- | --- | --- | --- |
| Route | `start.provider_used`, `final.llm` (`provider`, `requested`, `auto_selected`, `reason`, `timeout_s`) | `Automatisch → Claude Code` / `Lokaler Index` | `--ink3`; `--live` while streaming |
| Kontext | `final.context` (`focus_file`, `included`, `withheld_count`, `trimmed`, `ambiguous`) | `attempt.py + 6 Dateien · 2 zurückgehalten` | `--ink3` |
| Prüfung | `final.refusal` (deny receipt: contract, reason) | `budget.process_guard · abgelehnt` | `--bad` |
| Antwort | stamp (existing `GEMESSEN` / `MODELL` / `FEHLGESCHLAGEN`) + measured wait | `MODELL claude · 12,8 s` | `--ok` / `--bad` |
| Angebot | `final.act_offer` or `final.action` | objective, lane, Loslegen / Nicht jetzt | `--live` while open |
| Auftrag | task frames `hello/progress/final`, resumed dispatch | state, id, lane, providers, `Übergabe: bestätigt / nicht bestätigt / unklar`, artifacts (`files_changed`, `tests_run`, `draft_ids`) | `--live` running, `--ok`, `--bad`, `--ink3` unknown |
| Abbruch | cancellation status, halted observation | existing labels | `--bad` / `--ink3` |
| Editor | `contextRefs`, `final.editor_context` | `Editor-Anhang übergeben` | `--ink3` |

Rules: a row that has nothing measured is absent, not grey. Rows arrive as
their frame arrives (Route on `start`, Antwort on `final`, Auftrag on each
task frame). Each row is one line; a row with detail (selection reason,
withheld paths, refusal contract, artifact lists) expands in place with a
disclosure that says what it opens. Row glyphs are drawn SVG, not
characters, in the theme's `--ok/--bad/--live/--ink3`.

### 4.3 Threads

- Rail tab **Verlauf**: this project's conversations from
  `GET /api/conversations?project=&limit=` (new, read-only), newest first:
  first user message as title (clipped by the server), turn count, relative
  time of the last turn, last route. The current thread is marked; pressing
  a row saves it under the existing `daedalus-thread:<project>` key and
  resumes it through the existing `GET /api/conversations/{id}`.
- **Neuer Chat** stays where it is. Rename and delete are not offered: the
  spine is append-only and a local title store would be a second truth.
- The list refreshes when a turn settles, so a first turn in a new thread
  appears in the rail without a reload.

### 4.4 Composer

- `/` at the start of an empty composer opens a command menu (listbox,
  arrow keys, Enter, Esc). Commands and what they *actually* do:

| Command | Effect |
| --- | --- |
| `/status` | sends `status` — the deterministic route (`ikarus_os.classify`) |
| `/distill` | sends `distill` — deterministic |
| `/plan <Frage>` | opens "Was würde gelesen?" for that text; nothing is sent |
| `/karte <Modul>` | resolves the module on the map, focuses it, switches to Karte |
| `/neu` | new thread |
| `/modell` | opens the runtime picker |
| `/aufwand gering\|mittel\|hoch` | sets the effort sent with the next turn |
| `/abbrechen` | requests server cancellation of the running turn |
| `/hilfe` | prints this table as a local note, marked `OBERFLÄCHE`; not sent |

  A command that needs an argument and gets none stays in the box with the
  menu explaining the argument. Unknown `/x` is sent verbatim — Ikarus may
  know it; the surface does not pretend.
- **Aufwand** control (`low`/`medium`/`high` → gering/mittel/hoch) on the
  pre-flight rail beside the runtime picker; sent as `effort`; remembered
  per project under `daedalus-effort:<project>`; default `low`, which is
  what the backend already assumes.
- `↑` in an empty composer recalls the last sent message.
- The `Bühne … Einfügen`, editor attachment and context plan remain.

### 4.5 Transcript

- Exchanges stay two DOM articles (`.turn.you`, `.turn.ikarus`) so every
  existing spec and stylesheet contract holds; the model pairs them.
- Markdown through `react-markdown` + `remark-gfm` with a component map:
  headings clamped to `h3…h5`, GFM tables, task lists rendered read-only,
  links `http(s)` only with `rel="noreferrer"`, `img` rendered as its alt
  text, raw HTML never rendered. Code blocks keep the language label, copy
  button and line count.
- Streaming: caret; empty stream shows `Ikarus denkt · 4 s`; the elapsed
  clock lives on the thread bar as today.
- A `Neue Antwort ↓` button appears when new text arrives while the reader
  is scrolled up. Pinning stays as implemented.

## 5. Backend: one read-only route

`GET /api/conversations?project=<name>&limit=<1..50>` →

```json
{"ok": true, "project": "<name>", "conversations": [
  {"conversation_id": "conv_…", "turn_count": 4,
   "first_message": "…", "last_message": "…", "last_ts": "…",
   "last_intent": "chat", "last_provider_used": "claude_code_cli",
   "last_status": "answered"}
]}
```

Implementation: `SpineLedger.effect_key_groups(kind, limit, payload_match)`
— one SQL `GROUP BY effect_key ORDER BY MAX(id) DESC LIMIT ?` over
`conversation.turn` rows whose canonical payload contains
`"project":"<name>"` (the same escaped-LIKE technique the ledger already
uses). `ConversationStore.list_conversations(project, limit)` hydrates the
newest and oldest turn of each group (two bounded reads per row). No write,
no new table, no new kind. The route is registered beside the existing
conversation GET in `interfaces/http/read.py`. An unknown project returns
an empty list, not an error; a missing `project` is a 400.

## 6. Tokens and motion (two small debts the record asked for twice)

- `motion.css` publishes `--dur-fast`, `--dur`, `--dur-slow`, `--ease` on
  `:root` with the values of `tokens.ts`. The existing parity check in
  `useMotion.ts` guards drift. This is what lets a feature stylesheet write
  a transition without writing a number.
- `apply.ts` publishes `--ring` (focus ring colour) derived from the
  theme's accent and material, so the composer's focus ring stops being a
  20 % mix that vanishes on a pale theme.

## 7. Files

| Owner | Files |
| --- | --- |
| `features/conversation` | `Conversation.tsx` (orchestrator, slimmed), `model.ts` (types, ledger derivation, exchange pairing), `commands.ts` (parser + registry), `Ledger.tsx`, `Composer.tsx`, `ThreadList.tsx`, `MarkdownMessage.tsx` (react-markdown), `conversation.css`, `conversation.spec.ts` |
| `app` | `Cockpit.tsx` (rail tabs, `onGoMap`), `styles/shell.css` (talk grid: docked composer, rail tabs), `run-spec.mjs` (bundle the new spec) |
| `shared/api` | `listConversations`, `ConversationTurn.envelope/created_ts`, `ConversationListRow` |
| `shared/ui` | `motion/motion.css` (four properties), `theme/apply.ts` (`--ring`) |
| `apps/web` | `package.json`, `package-lock.json` (react-markdown, remark-gfm) |
| backend | `kernel/events/ledger.py` (`effect_key_groups`), `conversation.py` (`list_conversations`), `web_api.py` (`_conversation_list_view`), `interfaces/http/read.py` (route), `tests/test_conversation_list.py` |
| tests | `apps/web/tests/threads.spec.ts` (fixture-backed), `apps/web/tests/commands.spec.ts` (live deterministic route) |

## 8. Invariants (must survive)

- No new effectful entrypoint; the effect-registry digest is unchanged.
- `POST …/turns` remains the only creation; observation never re-POSTs;
  closing observation and server cancellation stay separate facts.
- Existing Playwright contracts: `Nachricht an Ikarus`, `Senden`,
  `Beobachtung schließen`, `.turn.you`, `.turn.ikarus`, `.turn-text`,
  `.stamp` with `GEMESSEN|MODELL|FEHLGESCHLAGEN`, `.talk-main`,
  `Übergabe bestätigen`, `daedalus-thread:` and `daedalus-cockpit-view`
  keys, `data-view`, reduced-motion behaviour.
- `run-spec.mjs` architecture audit (directed hierarchy, single root,
  registered shims) and `test:motion` stay green.
- Audit floor across themes and widths: contrast ≥ 4.5:1, targets ≥ 44 px,
  type ≥ 11 px, no horizontal overflow.
- German copy; no literal colour/radius/size/duration in feature CSS.

## 9. Evidence to produce

- `npx tsc --noEmit`, `npm run test:app`, `npm run test:motion`.
- `uv run pytest tests/test_conversation_list.py` plus the conversation,
  web-API and bridge suites that touch the spine.
- `python tools/gui_check.py` (Playwright against the built bundle).
- `node tools/audit.mjs` across three themes and four widths; `node
  tools/shoot.mjs` before/after PNGs with manifest.
- An independent review in fresh context against §8.
