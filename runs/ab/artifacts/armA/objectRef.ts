// ObjectRef — §4.3, §6.5. Identity is (type, id, scope); revision is state,
// not identity. The canonical text form deliberately omits `slug`: slugs are
// readable and may change on rename, while `id` is stable, so anything that
// must survive a rename (links, comparisons) has to be built from `id`.

import type { Scope } from "./scope";

export interface ObjectRef {
  type: string; // "character", "scene", "article", ...
  id: string; // STABLE, never changes on rename
  scope: Scope;
  revision: number;
  slug?: string; // readable, MAY change
}

// type:id@revision — revision is always emitted by formatObjectRef so the
// text form fully reconstructs everything except scope (supplied by the
// caller) and slug (deliberately not part of identity).
const OBJECT_REF_PATTERN = /^([A-Za-z][A-Za-z0-9_-]*):([^@:]+)(?:@(\d+))?$/;

export function formatObjectRef(ref: ObjectRef): string {
  return `${ref.type}:${ref.id}@${ref.revision}`;
}

export function parseObjectRef(text: string, scope: Scope): ObjectRef | null {
  if (typeof text !== "string") return null;
  const match = OBJECT_REF_PATTERN.exec(text);
  if (!match) return null;
  const [, type, id, revisionText] = match;
  const revision = revisionText === undefined ? 0 : Number(revisionText);
  return { type, id, scope, revision };
}

function scopeEquals(a: Scope, b: Scope): boolean {
  return (
    a.kind === b.kind &&
    a.universe === b.universe &&
    a.campaign === b.campaign &&
    a.session === b.session
  );
}

export function sameObject(a: ObjectRef, b: ObjectRef): boolean {
  return a.type === b.type && a.id === b.id && scopeEquals(a.scope, b.scope);
}
