import "server-only";

import { runeFetch } from "./rune-api";
import type { GithubConnectionResponse, GithubOAuthAppResponse } from "./rune-api-types";

export async function getGithubConnection(tenantId: string): Promise<GithubConnectionResponse> {
  return runeFetch<GithubConnectionResponse>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/github/connection`,
  );
}

export async function getGithubOAuthApp(tenantId: string): Promise<GithubOAuthAppResponse> {
  return runeFetch<GithubOAuthAppResponse>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/github/oauth-app`,
  );
}
