/**
 * Hand-kept mirror of src/rune_registry/api/schemas.py's auth response
 * models. Field names/shapes must match exactly — this is the contract
 * between the two codebases, not independently-designed types.
 */

export type UserResponse = {
  id: string;
  email: string;
  name: string;
  pictureUrl: string | null;
};

export type TenantMembershipResponse = {
  id: string;
  name: string;
  role: "admin" | "member";
};

export type AuthResponse = {
  accessToken: string;
  refreshToken: string;
  user: UserResponse;
  tenants: TenantMembershipResponse[];
  activeTenantId: string;
};

export type RefreshResponse = {
  accessToken: string;
  tenants: TenantMembershipResponse[];
  activeTenantId: string;
};

export type RuneApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};

/** Mirrors api/schemas.py's SearchResultItem/SearchResponse (design.md §5.1). */
export type SearchResultItem = {
  id: string;
  name: string;
  version: string;
  category: string;
  tags: string[];
  runtime: string[];
  digest: string;
  score: number;
  visibility: "public" | "private";
  ownerUser: string;
  ownerTenant: string;
};

export type PageMeta = {
  total: number;
  nextPageToken: string | null;
};

export type SearchResponse = {
  items: SearchResultItem[];
  page: PageMeta;
};

/** Mirrors api/schemas.py's ShareGrantResponse. */
export type ShareGrantResponse = {
  id: string;
  skillId: string;
  granteeType: "user" | "tenant";
  granteeId: string;
  permission: "read" | "read_write";
  grantedBy: string;
  grantedAt: string;
};

/** Mirrors api/schemas.py's PatSummaryResponse/CreatePatResponse. */
export type PatSummaryResponse = {
  id: string;
  name: string;
  createdAt: string;
  expiresAt: string;
};

export type CreatePatResponse = {
  id: string;
  name: string;
  token: string;
  expiresAt: string;
};

/** Mirrors api/schemas.py's MemberResponse/InviteMemberResponse. */
export type MemberResponse = {
  userId: string;
  email: string;
  name: string;
  role: "admin" | "member";
};

export type InviteMemberResponse = {
  email: string;
  role: "admin" | "member";
  status: "added" | "pending";
};

/** Mirrors api/schemas.py's DraftResponse/DraftSummaryResponse. */
export type DraftResponse = {
  id: string;
  ownerUser: string;
  ownerTenant: string;
  createdAt: string;
  forkedFromId: string | null;
  forkedFromVersion: string | null;
  files: string[];
  /** Non-null only when this draft is git-connected (drafts/git_sync.py) —
   * "github" is the only provider today. */
  provider: string | null;
  repoUrl: string | null;
  targetBranch: string | null;
  workingBranch: string | null;
  gitSyncStatus: "synced" | "error" | null;
  gitSyncError: string | null;
  /** The folder this draft's files live under in the repo, so one repo can
   * host several skills — null on a draft connected before per-skill
   * directories existed, until moveDraftToGitDirectoryAction migrates it. */
  gitSubdirectory: string | null;
};

export type DraftSummaryResponse = {
  id: string;
  createdAt: string;
  forkedFromId: string | null;
  forkedFromVersion: string | null;
  repoUrl: string | null;
  /** manifest.yaml's own `id`, read live — the same name the git folder
   * (DraftResponse.gitSubdirectory) is derived from. Null only if
   * manifest.yaml is missing/unparsable. */
  skillId: string | null;
};

/** Mirrors api/schemas.py's CreateDraftGitRequest. */
export type CreateDraftGitRequest = {
  provider: "github";
  repoUrl: string;
  targetBranch: string;
  workingBranch?: string;
  /** Set only on a resubmit after the user confirms initializing a
   * brand-new, empty repo (DRAFT_GIT_EMPTY_REPO on the first attempt). */
  confirmInitializeEmptyRepo?: boolean;
};

export type ValidationErrorItem = { code: string; message: string; file?: string | null };

/** Mirrors guardrails/certification.py's CertificationStatus values. */
export type GuardrailCertificationStatus =
  | "certified"
  | "attempted_with_findings"
  | "not_attempted";

/** [level, status] — always all 4 levels, in order. */
export type GuardrailLevelStatus = [1 | 2 | 3 | 4, GuardrailCertificationStatus];

/** Mirrors api/schemas.py's CertificationSummaryResponse — the
 * certification a draft would receive if published right now. Always a
 * projection, never persisted (contrast SkillMetadataResponse's
 * guardrailCertifiedLevel below, which is the real, permanent record). */
export type CertificationSummaryResponse = {
  highestCertifiedLevel: number | null;
  levelStatuses: GuardrailLevelStatus[];
};

export type ValidationResultResponse = {
  valid: boolean;
  errors: ValidationErrorItem[];
  warnings: ValidationErrorItem[];
  certification: CertificationSummaryResponse | null;
};

/** Mirrors api/schemas.py's GuardrailDefinitionResponse (design.md §4.5). */
export type GuardrailDefinitionResponse = {
  id: string;
  name: string;
  description: string;
  category: string;
  level: 1 | 2 | 3 | 4;
  mandatory: boolean;
  defaultEnabled: boolean;
  defaultSeverity: "BLOCK" | "WARN";
  standardRef: string;
};

export type TenantGuardrailPolicyResponse = {
  tenantId: string;
  enabledCheckIds: string[];
};

export type DraftPublishResponse = {
  id: string;
  version: string;
  digest: string;
  prUrl: string | null;
  releaseUrl: string | null;
  guardrailCertifiedLevel: number | null;
  guardrailLevelStatuses: GuardrailLevelStatus[];
  guardrailWarningCheckIds: string[];
};

/** Mirrors api/schemas.py's SkillMetadataResponse. */
export type SkillMetadataResponse = {
  id: string;
  name: string;
  version: string;
  description: string;
  owner: { team: string };
  category: string;
  tags: string[];
  runtime: { family: string; versionRange: string }[];
  digest: string;
  dependencies: { id: string; versionConstraint: string; resolvedVersion: string | null }[];
  visibility: "public" | "private";
  ownerUser: string;
  ownerTenant: string;
  /** Set only when this version was released via the git-native CI path
   * (POST /api/v1/skills/release) — null means published via the web UI's
   * drafts flow or a local `runectl publish`, not "unknown". */
  sourceRepo: string | null;
  sourceCommit: string | null;
  sourceTag: string | null;
  sourceBranch: string | null;
  /** The skill's own directory relative to sourceRepo's root, e.g.
   * "jira.create_ticket" when one repo hosts several skills — null means
   * the repo root *is* the skill. Scopes the "Source repo (at tag)" tab's
   * GitHub tree fetch to just this skill's files. */
  sourcePath: string | null;
  ciRunUrl: string | null;
  /** A point-in-time guardrail attestation computed once at publish — null
   * means "not available for this version" (published before certification
   * existed, or no guardrails service was reachable at publish time),
   * never "failed". Never recomputed on read, so it can drift from the
   * tenant's *current* guardrail policy over time — always show the
   * disclaimer wherever this is rendered. */
  guardrailCertifiedLevel: number | null;
  guardrailLevelStatuses: GuardrailLevelStatus[];
  guardrailWarningCheckIds: string[];
};

/** Mirrors api/schemas.py's SourceFilesResponse. Browsing-only view of the
 * full repo tree at this version's release ref, fetched live from GitHub —
 * separate from the packaged-archive file list (`listSkillFiles`).
 * `available: false` covers every reason it couldn't be shown (no source
 * repo recorded, private repo, GitHub unreachable) via `reason`. */
export type SourceFilesResponse = {
  available: boolean;
  files: string[];
  repoUrl: string | null;
  ref: string | null;
  reason: string | null;
};

/** Mirrors api/schemas.py's CustomGuardrailRuleResponse (design.md §4.5). */
export type CustomGuardrailRuleResponse = {
  id: string;
  tenantId: string;
  slug: string;
  name: string;
  description: string;
  category: string;
  severity: "BLOCK" | "WARN";
  standardRef: string;
  kind: string;
  config: Record<string, unknown>;
  createdBy: string;
  createdAt: string;
};

export type ValidateCustomGuardrailRuleResponse = {
  valid: boolean;
  error: string | null;
};

/** Mirrors api/schemas.py's RepoLinkResponse. */
export type RepoLinkResponse = {
  id: string;
  tenantId: string;
  skillId: string;
  repoUrl: string;
  createdBy: string;
  createdAt: string;
  /** Branches allowed to release, verified via the OIDC token's
   * `environment` claim — empty means no restriction. */
  releaseBranches: string[];
};

/** Mirrors api/schemas.py's GithubConnectUrlResponse. */
export type GithubConnectUrlResponse = {
  authorizeUrl: string;
};

/** Mirrors api/schemas.py's GithubConnectionResponse. */
export type GithubConnectionResponse = {
  connected: boolean;
  /** False when this tenant hasn't registered its own GitHub OAuth App
   * yet — the UI should hide "Connect GitHub" rather than show a button
   * that can only ever fail. */
  configured: boolean;
  githubLogin: string | null;
  githubAvatarUrl: string | null;
  connectedAt: string | null;
};

/** Mirrors api/schemas.py's GithubOAuthAppRequest/GithubOAuthAppResponse —
 * each tenant's own GitHub OAuth App credentials, configured under
 * Tenant Settings → Repositories rather than a deployment-wide .env. */
export type GithubOAuthAppRequest = {
  clientId: string;
  clientSecret: string;
};

export type GithubOAuthAppResponse = {
  configured: boolean;
  clientId: string | null;
  redirectUri: string;
};

/** Mirrors api/schemas.py's GithubRepoResponse. */
export type GithubRepoResponse = {
  fullName: string;
  owner: string;
  name: string;
  private: boolean;
  defaultBranch: string;
};
