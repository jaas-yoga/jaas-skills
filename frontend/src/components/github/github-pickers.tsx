"use client";

import { useEffect, useState, useTransition } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { listGithubBranchesAction, listGithubReposAction } from "@/lib/actions";
import type { GithubRepoResponse } from "@/lib/rune-api-types";

/** https://github.com/acme/tool-x(.git)? -> {owner: "acme", name: "tool-x"}
 * — null for anything else (a non-GitHub URL, which just means the live
 * picker isn't available for that value; manual entry always is). Shared
 * between repo-links-editor.tsx (release-branch authorization) and
 * create-draft-dialog.tsx (git-backed draft storage) — both only ever
 * accept this one URL form. */
export function parseGithubRepoUrl(url: string): { owner: string; name: string } | null {
  const match = url.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?\/?$/);
  if (!match) return null;
  return { owner: match[1], name: match[2] };
}

function useGithubBranches(tenantId: string, owner: string, repo: string) {
  const [branches, setBranches] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, startLoading] = useTransition();

  useEffect(() => {
    startLoading(async () => {
      const result = await listGithubBranchesAction(tenantId, owner, repo);
      if (result.ok) setBranches(result.branches);
      else setError(result.error);
    });
    // Fetched once per owner/repo, not on every keystroke.
  }, [tenantId, owner, repo]);

  return { branches, error, loading };
}

export function GithubRepoPicker({
  tenantId,
  onSelect,
}: {
  tenantId: string;
  onSelect: (repo: GithubRepoResponse) => void;
}) {
  const [repos, setRepos] = useState<GithubRepoResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, startLoading] = useTransition();

  useEffect(() => {
    startLoading(async () => {
      const result = await listGithubReposAction(tenantId);
      if (result.ok) setRepos(result.repos);
      else setError(result.error);
    });
    // Fetched once per dialog open, not on every keystroke — the search
    // box below filters the already-fetched list client-side.
  }, [tenantId]);

  const filtered = (repos ?? []).filter((r) =>
    r.fullName.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="space-y-2">
      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search repositories…"
        autoFocus
      />
      <div className="max-h-64 overflow-y-auto rounded-md border border-border">
        {loading ? (
          <div className="space-y-2 p-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : error ? (
          <p className="p-3 text-sm text-danger">{error}</p>
        ) : filtered.length === 0 ? (
          <p className="p-3 text-sm text-muted-foreground">
            {(repos ?? []).length === 0
              ? "No repositories with push access found on this GitHub account."
              : "No repositories match."}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {filtered.map((repo) => (
              <li key={repo.fullName}>
                <button
                  type="button"
                  onClick={() => onSelect(repo)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-muted"
                >
                  <span className="truncate font-mono">{repo.fullName}</span>
                  {repo.private && (
                    <Badge variant="outline" className="shrink-0 text-[10px]">
                      Private
                    </Badge>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function GithubBranchChecklist({
  tenantId,
  owner,
  repo,
  selected,
  onChange,
}: {
  tenantId: string;
  owner: string;
  repo: string;
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const { branches, error, loading } = useGithubBranches(tenantId, owner, repo);

  function toggle(branch: string) {
    const next = new Set(selected);
    if (next.has(branch)) next.delete(branch);
    else next.add(branch);
    onChange(next);
  }

  if (loading) {
    return (
      <div className="space-y-1.5 rounded-md border border-border p-2">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-4 w-28" />
        ))}
      </div>
    );
  }
  if (error) {
    return <p className="text-sm text-danger">{error}</p>;
  }

  // Anything already selected that the live branch list doesn't know about
  // (typed in manually before, or a since-deleted branch) is still shown
  // and still checked — switching to the picker can never silently drop it.
  const allBranches = [...(branches ?? []), ...[...selected].filter((b) => !branches?.includes(b))];

  return (
    <div className="max-h-40 space-y-1.5 overflow-y-auto rounded-md border border-border p-2">
      {allBranches.length === 0 ? (
        <p className="text-sm text-muted-foreground">No branches found.</p>
      ) : (
        allBranches.map((branch) => (
          <label key={branch} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-3.5 rounded border-border accent-brand"
              checked={selected.has(branch)}
              onChange={() => toggle(branch)}
            />
            <span className="font-mono">{branch}</span>
          </label>
        ))
      )}
    </div>
  );
}

