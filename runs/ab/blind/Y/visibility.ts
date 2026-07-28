// Visibility / Role — §4.5, §6.5. Server-side gate, never a client filter.
// The sharp requirement: "not_found" and "redacted" are different product
// states ("nicht vorhanden" vs. "vorhanden, aber verboten") and must never
// collapse into one — a link to a secret must not confirm the secret exists.
// Roles are compared as named edges, never reduced to a numeric rank (§4.5).

export type Role = "owner" | "gm" | "co_gm" | "player" | "observer" | "public";

export type Visibility =
  | "open" // any member of the campaign may see it
  | "gm_only" // GM-tier only; players know it EXISTS but not its content
  | "secret"; // its very EXISTENCE is confidential

export type Access =
  | { kind: "ok"; role: Role }
  | { kind: "redacted" } // exists, visible as a locked/withheld row
  | { kind: "not_found" }; // must be indistinguishable from "never existed"

export function isGmTier(role: Role): boolean {
  return role === "owner" || role === "gm" || role === "co_gm";
}

export function resolveAccess(role: Role, visibility: Visibility): Access {
  if (isGmTier(role)) return { kind: "ok", role };

  if (role === "public") return { kind: "not_found" };

  // Remaining roles here are campaign members who are not GM tier and not
  // public: player, observer.
  if (visibility === "open") return { kind: "ok", role };
  if (visibility === "gm_only") return { kind: "redacted" };
  return { kind: "not_found" }; // secret
}
