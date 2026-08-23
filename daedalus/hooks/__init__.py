"""daedalus.hooks — the Claude Code hooks of this repository, as one package.

Why one package and one process per event
-----------------------------------------
Until 2026-08-23 four separate scripts ran on every prompt (clock, architecture
delta, crew count, room mirror). Each cost a Python start (75 ms on this box)
and the crew count scanned the whole ``%TEMP%/claude`` tree: 129,434 files,
7.7 s per prompt, measured. They also resolved the repository from their own
``__file__``, so a session working in the unified tree (``agent_env_g0``) was
fed the archived tree's shift, architecture and room. The hooks package fixes
both: one dispatcher (``python -m daedalus.hooks <event>``), and the repository
is always the git toplevel of the ``cwd`` the harness hands over.

What a hook is allowed to say
-----------------------------
Hook output lands in the model's context and competes with the task for
attention. Two properties of the transformer transfer literally to that
channel (design: ``docs/superpowers/specs/2026-08-23-hooks-v2-design.md``,
evidence: ``docs/research/HOOKS_CONTEXT_RESEARCH_2026-08-23.md``):

* softmax competition — every injected token competes with task tokens, so
  the per-turn output is budgeted and MEASURED (``runs/hooks/ledger.jsonl``);
* positional bias — the cached prefix (SessionStart) and the latest turn
  (UserPromptSubmit) are attended; the middle is not. So the orientation card
  goes first and is re-seeded on compaction, the goal line goes last, and
  nothing that rarely changes is repeated: silence means unchanged, and the
  SessionStart legend says so once.

What a hook must never do
-------------------------
Break a turn (every path exits 0), enforce the plan (the owner retired that on
2026-08-22), or block reading. The one deny in this package stops Serena WRITE
tools when Serena's configured project root is not the tree the session works
in — the 2026-08-22 incident, where four edits landed in the archived tree.

Effect boundary
---------------
The package writes state and a ledger, spawns ``git`` and probes Serena's
loopback port. It is therefore a registered entrypoint (``daedalus.hooks`` in
``daedalus/spine/effect_boundary.py``) and ``__main__.main`` starts through
``begin_effect`` before any of those effects. A boundary refusal prints a line
to stderr and exits 0 — the hook protocol.
"""
