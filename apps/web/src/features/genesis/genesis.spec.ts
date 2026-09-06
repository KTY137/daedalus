import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { startGenesis, type GenesisRun } from '@/shared/api';
import { GenesisRunView, GenesisWorkspace } from './Genesis';
import { fetchGenesisSourceArchive, genesisSourceDownload } from './download';
import {
  createGenesisRequestKey,
  genesisArtifactRows,
  genesisBlockers,
  genesisFactRows,
  genesisRequestFor,
  genesisStatusTone,
  isGenesisRun,
  retainsGenesisRetryIdentity,
  safeGenesisPreviewUrl
} from './model';

export interface GenesisSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

const RUN_ID = 'genesis-0123456789abcdef01234567';
const PREVIEW_PATH = `/api/genesis/${RUN_ID}/preview/`;
const PREVIEW_URL = `http://127.0.0.1:4173${PREVIEW_PATH}`;
const ARTIFACT_KINDS = {
  autonomy_policy: 'autonomy policy',
  runtime_manifest: 'runtime manifest',
  build_intent: 'build intent',
  product_spec: 'product spec',
  policy_decision: 'policy decision',
  design_contract: 'design contract',
  target_fourfold: 'target fourfold',
  graph_proposal: 'graph proposal',
  mission: 'mission',
  materialization_plan: 'materialization plan',
  toolchain_manifest: 'toolchain manifest',
  attempt: 'attempt',
  evidence: 'evidence',
  run_record: 'run record',
  actual_fourfold: 'actual fourfold',
  roundtrip: 'roundtrip'
} as const;
const ARTIFACT_KEYS = Object.keys(ARTIFACT_KINDS) as Array<keyof typeof ARTIFACT_KINDS>;

function digest(index: number): string {
  return index.toString(16).padStart(64, '0');
}

const ARTIFACT_DIGESTS = Object.fromEntries(
  ARTIFACT_KEYS.map((key, index) => [key, digest(index + 1)])
) as Record<keyof typeof ARTIFACT_KINDS, string>;
const CANDIDATE_DIGEST = digest(32);

function artifact(kind: string, sha256: string) {
  return { kind, sha256, locator: `artifact-locator:sha256:${sha256}` };
}

function canonicalArtifacts() {
  return Object.fromEntries(
    ARTIFACT_KEYS.map((key) => [key, artifact(ARTIFACT_KINDS[key], ARTIFACT_DIGESTS[key])])
  ) as Record<string, { kind: string; sha256: string; locator: string }>;
}

function preview(url = PREVIEW_URL, overrides: Record<string, unknown> = {}) {
  return {
    kind: 'read-only-cas-preview',
    path: PREVIEW_PATH,
    url,
    ...overrides
  };
}

function fixture(overrides: Partial<GenesisRun> = {}): GenesisRun {
  const evidenceDigest = ARTIFACT_DIGESTS.evidence;
  const roundtripDigest = ARTIFACT_DIGESTS.roundtrip;
  return {
    run_id: RUN_ID,
    request_key: 'genesis:fixture-request',
    status: 'preview-ready',
    target: 'web',
    defaults: {
      accessibility: 'WCAG 2.2 AA',
      authentication: false,
      audience: 'one local user',
      base_repository: null,
      language: 'English UI generated from the supplied objective',
      product_class: 'local-first CRUD',
      stack: 'python-stdlib',
      storage: 'local-only',
      target: 'web',
      telemetry: false
    },
    blockers: [],
    mission: {
      mission_id: 'mission-0123456789abcdef01234567',
      objective: 'Baue einen lokalen Planer.',
      work_items: ['materialize'],
      success_criteria: ['build', 'test', 'runtime'],
      policy_sha256: ARTIFACT_DIGESTS.autonomy_policy
    },
    candidate: {
      kind: 'candidate source tree',
      sha256: CANDIDATE_DIGEST,
      locator: `artifact-locator:sha256:${CANDIDATE_DIGEST}`,
      files: ['index.html', 'styles.css', 'app.js']
    },
    evidence: {
      kind: 'evidence packet',
      sha256: evidenceDigest,
      locator: `artifact-locator:sha256:${evidenceDigest}`,
      status: 'passed',
      candidate_tree_sha256: CANDIDATE_DIGEST,
      checks: ['build', 'test', 'runtime']
    },
    roundtrip: {
      kind: 'round-trip report',
      sha256: roundtripDigest,
      locator: `artifact-locator:sha256:${roundtripDigest}`,
      status: 'passed',
      checks: { build: true, code: true, data: true, knowledge: true, runtime: true, test: true, type: true },
      feature_assurance: { mechanism: 'kernel-owned certified-template conformance' }
    },
    preview: preview(),
    artifacts: canonicalArtifacts(),
    publication: { status: 'not-requested', owner_approval_required: true, automatic_promotion: false },
    ...overrides
  };
}

function cloneRun(run: GenesisRun): GenesisRun {
  return JSON.parse(JSON.stringify(run)) as GenesisRun;
}

export async function runGenesisSpec(): Promise<GenesisSpecResult[]> {
  const results: GenesisSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const body = genesisRequestFor('  Baue einen lokalen Planer.  ', '  web  ', '  python-stdlib  ', ' request-7 ');
  check(
    'Genesis intake trims values and sends only the canonical request fields',
    JSON.stringify(body) === JSON.stringify({
      prompt: 'Baue einen lokalen Planer.', target: 'web', stack: 'python-stdlib', request_key: 'request-7'
    }),
    JSON.stringify(body)
  );
  const optional = genesisRequestFor('Produkt', ' ', '', 'request-8');
  check(
    'blank optional target and stack are omitted rather than invented',
    !('target' in optional) && !('stack' in optional),
    JSON.stringify(optional)
  );
  check(
    'the browser request key has a stable Genesis namespace',
    createGenesisRequestKey(() => 'fixed-uuid') === 'genesis:fixed-uuid'
  );

  const intakeHtml = renderToStaticMarkup(createElement(GenesisWorkspace));
  check(
    'Genesis intake is usable without a selected project',
    intakeHtml.includes('Produktbeschreibung')
      && intakeHtml.includes('<select')
      && intakeHtml.includes('Backend-Default')
      && intakeHtml.includes('Ohne Basis-Repository')
      && intakeHtml.includes('Ein-Personen-Listen')
      && intakeHtml.includes('kanban board')
      && intakeHtml.includes('Backlog, In Progress und Done')
      && intakeHtml.includes('CLI unterstützt Listen')
      && intakeHtml.includes('installierbare PWA')
      && !intakeHtml.includes('kleines Team')
      && !/<textarea[^>]*disabled/i.test(intakeHtml),
    intakeHtml.slice(0, 500)
  );
  const hiddenIntakeHtml = renderToStaticMarkup(createElement(GenesisWorkspace, { hidden: true }));
  check(
    'Genesis can stay mounted without remaining in the active accessibility tree',
    /<main[^>]*\shidden=""[^>]*>/i.test(hiddenIntakeHtml),
    hiddenIntakeHtml.slice(0, 220)
  );

  const run = fixture();
  check(
    'the exact complete Genesis response shape and request key are accepted',
    isGenesisRun(run, 'genesis:fixture-request')
      && isGenesisRun(fixture({ status: 'succeeded', preview: null }), 'genesis:fixture-request')
      && !isGenesisRun(run, 'genesis:foreign-request')
      && !isGenesisRun(fixture({ request_key: ' genesis:fixture-request ' }), 'genesis:fixture-request')
  );
  check(
    'blocked and running responses retain retry identity while terminal results release it',
    retainsGenesisRetryIdentity('blocked')
      && retainsGenesisRetryIdentity('running')
      && !retainsGenesisRetryIdentity('preview-ready')
      && !retainsGenesisRetryIdentity('failed')
  );
  check(
    'a partial response cannot be painted as a Genesis run',
    !isGenesisRun({ run_id: 'g', status: 'ready', preview: null })
  );
  check(
    'a failed Genesis run may retain evidence but can never retain a browser preview',
    isGenesisRun(fixture({ status: 'failed', preview: null }), 'genesis:fixture-request')
      && !isGenesisRun(fixture({ status: 'failed' }), 'genesis:fixture-request')
  );
  check(
    'green Genesis statuses require mission, artifact, candidate, evidence, round-trip and preview bindings',
    !isGenesisRun(fixture({ candidate: null }))
      && !isGenesisRun(fixture({ evidence: null }))
      && !isGenesisRun(fixture({ roundtrip: null }))
      && !isGenesisRun(fixture({ mission: {} }))
      && !isGenesisRun(fixture({ artifacts: {} }))
      && !isGenesisRun(fixture({ preview: null }))
      && !isGenesisRun(fixture({ status: 'succeeded', preview: null, artifacts: {} }))
      && !isGenesisRun(fixture({
        evidence: { ...(run.evidence as Record<string, unknown>), candidate_tree_sha256: '0'.repeat(64) }
      }))
      && genesisStatusTone('preview-ready') === 'ok'
      && genesisStatusTone('succeeded') === 'ok'
      && genesisStatusTone('ready') !== 'ok'
      && genesisStatusTone('deployed') !== 'ok'
  );
  const missingArtifactKeysAccepted = ARTIFACT_KEYS.filter((key) => {
    const mutant = cloneRun(run);
    delete (mutant.artifacts as Record<string, unknown>)[key];
    return isGenesisRun(mutant, 'genesis:fixture-request');
  });
  check(
    'every one of the sixteen canonical green artifact rows is mandatory',
    missingArtifactKeysAccepted.length === 0,
    missingArtifactKeysAccepted.join(', ')
  );
  const malformedArtifactRowsAccepted: string[] = [];
  for (const key of ARTIFACT_KEYS) {
    for (const [mutation, value] of [
      ['kind', `${ARTIFACT_KINDS[key]} altered`],
      ['sha256', 'not-a-sha256'],
      ['locator', `artifact-locator:sha256:${digest(63)}`]
    ] as const) {
      const mutant = cloneRun(run);
      const row = (mutant.artifacts as Record<string, Record<string, unknown>>)[key];
      row[mutation] = value;
      if (isGenesisRun(mutant, 'genesis:fixture-request')) {
        malformedArtifactRowsAccepted.push(`${key}.${mutation}`);
      }
    }
  }
  check(
    'all canonical artifact rows require exact kind, digest and locator identity',
    malformedArtifactRowsAccepted.length === 0,
    malformedArtifactRowsAccepted.join(', ')
  );
  const extraArtifact = cloneRun(run);
  (extraArtifact.artifacts as Record<string, unknown>).unexpected = artifact('unexpected', digest(62));
  check(
    'the green artifact map is exact and refuses additional authority claims',
    !isGenesisRun(extraArtifact, 'genesis:fixture-request')
  );
  const validButCrossBoundMutants: Array<[string, GenesisRun]> = [
    ['candidate/evidence', fixture({
      evidence: { ...(run.evidence as Record<string, unknown>), candidate_tree_sha256: digest(61) }
    })],
    ['evidence/artifacts', (() => {
      const mutant = cloneRun(run);
      (mutant.artifacts as Record<string, unknown>).evidence = artifact('evidence', digest(60));
      return mutant;
    })()],
    ['roundtrip/artifacts', (() => {
      const mutant = cloneRun(run);
      (mutant.artifacts as Record<string, unknown>).roundtrip = artifact('roundtrip', digest(59));
      return mutant;
    })()],
    ['mission/policy', fixture({
      mission: { ...(run.mission as Record<string, unknown>), policy_sha256: digest(58) }
    })]
  ];
  check(
    'candidate, evidence, round-trip and mission policy identities remain cross-bound',
    validButCrossBoundMutants.every(([, mutant]) => !isGenesisRun(mutant, 'genesis:fixture-request')),
    validButCrossBoundMutants
      .filter(([, mutant]) => isGenesisRun(mutant, 'genesis:fixture-request'))
      .map(([name]) => name)
      .join(', ')
  );
  const exactShapeMutants: Array<[string, GenesisRun]> = [
    ['candidate-extra', fixture({ candidate: { ...(run.candidate as Record<string, unknown>), extra: true } })],
    ['evidence-extra', fixture({ evidence: { ...(run.evidence as Record<string, unknown>), extra: true } })],
    ['roundtrip-extra', fixture({ roundtrip: { ...(run.roundtrip as Record<string, unknown>), extra: true } })],
    ['mission-extra', fixture({ mission: { ...(run.mission as Record<string, unknown>), extra: true } })],
    ['publication-extra', fixture({
      publication: { ...(run.publication as Record<string, unknown>), requested_by: 'candidate' }
    })],
    ['preview-extra', fixture({ preview: preview(PREVIEW_URL, { token: 'unbound' }) })],
    ['candidate-missing-files', (() => {
      const mutant = cloneRun(run);
      delete (mutant.candidate as Record<string, unknown>).files;
      return mutant;
    })()],
    ['evidence-missing-checks', (() => {
      const mutant = cloneRun(run);
      delete (mutant.evidence as Record<string, unknown>).checks;
      return mutant;
    })()],
    ['roundtrip-missing-assurance', (() => {
      const mutant = cloneRun(run);
      delete (mutant.roundtrip as Record<string, unknown>).feature_assurance;
      return mutant;
    })()],
    ['mission-missing-work-items', (() => {
      const mutant = cloneRun(run);
      delete (mutant.mission as Record<string, unknown>).work_items;
      return mutant;
    })()],
    ['publication-missing-approval', (() => {
      const mutant = cloneRun(run);
      delete (mutant.publication as Record<string, unknown>).owner_approval_required;
      return mutant;
    })()]
  ];
  check(
    'green candidate, evidence, round-trip, mission, preview and publication shapes are exact',
    exactShapeMutants.every(([, mutant]) => !isGenesisRun(mutant, 'genesis:fixture-request')),
    exactShapeMutants
      .filter(([, mutant]) => isGenesisRun(mutant, 'genesis:fixture-request'))
      .map(([name]) => name)
      .join(', ')
  );

  const defaults = genesisFactRows(run.defaults);
  check(
    'backend defaults stay visible as labelled facts',
    defaults.some((row) => row.label === 'Anmeldung' && row.value === 'false')
      && defaults.some((row) => row.label === 'Telemetrie' && row.value === 'false')
      && defaults.some((row) => row.label === 'Basis-Repository' && row.value === 'kein Repository'),
    JSON.stringify(defaults)
  );
  const serviceBlocker = "Unsupported required stack 'react' for target 'web'; this Genesis slice supports html-css-js, python-stdlib, vanilla, vanilla-js.";
  const blockers = genesisBlockers([serviceBlocker]);
  check(
    'service blocker strings remain visible without transformation',
    blockers[0] === serviceBlocker,
    JSON.stringify(blockers)
  );
  check(
    'structured compatibility blockers keep their code and explanation',
    genesisBlockers([{ code: 'secret_required', message: 'API-Schlüssel fehlt' }])[0]
      === 'secret_required: API-Schlüssel fehlt'
  );

  const artifacts = genesisArtifactRows(run);
  check(
    'candidate, evidence, round-trip and aggregate artifacts expose content digests without service duplicates',
    artifacts.length === 17 && artifacts.every((artifact) => Boolean(artifact.digest)),
    JSON.stringify(artifacts)
  );
  check(
    'artifact references remain distinct from their digest identity',
    artifacts.some((artifact) => artifact.reference === `artifact-locator:sha256:${CANDIDATE_DIGEST}`
      && artifact.digest === CANDIDATE_DIGEST)
  );
  const compileFailureArtifacts = genesisArtifactRows(fixture({
    status: 'failed',
    blockers: ['Compilation failed.'],
    roundtrip: { status: 'failed', error: 'Compilation failed.' },
    preview: null,
    artifacts: {}
  }));
  check(
    'an identityless failed round-trip stays a blocker rather than becoming a fake artifact',
    compileFailureArtifacts.length === 2
      && !compileFailureArtifacts.some((artifact) => artifact.label === 'Round-trip-Bericht'),
    JSON.stringify(compileFailureArtifacts)
  );

  const safePreview = safeGenesisPreviewUrl(run.preview, run.run_id);
  check(
    'the complete service preview contract accepts its exact numeric IPv4 loopback route',
    safePreview === PREVIEW_PATH,
    safePreview || 'refused'
  );
  check(
    'the service adapter numeric IPv6 loopback is accepted too',
    safeGenesisPreviewUrl(preview(`http://[::1]:4173${PREVIEW_PATH}`), RUN_ID)
      === PREVIEW_PATH
  );
  check(
    'a sibling loopback port can never become iframe navigation',
    safeGenesisPreviewUrl(preview(`http://127.0.0.1:9999${PREVIEW_PATH}`), RUN_ID) === PREVIEW_PATH
  );
  check(
    'the complete numeric IPv4 loopback block is accepted',
    safeGenesisPreviewUrl(preview(`http://127.0.0.2:4173${PREVIEW_PATH}`), RUN_ID) === PREVIEW_PATH
  );
  for (const [name, url] of [
    ['localhost alias', `http://localhost:4173${PREVIEW_PATH}`],
    ['numeric-looking DNS name', `http://127.attacker.invalid:4173${PREVIEW_PATH}`],
    ['public host', `http://192.0.2.10:4173${PREVIEW_PATH}`],
    ['non-http scheme', `https://127.0.0.1:4173${PREVIEW_PATH}`],
    ['credential-bearing URL', `http://user:pass@127.0.0.1:4173${PREVIEW_PATH}`],
    ['implicit port', `http://127.0.0.1${PREVIEW_PATH}`],
    ['wrong endpoint', `http://127.0.0.1:4173/api/genesis/${RUN_ID}/report/`],
    ['wrong run', 'http://127.0.0.1:4173/api/genesis/genesis-aaaaaaaaaaaaaaaaaaaaaaaa/preview/'],
    ['query-bearing URL', `${PREVIEW_URL}?mode=unsafe`],
    ['fragment-bearing URL', `${PREVIEW_URL}#unsafe`]
  ]) {
    check(`${name} cannot become a Genesis preview`, safeGenesisPreviewUrl(preview(url), RUN_ID) === undefined, url);
  }
  check(
    'URL-only preview data cannot bypass the service kind and path binding',
    safeGenesisPreviewUrl({ url: PREVIEW_URL }, RUN_ID) === undefined
  );
  check(
    'mismatched service preview metadata is refused',
    safeGenesisPreviewUrl(preview(PREVIEW_URL, { path: `/api/genesis/${RUN_ID}/other/` }), RUN_ID) === undefined
      && safeGenesisPreviewUrl(preview(PREVIEW_URL, { kind: 'mutable-preview' }), RUN_ID) === undefined
  );

  const html = renderToStaticMarkup(createElement(GenesisRunView, { run }));
  const cliRun = fixture({ status: 'succeeded', preview: null, target: 'cli' });
  const cliHtml = renderToStaticMarkup(createElement(GenesisRunView, { run: cliRun }));
  check(
    'verified web and CLI candidates offer source download with unpack and project instructions',
    [html, cliHtml].every((markup) => markup.includes('Quellcode herunterladen')
      && markup.includes('source/README.md')
      && markup.includes('source-tree.json')
      && markup.includes('genesis-run.json')
      && markup.includes('Projekt hinzufügen'))
  );
  check(
    'download URLs bind the exact validated run and lowercase candidate identity on the same origin',
    genesisSourceDownload(run)?.url === `/api/genesis/${RUN_ID}/source.zip?candidate_sha256=${CANDIDATE_DIGEST}`
      && genesisSourceDownload(cliRun)?.candidateSha256 === CANDIDATE_DIGEST
      && genesisSourceDownload(fixture({ run_id: '../foreign' })) === undefined
      && genesisSourceDownload(fixture({ evidence: null })) === undefined
      && genesisSourceDownload(fixture({ status: 'failed', preview: null })) === undefined
      && genesisSourceDownload(fixture({ status: 'running', candidate: null, evidence: null, roundtrip: null, preview: null })) === undefined
  );
  check(
    'failed and incomplete runs never offer a source download when rendered directly',
    [fixture({ status: 'failed', preview: null }), fixture({ evidence: null }), fixture({ status: 'running' })]
      .every((invalid) => !renderToStaticMarkup(createElement(GenesisRunView, { run: invalid })).includes('Quellcode herunterladen'))
  );
  check(
    'the result renders status, defaults, blockers and full artifact digests',
    html.includes(RUN_ID)
      && html.includes('authentication') === false
      && html.includes('Anmeldung')
      && html.includes('Keine Blocker gemeldet')
      && html.includes(CANDIDATE_DIGEST),
    html.slice(0, 400)
  );
  check(
    'the verified preview permits handled forms but keeps an opaque script sandbox and denied device permissions',
    html.includes(`<iframe src="${PREVIEW_PATH}"`)
      && html.includes('sandbox="allow-scripts allow-forms"')
      && !html.includes('allow-same-origin')
      && html.includes("camera &#x27;none&#x27;; microphone &#x27;none&#x27;")
      && html.includes('referrerPolicy="no-referrer"'),
    html.match(/<iframe[^>]+>/)?.[0] || 'no iframe'
  );
  check(
    'only the compact status is live and the storage boundary is explained',
    !/<section class="genesis-result"[^>]*aria-live/i.test(html)
      && /class="genesis-status"[^>]*role="status"[^>]*aria-live="polite"/i.test(html)
      && html.includes('Browser-Speicher und Service')
      && html.includes('nur bis zum Neuladen sichtbar'),
    html.slice(0, 500)
  );
  check(
    'the Genesis result has no merge or publish action',
    !/<(?:button|a)[^>]*>[^<]*(?:merge|publish|übernehmen|veröffentlichen)/i.test(html)
  );

  const refusedHtml = renderToStaticMarkup(createElement(GenesisRunView, {
    run: fixture({ preview: preview('https://example.com/candidate') })
  }));
  check(
    'an unsafe backend preview is explained and never rendered or linked',
    !refusedHtml.includes('<iframe')
      && !refusedHtml.includes('href=')
      && refusedHtml.includes('Preview-URL wurde abgelehnt'),
    refusedHtml.slice(-400)
  );
  const pathOnlyHtml = renderToStaticMarkup(createElement(GenesisRunView, {
    run: fixture({ preview: { kind: 'read-only-cas-preview', path: PREVIEW_PATH } })
  }));
  check(
    'the service path alone is never guessed into a browser navigation',
    !pathOnlyHtml.includes('<iframe') && !pathOnlyHtml.includes('href=')
  );
  const failedPreviewHtml = renderToStaticMarkup(createElement(GenesisRunView, {
    run: fixture({ status: 'failed' })
  }));
  check(
    'the view cannot render preview data for a failed status even when called without the response guard',
    !failedPreviewHtml.includes('<iframe')
      && !failedPreviewHtml.includes('href=')
      && failedPreviewHtml.includes('Noch keine sichere Preview-URL gemeldet')
  );

  const globals = globalThis as unknown as Record<string, unknown>;
  const originalWindow = globals.window;
  const originalFetch = globals.fetch;
  let requestedUrl = '';
  let requestedInit: RequestInit | undefined;
  try {
    globals.window = globalThis;
    globals.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestedUrl = String(input);
      requestedInit = init;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, genesis: run })
      } as Response;
    }) as typeof fetch;
    const response = await startGenesis(body);
    const sent = JSON.parse(String(requestedInit?.body || '{}'));
    check(
      'shared API posts the exact Genesis body to /api/genesis',
      requestedUrl === '/api/genesis'
        && requestedInit?.method === 'POST'
        && JSON.stringify(sent) === JSON.stringify(body)
        && response.genesis.run_id === run.run_id,
      `${requestedUrl} ${requestedInit?.method || ''} ${JSON.stringify(sent)}`
    );

    const archiveBytes = new Blob(['controlled ZIP bytes'], { type: 'application/zip' });
    const archiveHeaders = {
      'Content-Type': 'application/zip',
      'Content-Disposition': 'attachment; filename="server-name.zip"',
      'X-Daedalus-Candidate-Sha256': CANDIDATE_DIGEST
    };
    globals.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestedUrl = String(input);
      requestedInit = init;
      return new Response(archiveBytes, { status: 200, headers: archiveHeaders });
    }) as typeof fetch;
    const controller = new AbortController();
    const archive = await fetchGenesisSourceArchive(run, controller.signal);
    check(
      'source fetch disallows cross-origin navigation, redirects and caching and preserves cancellation',
      requestedUrl === `/api/genesis/${RUN_ID}/source.zip?candidate_sha256=${CANDIDATE_DIGEST}`
        && requestedInit?.method === 'GET'
        && requestedInit?.mode === 'same-origin'
        && requestedInit?.credentials === 'same-origin'
        && requestedInit?.redirect === 'error'
        && requestedInit?.cache === 'no-store'
        && requestedInit?.signal === controller.signal
        && await archive.blob.text() === 'controlled ZIP bytes'
        && archive.filename === `${RUN_ID}-${CANDIDATE_DIGEST.slice(0, 12)}-source.zip`
    );
    for (const [name, status, headers, content] of [
      ['HTTP refusal', 409, archiveHeaders, archiveBytes],
      ['foreign candidate', 200, { ...archiveHeaders, 'X-Daedalus-Candidate-Sha256': digest(33) }, archiveBytes],
      ['missing candidate', 200, { ...archiveHeaders, 'X-Daedalus-Candidate-Sha256': '' }, archiveBytes],
      ['HTML response', 200, { ...archiveHeaders, 'Content-Type': 'text/html' }, archiveBytes],
      ['inline response', 200, { ...archiveHeaders, 'Content-Disposition': 'inline' }, archiveBytes],
      ['empty archive', 200, archiveHeaders, new Blob([])]
    ] as const) {
      let bodyRead = false;
      globals.fetch = (async () => {
        const response = new Response(content, { status, headers });
        response.blob = async () => { bodyRead = true; return content; };
        return response;
      }) as typeof fetch;
      let refused = false;
      try {
        await fetchGenesisSourceArchive(run);
      } catch (error) {
        refused = error instanceof Error && error.message.length > 0;
      }
      check(
        `source download refuses ${name} with a visible error before saving`,
        refused && (name === 'empty archive' || !bodyRead)
      );
    }
    let invalidFetchCalls = 0;
    globals.fetch = (async () => { invalidFetchCalls += 1; throw new Error('Unexpected fetch'); }) as typeof fetch;
    try { await fetchGenesisSourceArchive(fixture({ evidence: null })); } catch { /* Expected refusal. */ }
    check('an incomplete source identity refuses before any download request', invalidFetchCalls === 0);
  } finally {
    if (originalWindow === undefined) delete globals.window;
    else globals.window = originalWindow;
    if (originalFetch === undefined) delete globals.fetch;
    else globals.fetch = originalFetch;
  }

  return results;
}
