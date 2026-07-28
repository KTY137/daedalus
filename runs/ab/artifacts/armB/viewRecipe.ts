export type Workspace = "welt" | "vorbereiten" | "tisch" | "schmiede";

export type RecipeId =
  | "article-reader"
  | "article-editor"
  | "relation-graph"
  | "timeline"
  | "atlas"
  | "actor-sheet"
  | "collection-table"
  | "comparison"
  | "scene-cinematic"
  | "scene-tactical"
  | "scene-outline";

// Runtime companion to the RecipeId union, for callers (e.g. deepLink.ts)
// that need to validate an arbitrary string against the known set.
export const RECIPE_IDS: readonly RecipeId[] = [
  "article-reader",
  "article-editor",
  "relation-graph",
  "timeline",
  "atlas",
  "actor-sheet",
  "collection-table",
  "comparison",
  "scene-cinematic",
  "scene-tactical",
  "scene-outline",
];

// §4.3's worked example, plus the §4.4 examples for scene/article/place.
// A recipe only arranges an already-projected object; roles are never part
// of this table (§4.4: player/gm/observer/public are not recipes).
const RECIPES: Readonly<
  Record<string, Partial<Record<Workspace, RecipeId>>>
> = {
  character: {
    welt: "article-reader",
    vorbereiten: "scene-outline",
    tisch: "actor-sheet",
    schmiede: "collection-table",
  },
  scene: {
    welt: "scene-cinematic",
    vorbereiten: "scene-outline",
    tisch: "scene-tactical",
  },
  article: {
    welt: "article-reader",
    schmiede: "article-editor",
  },
  place: {
    welt: "atlas",
  },
};

export function resolveRecipe(
  objectType: string,
  workspace: Workspace,
): RecipeId | null {
  return RECIPES[objectType]?.[workspace] ?? null;
}

// Selection survives a workspace switch exactly when both workspaces can
// arrange this object type — i.e. a recipe exists on both sides.
export function selectionSurvives(
  objectType: string,
  from: Workspace,
  to: Workspace,
): boolean {
  return (
    resolveRecipe(objectType, from) !== null &&
    resolveRecipe(objectType, to) !== null
  );
}
