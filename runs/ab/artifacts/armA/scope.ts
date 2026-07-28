// Scope — §4.1. Platform -> Universe -> Campaign -> Session containment chain.
// Session is a temporal execution context nested under its campaign, never a
// sibling content silo, so a "session" Scope always carries universe+campaign.

export type ScopeKind = "platform" | "universe" | "campaign" | "session";

export interface Scope {
  kind: ScopeKind;
  universe?: string; // slug
  campaign?: string; // slug
  session?: string; // session number as a string
}

// Shared slug grammar for universe/campaign slugs (also reused by deepLink.ts
// when it parses the same path segments outside a full Scope path).
export const SLUG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

const SESSION_PATTERN = /^[0-9]+$/;

export function formatScope(scope: Scope): string {
  if (scope.kind === "platform") return "/";
  const parts = [`/u/${scope.universe ?? ""}`];
  if (scope.kind === "universe") return parts.join("");
  parts.push(`/c/${scope.campaign ?? ""}`);
  if (scope.kind === "campaign") return parts.join("");
  parts.push(`/sessions/${scope.session ?? ""}`);
  return parts.join("");
}

export function parseScope(path: string): Scope | null {
  if (typeof path !== "string" || path.length === 0) return null;
  if (path === "/") return { kind: "platform" };

  const raw = path.split("/");
  // A valid non-root path starts with "/", so raw[0] is the empty string
  // produced by the leading slash.
  if (raw[0] !== "") return null;
  const segments = raw.slice(1);
  if (segments.length === 0) return null;

  if (segments[0] !== "u") return null;
  const universe = segments[1];
  if (!universe || !SLUG_PATTERN.test(universe)) return null;

  if (segments.length === 2) return { kind: "universe", universe };

  if (segments[2] !== "c") return null;
  const campaign = segments[3];
  if (!campaign || !SLUG_PATTERN.test(campaign)) return null;

  if (segments.length === 4) return { kind: "campaign", universe, campaign };

  if (segments[4] !== "sessions") return null;
  const session = segments[5];
  if (!session || !SESSION_PATTERN.test(session)) return null;

  if (segments.length === 6) {
    return { kind: "session", universe, campaign, session };
  }

  return null;
}
