/**
 * HIDDEN CONFORMANCE SUITE — pre-registered, written BEFORE either arm ran.
 * Neither arm sees this file. It tests only rules stated verbatim in SPEC.md.
 *
 * Point it at an arm:  ARM_CORE=/abs/path/to/src/core node --test conformance.test.ts
 *
 * A module that fails to import scores zero for its whole group rather than
 * aborting the run, so a partial implementation still produces a number.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const CORE = process.env.ARM_CORE;
if (!CORE) throw new Error("set ARM_CORE to the arm's src/core directory");

async function load(name: string): Promise<any> {
  const p = path.join(CORE, name);
  return await import(pathToFileURL(p).href);
}

/** Run `body` with the module, or fail this test with the import error. */
function withModule(name: string, body: (m: any) => void | Promise<void>) {
  return async () => {
    let m: any;
    try {
      m = await load(name);
    } catch (e: any) {
      assert.fail(`could not import ${name}: ${e?.message ?? e}`);
    }
    await body(m);
  };
}

// --------------------------------------------------------------------------
// scope.ts
// --------------------------------------------------------------------------
test("scope: parses the four documented path shapes", withModule("scope.ts", (m) => {
  assert.deepEqual(m.parseScope("/")?.kind, "platform");
  const u = m.parseScope("/u/eron");
  assert.equal(u?.kind, "universe");
  assert.equal(u?.universe, "eron");
  const c = m.parseScope("/u/eron/c/hauptrunde");
  assert.equal(c?.kind, "campaign");
  assert.equal(c?.universe, "eron");
  assert.equal(c?.campaign, "hauptrunde");
  const s = m.parseScope("/u/eron/c/hauptrunde/sessions/15");
  assert.equal(s?.kind, "session");
  assert.equal(s?.session, "15");
  assert.equal(s?.campaign, "hauptrunde");
}));

test("scope: format(parse(p)) === p for every valid shape", withModule("scope.ts", (m) => {
  for (const p of ["/", "/u/eron", "/u/eron/c/hauptrunde",
                   "/u/eron/c/hauptrunde/sessions/15"]) {
    const parsed = m.parseScope(p);
    assert.notEqual(parsed, null, `parseScope returned null for ${p}`);
    assert.equal(m.formatScope(parsed), p, `round trip failed for ${p}`);
  }
}));

test("scope: malformed input returns null and never throws", withModule("scope.ts", (m) => {
  for (const bad of ["", "u/eron", "/x/eron", "/u/", "/u/eron/c/",
                     "/u/eron/c/hauptrunde/sessions/", "/c/hauptrunde",
                     "/u/eron/c/hauptrunde/sessions/15/extra"]) {
    let got: unknown;
    assert.doesNotThrow(() => { got = m.parseScope(bad); },
      `threw on ${JSON.stringify(bad)}`);
    assert.equal(got, null, `expected null for ${JSON.stringify(bad)}`);
  }
}));

test("scope: a scope missing a required ancestor is invalid", withModule("scope.ts", (m) => {
  // A campaign without a universe, and a session without a campaign, are not
  // representable as valid paths -- parseScope must reject them.
  assert.equal(m.parseScope("/c/hauptrunde"), null);
  assert.equal(m.parseScope("/sessions/15"), null);
}));

// --------------------------------------------------------------------------
// objectRef.ts
// --------------------------------------------------------------------------
const SCOPE = { kind: "campaign", universe: "eron", campaign: "hauptrunde" };

test("objectRef: canonical form is built from type and id, never the slug",
  withModule("objectRef.ts", (m) => {
    const a = m.formatObjectRef({ type: "character", id: "olav-1", scope: SCOPE,
                                  revision: 3, slug: "olav-der-ehrliche" });
    const b = m.formatObjectRef({ type: "character", id: "olav-1", scope: SCOPE,
                                  revision: 3, slug: "olav-the-renamed" });
    assert.equal(a, b, "a rename changed the canonical form");
    assert.ok(!a.includes("ehrliche"), "the slug leaked into the canonical form");
    assert.ok(a.includes("olav-1"), "the stable id is missing from the canonical form");
}));

test("objectRef: sameObject ignores revision but respects identity",
  withModule("objectRef.ts", (m) => {
    const r3 = { type: "character", id: "olav-1", scope: SCOPE, revision: 3 };
    const r9 = { type: "character", id: "olav-1", scope: SCOPE, revision: 9 };
    assert.equal(m.sameObject(r3, r9), true, "revision changed identity");
    assert.equal(m.sameObject(r3, { ...r3, id: "other" }), false);
    assert.equal(m.sameObject(r3, { ...r3, type: "scene" }), false);
}));

test("objectRef: scope is part of identity", withModule("objectRef.ts", (m) => {
  const here = { type: "character", id: "olav-1", scope: SCOPE, revision: 1 };
  const elsewhere = { type: "character", id: "olav-1", revision: 1,
                      scope: { kind: "campaign", universe: "eron", campaign: "andere" } };
  assert.equal(m.sameObject(here, elsewhere), false,
    "the same id in a different campaign was treated as the same object");
}));

test("objectRef: round trips, defaults revision to 0, rejects junk",
  withModule("objectRef.ts", (m) => {
    const ref = { type: "character", id: "olav-1", scope: SCOPE, revision: 0 };
    const parsed = m.parseObjectRef(m.formatObjectRef(ref), SCOPE);
    assert.notEqual(parsed, null, "round trip produced null");
    assert.equal(parsed.type, "character");
    assert.equal(parsed.id, "olav-1");
    assert.equal(parsed.revision, 0, "revision did not default to 0");
    let got: unknown;
    assert.doesNotThrow(() => { got = m.parseObjectRef("", SCOPE); });
    assert.equal(got, null);
}));

// --------------------------------------------------------------------------
// viewRecipe.ts
// --------------------------------------------------------------------------
const REQUIRED: Array<[string, string, string]> = [
  ["character", "welt", "article-reader"],
  ["character", "vorbereiten", "scene-outline"],
  ["character", "tisch", "actor-sheet"],
  ["character", "schmiede", "collection-table"],
  ["scene", "tisch", "scene-tactical"],
  ["scene", "vorbereiten", "scene-outline"],
  ["scene", "welt", "scene-cinematic"],
  ["article", "welt", "article-reader"],
  ["article", "schmiede", "article-editor"],
  ["place", "welt", "atlas"],
];

test("viewRecipe: every required mapping from the document resolves",
  withModule("viewRecipe.ts", (m) => {
    for (const [type, ws, expected] of REQUIRED) {
      assert.equal(m.resolveRecipe(type, ws), expected,
        `${type} + ${ws} should be ${expected}`);
    }
}));

test("viewRecipe: unknown type or missing recipe returns null",
  withModule("viewRecipe.ts", (m) => {
    assert.equal(m.resolveRecipe("nonexistent-type", "welt"), null);
    assert.equal(m.resolveRecipe("place", "tisch"), null);
}));

test("viewRecipe: roles are not recipes", withModule("viewRecipe.ts", (m) => {
  for (const role of ["player", "gm", "observer", "public"]) {
    assert.equal(m.resolveRecipe("character", role as any), null,
      `a role (${role}) was accepted as a workspace`);
    for (const [type, ws] of REQUIRED) {
      assert.notEqual(m.resolveRecipe(type, ws), role,
        `a role (${role}) was returned as a recipe`);
    }
  }
}));

test("viewRecipe: selection survives exactly when both workspaces have a recipe",
  withModule("viewRecipe.ts", (m) => {
    // character has a recipe in all four
    assert.equal(m.selectionSurvives("character", "welt", "tisch"), true);
    assert.equal(m.selectionSurvives("character", "tisch", "schmiede"), true);
    // place has atlas in welt but nothing at the table
    assert.equal(m.selectionSurvives("place", "welt", "tisch"), false);
    assert.equal(m.selectionSurvives("nonexistent-type", "welt", "tisch"), false);
}));

// --------------------------------------------------------------------------
// visibility.ts  -- the sharpest rules in the brief
// --------------------------------------------------------------------------
const GM_TIER = ["owner", "gm", "co_gm"];
const NON_GM = ["player", "observer", "public"];

test("visibility: GM tier is exactly owner, gm, co_gm", withModule("visibility.ts", (m) => {
  for (const r of GM_TIER) assert.equal(m.isGmTier(r), true, `${r} should be GM tier`);
  for (const r of NON_GM) assert.equal(m.isGmTier(r), false, `${r} must not be GM tier`);
}));

test("visibility: open is visible to members, never to public",
  withModule("visibility.ts", (m) => {
    for (const r of [...GM_TIER, "player", "observer"]) {
      assert.equal(m.resolveAccess(r, "open").kind, "ok", `${r} should see open content`);
    }
    assert.equal(m.resolveAccess("public", "open").kind, "not_found",
      "campaign content was exposed to a public viewer");
}));

test("visibility: gm_only is redacted for members, not_found for public",
  withModule("visibility.ts", (m) => {
    for (const r of GM_TIER) {
      assert.equal(m.resolveAccess(r, "gm_only").kind, "ok");
    }
    for (const r of ["player", "observer"]) {
      assert.equal(m.resolveAccess(r, "gm_only").kind, "redacted",
        `${r} should see gm_only content as a redacted row (it may know it exists)`);
    }
    assert.equal(m.resolveAccess("public", "gm_only").kind, "not_found");
}));

test("visibility: SECRET never leaks its existence -- not_found, never redacted",
  withModule("visibility.ts", (m) => {
    for (const r of GM_TIER) {
      assert.equal(m.resolveAccess(r, "secret").kind, "ok");
    }
    for (const r of NON_GM) {
      const got = m.resolveAccess(r, "secret");
      assert.notEqual(got.kind, "redacted",
        `${r} got 'redacted' for a secret object -- that CONFIRMS it exists`);
      assert.equal(got.kind, "not_found",
        `${r} must receive not_found for a secret object`);
    }
}));

test("visibility: redacted and not_found stay distinguishable states",
  withModule("visibility.ts", (m) => {
    // The whole point of two variants: a player sees gm_only as redacted and
    // secret as not_found. Collapsing them into one 'denied' fails here.
    const a = m.resolveAccess("player", "gm_only").kind;
    const b = m.resolveAccess("player", "secret").kind;
    assert.notEqual(a, b, "gm_only and secret produced the same state for a player");
}));

test("visibility: ok carries the role it was resolved for",
  withModule("visibility.ts", (m) => {
    const got = m.resolveAccess("gm", "secret");
    assert.equal(got.kind, "ok");
    assert.equal(got.role, "gm");
}));

// --------------------------------------------------------------------------
// deepLink.ts
// --------------------------------------------------------------------------
test("deepLink: parses the four documented example URLs", withModule("deepLink.ts", (m) => {
  const a = m.parseDeepLink("/u/eron");
  assert.equal(a?.scope?.universe, "eron");

  const b = m.parseDeepLink("/u/eron/c/hauptrunde/world/objects/olav-der-ehrliche");
  assert.equal(b?.scope?.campaign, "hauptrunde");
  assert.equal(b?.workspace, "welt");
  assert.notEqual(b?.object, undefined, "the object selection was dropped");

  const c = m.parseDeepLink("/u/eron/c/hauptrunde/prepare?focus=scene.silberader");
  assert.equal(c?.workspace, "vorbereiten");
  assert.equal(c?.focus, "scene.silberader");

  const d = m.parseDeepLink(
    "/u/eron/c/hauptrunde/sessions/15/table?scene=silberader&recipe=tactical");
  assert.equal(d?.workspace, "tisch");
  assert.equal(d?.scope?.session, "15");
}));

test("deepLink: workspace segments map to the four workspaces",
  withModule("deepLink.ts", (m) => {
    const cases: Array<[string, string]> = [
      ["world", "welt"], ["prepare", "vorbereiten"], ["table", "tisch"],
    ];
    for (const [seg, ws] of cases) {
      const got = m.parseDeepLink(`/u/eron/c/hauptrunde/${seg}`);
      assert.equal(got?.workspace, ws, `/${seg} should be workspace ${ws}`);
    }
}));

test("deepLink: selection and recipe survive a build -> parse round trip",
  withModule("deepLink.ts", (m) => {
    const link = {
      scope: { kind: "campaign", universe: "eron", campaign: "hauptrunde" },
      workspace: "tisch",
      object: { type: "scene", id: "silberader-1", revision: 2,
                scope: { kind: "campaign", universe: "eron", campaign: "hauptrunde" } },
      recipe: "scene-tactical",
    };
    const round = m.parseDeepLink(m.buildDeepLink(link));
    assert.notEqual(round, null, "round trip produced null");
    assert.equal(round.workspace, "tisch");
    assert.equal(round.recipe, "scene-tactical", "the recipe was not deep-linkable");
    assert.equal(round.object?.id, "silberader-1", "the selection was not deep-linkable");
}));

test("deepLink: values needing encoding survive a round trip",
  withModule("deepLink.ts", (m) => {
    const focus = "scene.silber ader/&?x";
    const link = {
      scope: { kind: "campaign", universe: "eron", campaign: "hauptrunde" },
      workspace: "vorbereiten",
      focus,
    };
    const url = m.buildDeepLink(link);
    const round = m.parseDeepLink(url);
    assert.notEqual(round, null, "round trip produced null");
    assert.equal(round.focus, focus, "the focus value was corrupted by encoding");
}));

test("deepLink: malformed input returns null and never throws",
  withModule("deepLink.ts", (m) => {
    for (const bad of ["", "not-a-path", "/x/eron", "/u/", "u/eron/c/x"]) {
      let got: unknown;
      assert.doesNotThrow(() => { got = m.parseDeepLink(bad); },
        `threw on ${JSON.stringify(bad)}`);
      assert.equal(got, null, `expected null for ${JSON.stringify(bad)}`);
    }
}));
