# Rahmen — handoff notes, 2026-08-26

Everything below is either an acknowledgement of another lane's handoff item
that I could land from inside `Cockpit.tsx` / `shell.css` / `overlays.css` /
`responsive.css`, or a note for the record. Nothing here needed a change
outside those four files.

## → Ikarus — `align-content: stretch` landed

`.cockpit-body.talk`'s `align-content: start` is now `stretch` (shell.css,
~line 290). Your `.convo { flex: 1 1 auto }` should now fill the row exactly
instead of leaving the ~131px trailing band you measured at 1440×900. The
magic-number fallback (`min-height: min(70vh, 680px)` on `:root
.cockpit-body.talk .convo` in conversation.css) is yours to delete — I did not
touch conversation.css.

## → Kartograph — `stage-figures` markup landed

`stageHeaderInner` in Cockpit.tsx now renders the focus-node figures as

```tsx
<dl className="stage-figures">
  <div><dt>Importeure</dt><dd>{nh.focusNode.fan_in}</dd></div>
  <div><dt>Zeilen</dt><dd>{nh.focusNode.loc}</dd></div>
  <div><dt>Hitze</dt><dd>{nh.focusNode.score.toFixed(1)}</dd></div>
</dl>
```

as a sibling after `.stage-counts` (which now only carries the `direkt` /
`über zwei Ebenen` sentence — the `.muted` run is gone). `.stage-figures` is
unstyled on my side, exactly as agreed — it's yours in `stage.css`.

## → Instrumente — quiet-decision gap collapsed, CSS only

`.talk-main:has(> .decision.quiet) { gap: var(--u1); }` (shell.css, next to
`.talk-main`) collapses the reserved `--u4` gap under your borderless quiet
line down to one small unit, without moving where `<Decision/>` mounts or
touching `Decision.tsx`. Did not do the bigger move (hero-promoting into
`.talk-side`) — that changes where the component mounts in `talk-main`'s
composition and felt like it wanted your and Ikarus's sign-off, not a
unilateral CSS patch. Say the word if you'd rather have that instead.

Also: the `/api/drafts` project-scoping you flagged (item 5) is fixed —
coordinator wired the backend + `api.ts`, I added `project={project}` to
`<Decision>` in Cockpit.tsx per their ask. Not asking you to do anything here,
just closing the loop since you're the one who found it.

## → Material — `theme/apply.ts` crash, already resolved when I checked

Hit the same `TypeError: csv.split is not a function` in `splitRamp`
independently (~12:26–12:31, console + a fresh `chromium.launch()` context
in `tools/audit.mjs`, which is why my first two audit runs timed out waiting
for `.stage-node` — a fresh context has no prior good theme state to fall
back on the way a long-lived tab does). Gone by the time I re-checked a few
minutes later; Ikarus's handoff already has the fuller writeup with an exact
timestamp. No action needed from me, recording only so the timeout in my own
audit history doesn't look unexplained.

## Floor, at HEAD after all of the above

    node tools/audit.mjs --base http://127.0.0.1:5173 --widths 1440,1280,1024,900 --themes leitstand,nachtfenster,kammer
    → 0 theme/page/width combinations below the floor (24/24 ok)

(Full detail, including the two failing runs from mid-session before the
`.viewswitch` contrast/target fix and the theme-crash timeout, in my report to
the coordinator.)
