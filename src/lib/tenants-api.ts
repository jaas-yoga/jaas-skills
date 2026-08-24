import "server-only";

import { runeFetch } from "./rune-api";
import type { MemberResponse } from "./rune-api-types";

export async function listMembers(tenantId: string): Promise<MemberResponse[]> {
  return runeFetch<MemberResponse[]>(`/api/v1/tenants/${encodeURIComponent(tenantId)}/members`);
}
