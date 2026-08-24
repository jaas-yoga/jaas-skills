import "server-only";

import { runeFetch } from "./rune-api";
import type { RepoLinkResponse } from "./rune-api-types";

export async function listRepoLinks(tenantId: string): Promise<RepoLinkResponse[]> {
  return runeFetch<RepoLinkResponse[]>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/repo-links`);
}
