// ViewRecipe — §4.4. A recipe arranges an already-projected object for a job;
// it never grants field access or enables a command, and roles are not
// recipes (§4.3), so this module has no notion of Role at all.

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

// Exported for reuse (e.g. deepLink.ts validates a `recipe` query param
// against the known RecipeId set without duplicating this list).
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

// §4.3's worked example, plus the sibling mappings §4.4 lists for scene/
// article/place. Anything not listed here has no recipe for that workspace.
const RECIPE_TABLE: Record<string, Partial<Record<Workspace, RecipeId>>> = {
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
  const recipe = RECIPE_TABLE[objectType]?.[workspace];
  return recipe ?? null;
}

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
