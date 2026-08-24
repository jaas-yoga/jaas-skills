"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { parseGithubRepoUrl } from "@/components/github/github-pickers";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  createDraftAction,
  createDraftWithGitAction,
  listGithubBranchesAction,
  listGithubReposAction,
} from "@/lib/actions";

type Destination = "local" | "github";

function suggestWorkingBranch(repoFullName: string): string {
  const suffix = Math.random().toString(16).slice(2, 8);
  return `rune/draft/${repoFullName.split("/")[1]}-${suffix}`;
}

/** Replaces the plain `<form action={createDraftAction}>` button — "Create
 * Skill" now expands this panel inline, in the page's own flow (no modal).
 * Three chained dropdowns: where the draft lives, then (only when GitHub is
 * chosen) which repo — restricted to repos already registered under
 * Connected Repos (Tenant Settings → Repositories), not a live search over
 * the whole GitHub account — then which branch to target, defaulting to the
 * repo's default branch but changeable when the repo has others. */
export function CreateDraftDialog({
  label,
  tenantId,
  githubConnected,
  connectedRepoUrls,
}: {
  label: string;
  tenantId?: string;
  githubConnected: boolean;
  connectedRepoUrls: string[];
}) {
  const [open, setOpen] = useState(false);
  const [destination, setDestination] = useState<Destination>("local");
  const [selectedRepoUrl, setSelectedRepoUrl] = useState("");
  const [defaultBranchByUrl, setDefaultBranchByUrl] = useState<Record<string, string>>({});
  const [selectedBranch, setSelectedBranch] = useState("");
  const [branches, setBranches] = useState<string[] | null>(null);
  const [branchesLoading, startBranchesLoading] = useTransition();
  const [emptyRepoConfirm, setEmptyRepoConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();

  const canUseGithub = githubConnected && connectedRepoUrls.length > 0;
  const selectedRepoParsed = selectedRepoUrl ? parseGithubRepoUrl(selectedRepoUrl) : null;

  useEffect(() => {
    if (!open || !tenantId || !canUseGithub) return;
    // Only used to resolve each repo's default branch — the dropdown itself
    // is already restricted to connectedRepoUrls, this never browses the
    // wider account.
    listGithubReposAction(tenantId).then((result) => {
      if (!result.ok) return;
      const map: Record<string, string> = {};
      for (const repo of result.repos) {
        map[`https://github.com/${repo.fullName}`] = repo.defaultBranch;
      }
      setDefaultBranchByUrl(map);
    });
  }, [open, tenantId, canUseGithub]);

  useEffect(() => {
    if (!tenantId || !selectedRepoParsed) return;
    const defaultBranch = defaultBranchByUrl[selectedRepoUrl] ?? "";
    startBranchesLoading(async () => {
      setSelectedBranch(defaultBranch);
      const result = await listGithubBranchesAction(
        tenantId,
        selectedRepoParsed.owner,
        selectedRepoParsed.name,
      );
      if (result.ok) {
        setBranches(result.branches);
        if (!defaultBranch && result.branches.length > 0) setSelectedBranch(result.branches[0]);
      } else {
        setBranches([]);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, selectedRepoUrl, defaultBranchByUrl]);

  function reset() {
    setDestination("local");
    setSelectedRepoUrl("");
    setSelectedBranch("");
    setBranches(null);
    setEmptyRepoConfirm(false);
    setError(null);
  }

  function close() {
    setOpen(false);
    reset();
  }

  function handleCreateLocal() {
    setError(null);
    startTransition(async () => {
      await createDraftAction(undefined);
    });
  }

  function handleCreateGithub(confirmEmptyRepo = false) {
    if (!selectedRepoUrl) return;
    const fullName = selectedRepoParsed ? `${selectedRepoParsed.owner}/${selectedRepoParsed.name}` : "repo";
    const targetBranch = selectedBranch || defaultBranchByUrl[selectedRepoUrl] || "main";
    setError(null);
    startTransition(async () => {
      const result = await createDraftWithGitAction({
        provider: "github",
        repoUrl: selectedRepoUrl,
        targetBranch,
        workingBranch: suggestWorkingBranch(fullName),
        confirmInitializeEmptyRepo: confirmEmptyRepo,
      });
      if (!result.ok) {
        if (result.code === "DRAFT_GIT_EMPTY_REPO") {
          setSelectedBranch(targetBranch);
          setEmptyRepoConfirm(true);
          return;
        }
        setError(result.error);
        return;
      }
      close();
      router.push(`/drafts/${result.draftId}`);
    });
  }

  if (!open) {
    return <Button onClick={() => setOpen(true)}>{label}</Button>;
  }

  return (
    <Card className="w-full max-w-4xl">
      <CardContent className="space-y-3 pt-6">
        {emptyRepoConfirm ? (
          <div className="flex flex-nowrap items-end gap-3">
            <div className="w-52 space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                {selectedRepoParsed?.owner}/{selectedRepoParsed?.name} is empty — branch name
              </label>
              <Input
                value={selectedBranch}
                onChange={(e) => setSelectedBranch(e.target.value)}
                placeholder="main"
                className="font-mono"
                autoFocus
              />
            </div>
            <div className="ml-auto flex shrink-0 gap-2">
              <Button variant="outline" onClick={() => setEmptyRepoConfirm(false)} disabled={pending}>
                Cancel
              </Button>
              <Button
                onClick={() => handleCreateGithub(true)}
                disabled={pending || !selectedBranch.trim()}
              >
                Create branch & start
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-nowrap items-end gap-3">
            <div className="w-52 space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Where should this draft live?
              </label>
              <Select
                value={destination}
                onValueChange={(v) => {
                  setDestination(v as Destination);
                  setSelectedRepoUrl("");
                  setBranches(null);
                  setSelectedBranch("");
                }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">Local only</SelectItem>
                  <SelectItem value="github" disabled={!canUseGithub}>
                    GitHub repo
                  </SelectItem>
                </SelectContent>
              </Select>
              {!canUseGithub && (
                <p className="text-xs text-muted-foreground">
                  {tenantId ? (
                    <>
                      {githubConnected ? "No repos connected yet — c" : "C"}onnect a repo under{" "}
                      <Link
                        href={`/tenants/${tenantId}/repositories`}
                        className="text-brand hover:underline"
                        onClick={close}
                      >
                        Tenant Settings → Repositories
                      </Link>{" "}
                      to enable this.
                    </>
                  ) : (
                    "This tenant hasn't connected GitHub."
                  )}
                </p>
              )}
            </div>

            {destination === "github" && (
              <div className="w-52 space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Repository</label>
                <Select
                  value={selectedRepoUrl}
                  onValueChange={(url) => {
                    setSelectedRepoUrl(url);
                    setBranches(null);
                    setSelectedBranch("");
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select a connected repo…" />
                  </SelectTrigger>
                  <SelectContent>
                    {connectedRepoUrls.map((url) => {
                      const parsed = parseGithubRepoUrl(url);
                      return (
                        <SelectItem key={url} value={url} className="font-mono">
                          {parsed ? `${parsed.owner}/${parsed.name}` : url}
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              </div>
            )}

            {destination === "github" && selectedRepoUrl && (
              <div className="w-44 space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Branch</label>
                {branchesLoading ? (
                  <p className="text-xs text-muted-foreground">Loading branches…</p>
                ) : branches && branches.length > 0 ? (
                  <Select value={selectedBranch} onValueChange={setSelectedBranch}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Select a branch…" />
                    </SelectTrigger>
                    <SelectContent>
                      {branches.map((branch) => (
                        <SelectItem key={branch} value={branch} className="font-mono">
                          {branch}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No branches yet — the first commit will create one.
                  </p>
                )}
              </div>
            )}

            <div className="ml-auto flex shrink-0 gap-2">
              <Button variant="outline" onClick={close} disabled={pending}>
                Cancel
              </Button>
              {destination === "local" ? (
                <Button onClick={handleCreateLocal} disabled={pending}>
                  Create
                </Button>
              ) : (
                <Button
                  onClick={() => handleCreateGithub(false)}
                  disabled={pending || !selectedRepoUrl}
                >
                  Create
                </Button>
              )}
            </div>
          </div>
        )}

        {error && <p className="text-sm text-danger">{error}</p>}
      </CardContent>
    </Card>
  );
}
