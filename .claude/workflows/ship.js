export const meta = {
  name: 'ship',
  description: 'Plan → Momus critique → build lanes → Metron gate → Mnemosyne docs, with the crew sequence enforced by the script instead of by memory',
  whenToUse:
    'Any change consequential enough that silently skipping Momus or Metron would be a mistake. Pass the task description as args.',
  phases: [
    { title: 'Plan', detail: 'decompose into lanes with declared file ownership' },
    { title: 'Critique', detail: 'Momus attacks the plan on paper — can block' },
    { title: 'Build', detail: 'one owner per lane; parallel only when file sets are disjoint' },
    { title: 'Gate', detail: 'Metron runs the full suite and reports RAW output' },
    { title: 'Docs', detail: 'Mnemosyne re-syncs docs and stamps provenance' },
  ],
}

const TASK = typeof args === 'string' ? args : (args && args.task) || ''
if (!TASK.trim()) {
  throw new Error('ship: pass the task description as args, e.g. Workflow({name:"ship", args:"..."})')
}

const OWNERS = [
  'core-dev',
  'safety-dev',
  'test-dev',
  'extension-dev',
  'orchestration-dev',
  'docs-dev',
]

const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    lanes: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          owner: { type: 'string', enum: OWNERS },
          brief: { type: 'string' },
          files: {
            type: 'array',
            items: { type: 'string' },
            description: 'Every repo-relative file this lane will WRITE. Read-only files do not belong here.',
          },
        },
        required: ['name', 'owner', 'brief', 'files'],
        additionalProperties: false,
      },
    },
    risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['lanes', 'risks'],
  additionalProperties: false,
}

const CRITIQUE_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['GO', 'GO-WITH-CHANGES', 'BLOCK'] },
    blocking: {
      type: 'array',
      items: { type: 'string' },
      description: 'Defects that make the plan wrong as written. Empty unless verdict is BLOCK.',
    },
    changes: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'blocking', 'changes'],
  additionalProperties: false,
}

const LANE_SCHEMA = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    filesChanged: { type: 'array', items: { type: 'string' } },
    incomplete: {
      type: 'array',
      items: { type: 'string' },
      description: 'Anything asked for that was NOT delivered, and why. Empty if the lane is fully done.',
    },
  },
  required: ['summary', 'filesChanged', 'incomplete'],
  additionalProperties: false,
}

const GATE_SCHEMA = {
  type: 'object',
  properties: {
    passed: { type: 'boolean' },
    command: { type: 'string' },
    failures: { type: 'array', items: { type: 'string' } },
    rawTail: { type: 'string', description: 'Last ~40 lines of actual output, verbatim.' },
  },
  required: ['passed', 'command', 'failures', 'rawTail'],
  additionalProperties: false,
}

// ---------------------------------------------------------------- Plan

phase('Plan')
const plan = await agent(
  `Decompose this task into build lanes. Do NOT write any code — this is planning only.

TASK:
${TASK}

Read enough of the repo to be concrete. For each lane give: a short name, the owning crew agent (one of: ${OWNERS.join(', ')}), a brief precise enough that the owner needs no further context, and the exact repo-relative files that lane will WRITE.

Rules that matter for what happens next:
- The 'files' list is a write-ownership declaration. If two lanes list the same file, they will be forced to run sequentially, so keep write sets disjoint where you honestly can.
- Prefer few real lanes over many artificial ones. One lane is a fine answer.
- List genuine risks — things that could make this change wrong, not generic caution.`,
  { label: 'plan', phase: 'Plan', schema: PLAN_SCHEMA },
)

if (!plan || !plan.lanes.length) {
  return { stopped: 'planning produced no lanes', task: TASK }
}
log(`${plan.lanes.length} lane(s): ${plan.lanes.map((l) => l.name).join(', ')}`)

// ---------------------------------------------------------------- Critique

phase('Critique')
const critique = await agent(
  `Attack this plan on paper, before any code is written. You are the design critic; your job is to find what is wrong with it now, while changing it is still cheap.

TASK:
${TASK}

PROPOSED PLAN:
${JSON.stringify(plan, null, 2)}

Reserve BLOCK for defects that make the plan wrong as written — a correctness hole, a safety or egress breach, an approach that cannot deliver what was asked, a missing rollback on a destructive step. Style preferences and things you would have done differently are GO-WITH-CHANGES, not BLOCK.`,
  { label: 'momus', phase: 'Critique', agentType: 'momus', schema: CRITIQUE_SCHEMA },
)

if (critique && critique.verdict === 'BLOCK') {
  log(`BLOCKED by critique: ${critique.blocking.length} defect(s)`)
  return { blocked: true, task: TASK, plan, critique }
}

const guidance =
  critique && critique.changes.length
    ? `\n\nThe design critic reviewed this plan and requires these changes — apply them:\n- ${critique.changes.join('\n- ')}`
    : ''

// ---------------------------------------------------------------- Build

phase('Build')

const writeSets = new Set()
let disjoint = true
for (const lane of plan.lanes) {
  for (const file of lane.files) {
    if (writeSets.has(file)) disjoint = false
    writeSets.add(file)
  }
}

const buildLane = (lane) =>
  agent(
    `Implement exactly this lane. Other lanes of the same change are handled by other agents — stay inside your declared files.

LANE: ${lane.name}
BRIEF: ${lane.brief}
FILES YOU OWN (write only these): ${lane.files.join(', ')}

OVERALL TASK for context (do NOT implement the other lanes):
${TASK}${guidance}

Finish the whole lane. If something in it turns out to be blocked or wrong, do every other part in full and report what you left out and why in 'incomplete' — do not silently narrow the scope.`,
    { label: `build:${lane.name}`, phase: 'Build', agentType: lane.owner, schema: LANE_SCHEMA },
  )

let built
if (plan.lanes.length === 1) {
  built = [await buildLane(plan.lanes[0])]
} else if (disjoint) {
  log(`write sets are disjoint — building ${plan.lanes.length} lanes in parallel`)
  built = await parallel(plan.lanes.map((lane) => () => buildLane(lane)))
} else {
  log(`write sets overlap — building ${plan.lanes.length} lanes sequentially to avoid clobbering`)
  built = []
  for (const lane of plan.lanes) built.push(await buildLane(lane))
}

const laneResults = built.filter(Boolean)
const incomplete = laneResults.flatMap((r) => r.incomplete)
if (incomplete.length) log(`${incomplete.length} item(s) reported incomplete`)

// ---------------------------------------------------------------- Gate

phase('Gate')
const gate = await agent(
  `Run the project's full gate suite over the working tree and report what actually happened.

Run the real commands (pytest / unittest, plus any type-check or build step this repo defines). Do not summarize a run you did not perform, and do not repair anything — you are the sentinel, not the fixer.

If the box is under heavy load, say so rather than reporting a timing number you do not trust. Put the genuine tail of the output in rawTail, verbatim.`,
  { label: 'metron', phase: 'Gate', agentType: 'metron', schema: GATE_SCHEMA },
)

if (gate && !gate.passed) {
  log(`GATE FAILED: ${gate.failures.length} failure(s) — stopping before docs`)
  return { gateFailed: true, task: TASK, plan, critique, lanes: laneResults, gate }
}

// ---------------------------------------------------------------- Docs

phase('Docs')
const docs = await agent(
  `The following change just landed and passed its gate. Bring the docs back in sync in this same beat.

TASK:
${TASK}

LANES BUILT:
${JSON.stringify(laneResults, null, 2)}

Update HANDOFF / docs / status so they describe the code as it now is. Stamp every number you touch with its provenance (MEASURED / INHERITED / ASSUMED). Do not invent numbers, and do not restate what git history already records.`,
  { label: 'mnemosyne', phase: 'Docs', agentType: 'mnemosyne', schema: {
    type: 'object',
    properties: {
      updated: { type: 'array', items: { type: 'string' } },
      notes: { type: 'string' },
    },
    required: ['updated', 'notes'],
    additionalProperties: false,
  } },
)

return {
  task: TASK,
  plan,
  critique,
  parallelBuild: disjoint && plan.lanes.length > 1,
  lanes: laneResults,
  incomplete,
  gate,
  docs,
}
