# Build task: the Chronicle core navigation model

You are implementing a slice of an existing, already-written product architecture
into the repository at `design/visual-lab`. This is pure TypeScript domain logic:
**no React, no components, no CSS.**

The authoritative source is `design/06-giga-product-architecture.md`, sections
**4.1–4.6** and **6.5**. Read them. Where this brief and that document disagree,
the document wins — except for the module paths and exported signatures below,
which are fixed so the result is machine-checkable.

## What to build

Five modules under `design/visual-lab/src/core/`. Export exactly these names with
exactly these signatures. You may add more internal helpers, types and files.

### `src/core/scope.ts`

```ts
export type ScopeKind = "platform" | "universe" | "campaign" | "session";

export interface Scope {
  kind: ScopeKind;
  universe?: string;   // slug
  campaign?: string;   // slug
  session?: string;    // session number as a string
}

export function formatScope(scope: Scope): string;
export function parseScope(path: string): Scope | null;
```

Rules (§4.1):
- Path forms: `/` (platform), `/u/<universe>`, `/u/<universe>/c/<campaign>`,
  `/u/<universe>/c/<campaign>/sessions/<n>`.
- `parseScope` returns `null` for anything malformed. It never throws.
- `formatScope(parseScope(p))` must equal `p` for every valid `p`.
- A scope is only valid if every ancestor slug it needs is present: a `campaign`
  scope without a `universe` is invalid, a `session` scope without a campaign is
  invalid.
- Session is a temporal execution context, not a content silo — a session scope
  still belongs to its campaign.

### `src/core/objectRef.ts`

```ts
import type { Scope } from "./scope.ts";

export interface ObjectRef {
  type: string;        // "character", "scene", "article", ...
  id: string;          // STABLE, never changes on rename
  scope: Scope;
  revision: number;
  slug?: string;       // readable, MAY change
}

export function formatObjectRef(ref: ObjectRef): string;
export function parseObjectRef(text: string, scope: Scope): ObjectRef | null;
export function sameObject(a: ObjectRef, b: ObjectRef): boolean;
```

Rules (§4.3, §6.5):
- The canonical text form is built from `type` and `id` only — never the slug,
  because IDs stay stable across renames while slugs may change.
- `sameObject` compares identity, NOT revision: the same object at revision 3 and
  revision 9 is the same object. Scope is part of identity.
- `parseObjectRef` returns `null` on malformed input, never throws. `revision`
  defaults to `0` when absent.

### `src/core/viewRecipe.ts`

```ts
export type Workspace = "welt" | "vorbereiten" | "tisch" | "schmiede";

export type RecipeId =
  | "article-reader" | "article-editor" | "relation-graph" | "timeline"
  | "atlas" | "actor-sheet" | "collection-table" | "comparison"
  | "scene-cinematic" | "scene-tactical" | "scene-outline";

export function resolveRecipe(objectType: string, workspace: Workspace): RecipeId | null;
export function selectionSurvives(objectType: string, from: Workspace, to: Workspace): boolean;
```

Rules (§4.4, §4.3):
- A recipe decides how an already-projected object is ARRANGED. It never grants
  access to a field and never enables a command.
- `player`, `gm`, `observer`, `public` are roles, NOT recipes. `resolveRecipe`
  must never accept or return a role.
- Required mappings, taken from §4.3's worked example for `character`:
  - `character` + `welt` → `article-reader`
  - `character` + `vorbereiten` → `scene-outline`
  - `character` + `tisch` → `actor-sheet`
  - `character` + `schmiede` → `collection-table`
  - `scene` + `tisch` → `scene-tactical`
  - `scene` + `vorbereiten` → `scene-outline`
  - `scene` + `welt` → `scene-cinematic`
  - `article` + `welt` → `article-reader`
  - `article` + `schmiede` → `article-editor`
  - `place` + `welt` → `atlas`
- An unknown object type, or a type with no recipe for that workspace, returns
  `null`.
- `selectionSurvives` is true exactly when a recipe exists in BOTH workspaces:
  selection is kept across a workspace switch only if a recipe exists there.

### `src/core/visibility.ts`

```ts
export type Role = "owner" | "gm" | "co_gm" | "player" | "observer" | "public";

export type Visibility =
  | "open"        // any member of the campaign may see it
  | "gm_only"     // GM-tier only; players know it EXISTS but not its content
  | "secret";     // its very EXISTENCE is confidential

export type Access =
  | { kind: "ok"; role: Role }
  | { kind: "redacted" }     // exists, visible as a locked//withheld row
  | { kind: "not_found" };   // must be indistinguishable from "never existed"

export function resolveAccess(role: Role, visibility: Visibility): Access;
export function isGmTier(role: Role): boolean;
```

Rules (§4.5, §6.5) — **the sharpest requirements in this brief**:
- `owner`, `gm` and `co_gm` are GM tier. `player`, `observer`, `public` are not.
- `open` → `ok` for every role EXCEPT `public`, which gets `not_found`
  (a public viewer is not a campaign member; campaign content is not public).
- `gm_only` → `ok` for GM tier; `redacted` for `player` and `observer`;
  `not_found` for `public`.
- `secret` → `ok` for GM tier, and **`not_found` for everyone else**. It must
  NOT be `redacted`: *"Ein Link zu einem nicht mehr erlaubten Objekt bestätigt
  dessen Existenz nicht."* Rendering a secret object as a locked row confirms it
  exists, which is the leak this rule exists to prevent.
- `"nicht vorhanden"` and `"vorhanden, aber verboten"` are different product
  states and must stay distinguishable in this contract — that is exactly why
  `redacted` and `not_found` are separate variants rather than one `denied`.
- Roles are never collapsed into a rank number. Do not compute a numeric level
  and compare it.

### `src/core/deepLink.ts`

```ts
import type { Scope } from "./scope.ts";
import type { ObjectRef } from "./objectRef.ts";
import type { RecipeId, Workspace } from "./viewRecipe.ts";

export interface DeepLink {
  scope: Scope;
  workspace?: Workspace;
  object?: ObjectRef;
  recipe?: RecipeId;
  focus?: string;
}

export function buildDeepLink(link: DeepLink): string;
export function parseDeepLink(url: string): DeepLink | null;
```

Rules (§6.5):
- Shapes to support, matching the document's examples:
  - `/u/eron`
  - `/u/eron/c/hauptrunde/world/objects/olav-der-ehrliche`
  - `/u/eron/c/hauptrunde/prepare?focus=scene.silberader`
  - `/u/eron/c/hauptrunde/sessions/15/table?scene=silberader&recipe=tactical`
- Workspace path segments are `world`, `prepare`, `table`, `forge` for the
  workspaces `welt`, `vorbereiten`, `tisch`, `schmiede`.
- Selection and recipe are deep-linkable: an object and a `recipe` query
  parameter both survive a `build` → `parse` round trip.
- `parseDeepLink` returns `null` for a malformed URL and never throws.
- `buildDeepLink` must percent-encode values that need it, and `parseDeepLink`
  must decode them, so a slug or focus value containing `/`, `?`, `&` or a space
  survives a round trip intact.

## The gate

`npm --prefix design/visual-lab run build` must pass. That runs
`tsc --noEmit && vite build`. Warnings are fine; a non-zero exit is not.

Do not add dependencies. Do not modify `package.json`, `tsconfig.json`,
`vite.config.ts`, `App.tsx` or `main.tsx`. Do not delete or edit anything under
`design/fixtures/`.

## Definition of done

All five modules exist, export exactly the named symbols with those signatures,
implement the rules above, and the gate passes.
