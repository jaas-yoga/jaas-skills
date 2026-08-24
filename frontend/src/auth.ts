import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

import { decodeJwtExpMs } from "@/lib/jwt";
import type { AuthResponse, RefreshResponse } from "@/lib/rune-api-types";

const RUNE_API_URL = process.env.RUNE_API_URL ?? "http://127.0.0.1:8027";

// Re-mint the access token this many ms before it actually expires
// (ui-design.md risk register item 1) — a proactive margin, not reactive
// only-on-401, so a long-idle tab doesn't hit a dead token mid-request.
const REFRESH_MARGIN_MS = 60_000;

export const {
  handlers: { GET, POST },
  auth,
  signIn,
  signOut,
} = NextAuth({
  // Auth.js's default convention: reads AUTH_GOOGLE_ID/AUTH_GOOGLE_SECRET
  // from web/.env.local. Deliberately NOT the shared GOOGLE_CLIENT_ID/
  // GOOGLE_CLIENT_SECRET used by other local apps in this environment —
  // that client is registered with a pile of unrelated redirect URIs and
  // Google rejected token exchange for it ("doesn't comply with Google's
  // OAuth 2.0 policy"). This app gets its own dedicated OAuth client.
  providers: [Google],
  callbacks: {
    async jwt({ token, account, trigger, session }) {
      // ui-design.md §9 TenantSwitcher: useSession().update({ tenantId })
      // lands here with trigger === "update". Re-mint against the *current*
      // refresh token rather than trusting anything else in `session` —
      // that payload comes from the client and must be treated as
      // unvalidated input (see @auth/core's own warning on this param).
      if (trigger === "update" && session?.tenantId && token.runeRefreshToken) {
        try {
          const res = await fetch(`${RUNE_API_URL}/api/v1/auth/refresh`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              refreshToken: token.runeRefreshToken,
              tenantId: session.tenantId,
            }),
          });
          if (res.ok) {
            const data = (await res.json()) as RefreshResponse;
            token.runeAccessToken = data.accessToken;
            token.runeTenants = data.tenants;
            token.runeActiveTenantId = data.activeTenantId;
            token.runeAccessTokenExpiresAtMs = decodeJwtExpMs(data.accessToken) ?? undefined;
            token.runeError = undefined;
          }
        } catch {
          // Leave the token as-is on failure — switching tenants is a
          // best-effort UX action, not something that should sign anyone out.
        }
        return token;
      }

      // Initial sign-in: exchange the just-verified Google ID token for the
      // registry's own tokens (ui-design.md §4.2). `account` is only set on
      // this first call, never on subsequent session reads.
      if (account?.id_token) {
        try {
          const res = await fetch(`${RUNE_API_URL}/api/v1/auth/google`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ idToken: account.id_token }),
          });
          if (!res.ok) {
            token.runeError = "SignInFailed";
            return token;
          }
          const data = (await res.json()) as AuthResponse;
          token.runeAccessToken = data.accessToken;
          token.runeRefreshToken = data.refreshToken;
          token.runeUser = data.user;
          token.runeTenants = data.tenants;
          token.runeActiveTenantId = data.activeTenantId;
          token.runeAccessTokenExpiresAtMs = decodeJwtExpMs(data.accessToken) ?? undefined;
          token.runeError = undefined;
        } catch {
          token.runeError = "SignInFailed";
        }
        return token;
      }

      // Still comfortably valid — nothing to do.
      if (
        token.runeAccessTokenExpiresAtMs &&
        Date.now() < token.runeAccessTokenExpiresAtMs - REFRESH_MARGIN_MS
      ) {
        return token;
      }

      if (!token.runeRefreshToken) {
        return token;
      }

      try {
        const res = await fetch(`${RUNE_API_URL}/api/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refreshToken: token.runeRefreshToken }),
        });
        if (!res.ok) {
          token.runeError = "RefreshFailed";
          return token;
        }
        const data = (await res.json()) as RefreshResponse;
        token.runeAccessToken = data.accessToken;
        token.runeTenants = data.tenants;
        token.runeActiveTenantId = data.activeTenantId;
        token.runeAccessTokenExpiresAtMs = decodeJwtExpMs(data.accessToken) ?? undefined;
        token.runeError = undefined;
      } catch {
        token.runeError = "RefreshFailed";
      }
      return token;
    },

    async session({ session, token }) {
      session.runeAccessToken = token.runeAccessToken;
      session.runeUser = token.runeUser;
      session.runeTenants = token.runeTenants;
      session.runeActiveTenantId = token.runeActiveTenantId;
      session.runeError = token.runeError;
      if (token.runeUser) {
        session.user = {
          ...session.user,
          name: token.runeUser.name,
          email: token.runeUser.email,
          image: token.runeUser.pictureUrl ?? session.user?.image,
        };
      }
      return session;
    },
  },
});
