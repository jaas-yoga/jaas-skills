import "server-only";

import { runeFetch } from "./rune-api";
import type { PatSummaryResponse } from "./rune-api-types";

export async function listPats(): Promise<PatSummaryResponse[]> {
  return runeFetch<PatSummaryResponse[]>("/api/v1/account/tokens");
}
