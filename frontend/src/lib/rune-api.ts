import "server-only";

import { auth } from "@/auth";
import type { RuneApiError } from "./rune-api-types";

const RUNE_API_URL = process.env.RUNE_API_URL ?? "http://127.0.0.1:8027";

export class RuneApiRequestError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "RuneApiRequestError";
  }
}

/**
 * Server-only fetch helper (ui-design.md §4.2/§14.1): attaches the session's
 * registry access token — which never reaches the browser — so every route
 * handler/server component call to the backend is authenticated the same
 * way. `cache: "no-store"` because visibility/sharing results are per-caller
 * and must never be shared across sessions via Next.js's fetch cache.
 */
export async function runeFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await auth();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (session?.runeAccessToken) {
    headers.set("Authorization", `Bearer ${session.runeAccessToken}`);
  }

  const res = await fetch(`${RUNE_API_URL}${path}`, { ...init, headers, cache: "no-store" });

  if (!res.ok) {
    let body: RuneApiError | null = null;
    try {
      body = await res.json();
    } catch {
      // non-JSON error body (e.g. a proxy 502) — fall through with defaults
    }
    throw new RuneApiRequestError(
      res.status,
      body?.code ?? "UNKNOWN",
      body?.message ?? res.statusText,
      body?.details ?? {},
    );
  }

  // 204 No Content (every DELETE endpoint here) has no body to parse —
  // res.json() would throw on it, which callers can't tell apart from a
  // real failure. Callers of a 204 endpoint pass a `<void>`/unused T.
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}
