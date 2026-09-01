"""Response models for the public REST API. Design ref: design.md §5."""

from __future__ import annotations

from pydantic import BaseModel


class PageMeta(BaseModel):
    total: int
    nextPageToken: str | None = None


class SearchResultItem(BaseModel):
    id: str
    name: str
    version: str
    category: str
    tags: list[str]
    runtime: list[str]
    digest: str
    score: float
    visibility: str
    ownerUser: str
    ownerTenant: str
    status: str


class SearchResponse(BaseModel):
    items: list[SearchResultItem]
    page: PageMeta


class OwnerResponse(BaseModel):
    team: str


class RuntimeCompatibilityResponse(BaseModel):
    family: str
    versionRange: str


class ResolvedDependency(BaseModel):
    id: str
    versionConstraint: str
    resolvedVersion: str | None


class SkillMetadataResponse(BaseModel):
    id: str
    name: str
    version: str
    description: str
    owner: OwnerResponse
    category: str
    tags: list[str]
    runtime: list[RuntimeCompatibilityResponse]
    digest: str
    dependencies: list[ResolvedDependency]
    visibility: str
    ownerUser: str
    ownerTenant: str
    sourceRepo: str | None = None
    sourceCommit: str | None = None
    sourceTag: str | None = None
    sourceBranch: str | None = None
    # The skill's own directory relative to sourceRepo's root, e.g.
    # "jira.create_ticket" — None means the repo root *is* the skill.
    sourcePath: str | None = None
    ciRunUrl: str | None = None
    # A point-in-time guardrail attestation computed once at publish —
    # None means "not available for this version" (published before
    # certification existed, or no guardrails service was reachable at
    # publish time), never "failed". Never recomputed on read, so it can
    # drift from the tenant's *current* guardrail policy over time.
    guardrailCertifiedLevel: int | None = None
    guardrailLevelStatuses: list[tuple[int, str]] = []
    guardrailWarningCheckIds: list[str] = []
    # "active" | "yanked" (index/models.py's ArtifactStatus) — a direct
    # metadata fetch always reflects the true status, even for a yanked
    # version that a search/latest resolution would now skip.
    status: str


class CertificationSummaryResponse(BaseModel):
    """The *projected* certification a draft would receive if published
    right now (ValidationResultResponse.certification) — same shape as the
    persisted fields above, minus warning ids (ValidationResultResponse.
    warnings already lists every WARN finding with its check id)."""

    highestCertifiedLevel: int | None
    levelStatuses: list[tuple[int, str]]


class ArtifactTokenResponse(BaseModel):
    token: str
    expiresAt: str
    ttlSeconds: int


class GoogleSignInRequest(BaseModel):
    idToken: str
    tenantId: str | None = None


class RefreshRequest(BaseModel):
    refreshToken: str
    tenantId: str | None = None


class DevLoginRequest(BaseModel):
    email: str
    password: str
    tenantId: str | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    pictureUrl: str | None = None


class TenantMembershipResponse(BaseModel):
    id: str
    name: str
    role: str


class AuthResponse(BaseModel):
    accessToken: str
    refreshToken: str
    user: UserResponse
    tenants: list[TenantMembershipResponse]
    activeTenantId: str


class RefreshResponse(BaseModel):
    accessToken: str
    tenants: list[TenantMembershipResponse]
    activeTenantId: str


class ShareGrantResponse(BaseModel):
    id: str
    skillId: str
    granteeType: str
    granteeId: str
    permission: str
    grantedBy: str
    grantedAt: str


class CreateShareGrantRequest(BaseModel):
    granteeType: str
    granteeId: str
    permission: str = "read"


class YankRequest(BaseModel):
    reason: str | None = None


class YankResponse(BaseModel):
    id: str
    version: str
    status: str
    reason: str | None = None
    actor: str
    at: str


class ForkFromRequest(BaseModel):
    id: str
    version: str


class CreateDraftGitRequest(BaseModel):
    provider: str  # only "github" is accepted today
    repoUrl: str
    targetBranch: str
    # Server generates "jaas/draft/<id-suffix>" when omitted.
    workingBranch: str | None = None
    # A brand-new, empty repo (zero commits) can't be branched off — the
    # first request against one gets DRAFT_GIT_EMPTY_REPO instead of
    # silently creating an initial commit; the caller re-sends with this
    # set to true only after the admin explicitly confirms.
    confirmInitializeEmptyRepo: bool = False


class CreateDraftRequest(BaseModel):
    forkFrom: ForkFromRequest | None = None
    git: CreateDraftGitRequest | None = None


class DraftResponse(BaseModel):
    id: str
    ownerUser: str
    ownerTenant: str
    createdAt: str
    forkedFromId: str | None
    forkedFromVersion: str | None
    files: list[str]
    provider: str | None = None
    repoUrl: str | None = None
    targetBranch: str | None = None
    workingBranch: str | None = None
    gitSyncStatus: str | None = None  # "synced" | "error" | None (not git-connected)
    gitSyncError: str | None = None
    # The folder this draft's files live under in the repo, so one repo can
    # host several skills — None on a draft connected before this existed,
    # until POST .../git/move-to-directory migrates it.
    gitSubdirectory: str | None = None


class DraftSummaryResponse(BaseModel):
    id: str
    createdAt: str
    forkedFromId: str | None
    forkedFromVersion: str | None
    repoUrl: str | None = None
    # manifest.yaml's own `id` field, read live off local disk — the same
    # name git_sync.skill_directory_name derives the repo folder from, so
    # the drafts list can show something more meaningful than the opaque
    # draft_<uuid> id. None only if manifest.yaml is missing/unparsable.
    skillId: str | None = None


class PutFileRequest(BaseModel):
    content: str
    # False for the debounced autosave (local-disk write only, no git churn
    # on every keystroke); True from the explicit "Save Draft" button, which
    # is also the only place commitMessage is ever set.
    syncToGit: bool = True
    commitMessage: str | None = None


class FileContentResponse(BaseModel):
    path: str
    content: str


class SourceFilesResponse(BaseModel):
    """Browsing-only view of the full repo tree at this version's release
    ref, fetched live from GitHub's public API — separate from
    `list_skill_files`'s `/files`, which lists only the narrow, signed,
    actually-downloadable package. `available=False` covers every reason
    the tree couldn't be shown (no source repo recorded, private repo,
    GitHub unreachable/rate-limited) without distinguishing them to the
    caller beyond `reason`, since none of them are actionable client-side."""

    available: bool
    files: list[str] = []
    repoUrl: str | None = None
    ref: str | None = None
    reason: str | None = None


class ValidationErrorItem(BaseModel):
    code: str
    message: str
    file: str | None = None


class ValidationResultResponse(BaseModel):
    valid: bool
    errors: list[ValidationErrorItem]
    warnings: list[ValidationErrorItem] = []
    # The certification this draft would receive if published right now —
    # None when invalid/blocked (nothing was scanned) or the guardrails
    # service wasn't reachable. Always a projection, never persisted.
    certification: CertificationSummaryResponse | None = None


class GuardrailDefinitionResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    level: int
    mandatory: bool
    defaultEnabled: bool
    defaultSeverity: str
    standardRef: str


class TenantGuardrailPolicyRequest(BaseModel):
    enabledCheckIds: list[str]


class TenantGuardrailPolicyResponse(BaseModel):
    tenantId: str
    enabledCheckIds: list[str]


class CustomGuardrailRuleRequest(BaseModel):
    slug: str
    name: str
    description: str = ""
    category: str
    severity: str
    standardRef: str = ""
    kind: str
    config: dict = {}


class CustomGuardrailRuleResponse(BaseModel):
    id: str
    tenantId: str
    slug: str
    name: str
    description: str
    category: str
    severity: str
    standardRef: str
    kind: str
    config: dict
    createdBy: str
    createdAt: str


class ValidateCustomGuardrailRuleResponse(BaseModel):
    valid: bool
    error: str | None = None


class RepoLinkRequest(BaseModel):
    skillId: str
    repoUrl: str
    # Branches allowed to produce a release, verified against the OIDC
    # token's `environment` claim — empty means no restriction (default).
    releaseBranches: list[str] = []


class UpdateRepoLinkRequest(BaseModel):
    releaseBranches: list[str]


class RepoLinkResponse(BaseModel):
    id: str
    tenantId: str
    skillId: str
    repoUrl: str
    createdBy: str
    createdAt: str
    releaseBranches: list[str] = []


class GithubConnectUrlResponse(BaseModel):
    authorizeUrl: str


class GithubConnectionResponse(BaseModel):
    connected: bool
    # Whether this tenant has registered its own GitHub OAuth App
    # (authn/github_oauth_apps.py) — lets the UI hide "Connect GitHub"
    # entirely rather than showing a button that can only ever fail.
    configured: bool
    githubLogin: str | None = None
    githubAvatarUrl: str | None = None
    connectedAt: str | None = None


class GithubOAuthAppRequest(BaseModel):
    clientId: str
    clientSecret: str


class GithubOAuthAppResponse(BaseModel):
    configured: bool
    # Never the secret — write-only once saved, same posture as a PAT.
    clientId: str | None = None
    # Deployment-fixed (settings.github_oauth_redirect_uri) — surfaced so
    # an admin knows exactly what to register as their OAuth App's
    # "Authorization callback URL" on GitHub, without guessing.
    redirectUri: str


class GithubRepoResponse(BaseModel):
    fullName: str
    owner: str
    name: str
    private: bool
    defaultBranch: str


class ReleaseRequest(BaseModel):
    files: dict[str, str]  # path -> base64-encoded raw bytes
    tag: str  # the git tag that triggered this release, e.g. "v1.2.3"
    ciRunUrl: str | None = None
    # Only read on the PAT auth path — the OIDC path derives the repo from
    # the token itself, so a caller-supplied value there would be an
    # unverified claim; release_routes.py ignores this field when an OIDC
    # token was presented.
    repoUrl: str | None = None
    # PAT-path-only, best-effort declaration of which branch this release
    # came from — checked against the repo link's releaseBranches, but
    # unlike the OIDC path's `environment` claim, this is not
    # cryptographically verified. Ignored when an OIDC token is presented
    # (identity.environment is used instead).
    releaseBranch: str | None = None
    # Best-effort, client-supplied (cli.py's cmd_release, via `git
    # rev-parse --show-prefix`): the skill directory's path relative to
    # its repo root, e.g. "jira.create_ticket" when one repo hosts several
    # skills, empty/None for the reference CI workflow's "one repo per
    # skill" convention. Not cryptographically verified on either auth
    # path — it only ever scopes the read-only "browse full source at this
    # tag" feature (GET .../source-files) to this skill's own files, never
    # anything packaged/signed/executed, so an unverified claim here has
    # no security consequence, unlike repoUrl/releaseBranch above.
    sourcePath: str | None = None


class ReleaseResponse(BaseModel):
    id: str
    version: str
    digest: str
    guardrailCertifiedLevel: int | None = None
    guardrailLevelStatuses: list[tuple[int, str]] = []
    guardrailWarningCheckIds: list[str] = []


class DraftPublishRequest(BaseModel):
    visibility: str = "private"


class DraftPublishResponse(BaseModel):
    id: str
    version: str
    digest: str
    prUrl: str | None = None
    releaseUrl: str | None = None
    guardrailCertifiedLevel: int | None = None
    guardrailLevelStatuses: list[tuple[int, str]] = []
    guardrailWarningCheckIds: list[str] = []


class CreateTenantRequest(BaseModel):
    name: str


class MemberResponse(BaseModel):
    userId: str
    email: str
    name: str
    role: str


class InviteMemberRequest(BaseModel):
    email: str
    role: str = "member"


class InviteMemberResponse(BaseModel):
    email: str
    role: str
    status: str


class CreatePatRequest(BaseModel):
    name: str
    ttlSeconds: int = 60 * 60 * 24 * 90  # 90 days


class PatSummaryResponse(BaseModel):
    id: str
    name: str
    createdAt: str
    expiresAt: str


class CreatePatResponse(BaseModel):
    id: str
    name: str
    token: str
    expiresAt: str
