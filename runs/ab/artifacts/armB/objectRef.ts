import type { Scope } from "./scope.ts";

export interface ObjectRef {
  type: string; // "character", "scene", "article", ...
  id: string; // STABLE, never changes on rename
  scope: Scope;
  revision: number;
  slug?: string; // readable, MAY change
}

// Canonical text form is `type:id` — never the slug (§4.3/§6.5: ids stay
// stable across renames while slugs may change, so identity can't be built
// on a slug). An optional `@revision` suffix is accepted on parse for
// callers that carry a pinned revision, but is never emitted by
// formatObjectRef since the canonical form is type+id only.
const REF_RE = /^([^:@\s]+):([^:@\s]+)(?:@([0-9]+))?$/;

export function formatObjectRef(ref: ObjectRef): string {
  return `${ref.type}:${ref.id}`;
}

export function parseObjectRef(text: string, scope: Scope): ObjectRef | null {
  if (typeof text !== "string") return null;

  const match = text.match(REF_RE);
  if (!match) return null;
  const [, type, id, revisionText] = match;

  return {
    type,
    id,
    scope,
    revision: revisionText !== undefined ? Number(revisionText) : 0,
  };
}

function sameScope(a: Scope, b: Scope): boolean {
  return (
    a.kind === b.kind &&
    a.universe === b.universe &&
    a.campaign === b.campaign &&
    a.session === b.session
  );
}

// Identity, not revision: the same object at rev 3 and rev 9 is the same
// object. Scope is part of identity, revision is not.
export function sameObject(a: ObjectRef, b: ObjectRef): boolean {
  return a.type === b.type && a.id === b.id && sameScope(a.scope, b.scope);
}
