export type ScopeKind = "platform" | "universe" | "campaign" | "session";

export interface Scope {
  kind: ScopeKind;
  universe?: string; // slug
  campaign?: string; // slug
  session?: string; // session number as a string
}

// §4.1: slugs are readable path tokens (lowercase, digits, single internal
// hyphens). Session numbers are digit-only since they are ordinals, not slugs.
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SESSION_RE = /^[0-9]+$/;

export function formatScope(scope: Scope): string {
  switch (scope.kind) {
    case "platform":
      return "/";
    case "universe":
      return `/u/${scope.universe}`;
    case "campaign":
      return `/u/${scope.universe}/c/${scope.campaign}`;
    case "session":
      return `/u/${scope.universe}/c/${scope.campaign}/sessions/${scope.session}`;
  }
}

// Matches the four path forms from §4.1 directly, so a scope can only be
// built with the ancestor slugs its kind requires (a campaign can't parse
// without a universe, a session can't parse without a campaign).
const SCOPE_RE =
  /^\/u\/([^/]+)(?:\/c\/([^/]+)(?:\/sessions\/([^/]+))?)?$/;

export function parseScope(path: string): Scope | null {
  if (typeof path !== "string") return null;

  if (path === "/") return { kind: "platform" };

  const match = path.match(SCOPE_RE);
  if (!match) return null;
  const [, universe, campaign, session] = match;

  if (!SLUG_RE.test(universe)) return null;
  if (campaign !== undefined && !SLUG_RE.test(campaign)) return null;
  if (session !== undefined && !SESSION_RE.test(session)) return null;

  if (session !== undefined) {
    return { kind: "session", universe, campaign, session };
  }
  if (campaign !== undefined) {
    return { kind: "campaign", universe, campaign };
  }
  return { kind: "universe", universe };
}
