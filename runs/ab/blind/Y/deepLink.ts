// DeepLink — §6.5. Builds/parses the URL shapes:
//   /u/eron
//   /u/eron/c/hauptrunde/world/objects/olav-der-ehrliche
//   /u/eron/c/hauptrunde/prepare?focus=scene.silberader
//   /u/eron/c/hauptrunde/sessions/15/table?scene=silberader&recipe=tactical
//
// Judgment call: the source doc's illustrative URLs use a bare readable slug
// for the world/objects/<slug> case and a workspace-specific query key
// ("scene=") for the table case. Neither survives a generic round trip on
// its own: a slug alone loses `type`/`revision`, and "scene" is a name this
// module cannot derive for an arbitrary object type. So both the world path
// form and the table query form are unified into one representation — the
// object is always appended as an /objects/<ref> path segment, where <ref>
// is objectRef's own type:id@revision text form, percent-encoded as one
// segment. This keeps the four scope/workspace shapes from the doc, keeps
// build+parse as true inverses, and still round-trips full ObjectRef
// identity (§6.5 requires selection to be deep-linkable, not merely a slug).

import type { Scope } from "./scope";
import { formatScope, SLUG_PATTERN } from "./scope";
import type { ObjectRef } from "./objectRef";
import { formatObjectRef, parseObjectRef } from "./objectRef";
import type { RecipeId, Workspace } from "./viewRecipe";
import { RECIPE_IDS } from "./viewRecipe";

export interface DeepLink {
  scope: Scope;
  workspace?: Workspace;
  object?: ObjectRef;
  recipe?: RecipeId;
  focus?: string;
}

const WORKSPACE_TO_SEGMENT: Record<Workspace, string> = {
  welt: "world",
  vorbereiten: "prepare",
  tisch: "table",
  schmiede: "forge",
};

const SEGMENT_TO_WORKSPACE: Record<string, Workspace> = {
  world: "welt",
  prepare: "vorbereiten",
  table: "tisch",
  forge: "schmiede",
};

const SESSION_PATTERN = /^[0-9]+$/;
const RECIPE_ID_SET = new Set<string>(RECIPE_IDS);

export function buildDeepLink(link: DeepLink): string {
  const scopePath = formatScope(link.scope);
  let path = scopePath === "/" ? "" : scopePath;

  if (link.workspace) {
    path += `/${WORKSPACE_TO_SEGMENT[link.workspace]}`;
  }

  if (link.object) {
    path += `/objects/${encodeURIComponent(formatObjectRef(link.object))}`;
  }

  if (path === "") path = "/";

  const params = new URLSearchParams();
  if (link.recipe) params.set("recipe", link.recipe);
  if (link.focus !== undefined) params.set("focus", link.focus);

  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

// Consumes a leading "u/<universe>[/c/<campaign>[/sessions/<n>]]" prefix from
// already-decoded path segments and returns the resulting Scope plus how
// many segments it consumed. Mirrors scope.ts's grammar but as a prefix
// parse, since a DeepLink path continues past the scope with workspace/
// object segments that a whole-string parseScope(path) would reject.
function consumeScope(
  segments: string[],
): { scope: Scope; consumed: number } | null {
  if (segments[0] !== "u") return null;
  const universe = segments[1];
  if (!universe || !SLUG_PATTERN.test(universe)) return null;

  if (segments[2] !== "c") {
    return { scope: { kind: "universe", universe }, consumed: 2 };
  }
  const campaign = segments[3];
  if (!campaign || !SLUG_PATTERN.test(campaign)) return null;

  if (segments[4] !== "sessions") {
    return { scope: { kind: "campaign", universe, campaign }, consumed: 4 };
  }
  const session = segments[5];
  if (!session || !SESSION_PATTERN.test(session)) return null;

  return {
    scope: { kind: "session", universe, campaign, session },
    consumed: 6,
  };
}

export function parseDeepLink(url: string): DeepLink | null {
  let parsed: URL;
  try {
    parsed = new URL(url, "http://deep-link.invalid");
  } catch {
    return null;
  }

  const rawSegments = parsed.pathname.split("/");
  if (rawSegments[0] !== "") return null;

  let segments: string[];
  try {
    segments = rawSegments.slice(1).filter((s) => s.length > 0).map((s) =>
      decodeURIComponent(s)
    );
  } catch {
    return null;
  }

  let scope: Scope;
  let idx: number;
  if (segments.length === 0) {
    scope = { kind: "platform" };
    idx = 0;
  } else {
    const consumed = consumeScope(segments);
    if (!consumed) return null;
    scope = consumed.scope;
    idx = consumed.consumed;
  }

  let workspace: Workspace | undefined;
  if (segments[idx] !== undefined && SEGMENT_TO_WORKSPACE[segments[idx]]) {
    workspace = SEGMENT_TO_WORKSPACE[segments[idx]];
    idx += 1;
  }

  let object: ObjectRef | undefined;
  if (segments[idx] === "objects") {
    const token = segments[idx + 1];
    if (token === undefined) return null;
    const ref = parseObjectRef(token, scope);
    if (!ref) return null;
    object = ref;
    idx += 2;
  }

  if (idx !== segments.length) return null; // trailing unrecognized segments

  const recipeParam = parsed.searchParams.get("recipe");
  let recipe: RecipeId | undefined;
  if (recipeParam !== null) {
    if (!RECIPE_ID_SET.has(recipeParam)) return null;
    recipe = recipeParam as RecipeId;
  }

  const focusParam = parsed.searchParams.get("focus");

  const result: DeepLink = { scope };
  if (workspace) result.workspace = workspace;
  if (object) result.object = object;
  if (recipe) result.recipe = recipe;
  if (focusParam !== null) result.focus = focusParam;
  return result;
}
