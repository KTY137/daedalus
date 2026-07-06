# Era 3 — Plan (proposed)

Status after Era 1+2 (2026-07-06): local write pipeline validated end-to-end
(docs/VALIDATION_RUN.md), API-first webapp secured and serving, 212 tests green.
Era 3 is about turning validated plumbing into daily-driver workflows.

## 1. Advisory-apply loop (highest value) — ✅ MOSTLY DONE (ce5cb91, abf29f9)
Drafts from advisory-mode tasks used to die inside the result report. Now:
- ✅ Persist advisory drafts to `runs/drafts/<ts>-<slug>.json` (`daedalus drafts list|show|rm`).
- ✅ `daedalus drafts apply|dismiss` — apply returns a review packet for the Claude
  lane and marks the draft handled; never auto-writes (a5b4b0d: path-traversal-guarded).
- ✅ API: `GET /api/drafts` (+pending_count), `GET/POST /api/drafts/<id>[/apply|dismiss]`.
- ✅ DONE: the webapp **inbox tray** UI (React) — `InboxTray` in `apps/web/src/App.tsx`
  with sidebar pending badge, apply/dismiss, review-packet display (3ee70a5; verified
  present in the built `dist/` bundle 2026-07-06).

## 4. One UI contract — ✅ DONE (a5b4b0d)
`tests/test_ui_contract.py` pins webview↔webapp parity (shared `core.get_dashboard`,
identical keys + Role Wheel taxonomy). VSIX repackage ✅ (`daedalus-vscode-0.3.0.vsix`,
2026-07-06).

## 2. Multi-file waves (build loop, phase C payoff)
- Lift MAX_REWRITE_FILES=3 per task into a wave plan: Ikarus splits a >3-file
  feature into sequential single-file rewrite tasks with a shared brief.
- Wire `daedalus build` sessions to live dispatch (status planned -> running ->
  done; report-back over the file bus).
- Validation: one multi-file feature into sunny_garden (e.g. "add a fertilizing
  module + tests + docs") fully locally, gated.

## 3. Webapp polish (Agent OS)
- Graph: live queue glow (poll /api/dashboard), category colors from taxonomy,
  node click -> inspector editing round-trip (PUT endpoints exist).
- Role Wheel view parity with the VS Code webview.
- VSIX: repackage the wrapper extension; webview loads http://127.0.0.1:8765
  with project context; document the one-command start (`python -m daedalus.web_api`).

## 4. Hardening backlog (rolling)
- ✅ Model tiers decided by user 2026-07-06: `core-dev` + `picasso` -> opus,
  `qa-critic` (Nemesis) -> fable; delegates `argus`/`hermes` stay haiku.
- ✅ Merged `feat/api-webapp-agent-os` -> main (94583a0); merged local branches deleted.
  Leftover UNMERGED branch `worktree-agent-a6f4b9af…` (a357049, docs-only) kept for review.
- NEW (2026-07-06): crew delegation protocol — every Claude crew agent may fan out up to
  two haiku delegates via the Agent tool (`.claude/agents/argus.md` scout /
  `.claude/agents/hermes.md` scribe). Claude-side only; NOT harness/Ollama personas.
- Advisory lane content-egress audit for the future DeepSeek lane (deny_content
  already enforced locally; re-verify before enabling any external key).
- Watcher service: run `daedalus watch` as a background task in VS Code, so
  queued API tasks actually drain.

## Suggested order
1 (drafts) -> 3 (webapp shows them) -> 2 (waves) -> 4 (rolling).
