import "server-only";

import { runeFetch } from "./rune-api";
import type {
  ShareGrantResponse,
  SkillMetadataResponse,
  SearchResponse,
  SourceFilesResponse,
} from "./rune-api-types";

export async function searchSkills(params: {
  query?: string;
  category?: string;
  tags?: string;
  runtime?: string;
  page?: number;
  pageSize?: number;
}): Promise<SearchResponse> {
  const qs = new URLSearchParams();
  if (params.query) qs.set("query", params.query);
  if (params.category) qs.set("category", params.category);
  if (params.tags) qs.set("tags", params.tags);
  if (params.runtime) qs.set("runtime", params.runtime);
  qs.set("page", String(params.page ?? 1));
  qs.set("pageSize", String(params.pageSize ?? 100));

  return runeFetch<SearchResponse>(`/api/v1/skills?${qs.toString()}`);
}

export async function getSkillMetadata(
  skillId: string,
  version: string,
): Promise<SkillMetadataResponse> {
  return runeFetch<SkillMetadataResponse>(
    `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(version)}`,
  );
}

/** Returns [] rather than throwing on 403 — a non-owner/non-admin viewing a
 * skill they don't manage simply sees no share management UI, not an error. */
export async function listShareGrants(skillId: string): Promise<ShareGrantResponse[]> {
  try {
    return await runeFetch<ShareGrantResponse[]>(
      `/api/v1/skills/${encodeURIComponent(skillId)}/shares`,
    );
  } catch {
    return [];
  }
}

/** Read-only: only ever the packaged archive's contents — manifest.yaml,
 * schema.json/permissions.yaml/dependencies.yaml (real or defaulted), and
 * the entrypoint file if one existed at publish time (see
 * artifact/publish.py's load_source_documents). Anything else in the
 * skill's source directory (README.md, tests/, ...) still never appears. */
export async function listSkillFiles(skillId: string, version: string): Promise<string[]> {
  return runeFetch<string[]>(
    `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(version)}/files`,
  );
}

export async function getSkillFile(
  skillId: string,
  version: string,
  path: string,
): Promise<string> {
  // Not encodeURIComponent(path) — it would escape "/" as "%2F", breaking a
  // multi-segment path against FastAPI's {file_path:path} converter (same
  // reasoning as drafts-api.ts's getDraftFile).
  const result = await runeFetch<{ path: string; content: string }>(
    `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(version)}/files/${path}`,
  );
  return result.content;
}

/** Full repo tree at this version's release tag, fetched live from GitHub
 * (browsing only — not what's actually packaged/signed, see
 * listSkillFiles). `available: false` when there's no source repo
 * recorded or GitHub can't be reached/it's private. */
export async function listSkillSourceFiles(
  skillId: string,
  version: string,
): Promise<SourceFilesResponse> {
  return runeFetch<SourceFilesResponse>(
    `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(version)}/source-files`,
  );
}

export async function getSkillSourceFile(
  skillId: string,
  version: string,
  path: string,
): Promise<string> {
  // Not encodeURIComponent(path) — same reasoning as getSkillFile above.
  const result = await runeFetch<{ path: string; content: string }>(
    `/api/v1/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(version)}/source-files/${path}`,
  );
  return result.content;
}
