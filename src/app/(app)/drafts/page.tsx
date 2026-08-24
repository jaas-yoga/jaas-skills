import { FolderOpen, GitBranch } from "lucide-react";
import Link from "next/link";

import { auth } from "@/auth";
import { CreateDraftDialog } from "@/components/drafts/create-draft-dialog";
import { DeleteDraftButton } from "@/components/drafts/delete-draft-button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { listDrafts } from "@/lib/drafts-api";
import { getGithubConnection } from "@/lib/github-api";
import { listRepoLinks } from "@/lib/repo-links-api";

export default async function DraftsPage() {
  const session = await auth();
  const tenantId = session?.runeActiveTenantId;
  const [drafts, githubConnection, repoLinks] = await Promise.all([
    listDrafts(),
    tenantId ? getGithubConnection(tenantId) : Promise.resolve(null),
    tenantId ? listRepoLinks(tenantId) : Promise.resolve([]),
  ]);
  const githubConnected = githubConnection?.connected ?? false;
  // A draft may only be connected to a repo already registered under
  // Connected Repos (Tenant Settings → Repositories) — same admin-curated
  // allow-list CI releases require, deduped since several skill ids can
  // share one repo.
  const connectedRepoUrls = Array.from(new Set(repoLinks.map((link) => link.repoUrl)));

  return (
    <div className="w-full space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Drafts</h1>
          <p className="text-sm text-muted-foreground">
            Your in-progress, unpublished skill packages.
          </p>
        </div>
        <CreateDraftDialog
          label="Create Skill"
          tenantId={tenantId}
          githubConnected={githubConnected}
          connectedRepoUrls={connectedRepoUrls}
        />
      </div>

      {drafts.length === 0 ? (
        <EmptyState
          icon={FolderOpen}
          title="No drafts yet"
          description="Start one from scratch, or open a published skill and choose New Version to fork it."
          action={
            <CreateDraftDialog
              label="Create Your First Skill"
              tenantId={tenantId}
              githubConnected={githubConnected}
              connectedRepoUrls={connectedRepoUrls}
            />
          }
        />
      ) : (
        <div className="space-y-2">
          {drafts.map((draft) => (
            <Link key={draft.id} href={`/drafts/${draft.id}`}>
              <Card className="transition-colors hover:border-brand">
                <CardContent className="flex items-center justify-between py-4">
                  <div>
                    <div className="flex items-center gap-1.5">
                      <p className="text-sm font-medium text-foreground">
                        {draft.skillId ?? draft.id}
                      </p>
                      {draft.repoUrl && (
                        <GitBranch
                          className="size-3.5 text-muted-foreground"
                          aria-label="Connected to a git repo"
                        />
                      )}
                    </div>
                    {draft.skillId && (
                      <p className="font-mono text-xs text-muted-foreground">{draft.id}</p>
                    )}
                    {draft.forkedFromId && (
                      <p className="text-xs text-muted-foreground">
                        Forked from {draft.forkedFromId}@{draft.forkedFromVersion}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <p className="text-xs text-muted-foreground">
                      {new Date(draft.createdAt).toLocaleString()}
                    </p>
                    <DeleteDraftButton draftId={draft.id} />
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
