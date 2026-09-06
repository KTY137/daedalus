# G1-UI-18 — The status line does not promise what already failed

Packet ID: G1-UI-18
Artifact role: primary
Active gate: 1
Classification: ALIGNED (presentation only; no API, policy or evidence
change; the five-state health vocabulary is applied, not altered)
Owner: repository owner (owner loop of 2026-09-06, iteration 3 of four)
Base revision: 585b7ea4 plus the uncommitted tree incl. G1-UI-15/16/17
Dependencies: G1-UI-17
Authority: IKARUS_ARIADNE_MASTER_PLAN.md revision 12.

## Primary acceptance claim

Every item in the status line states what is known: with no project the
line says so instead of printing a dash, and when the state read has
failed the second row says "ungelesen" instead of a breathing "wird
gelesen …" that promises a result that is not coming. The composer's two
role words are set as words, not as tracked uppercase labels.

## Baseline (measured 2026-09-06 02:33, backend answering HTTP 500)

- Row one opened with a bold "—" (no project), followed by the red chip
  "Zustand ungelesen — Anfrage fehlgeschlagen: HTTP 500."
- Row two showed the pending item "Kern und Karte werden gelesen …" with
  the breathing dot, although the same request had already failed. Two
  items on one line contradicted each other.
- Composer rail: "ANTWORTET" and "AUFWAND" in tracked uppercase at the
  smallest step, twice in one 44 px row.

## Scope

Owned paths: `apps/web/src/app/StatusLine.tsx` (two branches),
`apps/web/src/features/conversation/conversation.css` (`.brain-btn-role`,
`.effort-role`), this packet. Not touched: health vocabulary, promotion
chip, aria-labels ("Wer antwortet: …", "Zustand öffnen: …"), the
`status-details-toggle`.

## Changes

- No project: `<span class="status-item muted">Kein Projekt gewählt</span>`
  instead of `<b>—</b>`.
- Failed read: when `healthError` is set and no structure has arrived, the
  second row shows the muted "Kern und Karte ungelesen"; the pending text
  remains for the genuine in-flight case.
- Rail roles: text-transform, tracking and label weight removed; colour and
  size unchanged.

## Acceptance matrix

| Check | Evidence |
| --- | --- |
| Type | `npx tsc --noEmit -p .` exit 0 |
| Bootstrap | `npm run test:app` 527/527 |
| Pinned names | health.spec expects "Zustand ungelesen" (kept); promotion.spec "Promotion unbekannt" (kept); spend-settings.spec "Wer antwortet: Automatisch" (aria-label, kept); ide.spec `.status-details-toggle` (kept) |
| Visual | Composer and footer crops before/after at 1440 px in the artifact "Daedalus GUI Iterationen" |
| Not run | `tools/gui_check.py` browser suite |

## Rollback

Revert the two files.
