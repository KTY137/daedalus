export type Role = "owner" | "gm" | "co_gm" | "player" | "observer" | "public";

export type Visibility =
  | "open" // any member of the campaign may see it
  | "gm_only" // GM-tier only; players know it EXISTS but not its content
  | "secret"; // its very EXISTENCE is confidential

export type Access =
  | { kind: "ok"; role: Role }
  | { kind: "redacted" } // exists, visible as a locked/withheld row
  | { kind: "not_found" }; // must be indistinguishable from "never existed"

const GM_TIER: ReadonlySet<Role> = new Set(["owner", "gm", "co_gm"]);

export function isGmTier(role: Role): boolean {
  return GM_TIER.has(role);
}

// §4.5/§6.5: roles are never collapsed into a rank number — they are
// compared as a set membership check (GM tier) plus an explicit per-role
// carve-out for `public`, never a numeric level comparison.
export function resolveAccess(role: Role, visibility: Visibility): Access {
  // `public` is not a campaign member at all: campaign content — open,
  // gm_only or secret — is never visible to a public viewer, and a public
  // viewer never even learns it exists.
  if (role === "public") {
    return { kind: "not_found" };
  }

  if (isGmTier(role)) {
    return { kind: "ok", role };
  }

  // Remaining roles here are `player` and `observer`.
  switch (visibility) {
    case "open":
      return { kind: "ok", role };
    case "gm_only":
      return { kind: "redacted" };
    case "secret":
      // Never `redacted` here: rendering a locked row would confirm the
      // object exists, which is exactly the leak `secret` exists to prevent.
      return { kind: "not_found" };
  }
}
