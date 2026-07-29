export const meta = {
  name: 'audit',
  description: 'Multi-lens bug hunt that keeps going until two rounds turn up nothing new, then refutes every finding adversarially before reporting it',
  whenToUse:
    'When the question is "what is wrong in here" and you do not know how many answers there are. Pass the scope as args (a path, a subsystem, or a description); defaults to the whole repo.',
  phases: [
    { title: 'Find', detail: 'one finder per lens, run in rounds' },
    { title: 'Verify', detail: 'three skeptics per finding, each told to refute it' },
  ],
}

const SCOPE = (typeof args === 'string' ? args : (args && args.scope) || '') || 'the whole repository'

// Distinct lenses, not redundant passes — a cheap mirror of one lens finds what that
// lens already found. Each of these fails differently, which is the point.
const LENSES = [
  {
    key: 'correctness',
    agentType: 'qa-critic',
    brief:
      'Logic that is wrong, not merely ugly: off-by-one, wrong branch taken, state mutated under a stale assumption, an error path that swallows the error, a promise/exception that escapes. For each, name concrete inputs that produce the wrong output.',
  },
  {
    key: 'safety',
    agentType: 'cerberus',
    brief:
      'The fail-closed fence: anything that can write where it must not, spend where it must not, or leave the machine unannounced. Egress that is not gated, a guard that fails open, a secret or device path that is reachable, a claim to the user that something was withheld when it was not.',
  },
  {
    key: 'structure',
    agentType: 'aristaeus',
    brief:
      'Rot that is actively costing something: dead code still referenced by docs or config, duplicated logic that has already drifted between copies, a module boundary that no longer holds. Only report rot you can tie to a concrete present-day cost.',
  },
  {
    key: 'coverage',
    agentType: 'test-dev',
    brief:
      'Behavior that would break silently: a code path with no test that a plausible edit would break, a test that asserts the mock rather than the behavior, a regression test that no longer reproduces its original bug.',
  },
]

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          file: { type: 'string' },
          line: { type: 'integer' },
          detail: { type: 'string' },
          failureScenario: {
            type: 'string',
            description: 'Concrete inputs or state → the wrong output, crash, or breach that results.',
          },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
        },
        required: ['title', 'file', 'line', 'detail', 'failureScenario', 'severity'],
        additionalProperties: false,
      },
    },
  },
  required: ['findings'],
  additionalProperties: false,
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    reason: { type: 'string' },
  },
  required: ['refuted', 'reason'],
  additionalProperties: false,
}

const key = (f) => `${f.file}:${f.line}:${f.title}`.toLowerCase()

// Dedup against everything ever seen — including findings the skeptics later killed.
// Deduping against the confirmed list instead would resurrect rejected findings every
// round and the loop would never go dry.
const seen = new Set()
const confirmed = []
let dryRounds = 0
let round = 0

while (dryRounds < 2 && round < 6) {
  round += 1
  phase('Find')

  const rounds = await parallel(
    LENSES.map((lens) => () =>
      agent(
        `Hunt for real defects in ${SCOPE}, through one specific lens.

YOUR LENS — ${lens.key}:
${lens.brief}

${round > 1 ? `This is round ${round}. Earlier rounds already reported the findings listed below; do NOT report them again. Go somewhere they did not look.\n\nALREADY REPORTED:\n${[...seen].join('\n')}\n` : ''}
Report only defects you can point at in the code, with a failure scenario concrete enough that someone could reproduce it. A finding you are unsure about is still worth reporting — a later stage will try to refute it — but a finding you invented to fill the list is not. Returning zero findings is a valid and useful answer.`,
        { label: `find:${lens.key}:r${round}`, phase: 'Find', agentType: lens.agentType, schema: FINDINGS_SCHEMA },
      ),
    ),
  )

  const fresh = rounds
    .filter(Boolean)
    .flatMap((r) => r.findings)
    .filter((f) => !seen.has(key(f)))

  if (!fresh.length) {
    dryRounds += 1
    log(`round ${round}: nothing new (${dryRounds}/2 dry)`)
    continue
  }

  dryRounds = 0
  fresh.forEach((f) => seen.add(key(f)))
  log(`round ${round}: ${fresh.length} new finding(s) → verifying`)

  phase('Verify')
  const judged = await parallel(
    fresh.map((finding) => () =>
      parallel(
        ['does the code actually do this', 'is the failure scenario reachable in practice', 'is this already handled elsewhere'].map(
          (angle) => () =>
            agent(
              `Try to REFUTE this claimed defect. Your default answer is refuted=true; only set refuted=false if you checked and the defect genuinely holds.

CLAIM: ${finding.title}
WHERE: ${finding.file}:${finding.line}
DETAIL: ${finding.detail}
CLAIMED FAILURE: ${finding.failureScenario}

YOUR ANGLE: ${angle}

Read the actual code. Refute it if the claim misreads the code, if the failure scenario cannot occur, if a guard elsewhere already prevents it, or if it describes intended behavior.`,
              { label: `refute:${finding.file}`, phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' },
            ),
        ),
      ).then((votes) => {
        const live = votes.filter(Boolean)
        const survives = live.length > 0 && live.filter((v) => !v.refuted).length >= 2
        return { finding, survives, votes: live }
      }),
    ),
  )

  for (const j of judged.filter(Boolean)) {
    if (j.survives) confirmed.push({ ...j.finding, votes: j.votes })
  }
  log(`round ${round}: ${judged.filter((j) => j && j.survives).length} survived refutation`)
}

if (round >= 6 && dryRounds < 2) {
  log('stopped at the 6-round cap while still finding new material — this audit is not exhaustive')
}

const rank = { critical: 0, high: 1, medium: 2, low: 3 }
confirmed.sort((a, b) => rank[a.severity] - rank[b.severity])

return {
  scope: SCOPE,
  rounds: round,
  exhausted: dryRounds >= 2,
  proposed: seen.size,
  confirmed,
}
