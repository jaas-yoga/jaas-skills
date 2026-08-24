"use client";

import { GitBranch, Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import {
  GithubBranchChecklist,
  GithubRepoPicker,
  parseGithubRepoUrl,
} from "@/components/github/github-pickers";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { createRepoLinkAction, deleteRepoLinkAction, updateRepoLinkAction } from "@/lib/actions";
import type { GithubRepoResponse, RepoLinkResponse } from "@/lib/rune-api-types";

function parseBranches(text: string): string[] {
  return text
    .split(",")
    .map((b) => b.trim())
    .filter(Boolean);
}

function ConnectRepoDialog({
  tenantId,
  editing,
  githubConnected,
  open,
  onOpenChange,
}: {
  tenantId: string;
  /** null = "Connect a repo" (create); a link = "Edit release branches"
   * (update — skill id/repo url are immutable once linked). */
  editing: RepoLinkResponse | null;
  /** Whether this tenant has a working GitHub connection — gates whether
   * the live picker is even offered; manual entry always works regardless. */
  githubConnected: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const isEdit = editing !== null;
  const editingParsedRepo = editing ? parseGithubRepoUrl(editing.repoUrl) : null;
  const canPickFromGithubForEdit = githubConnected && editingParsedRepo !== null;

  const [skillId, setSkillId] = useState(editing?.skillId ?? "");
  const [repoUrl, setRepoUrl] = useState(editing?.repoUrl ?? "");
  const [branchesText, setBranchesText] = useState((editing?.releaseBranches ?? []).join(", "));
  const [selectedBranches, setSelectedBranches] = useState<Set<string>>(
    new Set(editing?.releaseBranches ?? []),
  );
  // Create mode defaults straight into the picker when GitHub is
  // connected (the headline feature); edit mode defaults to manual since
  // it already has a concrete value pre-filled — picking from GitHub
  // there is an opt-in upgrade, not the default.
  const [mode, setMode] = useState<"manual" | "github">(
    !isEdit && githubConnected ? "github" : "manual",
  );
  const [pickerStep, setPickerStep] = useState<"repo" | "branches">("repo");
  const [selectedRepo, setSelectedRepo] = useState<GithubRepoResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<RepoLinkResponse | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function toggleMode() {
    if (mode === "manual") {
      setSelectedBranches(new Set(parseBranches(branchesText)));
      setMode("github");
    } else {
      setBranchesText(Array.from(selectedBranches).join(", "));
      setMode("manual");
    }
  }

  function handleSubmit() {
    if (!isEdit && (!skillId.trim() || !repoUrl.trim())) return;
    const releaseBranches =
      mode === "manual" ? parseBranches(branchesText) : Array.from(selectedBranches);
    setError(null);
    startTransition(async () => {
      const result = isEdit
        ? await updateRepoLinkAction(tenantId, editing.skillId, releaseBranches)
        : await createRepoLinkAction(tenantId, {
            skillId: skillId.trim(),
            repoUrl: repoUrl.trim(),
            releaseBranches,
          });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      if (isEdit) {
        onOpenChange(false);
      } else {
        setCreated(result.link);
      }
      router.refresh();
    });
  }

  function handleClose() {
    onOpenChange(false);
    setSkillId("");
    setRepoUrl("");
    setBranchesText("");
    setSelectedBranches(new Set());
    setMode("manual");
    setPickerStep("repo");
    setSelectedRepo(null);
    setError(null);
    setCreated(null);
  }

  const canToggleMode = isEdit ? canPickFromGithubForEdit : githubConnected;
  const showBranchArea = isEdit || mode === "manual" || pickerStep === "branches";

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : handleClose())}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${editing.skillId}` : "Connect a repo"}</DialogTitle>
          <DialogDescription>
            {isEdit ? (
              "Which branches may produce a release. Leave empty to allow any — the default, and what every link had before this existed."
            ) : (
              <>
                Registers which git repo may release this skill id from CI — required before{" "}
                <code className="rounded bg-muted px-1 py-0.5">runectl release</code> will accept
                a release for it. A skill id can only ever be linked to one repo, tenant-wide.
              </>
            )}
          </DialogDescription>
        </DialogHeader>

        {created ? (
          <div className="space-y-3">
            <p className="text-sm text-success">
              Connected <code className="rounded bg-muted px-1 py-0.5">{created.skillId}</code> to{" "}
              {created.repoUrl}.
            </p>
            <div className="rounded-lg border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
              <p className="mb-2 font-medium text-foreground">Next: set up the release workflow</p>
              <p className="mb-2">
                Copy{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  examples/ci/github-actions-release.yml
                </code>{" "}
                from the registry repo into{" "}
                <code className="rounded bg-muted px-1 py-0.5">.github/workflows/</code> in{" "}
                {created.repoUrl}. It uses GitHub Actions OIDC — no secret to store — as long as
                the workflow requests an ID token with{" "}
                <code className="rounded bg-muted px-1 py-0.5">permissions: id-token: write</code>.
              </p>
              {created.releaseBranches.length > 0 && (
                <p className="mb-2">
                  Since this link restricts releases to{" "}
                  <code className="rounded bg-muted px-1 py-0.5">
                    {created.releaseBranches.join(", ")}
                  </code>
                  , each release job must also declare a matching{" "}
                  <code className="rounded bg-muted px-1 py-0.5">environment:</code> (configure
                  its deployment branch policy under the repo&apos;s Settings → Environments) —
                  that&apos;s the only way we can verify which branch a tag came from.
                </p>
              )}
              <p>
                Prefer a personal access token instead? Mint one under Account → Access Tokens and
                pass it as <code className="rounded bg-muted px-1 py-0.5">--token</code> to{" "}
                <code className="rounded bg-muted px-1 py-0.5">runectl release</code>.
              </p>
            </div>
          </div>
        ) : (
          <>
            {!isEdit && mode === "github" && pickerStep === "repo" && (
              <GithubRepoPicker
                tenantId={tenantId}
                onSelect={(repo) => {
                  setSelectedRepo(repo);
                  setSkillId((prev) => prev || repo.name);
                  setRepoUrl(`https://github.com/${repo.fullName}`);
                  setPickerStep("branches");
                }}
              />
            )}

            {!isEdit && (mode === "manual" || pickerStep === "branches") && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Skill id</label>
                <Input
                  value={skillId}
                  onChange={(e) => setSkillId(e.target.value)}
                  placeholder="acme.tool.my-skill"
                  autoFocus={mode === "manual"}
                />
              </div>
            )}

            {!isEdit && mode === "manual" && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Repo URL</label>
                <Input
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/acme/my-skill"
                />
              </div>
            )}

            {!isEdit && mode === "github" && pickerStep === "branches" && selectedRepo && (
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  Repository:{" "}
                  <span className="font-mono text-foreground">{selectedRepo.fullName}</span>
                </span>
                <button
                  type="button"
                  className="text-brand hover:underline"
                  onClick={() => setPickerStep("repo")}
                >
                  Change
                </button>
              </div>
            )}

            {showBranchArea && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Release branches (optional{mode === "manual" ? ", comma-separated" : ""})
                </label>
                {mode === "manual" ? (
                  <Input
                    value={branchesText}
                    onChange={(e) => setBranchesText(e.target.value)}
                    placeholder="main, staging"
                  />
                ) : (
                  <GithubBranchChecklist
                    tenantId={tenantId}
                    owner={isEdit ? editingParsedRepo!.owner : selectedRepo!.owner}
                    repo={isEdit ? editingParsedRepo!.name : selectedRepo!.name}
                    selected={selectedBranches}
                    onChange={setSelectedBranches}
                  />
                )}
              </div>
            )}

            {canToggleMode && (
              <button
                type="button"
                className="text-xs text-brand hover:underline"
                onClick={toggleMode}
              >
                {mode === "manual"
                  ? "Pick from GitHub instead"
                  : "Enter details manually instead"}
              </button>
            )}

            {error && <p className="text-sm text-danger">{error}</p>}
          </>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {created ? "Done" : "Cancel"}
          </Button>
          {!created && (
            <Button
              onClick={handleSubmit}
              disabled={pending || (!isEdit && (!skillId.trim() || !repoUrl.trim()))}
            >
              {pending ? <Loader2 className="size-4 animate-spin" /> : null}
              {isEdit ? "Save" : "Connect"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** design.md §4.5's git-native release flow — a tenant admin must register
 * a skill id's repo here before CI's `runectl release`/OIDC path (or a PAT)
 * is authorized to release it (anti-squatting; authn/repo_links.py in the
 * backend enforces this server-side regardless of what this UI shows). */
export function RepoLinksEditor({
  tenantId,
  links,
  githubConnected,
  isAdmin,
}: {
  tenantId: string;
  links: RepoLinkResponse[];
  githubConnected: boolean;
  isAdmin: boolean;
}) {
  const [editing, setEditing] = useState<RepoLinkResponse | "new" | null>(null);
  const [deletingSkillId, setDeletingSkillId] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  function handleDelete(skillId: string) {
    setDeletingSkillId(skillId);
    startTransition(async () => {
      await deleteRepoLinkAction(tenantId, skillId);
      setDeletingSkillId(null);
      router.refresh();
    });
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Connected Repos</h2>
          <p className="text-xs text-muted-foreground">
            Skill ids this tenant has authorized to release from CI on a tag push.
          </p>
        </div>
        {isAdmin && (
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus className="size-4" />
            Connect a repo
          </Button>
        )}
      </div>

      {links.length === 0 ? (
        <EmptyState
          icon={GitBranch}
          title="No repos connected"
          description={
            isAdmin
              ? "Connect a skill id to its git repo to release it from CI."
              : "This tenant hasn't connected any git repos yet."
          }
        />
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-lg border border-border">
          {links.map((link) => (
            <div key={link.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{link.skillId}</p>
                <p className="truncate text-xs text-muted-foreground">{link.repoUrl}</p>
                {link.releaseBranches.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {link.releaseBranches.map((branch) => (
                      <Badge key={branch} variant="outline" className="text-[10px]">
                        {branch}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
              {isAdmin && (
                <div className="flex shrink-0 items-center gap-1">
                  <Button variant="ghost" size="icon" onClick={() => setEditing(link)}>
                    <Pencil className="size-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDelete(link.skillId)}
                    disabled={pending && deletingSkillId === link.skillId}
                  >
                    {pending && deletingSkillId === link.skillId ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Trash2 className="size-4" />
                    )}
                  </Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <ConnectRepoDialog
        tenantId={tenantId}
        editing={editing === "new" || editing === null ? null : editing}
        githubConnected={githubConnected}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      />
    </div>
  );
}
