import { formatScope, type Scope } from "./scope";
import type { ObjectRef } from "./objectRef.ts";
import { RECIPE_IDS, type RecipeId, type Workspace } from "./viewRecipe";

export interface DeepLink {
  scope: Scope;
  workspace?: Workspace;
  object?: ObjectRef;
  recipe?: RecipeId;
  focus?: string;
}

const WORKSPACE_SEGMENT: Record<Workspace, string> = {
  welt: "world",
  vorbereiten: "prepare",
  tisch: "table",
  schmiede: "forge",
};

const SEGMENT_WORKSPACE: Record<string, Workspace> = {
  world: "welt",
  prepare: "vorbereiten",
  table: "tisch",
  forge: "schmiede",
};

// §6.5 shows two encodings for "which object": a pretty reader path
// (`world/objects/<slug>`) and a query pair keyed by the object's type
// (`?scene=<slug>&recipe=<id>`). Judgment call: the pretty path is only
// used for the "reading an object in Welt, nothing else selected" case —
// the moment a recipe or focus also needs to ride along, the object moves
// to the query form, because the query form is the only one of the two that
// keeps the object's `type` (its query key) instead of dropping it.
function shouldUseObjectPath(link: DeepLink): boolean {
  return (
    link.object !== undefined &&
    link.workspace === "welt" &&
    link.recipe === undefined &&
    link.focus === undefined
  );
}

export function buildDeepLink(link: DeepLink): string {
  const scopePath = formatScope(link.scope);
  const segments = scopePath === "/" ? [] : scopePath.slice(1).split("/");

  if (link.workspace) {
    segments.push(WORKSPACE_SEGMENT[link.workspace]);
  }

  const query = new URLSearchParams();
  const useObjectPath = shouldUseObjectPath(link);

  if (link.object) {
    // Deep links address objects by their readable slug when one exists
    // (falling back to id); resolving a slug back to the stable id it
    // shadows is a server-side lookup this pure module doesn't perform.
    const token = link.object.slug ?? link.object.id;
    if (useObjectPath) {
      segments.push("objects", encodeURIComponent(token));
    } else {
      query.set(link.object.type, token);
    }
  }

  if (link.recipe) query.set("recipe", link.recipe);
  if (link.focus) query.set("focus", link.focus);

  const path = "/" + segments.join("/");
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

// Mirrors parseScope's grammar but works incrementally over path segments,
// since a deep link's scope prefix is followed by workspace/object segments
// that parseScope (which only accepts a complete scope path) doesn't know
// about.
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SESSION_RE = /^[0-9]+$/;

function extractScope(
  segments: string[],
): { scope: Scope; rest: string[] } | null {
  if (segments.length === 0) return { scope: { kind: "platform" }, rest: [] };
  if (segments[0] !== "u") return null;

  const universe = segments[1];
  if (universe === undefined || !SLUG_RE.test(universe)) return null;

  if (segments[2] !== "c") {
    return { scope: { kind: "universe", universe }, rest: segments.slice(2) };
  }

  const campaign = segments[3];
  if (campaign === undefined || !SLUG_RE.test(campaign)) return null;

  if (segments[4] !== "sessions") {
    return {
      scope: { kind: "campaign", universe, campaign },
      rest: segments.slice(4),
    };
  }

  const session = segments[5];
  if (session === undefined || !SESSION_RE.test(session)) return null;

  return {
    scope: { kind: "session", universe, campaign, session },
    rest: segments.slice(6),
  };
}

export function parseDeepLink(url: string): DeepLink | null {
  if (typeof url !== "string" || url.length === 0) return null;

  try {
    const parsed = new URL(url, "http://deep-link.invalid");
    const pathname = parsed.pathname;
    if (!pathname.startsWith("/")) return null;

    const rawSegments =
      pathname === "/" ? [] : pathname.slice(1).split("/").filter(Boolean);
    const segments = rawSegments.map((segment) => decodeURIComponent(segment));

    const scoped = extractScope(segments);
    if (!scoped) return null;
    const { scope, rest } = scoped;

    let workspace: Workspace | undefined;
    let afterWorkspace = rest;
    if (rest.length > 0) {
      const mapped = SEGMENT_WORKSPACE[rest[0]];
      if (!mapped) return null;
      workspace = mapped;
      afterWorkspace = rest.slice(1);
    }

    let object: ObjectRef | undefined;
    if (afterWorkspace.length === 2 && afterWorkspace[0] === "objects") {
      const token = afterWorkspace[1];
      if (token.length === 0) return null;
      // No type rides along in this path form (it's the "pretty reader
      // URL" shape) — "object" is a documented placeholder type; resolving
      // the concrete type is a server-side concern.
      object = { type: "object", id: token, slug: token, scope, revision: 0 };
    } else if (afterWorkspace.length > 0) {
      return null;
    }

    const query = parsed.searchParams;

    let recipe: RecipeId | undefined;
    const recipeRaw = query.get("recipe");
    if (recipeRaw !== null) {
      if (!(RECIPE_IDS as readonly string[]).includes(recipeRaw)) return null;
      recipe = recipeRaw as RecipeId;
    }

    const focusRaw = query.get("focus");
    const focus = focusRaw !== null ? focusRaw : undefined;

    if (!object) {
      for (const [key, value] of query.entries()) {
        if (key === "recipe" || key === "focus") continue;
        object = { type: key, id: value, slug: value, scope, revision: 0 };
        break;
      }
    }

    return { scope, workspace, object, recipe, focus };
  } catch {
    return null;
  }
}
