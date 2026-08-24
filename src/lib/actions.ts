"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { signOut } from "@/auth";
import { getDraftFile } from "@/lib/drafts-api";
import { RuneApiRequestError, runeFetch } from "@/lib/rune-api";
import { getSkillFile, getSkillSourceFile, listSkillSourceFiles } from "@/lib/skills-api";
import type {
  CreateDraftGitRequest,
  CreatePatResponse,
  CustomGuardrailRuleResponse,
  DraftPublishResponse,
  DraftResponse,
  GithubConnectUrlResponse,
  GithubOAuthAppRequest,
  GithubOAuthAppResponse,
  GithubRepoResponse,
  InviteMemberResponse,
  RepoLinkResponse,
  SourceFilesResponse,
  TenantGuardrailPolicyResponse,
  TenantMembershipResponse,
  ValidateCustomGuardrailRuleResponse,
  ValidationResultResponse,
} from "@/lib/rune-api-types";

export async function signOutAction() {
  await signOut({ redirectTo: "/login" });
}

export type ActionResult = { ok: true } | { ok: false; error: string };

/** ui-design.md §10.5 — People/Tenants tab "add" action. `path` is the
 * calling page's own pathname, revalidated on success so the grant list and
 * (for the grantee, on their next load) search results reflect it
 * immediately — grants are looked up per-request, never cached in the
 * index (design.md §7.2 item 4). */
export async function createShareGrantAction(
  skillId: string,
  input: { granteeType: "user" | "tenant"; granteeId: string; permission: "read" | "read_write" },
  path: string,
): Promise<ActionResult> {
  try {
    await runeFetch(`/api/v1/skills/${encodeURIComponent(skillId)}/shares`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to create share grant.",
    };
  }
  revalidatePath(path);
  return { ok: true };
}

export async function revokeShareGrantAction(
  skillId: string,
  grantId: string,
  path: string,
): Promise<ActionResult> {
  try {
    await runeFetch(
      `/api/v1/skills/${encodeURIComponent(skillId)}/shares/${encodeURIComponent(grantId)}`,
      { method: "DELETE" },
    );
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to revoke share grant.",
    };
  }
  revalidatePath(path);
  return { ok: true };
}

/** ui-design.md §11.4. Creates a blank draft, or forks a published version
 * into a new one, then navigates straight into the authoring workspace. */
export async function createDraftAction(forkFrom?: { id: string; version: string }) {
  const draft = await runeFetch<DraftResponse>("/api/v1/drafts", {
    method: "POST",
    body: JSON.stringify({ forkFrom: forkFrom ?? null }),
  });
  redirect(`/drafts/${draft.id}`);
}

export type CreateDraftWithGitResult =
  | { ok: true; draftId: string }
  | { ok: false; error: string; code?: string };

/** Same creation call as createDraftAction, plus a git connection set up
 * server-side (working branch created off `targetBranch`, seed files
 * committed) before the draft is ready to edit. Any failure there rolls
 * the whole draft back (drafts/git_sync.py's create_draft), so this is
 * all-or-nothing from the caller's point of view. `code` lets the caller
 * special-case DRAFT_GIT_EMPTY_REPO — a brand-new repo with zero commits
 * — into a confirm-and-retry step rather than a plain error. */
export async function createDraftWithGitAction(
  git: CreateDraftGitRequest,
): Promise<CreateDraftWithGitResult> {
  try {
    const draft = await runeFetch<DraftResponse>("/api/v1/drafts", {
      method: "POST",
      body: JSON.stringify({ forkFrom: null, git }),
    });
    return { ok: true, draftId: draft.id };
  } catch (err) {
    if (err instanceof RuneApiRequestError) {
      return { ok: false, error: err.message, code: err.code };
    }
    return { ok: false, error: "Failed to create draft." };
  }
}

export async function getDraftFileAction(draftId: string, path: string): Promise<string> {
  return getDraftFile(draftId, path);
}

/** Read-only counterpart for a published version's file viewer — no save
 * path exists here on purpose, unlike getDraftFileAction. */
export async function getSkillFileAction(
  skillId: string,
  version: string,
  path: string,
): Promise<string> {
  return getSkillFile(skillId, version, path);
}

/** Counterpart for the "Source repo (at tag)" tab — fetches a file's
 * content live from GitHub rather than from the packaged archive. */
export async function getSkillSourceFileAction(
  skillId: string,
  version: string,
  path: string,
): Promise<string> {
  return getSkillSourceFile(skillId, version, path);
}

/** Fetched lazily (only when the "Source repo" tab is opened), not on
 * initial page load — this hits GitHub's live API, unlike everything else
 * on the published-skill page which reads only from the registry's own
 * index/storage. */
export async function listSkillSourceFilesAction(
  skillId: string,
  version: string,
): Promise<SourceFilesResponse> {
  return listSkillSourceFiles(skillId, version);
}

export type SaveFileResult =
  | {
      ok: true;
      files: string[];
      gitSyncStatus: "synced" | "error" | null;
      gitSyncError: string | null;
    }
  | { ok: false; error: string };

/** ui-design.md §11.2 — backs both the debounced autosave and the explicit
 * "Save Draft" button; the tab-strip status indicator is driven by whichever
 * called last. When the draft is git-connected, a commit to its working
 * branch only happens when `syncToGit` is true — the debounced autosave
 * passes false so every keystroke doesn't spam the repo with commits, and
 * only the explicit "Save Draft" button (which also prompts for
 * `commitMessage`) sets it. A sync failure there still returns ok:true (the
 * local save always succeeds), surfaced via gitSyncStatus instead. */
export async function saveDraftFileAction(
  draftId: string,
  path: string,
  content: string,
  options: { syncToGit?: boolean; commitMessage?: string } = {},
): Promise<SaveFileResult> {
  try {
    const draft = await runeFetch<DraftResponse>(`/api/v1/drafts/${draftId}/files/${path}`, {
      method: "PUT",
      body: JSON.stringify({
        content,
        syncToGit: options.syncToGit ?? false,
        commitMessage: options.commitMessage ?? null,
      }),
    });
    return { ok: true, files: draft.files, gitSyncStatus: draft.gitSyncStatus, gitSyncError: draft.gitSyncError };
  } catch (err) {
    return { ok: false, error: err instanceof RuneApiRequestError ? err.message : "Save failed." };
  }
}

export async function deleteDraftFileAction(
  draftId: string,
  path: string,
): Promise<SaveFileResult> {
  try {
    const draft = await runeFetch<DraftResponse>(`/api/v1/drafts/${draftId}/files/${path}`, {
      method: "DELETE",
    });
    return { ok: true, files: draft.files, gitSyncStatus: draft.gitSyncStatus, gitSyncError: draft.gitSyncError };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Delete failed.",
    };
  }
}

export type MoveDraftToGitDirectoryResult =
  | { ok: true; gitSubdirectory: string; gitSyncStatus: "synced" | "error" | null }
  | { ok: false; error: string; code?: string };

/** One-time migration for a draft that was git-connected before every
 * skill got its own folder — moves its already-committed files from the
 * repo root into `<skill-id>/` in a single commit, so one repo can host
 * several skills without their files colliding. Drafts connected after this
 * feature shipped already use a directory from creation and never need
 * this. See api/draft_routes.py::move_draft_to_git_directory. */
export async function moveDraftToGitDirectoryAction(
  draftId: string,
): Promise<MoveDraftToGitDirectoryResult> {
  try {
    const draft = await runeFetch<DraftResponse>(
      `/api/v1/drafts/${draftId}/git/move-to-directory`,
      { method: "POST" },
    );
    return {
      ok: true,
      gitSubdirectory: draft.gitSubdirectory ?? "",
      gitSyncStatus: draft.gitSyncStatus,
    };
  } catch (err) {
    if (err instanceof RuneApiRequestError) {
      return { ok: false, error: err.message, code: err.code };
    }
    return { ok: false, error: "Failed to move this skill into a directory." };
  }
}

/** Discards the whole draft, not just one file — irreversible, no
 * trash/undo (matches DELETE /api/v1/drafts/{draftId} on the backend).
 * Redirects to the drafts list on success since the workspace it was
 * called from no longer exists. */
export async function deleteDraftAction(draftId: string): Promise<ActionResult> {
  try {
    await runeFetch(`/api/v1/drafts/${draftId}`, { method: "DELETE" });
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to delete draft.",
    };
  }
  revalidatePath("/drafts");
  return { ok: true };
}

/** ui-design.md §11.3 — runs the exact same validate_skill_package the CLI
 * and the publish pipeline use; there is only one validation implementation. */
export async function validateDraftAction(draftId: string): Promise<ValidationResultResponse> {
  return runeFetch<ValidationResultResponse>(`/api/v1/drafts/${draftId}/validate`, {
    method: "POST",
  });
}

export type PublishDraftResult =
  | { ok: true; skill: DraftPublishResponse }
  | { ok: false; error: string; code?: string; prUrl?: string };

export async function publishDraftAction(
  draftId: string,
  visibility: "public" | "private",
): Promise<PublishDraftResult> {
  try {
    const skill = await runeFetch<DraftPublishResponse>(`/api/v1/drafts/${draftId}/publish`, {
      method: "POST",
      body: JSON.stringify({ visibility }),
    });
    return { ok: true, skill };
  } catch (err) {
    if (err instanceof RuneApiRequestError) {
      return {
        ok: false,
        error: err.message,
        code: err.code,
        prUrl: typeof err.details.prUrl === "string" ? err.details.prUrl : undefined,
      };
    }
    return { ok: false, error: "Publish failed." };
  }
}

export type CreateTenantResult =
  | { ok: true; tenant: TenantMembershipResponse }
  | { ok: false; error: string };

/** ui-design.md §9 "Create Tenant" flow. Creating a tenant only mints the
 * membership server-side — the caller's session still has the *old* tenant
 * list until TenantSwitcher's useSession().update() re-mints the token
 * (src/auth.ts's trigger:"update" branch), so this alone doesn't switch
 * anyone into the new tenant. */
export async function createTenantAction(name: string): Promise<CreateTenantResult> {
  try {
    const tenant = await runeFetch<TenantMembershipResponse>("/api/v1/tenants", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    return { ok: true, tenant };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to create tenant.",
    };
  }
}

export type InviteMemberResult =
  | { ok: true; invite: InviteMemberResponse }
  | { ok: false; error: string };

export async function inviteMemberAction(
  tenantId: string,
  email: string,
  role: "admin" | "member",
): Promise<InviteMemberResult> {
  try {
    const invite = await runeFetch<InviteMemberResponse>(
      `/api/v1/tenants/${tenantId}/members`,
      { method: "POST", body: JSON.stringify({ email, role }) },
    );
    revalidatePath(`/tenants/${tenantId}/members`);
    return { ok: true, invite };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to invite member.",
    };
  }
}

export type UpdateGuardrailPolicyResult =
  | { ok: true; policy: TenantGuardrailPolicyResponse }
  | { ok: false; error: string };

/** design.md §4.5, ui-design.md §10.7 — admin-only; the server rejects the
 * request outright (403) if the caller isn't a tenant admin, same as
 * inviteMemberAction above. */
export async function updateGuardrailPolicyAction(
  tenantId: string,
  enabledCheckIds: string[],
): Promise<UpdateGuardrailPolicyResult> {
  try {
    const policy = await runeFetch<TenantGuardrailPolicyResponse>(
      `/api/v1/tenants/${tenantId}/guardrail-policy`,
      { method: "PUT", body: JSON.stringify({ enabledCheckIds }) },
    );
    revalidatePath(`/tenants/${tenantId}/guardrails`);
    return { ok: true, policy };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to update guardrails.",
    };
  }
}

export type CreatePatResult =
  | { ok: true; pat: CreatePatResponse }
  | { ok: false; error: string };

/** ui-design.md §4.4. The raw token is shown to the caller exactly once —
 * this action's return value is the only place it ever appears; the list
 * endpoint never returns it again. */
export async function createPatAction(name: string): Promise<CreatePatResult> {
  try {
    const pat = await runeFetch<CreatePatResponse>("/api/v1/account/tokens", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    revalidatePath("/account/tokens");
    return { ok: true, pat };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to create token.",
    };
  }
}

export async function revokePatAction(patId: string): Promise<ActionResult> {
  try {
    await runeFetch(`/api/v1/account/tokens/${patId}`, { method: "DELETE" });
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to revoke token.",
    };
  }
  revalidatePath("/account/tokens");
  return { ok: true };
}

export type CustomGuardrailRuleInput = {
  slug: string;
  name: string;
  description: string;
  category: string;
  severity: "BLOCK" | "WARN";
  standardRef: string;
  kind: string;
  config: Record<string, unknown>;
};

export type PutCustomGuardrailRuleResult =
  | { ok: true; rule: CustomGuardrailRuleResponse }
  | { ok: false; error: string };

/** design.md §4.5 "custom rules". The guardrails service is the single
 * source of truth for whether a rule is well-formed — this action doesn't
 * pre-validate, the backend does that itself (via POST .../validate before
 * it ever persists), same as validateCustomGuardrailRuleAction below but
 * for the actual save path. */
export async function putCustomGuardrailRuleAction(
  tenantId: string,
  input: CustomGuardrailRuleInput,
): Promise<PutCustomGuardrailRuleResult> {
  try {
    const rule = await runeFetch<CustomGuardrailRuleResponse>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/custom-guardrails/${encodeURIComponent(input.slug)}`,
      { method: "PUT", body: JSON.stringify(input) },
    );
    revalidatePath(`/tenants/${tenantId}/guardrails`);
    return { ok: true, rule };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to save custom rule.",
    };
  }
}

export async function deleteCustomGuardrailRuleAction(
  tenantId: string,
  slug: string,
): Promise<ActionResult> {
  try {
    await runeFetch(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/custom-guardrails/${encodeURIComponent(slug)}`,
      { method: "DELETE" },
    );
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to delete custom rule.",
    };
  }
  revalidatePath(`/tenants/${tenantId}/guardrails`);
  return { ok: true };
}

/** Dry-run only — never saves anything. Used for live "Validate" feedback
 * while a rule is being authored in the editor, before Save is pressed. */
export async function validateCustomGuardrailRuleAction(
  tenantId: string,
  input: CustomGuardrailRuleInput,
): Promise<ValidateCustomGuardrailRuleResponse> {
  return runeFetch<ValidateCustomGuardrailRuleResponse>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/custom-guardrails/validate`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export type CreateRepoLinkResult =
  | { ok: true; link: RepoLinkResponse }
  | { ok: false; error: string };

/** ui-design.md / design.md §4.5's git-native release flow — registers
 * which repo may release a given skill id before CI can ever call
 * POST /api/v1/skills/release for it (anti-squatting, see
 * authn/repo_links.py in the backend). */
export async function createRepoLinkAction(
  tenantId: string,
  input: { skillId: string; repoUrl: string; releaseBranches: string[] },
): Promise<CreateRepoLinkResult> {
  try {
    const link = await runeFetch<RepoLinkResponse>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/repo-links`,
      { method: "POST", body: JSON.stringify(input) },
    );
    revalidatePath(`/tenants/${tenantId}/guardrails`);
    return { ok: true, link };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to connect repo.",
    };
  }
}

/** Full-replace of the allowed release branches for an existing link —
 * see api/tenant_routes.py::update_repo_link. */
export async function updateRepoLinkAction(
  tenantId: string,
  skillId: string,
  releaseBranches: string[],
): Promise<CreateRepoLinkResult> {
  try {
    const link = await runeFetch<RepoLinkResponse>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/repo-links/${encodeURIComponent(skillId)}`,
      { method: "PUT", body: JSON.stringify({ releaseBranches }) },
    );
    revalidatePath(`/tenants/${tenantId}/guardrails`);
    return { ok: true, link };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to update repo link.",
    };
  }
}

export async function deleteRepoLinkAction(
  tenantId: string,
  skillId: string,
): Promise<ActionResult> {
  try {
    await runeFetch(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/repo-links/${encodeURIComponent(skillId)}`,
      { method: "DELETE" },
    );
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to remove repo link.",
    };
  }
  revalidatePath(`/tenants/${tenantId}/guardrails`);
  return { ok: true };
}

/** Kicks off "Connect GitHub" — the only action in this file that ends in
 * an off-app redirect rather than returning data. Fetches a one-time
 * authorize URL (minted server-side, carries a signed state — see
 * authn/github_oauth.py) and sends the browser straight to github.com;
 * GitHub's own redirect back lands on api/github_routes.py::github_callback
 * directly (not through this app), which is why there's no "finish
 * connecting" action here — the backend handles that leg entirely. */
export async function connectGithubAction(tenantId: string): Promise<void> {
  const { authorizeUrl } = await runeFetch<GithubConnectUrlResponse>(
    `/api/v1/tenants/${encodeURIComponent(tenantId)}/github/connect-url`,
  );
  redirect(authorizeUrl);
}

export async function disconnectGithubAction(tenantId: string): Promise<ActionResult> {
  try {
    await runeFetch(`/api/v1/tenants/${encodeURIComponent(tenantId)}/github/connection`, {
      method: "DELETE",
    });
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to disconnect GitHub.",
    };
  }
  revalidatePath(`/tenants/${tenantId}/repositories`);
  return { ok: true };
}

export type SaveGithubOAuthAppResult =
  | { ok: true; app: GithubOAuthAppResponse }
  | { ok: false; error: string };

/** Tenant admin registers this tenant's own GitHub OAuth App (Client ID +
 * Secret) — required before connectGithubAction above has anything to
 * connect to. See authn/github_oauth_apps.py. */
export async function saveGithubOAuthAppAction(
  tenantId: string,
  input: GithubOAuthAppRequest,
): Promise<SaveGithubOAuthAppResult> {
  try {
    const app = await runeFetch<GithubOAuthAppResponse>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/github/oauth-app`,
      { method: "PUT", body: JSON.stringify(input) },
    );
    return { ok: true, app };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to save GitHub OAuth App.",
    };
  }
}

export async function removeGithubOAuthAppAction(tenantId: string): Promise<ActionResult> {
  try {
    await runeFetch(`/api/v1/tenants/${encodeURIComponent(tenantId)}/github/oauth-app`, {
      method: "DELETE",
    });
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to remove GitHub OAuth App.",
    };
  }
  revalidatePath(`/tenants/${tenantId}/repositories`);
  return { ok: true };
}

export type ListGithubReposResult =
  | { ok: true; repos: GithubRepoResponse[] }
  | { ok: false; error: string };

export async function listGithubReposAction(tenantId: string): Promise<ListGithubReposResult> {
  try {
    const repos = await runeFetch<GithubRepoResponse[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/github/repos`,
    );
    return { ok: true, repos };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to load repositories.",
    };
  }
}

export type ListGithubBranchesResult =
  | { ok: true; branches: string[] }
  | { ok: false; error: string };

export async function listGithubBranchesAction(
  tenantId: string,
  owner: string,
  repo: string,
): Promise<ListGithubBranchesResult> {
  try {
    const branches = await runeFetch<string[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/github/repos/` +
        `${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/branches`,
    );
    return { ok: true, branches };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof RuneApiRequestError ? err.message : "Failed to load branches.",
    };
  }
}
