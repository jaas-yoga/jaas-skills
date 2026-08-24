import type { TenantMembershipResponse, UserResponse } from "@/lib/rune-api-types";

/** ui-design.md §4.3 — the registry's own tokens/claims, carried inside
 * Auth.js's encrypted session (never sent to the browser as a bare JWT). */
declare module "next-auth" {
  interface Session {
    runeAccessToken?: string;
    runeUser?: UserResponse;
    runeTenants?: TenantMembershipResponse[];
    runeActiveTenantId?: string;
    runeError?: "RefreshFailed" | "SignInFailed";
  }
}

// Not "next-auth/jwt" — the `jwt` callback's `token` parameter type
// resolves through @auth/core's own AuthConfig["callbacks"], which imports
// JWT directly from "@auth/core/jwt" (see node_modules/@auth/core/index.d.ts
// and lib/index.d.ts), so that's the module declaration merging must target.
declare module "@auth/core/jwt" {
  interface JWT {
    runeAccessToken?: string;
    runeRefreshToken?: string;
    runeAccessTokenExpiresAtMs?: number;
    runeUser?: UserResponse;
    runeTenants?: TenantMembershipResponse[];
    runeActiveTenantId?: string;
    runeError?: "RefreshFailed" | "SignInFailed";
  }
}
