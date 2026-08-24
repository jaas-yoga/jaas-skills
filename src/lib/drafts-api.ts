import "server-only";

import { runeFetch } from "./rune-api";
import type { DraftResponse, DraftSummaryResponse } from "./rune-api-types";

export async function listDrafts(): Promise<DraftSummaryResponse[]> {
  return runeFetch<DraftSummaryResponse[]>("/api/v1/drafts");
}

export async function getDraft(draftId: string): Promise<DraftResponse> {
  return runeFetch<DraftResponse>(`/api/v1/drafts/${encodeURIComponent(draftId)}`);
}

export async function getDraftFile(draftId: string, path: string): Promise<string> {
  // Not encodeURIComponent(path) — it would escape "/" as "%2F", breaking a
  // multi-segment path against FastAPI's {file_path:path} converter, which
  // expects literal slashes. The backend's own path-safety check
  // (drafts/store.py's _safe_file_path) is what actually guards this.
  const result = await runeFetch<{ path: string; content: string }>(
    `/api/v1/drafts/${encodeURIComponent(draftId)}/files/${path}`,
  );
  return result.content;
}
